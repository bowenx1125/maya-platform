"""Closed structured-turn validation and deterministic word-boundary helpers."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from typing import Literal

from .policy import TurnPlan
from .types import (
    FinalReadyTurn,
    ParticipantContext,
    PendingQuestion,
    PublicSource,
    SnapshotRetrievalReceipt,
    StructuredTurnResult,
    TurnValidationError,
    ValidatedTurn,
)

# Keep counting deterministic and intentionally conservative.  Punctuation is
# not a word; contractions and hyphenated English words count as one token.
WORD_RE = re.compile(r"[A-Za-z0-9]+(?:['’\-][A-Za-z0-9]+)*")
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
# A sentence may close with a quote or bracket after its terminal punctuation.
# The look-ahead is what prevents an internal decimal/abbreviation from being
# treated as a safe trim point.  If no terminal punctuation exists, the final
# ``$`` branch yields one complete (but only usable when it fits) segment.
_SENTENCE_RE = re.compile(
    r"\S.*?(?:[.!?](?:[\"'’”»)]*)(?=\s|$)|$)",
    re.DOTALL,
)
_WHITESPACE_RE = re.compile(r"\s+")
_SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([,.;:!?])")
_VOTE_PATTERNS = (
    re.compile(r"\b(?:please|kindly|you should|i ask you to)\s+(?:all\s+)?vote\b", re.I),
    re.compile(r"\bvote\s+(?:for|with)\s+(?:me|us|this\s+agent|our\s+side)\b", re.I),
    re.compile(r"\bvote\s+(?:for|with|against)\s+[A-Za-z][\w-]*\b", re.I),
    re.compile(
        r"\b(?:please|kindly|urge|ask|invite|encourage|tell)\b[^.!?]{0,80}"
        r"\b(?:vote|choose|select)\b",
        re.I,
    ),
    re.compile(r"\b(?:choose|select|support)\s+me\b", re.I),
    re.compile(r"\b(?:give|cast)\s+(?:me|us)\s+(?:your\s+)?vote\b", re.I),
    re.compile(r"\b(?:cast|submit)\s+(?:your|a)\s+vote\b", re.I),
    re.compile(r"\b(?:win|winning)\s+this\s+vote\b", re.I),
)
_EXPLICIT_SOURCE_PATTERNS = (
    re.compile(r"\baccording\s+to\b", re.I),
    # Project 5.4 reserves concrete factual numbers for retrieved evidence.
    # General reasoning may compare values qualitatively, but a no-match turn
    # cannot assert a year, count, amount, rate, or other exact numeral.
    re.compile(r"\b\d[\d,]*(?:\.\d+)?\b"),
    re.compile(r"\b\d+(?:\.\d+)?\s*(?:%|percent|percentage\s+points?)\b", re.I),
    re.compile(
        r"\b(?:one|two|three|four|five|six|seven|eight|nine|ten|hundred|thousand|"
        r"million|billion)\s+out\s+of\s+(?:one|two|three|four|five|six|seven|eight|"
        r"nine|ten|hundred|thousand|million|billion)\b",
        re.I,
    ),
    re.compile(
        r"\b(?:one|two|three|four|five|six|seven|eight|nine|ten|hundred|thousand|"
        r"million|billion)(?:\s+(?:hundred|thousand|million|billion))?\s+"
        r"(?:users?|people|cases?|creators?|respondents?|accounts?|countries|studies|"
        r"reports?|dollars?|years?)\b",
        re.I,
    ),
    # Written-out values are concrete factual quantities too. They must not
    # bypass the no-match rule merely because a provider avoids Arabic digits.
    re.compile(
        r"\b(?:a\s+dozen|dozens|a\s+score|scores|half|"
        r"(?:a|one|two|three|four|five|six|seven|eight|nine|ten)[-\s]+"
        r"(?:halves?|thirds?|quarters?|fourths?|fifths?|sixths?|sevenths?|eighths?|"
        r"ninths?|tenths?)|"
        r"hundreds|thousands|millions|billions)\b",
        re.I,
    ),
    re.compile(
        r"\b(?:a\s+)?(?:\d{4}\s+)?(?:survey|poll|study|report|analysis)\s+"
        r"(?:found|concluded|reported|showed|proved|indicated)\b",
        re.I,
    ),
    re.compile(
        r"\b(?:experts?|researchers?|officials?|official\s+figures)"
        r"(?:\s+at\s+[A-Z][\w.-]*(?:\s+[A-Z][\w.-]*){0,3})?\s+"
        r"(?:found|concluded|reported|showed|proved|indicated|confirm(?:ed|s)?)\b",
        re.I,
    ),
    # No-match speech may discuss uncertainty or evidence in the abstract,
    # but it cannot attribute a factual conclusion to unnamed authorities.
    re.compile(
        r"\b(?:experts?|scholars?|researchers?|officials?|"
        r"(?:multiple|several|many|independent)?\s*stud(?:y|ies)|"
        r"(?:multiple|several|many|independent)?\s*reports?|"
        r"(?:multiple|several|many)?\s*(?:surveys?|polls?|analyses))\s+"
        r"(?:(?:have|has|had)\s+)?"
        r"(?:say|says|said|agree|agrees|agreed|establish|establishes|established|"
        r"find|finds|found|conclude|concludes|concluded|report|reports|reported|"
        r"show|shows|showed|prove|proves|proved|indicate|indicates|indicated|"
        r"confirm|confirms|confirmed|suggest|suggests|suggested|"
        r"demonstrate|demonstrates|demonstrated)\b",
        re.I,
    ),
    re.compile(
        r"\b(?:research|stud(?:y|ies)|reports?|statistics?|data)\s+"
        r"(?:show|shows|suggest|suggests|indicate|indicates|demonstrate|demonstrates|"
        r"find|finds)\b",
        re.I,
    ),
    re.compile(
        r"\b(?:the|this|our|an?)\s+(?:knowledge\s+base|database|dataset|document|"
        r"report|study|source|file|evidence)\s+"
        r"(?:says|states|shows|reports|proves|found|indicates)\b",
        re.I,
    ),
    re.compile(
        r"\b(?:based\s+on|as\s+(?:documented|reported|shown)\s+by)\s+"
        r"(?:the\s+)?(?:evidence|research|data|report|study|source|document)\b",
        re.I,
    ),
    re.compile(r"\b(?:source|citation|reference)\s*[:#]\s*\S+", re.I),
    re.compile(r"\[[^\]\n]{1,160}\.(?:md|pdf|txt|csv|html?)\]", re.I),
    re.compile(r"\b[\w.-]+\.(?:md|pdf|txt|csv|html?)\b", re.I),
    re.compile(r"\bhttps?://\S+", re.I),
    re.compile(
        r"\b(?:the|this|our|an?)\s+(?:attached|assigned|provided|retrieved|linked)\s+"
        r"(?:source|document|report|study|file|dataset)\b",
        re.I,
    ),
)


def _words(value: str) -> list[str]:
    return WORD_RE.findall(value)


def _semantic_text(value: str) -> str:
    """Normalize only presentation whitespace/punctuation for containment.

    Providers often add a line break before a question mark or vary the case
    of a returned question.  Those are the same spoken text for the contract;
    this helper does not remove words or permit a paraphrase.
    """

    normalized = unicodedata.normalize("NFKC", value).replace("’", "'")
    normalized = _WHITESPACE_RE.sub(" ", normalized.strip()).casefold()
    return _SPACE_BEFORE_PUNCT_RE.sub(r"\1", normalized)


def _contains_semantic_text(speech: str, text: str) -> bool:
    question = _semantic_text(text)
    return bool(question) and question in _semantic_text(speech)


def assert_speech_language(speech: str, language: str) -> None:
    """Reject a speech written in a language this Debate did not choose.

    The rule was "must be English", asserted separately in two validators. It
    is now the Debate's own choice, checked in one place: a Chinese debate must
    contain Han characters, and an English one must contain none.
    """

    from app.modules.debates.output_language import CJK_RE

    has_cjk = CJK_RE.search(speech) is not None
    if language == "zh":
        if not has_cjk:
            raise TurnValidationError(
                "This debate is generated in Chinese.", json_pointers=("/speech",)
            )
        return
    if has_cjk:
        raise TurnValidationError(
            "Authoritative debate speech must be English.", json_pointers=("/speech",)
        )


def count_turn_words(
    speech: str,
    question_text: str | None = None,
    language: str = "en",
) -> int:
    """Count speech plus a separate question exactly once.

    Providers commonly include their question in the speech body while also
    returning it in the structured field.  If the question is already present
    as a substring it is counted once; otherwise its words are added so a
    metadata-only question cannot evade the length rule.

    A Chinese speech is counted in Han characters: the Latin word pattern finds
    none at all in one, so every Chinese turn would have measured zero words
    and failed the minimum.
    """

    from app.modules.debates.output_language import speech_units

    def measure(value: str) -> int:
        return speech_units(value, "zh") if language == "zh" else len(_words(value))

    count = measure(speech)
    if (
        question_text
        and question_text.strip()
        and not _contains_semantic_text(speech, question_text)
    ):
        count += measure(question_text)
    return count


def has_direct_vote_solicitation(value: str) -> bool:
    return any(pattern.search(value) is not None for pattern in _VOTE_PATTERNS)


def has_explicit_source_claim(value: str) -> bool:
    """Detect a source attribution or concrete quantity without a receipt.

    This intentionally does not reject ordinary words such as ``evidence`` or
    ``research`` on their own.  A no-match turn may still reason about a topic;
    only an attribution/quantity shape (URL, filename, ``according to``, an
    institutional claim, or a concrete factual amount) is rejected.
    """

    return any(pattern.search(value) is not None for pattern in _EXPLICIT_SOURCE_PATTERNS)


def truncate_complete_sentences(speech: str, *, max_words: int = 200) -> str | None:
    """Trim only at complete sentence boundaries and never hard-cut a word."""

    if max_words < 1:
        return None
    if len(_words(speech)) <= max_words:
        return speech.strip()
    candidates: list[str] = []
    for match in _SENTENCE_RE.finditer(speech.strip()):
        sentence = " ".join(match.group(0).split()).strip()
        if sentence:
            candidates.append(sentence)
    if not candidates:
        return None
    prefix: list[str] = []
    best: str | None = None
    for sentence in candidates:
        candidate = " ".join(prefix + [sentence]).strip()
        if len(_words(candidate)) > max_words:
            break
        prefix.append(sentence)
        best = candidate
    return best


def _nonblank(value: str | None, label: str) -> None:
    if value is None or not value.strip():
        raise TurnValidationError(f"{label} is required for this turn.")


def _expected_pending(
    pending_question: PendingQuestion | None,
    participant_id: str,
) -> PendingQuestion | None:
    if pending_question is None:
        return None
    if pending_question.target_participant_id != participant_id:
        raise TurnValidationError("A pending question targets a different participant.")
    return pending_question


class TurnValidator:
    """Server-authoritative validation for one provider result."""

    def __init__(
        self,
        *,
        min_words: int = 80,
        max_words: int = 200,
        language: str = "en",
    ) -> None:
        self.language = language
        if language == "zh":
            from app.modules.debates.output_language import unit_bounds

            min_words, max_words = unit_bounds("zh", min_words, max_words)
        if min_words < 1 or max_words < min_words:
            raise ValueError("invalid turn word bounds")
        self.min_words = min_words
        self.max_words = max_words

    def validate(
        self,
        value: StructuredTurnResult | dict[str, object],
        *,
        plan: TurnPlan,
        participant: ParticipantContext,
        receipts: Sequence[SnapshotRetrievalReceipt] = (),
        predecessors: Sequence[FinalReadyTurn] = (),
        pending_question: PendingQuestion | None = None,
    ) -> ValidatedTurn:
        result = StructuredTurnResult.from_provider(value)
        self._validate_base(result, plan, participant)
        typed_receipts = self._validate_receipts(receipts, participant.snapshot_id)
        used_receipts = self._used_receipts(result, typed_receipts)
        self._validate_prefix(predecessors, plan)
        expected_question = _expected_pending(pending_question, participant.participant_id)
        if plan.round_no == 1:
            self._validate_round_one(result)
        elif plan.round_no == 2:
            self._validate_round_two(
                result,
                plan=plan,
                participant=participant,
                predecessors=predecessors,
                pending_question=expected_question,
                used_receipts=used_receipts,
            )
        else:  # pragma: no cover - TurnPolicy itself prevents this
            raise TurnValidationError("The Demo rule set has only two rounds.")

        question_text = result.question.text if result.question.type != "none" else None
        if question_text is not None and not _contains_semantic_text(result.speech, question_text):
            raise TurnValidationError("The question text must appear in speech.")
        word_count = count_turn_words(result.speech, question_text, self.language)
        if word_count < self.min_words or word_count > self.max_words:
            raise TurnValidationError(
                f"Speech must contain {self.min_words}-{self.max_words} words "
                "including its question."
            )
        combined = result.speech
        if question_text:
            combined += " " + question_text
        if has_direct_vote_solicitation(combined):
            raise TurnValidationError("Direct vote solicitation is not allowed.")

        if used_receipts:
            retrieval_status: Literal["matched", "no_match"] = "matched"
            grounding_mode: Literal["rag_grounded", "mixed", "general_reasoning"] = "mixed"
            sources = tuple(
                PublicSource(
                    source_filename=receipt.source_filename,
                    chunk_id=receipt.chunk_id,
                    evidence_id=receipt.resolved_evidence_id(),
                    rank=receipt.rank,
                    score=receipt.score,
                )
                for receipt in used_receipts
            )
        else:
            if typed_receipts:
                # A retrieval hit that the provider ignores is not allowed to
                # silently become general reasoning: it consumes the shared
                # repair attempt and is surfaced as a structural rule error.
                raise TurnValidationError("Matched retrieval must use at least one evidence ID.")
            if has_explicit_source_claim(result.speech):
                raise TurnValidationError(
                    "A no-match turn cannot make an explicit source attribution "
                    "or concrete factual quantity."
                )
            retrieval_status = "no_match"
            grounding_mode = "general_reasoning"
            sources = ()
        return ValidatedTurn(
            result=result,
            retrieval_status=retrieval_status,
            grounding_mode=grounding_mode,
            used_receipts=used_receipts,
            public_sources=sources,
            word_count=word_count,
        )

    def validate_after_sentence_trim(
        self,
        value: StructuredTurnResult,
        *,
        plan: TurnPlan,
        participant: ParticipantContext,
        receipts: Sequence[SnapshotRetrievalReceipt] = (),
        predecessors: Sequence[FinalReadyTurn] = (),
        pending_question: PendingQuestion | None = None,
    ) -> ValidatedTurn:
        """Retry every structural rule after a complete-sentence trim."""

        question_text = value.question.text if value.question.type != "none" else None
        if question_text and not _contains_semantic_text(value.speech, question_text):
            raise TurnValidationError("The question text must appear in speech.")
        # The question is required to be inside ``speech``.  Do not subtract
        # its words a second time: ``count_turn_words`` counts it once, and a
        # sentence trim must preserve the complete sentence containing it.
        trimmed = truncate_complete_sentences(value.speech, max_words=self.max_words)
        if trimmed is None:
            raise TurnValidationError("No complete-sentence boundary satisfies the word limit.")
        if question_text and not _contains_semantic_text(trimmed, question_text):
            raise TurnValidationError("Sentence trimming would remove the required question.")
        candidate = value.model_copy(update={"speech": trimmed})
        return self.validate(
            candidate,
            plan=plan,
            participant=participant,
            receipts=receipts,
            predecessors=predecessors,
            pending_question=pending_question,
        )

    def _validate_base(
        self,
        result: StructuredTurnResult,
        plan: TurnPlan,
        participant: ParticipantContext,
    ) -> None:
        if plan.participant_id != participant.participant_id:
            raise TurnValidationError("The turn plan and participant do not match.")
        assert_speech_language(result.speech, self.language)
        if not result.speech.strip():
            raise TurnValidationError("Speech cannot be blank.")
        if participant.stance_mode == "open" and result.new_stance is not None:
            raise TurnValidationError("An open participant cannot synthesize an enum stance.")
        if result.position_update == "switched" and participant.stance_mode != "assigned":
            raise TurnValidationError("Only an assigned participant may switch stance.")
        if result.position_update != "unchanged":
            _nonblank(result.position_update_reason, "position_update_reason")

    @staticmethod
    def _validate_receipts(
        receipts: Sequence[SnapshotRetrievalReceipt], snapshot_id: str
    ) -> tuple[SnapshotRetrievalReceipt, ...]:
        result = tuple(receipts)
        ids: set[str] = set()
        for receipt in result:
            if receipt.snapshot_id != snapshot_id:
                raise TurnValidationError("A receipt belongs to another participant snapshot.")
            evidence_id = receipt.resolved_evidence_id()
            if evidence_id in ids:
                raise TurnValidationError("Retrieval receipts contain a duplicate evidence ID.")
            ids.add(evidence_id)
        return result

    @staticmethod
    def _used_receipts(
        result: StructuredTurnResult,
        receipts: Sequence[SnapshotRetrievalReceipt],
    ) -> tuple[SnapshotRetrievalReceipt, ...]:
        available = {receipt.resolved_evidence_id(): receipt for receipt in receipts}
        used_ids = tuple(result.used_evidence_id)
        if len(used_ids) != len(set(used_ids)):
            raise TurnValidationError("used_evidence_id must be unique.")
        unknown = [evidence_id for evidence_id in used_ids if evidence_id not in available]
        if unknown:
            raise TurnValidationError(
                "The provider returned a forged or cross-request evidence ID."
            )
        return tuple(available[evidence_id] for evidence_id in used_ids)

    @staticmethod
    def _validate_prefix(
        predecessors: Sequence[FinalReadyTurn], plan: TurnPlan
    ) -> tuple[FinalReadyTurn, ...]:
        ordered = tuple(sorted(predecessors, key=lambda item: item.turn_index))
        if tuple(item.turn_index for item in ordered) != tuple(range(plan.turn_index)):
            raise TurnValidationError("The predecessor set is not the complete planned prefix.")
        if tuple(item.turn_id for item in ordered) != plan.predecessor_turn_ids:
            raise TurnValidationError("The predecessor IDs do not match the planned prefix.")
        for predecessor in ordered:
            if predecessor.publication_status not in {"final_ready", "public"}:
                raise TurnValidationError("A predecessor is not final-ready.")
        return ordered

    @staticmethod
    def _validate_round_one(result: StructuredTurnResult) -> None:
        if result.answered_question_id is not None:
            raise TurnValidationError("Round one cannot answer a pending question.")
        if result.rebuttal_target_turn_id is not None:
            raise TurnValidationError("Round one cannot rebut an earlier turn.")
        if result.question.type != "none" or result.question.target_participant_id is not None:
            raise TurnValidationError("Round one has no participant question.")
        if result.question.text is not None:
            raise TurnValidationError("Round one has no question text.")
        _nonblank(result.new_argument_summary, "new_argument_summary")
        _nonblank(result.turn_summary, "turn_summary")
        _nonblank(result.position_summary, "position_summary")
        if result.position_update != "unchanged" or result.new_stance is not None:
            raise TurnValidationError("Round one cannot update an assigned position yet.")

    @staticmethod
    def _validate_round_two(
        result: StructuredTurnResult,
        *,
        plan: TurnPlan,
        participant: ParticipantContext,
        predecessors: Sequence[FinalReadyTurn],
        pending_question: PendingQuestion | None,
        used_receipts: Sequence[SnapshotRetrievalReceipt],
    ) -> None:
        prior = tuple(predecessors)
        if not prior:
            raise TurnValidationError("Round two needs earlier final-ready turns.")
        target = result.rebuttal_target_turn_id
        if target is None:
            raise TurnValidationError("Round two must rebut a specific earlier turn.")
        target_turn = next((item for item in prior if item.turn_id == target), None)
        if target_turn is None:
            raise TurnValidationError("The rebuttal target is not a final-ready predecessor.")
        if target_turn.participant_id == participant.participant_id:
            raise TurnValidationError("A participant cannot rebut its own earlier turn.")
        _nonblank(result.rebuttal_summary, "rebuttal_summary")
        _nonblank(result.new_argument_summary, "new_argument_summary")
        _nonblank(result.turn_summary, "turn_summary")
        _nonblank(result.position_summary, "position_summary")

        if pending_question is None:
            if result.answered_question_id is not None:
                raise TurnValidationError("There is no pending question for this turn.")
        elif result.answered_question_id != pending_question.question_id:
            raise TurnValidationError("The assigned question was not answered by exact ID.")

        if plan.is_final:
            if result.question.type != "audience_reflection":
                raise TurnValidationError(
                    "The final turn must ask an audience reflection question."
                )
            if result.question.target_participant_id is not None:
                raise TurnValidationError("An audience reflection has no participant target.")
        else:
            if result.question.type != "agent":
                raise TurnValidationError(
                    "A non-final round-two turn must ask the next participant."
                )
            if result.question.target_participant_id != plan.next_participant_id:
                raise TurnValidationError(
                    "The question target is not the next planned participant."
                )
        _nonblank(result.question.text, "question.text")

        if participant.stance_mode == "assigned" and result.position_update == "switched":
            if result.new_stance is None:
                raise TurnValidationError("A switched assigned stance needs new_stance.")
            current_stance = participant.current_stance or participant.initial_stance
            if result.new_stance == current_stance:
                raise TurnValidationError("A switched stance must differ from current_stance.")
            if not used_receipts and target_turn is None:  # defensive, target is checked above
                raise TurnValidationError("A switched stance needs an influencing source.")
        elif result.new_stance is not None:
            raise TurnValidationError("new_stance is only allowed for an assigned switch.")


def final_ready_turn(
    validated: ValidatedTurn,
    *,
    turn_id: str,
    participant_id: str,
    snapshot_id: str,
    round_no: int,
    turn_index: int,
    predecessor_turn_ids: Sequence[str],
    cutoff_turn_index: int,
    transcript_hash: str,
    attempt: int,
) -> FinalReadyTurn:
    if attempt not in {1, 2}:
        raise ValueError("turn attempt must be one or two")
    return FinalReadyTurn(
        turn_id=turn_id,
        participant_id=participant_id,
        snapshot_id=snapshot_id,
        round_no=round_no,
        turn_index=turn_index,
        speech=validated.result.speech,
        structured=validated.result,
        retrieval_status=validated.retrieval_status,
        grounding_mode=validated.grounding_mode,
        used_receipts=validated.used_receipts,
        predecessor_turn_ids=tuple(predecessor_turn_ids),
        cutoff_turn_index=cutoff_turn_index,
        transcript_hash=transcript_hash,
        attempt=attempt,  # type: ignore[arg-type]
        evidence_trace=validated.evidence_trace,
    )


__all__ = [
    "WORD_RE",
    "TurnValidator",
    "count_turn_words",
    "final_ready_turn",
    "has_direct_vote_solicitation",
    "has_explicit_source_claim",
    "truncate_complete_sentences",
]
