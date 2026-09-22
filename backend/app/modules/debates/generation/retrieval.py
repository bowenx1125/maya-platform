"""Typed, snapshot-scoped retrieval for a single debate turn."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol, cast

from app.modules.agents.markdown import AgentMarkdown
from app.modules.knowledge.mock_lexical import (
    MOCK_LEXICAL_ANCHOR_POLICY_ID,
    MockLexicalAnchorV2,
)

from .four_round import TEACHING_PROTOCOL, received_questions, visible_predecessors
from .segments import SegmentBarrage, SegmentPersona, coerce_persona
from .types import (
    GenerationContext,
    PendingQuestion,
    SnapshotRetrievalReceipt,
)

STRICT_THRESHOLD = 0.20
RELAXED_THRESHOLD = 0.08
MAX_SUBQUERIES = 3
TOP_K = 6
MOCK_LEXICAL_CANDIDATE_LIMIT = 256
SUBQUERY_KINDS = {
    "viewpoint",
    "pending_question",
    "rebuttal",
    "updated_position",
    "context",
    "barrage",
}


class RAGRetrievalError(RuntimeError):
    """A retrieval failure that is safe to route through turn retry logic."""

    def __init__(self, message: str, *, technical: bool = True) -> None:
        super().__init__(message)
        self.technical = technical
        self.code = "provider_unavailable" if technical else "turn_generation_failed"


@dataclass(frozen=True, slots=True)
class TurnSubquery:
    """One typed semantic query within a turn's retrieval request."""

    query_kind: str
    text: str

    def __post_init__(self) -> None:
        if not self.query_kind or not self.text.strip():
            raise ValueError("subquery kind and text are required")
        if self.query_kind not in SUBQUERY_KINDS:
            raise ValueError("subquery kind is not part of the closed retrieval contract")

    @property
    def query_hash(self) -> str:
        return hashlib.sha256(self.text.strip().encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    """Merged receipts and semantic-attempt metadata for one turn."""

    snapshot_id: str
    receipts: tuple[SnapshotRetrievalReceipt, ...]
    subqueries: tuple[TurnSubquery, ...]
    strict_calls: int
    relaxed_calls: int
    policy_id: str | None = None
    topic_anchor_hash: str | None = None

    @property
    def matched(self) -> bool:
        return bool(self.receipts)


class SnapshotSearch(Protocol):
    """Minimal adapter accepted by :class:`SnapshotRetriever`."""

    def search(
        self,
        snapshot_id: str,
        query: str,
        *,
        top_k: int = TOP_K,
    ) -> Iterable[object]:
        """Search only the supplied immutable snapshot."""


def _safe_filename(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RAGRetrievalError("A retrieval result has no safe source filename.", technical=False)
    if (
        "/" in value
        or "\\" in value
        or "\x00" in value
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise RAGRetrievalError(
            "A retrieval result has an unsafe source filename.", technical=False
        )
    return value


def _value(candidate: object, name: str, default: object = None) -> object:
    if isinstance(candidate, Mapping):
        return candidate.get(name, default)
    return getattr(candidate, name, default)


def _candidate_tuple(candidate: object) -> tuple[str, str, float, int, int, str]:
    chunk_id = _value(candidate, "chunk_id")
    filename = _value(candidate, "source_filename")
    score = _value(candidate, "score")
    document_order = _value(candidate, "document_order", 0)
    chunk_index = _value(candidate, "chunk_index", 0)
    text = _value(candidate, "chunk_text", _value(candidate, "text", ""))
    if not isinstance(chunk_id, str) or not chunk_id:
        raise RAGRetrievalError("A retrieval result has no chunk identity.", technical=False)
    safe_filename = _safe_filename(filename)
    if not isinstance(text, str) or not text.strip():
        raise RAGRetrievalError("A retrieval result has no chunk text.", technical=False)
    try:
        numeric_score = float(cast(str | float | int, score))
        doc_order = int(cast(str | float | int, document_order))
        index = int(cast(str | float | int, chunk_index))
    except (TypeError, ValueError) as exc:
        raise RAGRetrievalError(
            "A retrieval result has invalid ranking metadata.", technical=False
        ) from exc
    if not math.isfinite(numeric_score):
        raise RAGRetrievalError("A retrieval result has an invalid score.", technical=False)
    return chunk_id, safe_filename, numeric_score, doc_order, index, text


def _invoke_search(
    search: SnapshotSearch | Callable[..., Iterable[object]],
    snapshot_id: str,
    query: str,
    top_k: int,
) -> tuple[object, ...]:
    """Call either the snapshot-aware adapter or the existing local adapter.

    Wave 1's ``MockVectorStore`` predates the snapshot argument and accepts
    ``search(query, top_k=...)``.  Supporting that narrow legacy shape keeps
    the adapter reusable while the caller still supplies the authoritative
    snapshot scope.  New adapters should implement the three-argument form.
    """

    method_candidate = getattr(search, "search", None)
    method: Callable[..., Iterable[object]] = (
        cast(Callable[..., Iterable[object]], method_candidate)
        if callable(method_candidate)
        else cast(Callable[..., Iterable[object]], search)
    )
    try:
        result = method(snapshot_id, query, top_k=top_k)
    except TypeError as first_error:
        try:
            result = method(query, top_k=top_k)
        except TypeError as second_error:
            raise first_error from second_error
    try:
        return tuple(result)
    except TypeError as exc:
        raise RAGRetrievalError("The retrieval adapter returned an invalid result.") from exc


def _normalise_subqueries(subqueries: Sequence[TurnSubquery | str]) -> tuple[TurnSubquery, ...]:
    result: list[TurnSubquery] = []
    for index, item in enumerate(subqueries):
        if isinstance(item, TurnSubquery):
            result.append(item)
        elif isinstance(item, str):
            result.append(TurnSubquery("viewpoint" if index == 0 else "context", item))
        else:
            raise RAGRetrievalError("A turn subquery is not typed.", technical=False)
    if not result:
        raise RAGRetrievalError(
            "A turn must contain at least one retrieval query.", technical=False
        )
    if len(result) > MAX_SUBQUERIES:
        raise RAGRetrievalError(
            "A turn may contain at most three typed retrieval queries.", technical=False
        )
    return tuple(result)


class SnapshotRetriever:
    """Perform strict→relaxed retrieval and merge at most six receipts."""

    def __init__(
        self,
        search: SnapshotSearch | Callable[..., Iterable[object]],
        *,
        strict_threshold: float = STRICT_THRESHOLD,
        relaxed_threshold: float = RELAXED_THRESHOLD,
        top_k: int = TOP_K,
    ) -> None:
        if not 0 < relaxed_threshold <= strict_threshold:
            raise ValueError("relaxed threshold must not exceed strict threshold")
        if top_k < 1:
            raise ValueError("top_k must be positive")
        self.search = search
        self.strict_threshold = strict_threshold
        self.relaxed_threshold = relaxed_threshold
        self.top_k = min(top_k, TOP_K)

    def retrieve(
        self,
        snapshot_id: str,
        subqueries: Sequence[TurnSubquery | str],
        *,
        policy_id: str | None = None,
        topic_anchor: str | None = None,
    ) -> RetrievalResult:
        if not snapshot_id:
            raise RAGRetrievalError(
                "A turn must provide its participant snapshot.", technical=False
            )
        typed = _normalise_subqueries(subqueries)
        lexical_anchor: MockLexicalAnchorV2 | None = None
        topic_anchor_hash: str | None = None
        candidate_limit = self.top_k
        if policy_id is not None:
            if policy_id != MOCK_LEXICAL_ANCHOR_POLICY_ID:
                raise RAGRetrievalError(
                    "The Mock retrieval policy is not supported.", technical=False
                )
            if not isinstance(topic_anchor, str) or not topic_anchor.strip():
                raise RAGRetrievalError(
                    "The Mock lexical policy requires an authoritative topic anchor.",
                    technical=False,
                )
            lexical_anchor = MockLexicalAnchorV2.from_topic(topic_anchor)
            topic_anchor_hash = hashlib.sha256(topic_anchor.strip().encode("utf-8")).hexdigest()
            candidate_limit = MOCK_LEXICAL_CANDIDATE_LIMIT
        merged: dict[tuple[str, str], SnapshotRetrievalReceipt] = {}
        strict_calls = 0
        relaxed_calls = 0
        for subquery in typed:
            strict_calls += 1
            raw = _invoke_search(self.search, snapshot_id, subquery.text, candidate_limit)
            for item in raw:
                candidate_snapshot = _value(item, "snapshot_id")
                if candidate_snapshot is not None and candidate_snapshot != snapshot_id:
                    raise RAGRetrievalError(
                        "A retrieval result belongs to another snapshot.", technical=False
                    )
            parsed = [_candidate_tuple(item) for item in raw]
            parsed.sort(key=lambda item: (-item[2], item[3], item[4], item[0]))
            if lexical_anchor is not None:
                parsed = [item for item in parsed if lexical_anchor.accepts(item[5])]
            strict_matches = [item for item in parsed if item[2] >= self.strict_threshold]
            threshold_key: Literal["strict", "relaxed"] = "strict"
            if not strict_matches:
                relaxed_calls += 1
                raw = _invoke_search(self.search, snapshot_id, subquery.text, candidate_limit)
                for item in raw:
                    candidate_snapshot = _value(item, "snapshot_id")
                    if candidate_snapshot is not None and candidate_snapshot != snapshot_id:
                        raise RAGRetrievalError(
                            "A retrieval result belongs to another snapshot.", technical=False
                        )
                parsed = [_candidate_tuple(item) for item in raw]
                parsed.sort(key=lambda item: (-item[2], item[3], item[4], item[0]))
                if lexical_anchor is not None:
                    parsed = [item for item in parsed if lexical_anchor.accepts(item[5])]
                strict_matches = [item for item in parsed if item[2] >= self.relaxed_threshold]
                threshold_key = "relaxed"
            for rank, (chunk_id, filename, score, _doc_order, _chunk_index, text) in enumerate(
                strict_matches[: self.top_k], start=1
            ):
                receipt = SnapshotRetrievalReceipt(
                    snapshot_id=snapshot_id,
                    query_kind=subquery.query_kind,
                    query_hash=subquery.query_hash,
                    threshold_key=threshold_key,
                    rank=rank,
                    score=score,
                    chunk_id=chunk_id,
                    source_filename=filename,
                    text=text,
                    evidence_id=self._evidence_id(snapshot_id, subquery, threshold_key, chunk_id),
                )
                key = receipt.identity_key()
                previous = merged.get(key)
                if previous is None or self._receipt_sort_key(receipt) < self._receipt_sort_key(
                    previous
                ):
                    merged[key] = receipt
        receipts = tuple(sorted(merged.values(), key=self._receipt_sort_key)[: self.top_k])
        return RetrievalResult(
            snapshot_id=snapshot_id,
            receipts=receipts,
            subqueries=typed,
            strict_calls=strict_calls,
            relaxed_calls=relaxed_calls,
            policy_id=policy_id,
            topic_anchor_hash=topic_anchor_hash,
        )

    @staticmethod
    def _evidence_id(
        snapshot_id: str,
        subquery: TurnSubquery,
        threshold_key: str,
        chunk_id: str,
    ) -> str:
        raw = "\x1f".join(
            (snapshot_id, subquery.query_kind, subquery.query_hash, threshold_key, chunk_id)
        )
        return "evidence-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]

    @staticmethod
    def _receipt_sort_key(
        receipt: SnapshotRetrievalReceipt,
    ) -> tuple[float, int, int, str, str]:
        # Strict wins a tie because it has stronger semantic evidence.  Rank
        # and query kind make equal-score merges deterministic across adapters.
        threshold_order = 0 if receipt.threshold_key == "strict" else 1
        return (
            -receipt.score,
            threshold_order,
            receipt.rank,
            receipt.query_kind,
            receipt.chunk_id,
        )


def _first_other_claim(context: GenerationContext) -> str:
    for predecessor in context.predecessors:
        if predecessor.participant_id != context.participant.participant_id:
            return predecessor.speech
    return "the earlier perspective in this discussion"


def build_turn_subqueries(
    context: GenerationContext,
    *,
    pending_question: PendingQuestion | None = None,
) -> tuple[TurnSubquery, ...]:
    """Build the bounded, typed query set for round one or round two."""

    if getattr(context, "turn_protocol", "legacy_v1") == "segments_v2":
        return build_segment_subqueries(context, barrages=context.barrages)

    position = context.participant.effective_position_summary or "the current position"
    topic = context.topic.strip()
    # New mutual-learning plans use their explicit phase and round barrier.
    # Keep this branch ahead of the legacy round-number vocabulary so adding
    # exchange rounds never changes old v1/v2 retrieval semantics.
    if getattr(context.turn, "barrier", "prefix") == "round":
        if context.turn.phase == "opening":
            return (
                TurnSubquery(
                    "viewpoint",
                    (
                        f"{topic}\nState this participant's independent viewpoint "
                        "and core reasons.\n"
                        f"Current position: {position}"
                    ),
                ),
            )
        question = pending_question or context.effective_pending_question
        mutual_queries: list[TurnSubquery] = []
        if question is not None:
            mutual_queries.append(
                TurnSubquery(
                    "pending_question",
                    f"{topic}\nAnswer this specific question from another participant: "
                    f"{question.text}",
                )
            )
        claim = _first_other_claim(context)
        mutual_queries.append(
            TurnSubquery(
                "rebuttal",
                f"{topic}\nEngage or accurately refine this earlier-round public claim: {claim}",
            )
        )
        mutual_queries.append(
            TurnSubquery(
                "updated_position",
                f"{topic}\nFind evidence that supports or qualifies the updated position: "
                f"{position}",
            )
        )
        return tuple(mutual_queries[:MAX_SUBQUERIES])
    raise RAGRetrievalError(
        "Retrieval supports only the mutual-learning and segments protocols.", technical=False
    )


def _segment_persona_focus(persona: SegmentPersona | AgentMarkdown) -> str:
    """Render only Persona fields useful for evidence matching."""

    if isinstance(persona, AgentMarkdown):
        return f"Agent: {persona.name}\nAgent Markdown:\n{persona.markdown}"
    return "\n".join(
        (
            f"Persona name: {persona.name}",
            f"Role: {persona.identity['role']}",
            f"Cultural lens: {'; '.join(persona.cultural_lens)}",
            f"Initial position: {persona.initial_position}",
        )
    )


def _segment_barrage_rows(rows: Sequence[object]) -> tuple[SegmentBarrage, ...]:
    """Read the already-frozen anonymous pool used by a final turn query."""

    result: list[SegmentBarrage] = []
    for index, row in enumerate(rows, start=1):
        if isinstance(row, SegmentBarrage):
            result.append(row)
            continue
        if not isinstance(row, Mapping):
            raise RAGRetrievalError("A frozen barrage is not a mapping.", technical=False)
        row_id = row.get("id", f"B{index}")
        text = row.get("text")
        if not isinstance(row_id, str) or not isinstance(text, str):
            raise RAGRetrievalError("A frozen barrage has invalid shape.", technical=False)
        try:
            result.append(SegmentBarrage(id=row_id, text=text))
        except ValueError as exc:
            raise RAGRetrievalError("A frozen barrage has invalid text.", technical=False) from exc
    return tuple(result)


def build_segment_subqueries(
    context: GenerationContext,
    *,
    persona: object | None = None,
    barrages: Sequence[object] = (),
) -> tuple[TurnSubquery, ...]:
    """Build the bounded deterministic query set for ``segments_v2``.

    Every teaching round queries the speaker's own knowledge: opening grounds
    the claim, discussion compares the speaker's opening with its question
    target, response uses actual questions, and conclusion checks the considered
    position and frozen classroom questions.  Queries share one embedding batch.
    Complete visible speech remains in the LLM history; no query-planning model
    runs here and no history or barrage text is summarized or truncated there.
    """

    if not isinstance(context, GenerationContext):
        raise RAGRetrievalError("segment retrieval needs a typed context.", technical=False)
    topic = context.topic.strip()
    if not topic:
        raise RAGRetrievalError("segment retrieval needs a topic.", technical=False)
    source_persona = persona if persona is not None else context.participant.persona
    if source_persona is None:
        raise RAGRetrievalError("segments_v2 retrieval needs a compiled Persona.", technical=False)
    try:
        segment_persona = (
            source_persona
            if isinstance(source_persona, SegmentPersona)
            else coerce_persona(source_persona)  # type: ignore[arg-type]
        )
    except (TypeError, ValueError) as exc:
        raise RAGRetrievalError(
            "segments_v2 retrieval Persona is invalid.", technical=False
        ) from exc

    initial_position = (
        context.participant.initial_position_summary
        if isinstance(segment_persona, AgentMarkdown)
        else segment_persona.initial_position
    )
    if context.teaching_protocol == TEACHING_PROTOCOL and context.turn.round_no > 1:
        visible = visible_predecessors(context)
        own_id = context.participant.participant_id
        own_turns = [item for item in visible if item.participant_id == own_id]
        opening = next((item.speech for item in own_turns if item.round_no == 1), "")
        own_position = opening or initial_position
        if context.turn.round_no == 2:
            agents = sorted(context.participants, key=lambda item: item.order_index)
            ids = [item.participant_id for item in agents]
            target_id = ids[(ids.index(own_id) + 1) % len(ids)]
            target_opening = next(
                (
                    item.speech
                    for item in visible
                    if item.round_no == 1 and item.participant_id == target_id
                ),
                "",
            )
            return (
                TurnSubquery(
                    "rebuttal",
                    f"{topic}\nMy opening position and evidence:\n{own_position}\n"
                    f"The other Agent's opening to discuss and question:\n{target_opening}\n"
                    "Find a focused source that supports, qualifies or challenges this comparison.",
                ),
            )
        if context.turn.round_no == 3:
            questions = received_questions(context)
            if questions:
                actual = "\n".join(item["text"] for item in questions)
            else:
                challenges = [
                    item.speech
                    for item in visible
                    if item.round_no == 2 and item.participant_id != own_id
                ]
                if not challenges:
                    raise RAGRetrievalError(
                        "Response round has no question or specific discussion point.",
                        technical=False,
                    )
                actual = challenges[-1]
            return (
                TurnSubquery(
                    "pending_question",
                    f"{topic}\nMy opening position:\n{own_position}\n"
                    f"Answer these actual questions or challenged points:\n{actual}",
                ),
            )
        memory: Mapping[str, object] | None = None
        for item in reversed(own_turns):
            if item.round_no != 3:
                continue
            saved = getattr(item.structured, "discussion_memory", None)
            if isinstance(saved, Mapping):
                memory = cast(Mapping[str, object], saved)
                break
        last_position = own_turns[-1].speech if own_turns else own_position
        final_position = str(memory["position"]) if memory is not None else last_position
        unresolved = str(memory["unresolved_question"]) if memory is not None else ""
        influence = memory.get("influence") if memory is not None else None
        other_point = str(influence["point"]) if isinstance(influence, Mapping) else ""
        if not other_point:
            other_point = next(
                (item.speech for item in reversed(visible) if item.participant_id != own_id), ""
            )
        queries = [
            TurnSubquery(
                "updated_position",
                f"{topic}\nMy considered position after discussion:\n{final_position}\n"
                "Find evidence that supports or limits this final judgment.",
            ),
            TurnSubquery(
                "rebuttal",
                f"{topic}\nThe other Agent's specific point to assess:\n{other_point}\n"
                f"Unresolved question:\n{unresolved}\n"
                "Find evidence for agreement, criticism or a remaining uncertainty.",
            ),
        ]
        frozen_barrages = _segment_barrage_rows(barrages)
        if frozen_barrages:
            barrage_text = "\n\n".join(f"[{item.id}] {item.text}" for item in frozen_barrages)
            queries.append(
                TurnSubquery(
                    "barrage",
                    f"{topic}\nFrozen classroom questions for the conclusion:\n{barrage_text}\n"
                    "Find evidence relevant to the questions without inventing missing facts.",
                )
            )
        return tuple(queries)

    if context.turn.round_no == 1 or getattr(context.turn, "phase", "") == "opening":
        queries = [
            TurnSubquery("viewpoint", topic),
            TurnSubquery(
                "context",
                (
                    f"{topic}\n"
                    "Evidence relevant to this Persona focus:\n"
                    f"{_segment_persona_focus(segment_persona)}"
                ),
            ),
        ]
    else:
        current_position = context.participant.effective_position_summary.strip()
        queries = [
            TurnSubquery(
                "updated_position",
                (f"{topic}\nCurrent position: {current_position or initial_position}"),
            ),
            TurnSubquery(
                "rebuttal",
                f"{topic}\nEvidence for a careful response to earlier-round perspectives.",
            ),
        ]
    frozen_barrages = _segment_barrage_rows(barrages)
    if frozen_barrages:
        barrage_text = "\n\n".join(f"[{item.id}] {item.text}" for item in frozen_barrages)
        queries.append(
            TurnSubquery(
                "barrage",
                (
                    f"Topic:\n{topic}\n"
                    "Frozen anonymous classroom barrages to address in the final turn:\n"
                    f"{barrage_text}\n"
                    "Find evidence relevant to every listed barrage."
                ),
            )
        )
    else:
        queries.append(
            TurnSubquery(
                "updated_position",
                (
                    f"Topic:\n{topic}\n"
                    f"Current Agent focus:\n{_segment_persona_focus(segment_persona)}\n"
                    "Find evidence that supports or qualifies this considered position."
                ),
            )
        )
    return tuple(queries)


__all__ = [
    "MAX_SUBQUERIES",
    "MOCK_LEXICAL_CANDIDATE_LIMIT",
    "RELAXED_THRESHOLD",
    "RAGRetrievalError",
    "RetrievalResult",
    "STRICT_THRESHOLD",
    "SnapshotRetriever",
    "SnapshotSearch",
    "SUBQUERY_KINDS",
    "TOP_K",
    "TurnSubquery",
    "build_segment_subqueries",
    "build_turn_subqueries",
]
