"""M14 persistence, report input boundaries and Mock generation service.

This file intentionally consumes interaction data through SQL projections
rather than importing M13's implementation details.  The only values that
cross the anonymous boundary are frozen ``message_id`` and ``raw_text``;
nickname rows are never selected by the insight policy or report builder.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol, cast
from uuid import UUID, uuid4

from sqlalchemy import delete, inspect, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import (
    PlatformError,
    conflict,
    forbidden,
    idempotency_conflict,
    invalid_state,
    not_found,
)
from app.core.models import (
    CourseMember,
    DemoAcceptanceRun,
    IdempotencyRecord,
    Job,
    KnowledgeChunk,
    ProviderExportManifest,
    ProviderOperation,
    ProviderPolicySnapshot,
)
from app.modules.debates.final_input import read_final_input
from app.modules.debates.generation.segment_grading import (
    AgentGradeSummary,
    SegmentGradingError,
    aggregate_agent_scores,
)
from app.modules.debates.models import Debate, DebateParticipant, DebateTurn, TurnSource
from app.modules.debates.output_language import debate_output_language
from app.modules.debates.playback.eligibility import has_complete_finished_playback
from app.modules.debates.round_count import (
    debate_round_count,
    uses_segment_protocol,
)
from app.modules.debates.round_count import (
    expected_turn_count as planned_turn_count,
)
from app.modules.interactions.models import BarrageMessage
from app.providers.control import (
    LLM_MAYA_REPORT_BUCKET,
    ExportConfirmationV1,
    ExportFieldV1,
    ExportManifestV1,
    ProviderReservationRequestV1,
    ProviderScopeBudgetV1,
)
from app.providers.llm_price_card import LLM_RESERVED_OUTPUT_TOKEN_CAP
from app.providers.llm_privacy import LLM_ANONYMOUS_BARRAGE_FIELD_CLASS

from .models import (
    BarrageInsightAssignment,
    BarrageInsightSnapshot,
    CivilizationReport,
    CivilizationReportCurrentSuccess,
    CivilizationReportRevision,
)
from .models import (
    BarrageInsightItem as BarrageInsightItemRow,
)
from .policy import (
    MOCK_BARRAGE_INSIGHT_POLICY_KEY,
    MOCK_MAYA_REPORT_POLICY_KEY,
    mock_barrage_insight_v1,
    validate_insight_partition,
)
from .real_prompt import ReportWireRequest
from .real_provider import REAL_REPORT_MODEL, ReportProviderError
from .real_schema import (
    ReportBarrage,
    ReportInsight,
    ReportParticipant,
    ReportReply,
    ReportRequest,
    ReportRequestV2,
    ReportSource,
    ReportSpeech,
    ReportVote,
)
from .schemas import (
    BarrageInsight,
    FailedReportRevision,
    GeneratingReportRevision,
    ManifestBarrage,
    ManifestInsight,
    ManifestInsightItem,
    ManifestParticipant,
    ManifestReply,
    ManifestTurn,
    ManifestTurnSource,
    ManifestTurnSourceV2,
    ManifestTurnV2,
    ManifestVote,
    MockBarrageInsightResult,
    ReadyReportRevision,
    Report,
    ReportAgentScore,
    ReportInputManifestV1,
    ReportInputManifestV2,
    ReportRevision,
    ReportRevisionSummary,
    ReportScoreSummary,
    ReportSectionOutput,
)
from .schemas import (
    BarrageInsightItem as BarrageInsightItemDTO,
)

LOGGER = logging.getLogger(__name__)

WORD_RE = re.compile(r"[A-Za-z0-9]+(?:['’\-][A-Za-z0-9]+)*")
REPORT_GENERATE_OPERATION = "report.generate"
# How many times a teacher may ask for a report on one Debate, and how many
# provider calls one of those asks may make. The scope budget is sized from
# these so the buttons the product shows can all actually be pressed.
REPORT_REGENERATION_CAP = 5
REPORT_ATTEMPT_CAP = 2
REPORT_HEADINGS = (
    "# Civilization Mutual Learning Report",
    "## Debate Overview",
    "## Evidence and Arguments",
    "## Areas of Convergence",
    "## Continuing Tensions and Questions",
    "## Classroom Perspectives",
    "## Mutual Learning Reflection",
)
_CITATION_RE = re.compile(r"\[evidence:([A-Za-z0-9_.:-]{1,128})\]")
_UNSAFE_REPORT_TERMS_RE = re.compile(
    r"\b(?:winner|winners|won|winning|vote\s+for\s+me|please\s+vote|nickname)\b",
    re.IGNORECASE,
)
_REPORT_PADDING_SENTENCE = (
    "This record supports careful comparison, source checking, respectful questioning, "
    "and revision after dialogue."
)


class RealReportProviderPort(Protocol):
    """Narrow provider seam used by the report worker and fake transports."""

    def build_request(self, value: ReportRequest) -> ReportWireRequest: ...

    def execute_prepared(self, value: ReportWireRequest) -> ReportSectionOutput: ...


class RealReportRepositoryPort(Protocol):
    """The durable operation methods required by one-shot Real Report."""

    def get_policy_snapshot(self, reference: str) -> Any: ...

    def ensure_export_manifest(self, manifest: ExportManifestV1, **kwargs: Any) -> str: ...

    def get_export_manifest(self, reference: str) -> ExportManifestV1 | None: ...

    def create_prepared(self, request: ProviderReservationRequestV1) -> Any: ...

    def get(self, operation_id: str) -> Any: ...

    def ensure_scope_budget(self, scope_id: str, budget: ProviderScopeBudgetV1) -> None: ...

    def assert_hashes_current(self, request: ProviderReservationRequestV1) -> None: ...

    def reserve(self, operation_id: str) -> Any: ...

    def transition(self, operation_id: str, **kwargs: Any) -> Any: ...

    def mark_failed(self, operation_id: str, *, safe_error_code: str) -> Any: ...

    def mark_not_sent(self, operation_id: str, *, safe_error_code: str) -> Any: ...

    def mark_acceptance_unknown(self, operation_id: str, *, safe_error_code: str) -> Any: ...

    def complete_report_in_session(
        self,
        db: Session,
        operation_id: str,
        *,
        response_hash: str,
    ) -> Any: ...


@dataclass(frozen=True, slots=True)
class RealReportRuntime:
    """One-shot report provider plus its server-side control repository."""

    provider: RealReportProviderPort
    repository: Any


def utc_now() -> datetime:
    return datetime.now(UTC)


def _uuid(value: str | UUID) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))


def _sha256(value: str | bytes) -> str:
    payload = value if isinstance(value, bytes) else value.encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _has_table(db: Session, table_name: str) -> bool:
    bind = db.get_bind()
    return bool(inspect(bind).has_table(table_name))


def _require_teacher(db: Session, actor_user_id: str, debate_id: str) -> Debate:
    debate = db.get(Debate, debate_id)
    if debate is None:
        raise not_found()
    role = db.scalar(
        select(CourseMember.role).where(
            CourseMember.course_id == debate.course_id,
            CourseMember.user_id == actor_user_id,
        )
    )
    if role is None:
        raise not_found()
    if role != "teacher":
        raise forbidden()
    # Partial Finish is product-level ``debate_finished`` but its playback is
    # terminal stopped. Require the complete public two-round plan for every
    # report/history read and generation command.
    if debate.status == "stopped" or (
        debate.status in {"debate_finished", "completed"}
        and not has_complete_finished_playback(db, debate_id)
    ):
        raise not_found()
    return debate


def _window_row(db: Session, debate_id: str) -> Mapping[str, Any] | None:
    if not _has_table(db, "classroom_interaction_windows"):
        return None
    row = (
        db.execute(
            text(
                "SELECT id, debate_id, status, frozen_barrage_ids_json, "
                "frozen_barrage_input_hash, frozen_vote_totals_json, frozen_vote_input_hash, "
                "frozen_barrage_count, frozen_vote_count "
                "FROM classroom_interaction_windows WHERE debate_id=:debate_id"
            ),
            {"debate_id": debate_id},
        )
        .mappings()
        .first()
    )
    return cast(Mapping[str, Any] | None, row)


def _json_list(value: Any) -> list[str]:
    if not isinstance(value, str):
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return []
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        return []
    return list(parsed)


def _frozen_message_rows(db: Session, window: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    ids = _json_list(window.get("frozen_barrage_ids_json"))
    if len(ids) != len(set(ids)):
        raise invalid_state("The finalized classroom interaction snapshot is inconsistent.")
    if not _has_table(db, "barrage_messages"):
        return []
    rows = (
        db.execute(
            text(
                "SELECT id, sequence, raw_text FROM barrage_messages "
                "WHERE window_id=:window_id AND debate_id=:debate_id"
            ),
            {"window_id": window["id"], "debate_id": window["debate_id"]},
        )
        .mappings()
        .all()
    )
    by_id = {str(row["id"]): row for row in rows}
    # A missing frozen ID is an immutable-boundary failure, not permission to
    # silently feed a shorter input to the policy.
    if any(message_id not in by_id for message_id in ids):
        raise invalid_state("The frozen classroom interaction input is incomplete.")
    if _has_table(db, "interaction_final_barrages"):
        final_rows = (
            db.execute(
                text(
                    "SELECT barrage_message_id, sequence FROM interaction_final_barrages "
                    "WHERE window_id=:window_id AND debate_id=:debate_id "
                    "ORDER BY sequence, barrage_message_id"
                ),
                {"window_id": window["id"], "debate_id": window["debate_id"]},
            )
            .mappings()
            .all()
        )
        final_ids = [str(row["barrage_message_id"]) for row in final_rows]
        if final_ids != ids:
            raise invalid_state("The normalized frozen classroom input is inconsistent.")
    frozen_rows = [cast(Mapping[str, Any], by_id[message_id]) for message_id in ids]
    frozen_inputs = [
        {"message_id": str(row["id"]), "raw_text": str(row["raw_text"])} for row in frozen_rows
    ]
    expected_hash = _sha256(
        json.dumps(
            frozen_inputs,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    try:
        frozen_count_value = window.get("frozen_barrage_count")
        if frozen_count_value is None:
            raise TypeError
        frozen_count = int(cast(str | int, frozen_count_value))
    except (TypeError, ValueError):
        raise invalid_state("The finalized classroom snapshot has no barrage count.") from None
    if (
        frozen_count != len(frozen_rows)
        or str(window.get("frozen_barrage_input_hash")) != expected_hash
    ):
        raise invalid_state("The finalized classroom barrage snapshot is inconsistent.")
    return frozen_rows


def _final_vote_rows(db: Session, debate_id: str, window_id: str) -> list[Mapping[str, Any]]:
    if not _has_table(db, "interaction_final_vote_counts"):
        return []
    rows = (
        db.execute(
            text(
                "SELECT participant_id, count FROM interaction_final_vote_counts "
                "WHERE window_id=:window_id AND debate_id=:debate_id"
            ),
            {"window_id": window_id, "debate_id": debate_id},
        )
        .mappings()
        .all()
    )
    return [cast(Mapping[str, Any], row) for row in rows]


def _verify_frozen_vote_projection(
    window: Mapping[str, Any],
    participants: Sequence[DebateParticipant],
    final_votes: Sequence[Mapping[str, Any]],
) -> None:
    """Verify M13's immutable final vote rows before report consumption."""

    if not final_votes and window.get("frozen_vote_totals_json") is None:
        return
    counts: dict[str, int] = {}
    for row in final_votes:
        participant_id = str(row["participant_id"])
        if participant_id in counts:
            raise invalid_state("The finalized vote snapshot contains a duplicate participant.")
        try:
            count = int(row["count"])
        except (TypeError, ValueError):
            raise invalid_state("The finalized vote snapshot has an invalid count.") from None
        if count < 0:
            raise invalid_state("The finalized vote snapshot has a negative count.")
        counts[participant_id] = count
    expected: list[dict[str, str | int]] = [
        {
            "participant_id": str(participant.id),
            "count": counts.get(str(participant.id), 0),
        }
        for participant in participants
    ]
    if set(counts) != {str(participant.id) for participant in participants}:
        raise invalid_state("The finalized vote snapshot is incomplete.")
    canonical = json.dumps(expected, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    try:
        frozen_vote_count_value = window.get("frozen_vote_count")
        if frozen_vote_count_value is None:
            raise TypeError
        frozen_vote_count = int(cast(str | int, frozen_vote_count_value))
    except (TypeError, ValueError):
        raise invalid_state("The finalized classroom snapshot has no vote count.") from None
    if (
        str(window.get("frozen_vote_totals_json")) != canonical
        or str(window.get("frozen_vote_input_hash")) != _sha256(canonical)
        or frozen_vote_count != sum(int(item["count"]) for item in expected)
    ):
        raise invalid_state("The finalized classroom vote snapshot is inconsistent.")


@dataclass(frozen=True)
class ReportSourceContext:
    turn_source_id: UUID
    turn_id: UUID
    turn_index: int
    rank: int
    snapshot_id: UUID
    chunk_id: UUID
    source_filename: str
    chunk_text: str
    evidence_id: str = ""


@dataclass(frozen=True)
class ReportTurnContext:
    turn_id: UUID
    participant_id: UUID
    participant_name: str
    round_no: int
    turn_index: int
    speech: str
    used_evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReportBarrageContext:
    """An anonymous, frozen final-input candidate kept out of legacy reports."""

    barrage_id: str
    turn_index: int
    text: str


@dataclass(frozen=True)
class ReportReplyContext:
    """One actual segment paragraph binding to a frozen barrage candidate."""

    barrage_id: str
    slot: str
    turn_index: int
    paragraph_index: int


def _segment_turn_payload(
    turn: DebateTurn,
) -> tuple[tuple[str, ...], tuple[tuple[int, str], ...], tuple[object, ...]]:
    """Read the closed persisted segment shape without inventing legacy fields."""

    from app.modules.debates.generation.segments import load_stored_segment_turn_result

    try:
        value = json.loads(str(turn.structured_json or ""))
        result = load_stored_segment_turn_result(value)
        if result.speech != turn.speech:
            raise ValueError("paragraph text differs from saved speech")
    except (TypeError, ValueError):
        raise invalid_state("A segment turn has invalid saved paragraphs.") from None
    return (
        result.used_evidence_ids,
        tuple(
            (index, segment.reply_to)
            for index, segment in enumerate(result.segments)
            if segment.reply_to is not None
        ),
        result.segments,
    )


def _segment_final_input(
    db: Session,
    debate: Debate,
    turns: Sequence[DebateTurn],
    frozen_barrages: Sequence[Mapping[str, Any]],
) -> tuple[tuple[ReportBarrageContext, ...], dict[str, str]]:
    """Project the immutable final-input pool to opaque B IDs and turn indexes."""

    value = read_final_input(debate)
    if value is None:
        raise invalid_state("A segment Debate has no frozen final input.")
    candidates = value.get("barrages")
    message_ids = value.get("message_ids")
    if not isinstance(candidates, list) or not isinstance(message_ids, list):
        raise invalid_state("The frozen final input has an invalid barrage shape.")
    if len(candidates) != len(message_ids):
        raise invalid_state("The frozen final input barrage mapping is incomplete.")
    frozen_by_id = {str(row["id"]): row for row in frozen_barrages}
    turn_indexes = {str(row.id): row.turn_index for row in turns}
    rows = list(
        db.scalars(
            select(BarrageMessage).where(
                BarrageMessage.debate_id == debate.id,
                BarrageMessage.id.in_([str(item) for item in message_ids]),
            )
        ).all()
    )
    row_by_id = {str(row.id): row for row in rows}
    contexts: list[ReportBarrageContext] = []
    b_to_message: dict[str, str] = {}
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, Mapping):
            raise invalid_state("The frozen final input has an invalid barrage.")
        barrage_id = candidate.get("id")
        text_value = candidate.get("text")
        message_id = str(message_ids[index])
        if (
            not isinstance(barrage_id, str)
            or re.fullmatch(r"B[1-9][0-9]*", barrage_id) is None
            or not isinstance(text_value, str)
            or not text_value.strip()
            or message_id not in frozen_by_id
            or message_id not in row_by_id
        ):
            raise invalid_state("The frozen final input barrage is not an immutable classroom row.")
        row = row_by_id[message_id]
        if row.turn_id is None or str(row.turn_id) not in turn_indexes:
            raise invalid_state("The frozen final input barrage is outside the prepared turns.")
        contexts.append(
            ReportBarrageContext(
                barrage_id=barrage_id,
                turn_index=turn_indexes[str(row.turn_id)],
                text=text_value,
            )
        )
        b_to_message[barrage_id] = message_id
    if len(b_to_message) != len(contexts):
        raise invalid_state("The frozen final input has duplicate barrage IDs.")
    return tuple(contexts), b_to_message


@dataclass(frozen=True)
class ReportContext:
    debate: Debate
    manifest: ReportInputManifestV1 | ReportInputManifestV2
    turns: tuple[ReportTurnContext, ...]
    sources: tuple[ReportSourceContext, ...]
    vote_total: int
    barrage_total: int
    classroom_barrages: tuple[ReportBarrageContext, ...] = ()
    replies: tuple[ReportReplyContext, ...] = ()
    protocol_version: str = "legacy_v1"
    score_summary: ReportScoreSummary | None = None


class ReportInsightEnqueuer:
    """M13 close adapter that creates the immutable M14 snapshot and Job.

    The interaction module depends only on this tiny protocol.  It never
    imports report models or runs policy code inside its anonymous writer.
    """

    def enqueue_after_interaction_close(
        self,
        session: Session,
        *,
        window: Any,
        input_hash: str,
    ) -> None:
        snapshot = create_insight_snapshot(
            session,
            debate_id=str(window.debate_id),
            window_id=str(window.id),
            input_hash=input_hash,
            revision_no=1,
        )
        ensure_insight_job(session, snapshot)


def _validate_db_insight_partition(
    db: Session,
    snapshot: BarrageInsightSnapshot,
    frozen_message_ids: Sequence[str],
) -> tuple[int, int, dict[str, int]]:
    assignments = list(
        db.scalars(
            select(BarrageInsightAssignment).where(
                BarrageInsightAssignment.snapshot_id == snapshot.id
            )
        ).all()
    )
    frozen = [str(value) for value in frozen_message_ids]
    if len(assignments) != len(frozen):
        raise invalid_state("The insight assignment partition is incomplete.")
    seen: set[str] = set()
    item_counts: dict[str, int] = {}
    included = 0
    filtered = 0
    for assignment in assignments:
        message_id = str(assignment.barrage_message_id)
        if message_id in seen or message_id not in set(frozen):
            raise invalid_state("The insight assignment partition is invalid.")
        seen.add(message_id)
        if assignment.disposition == "included":
            if assignment.item_id is None or assignment.filter_reason is not None:
                raise invalid_state("The included insight assignment is invalid.")
            included += 1
            item_counts[str(assignment.item_id)] = item_counts.get(str(assignment.item_id), 0) + 1
        elif assignment.disposition == "filtered":
            if assignment.item_id is not None or not (
                assignment.filter_reason
                and assignment.filter_reason.startswith(f"{MOCK_BARRAGE_INSIGHT_POLICY_KEY}:")
            ):
                raise invalid_state("The filtered insight assignment is invalid.")
            filtered += 1
        else:
            raise invalid_state("The insight assignment disposition is invalid.")
    if seen != set(frozen):
        raise invalid_state("The insight assignment partition does not match frozen input.")
    return included, filtered, item_counts


def create_insight_snapshot(
    db: Session,
    *,
    debate_id: str,
    window_id: str,
    input_hash: str,
    revision_no: int = 1,
) -> BarrageInsightSnapshot:
    """Create one immutable generating snapshot (called by M13 close/retry)."""

    existing = db.scalar(
        select(BarrageInsightSnapshot).where(
            BarrageInsightSnapshot.debate_id == debate_id,
            BarrageInsightSnapshot.revision_no == revision_no,
        )
    )
    if existing is not None:
        return existing
    now = utc_now()
    snapshot = BarrageInsightSnapshot(
        id=str(uuid4()),
        window_id=window_id,
        debate_id=debate_id,
        revision_no=revision_no,
        policy_key=MOCK_BARRAGE_INSIGHT_POLICY_KEY,
        status="generating",
        attempt=1,
        input_hash=input_hash,
        included_count=0,
        filtered_count=0,
        safe_error_code=None,
        created_at=now,
        updated_at=now,
    )
    db.add(snapshot)
    db.flush()
    return snapshot


def _next_snapshot_revision(db: Session, debate_id: str) -> int:
    value = db.scalar(
        select(BarrageInsightSnapshot.revision_no)
        .where(BarrageInsightSnapshot.debate_id == debate_id)
        .order_by(BarrageInsightSnapshot.revision_no.desc())
    )
    return int(value or 0) + 1


def _insert_generation_job(
    db: Session,
    *,
    debate_id: str,
    operation: str,
    owner_column: str,
    owner_id: str,
) -> Job:
    """Insert one typed-owner Job without requiring pre-0007 ORM columns."""

    table_columns = set(Job.__table__.c.keys())
    existing: Job | None = None
    if owner_column in table_columns:
        existing = db.scalar(
            select(Job).where(
                getattr(Job, owner_column) == owner_id,
                Job.operation == operation,
            )
        )
    else:
        existing = db.scalar(
            select(Job).where(
                Job.operation == operation,
                Job.idempotency_key == f"{operation}:{owner_id}",
            )
        )
    if existing is not None:
        return existing
    values: dict[str, Any] = {
        "id": str(uuid4()),
        "debate_id": debate_id,
        "idempotency_key": f"{operation}:{owner_id}",
        "operation": operation,
        "state": "pending",
        "safe_error_code": None,
        "attempt": 0,
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }
    if owner_column in table_columns:
        values[owner_column] = owner_id
    job = Job(**values)
    db.add(job)
    db.flush()
    return job


def ensure_insight_job(db: Session, snapshot: BarrageInsightSnapshot) -> Job:
    return _insert_generation_job(
        db,
        debate_id=snapshot.debate_id,
        operation="barrage_insight.generate",
        owner_column="insight_snapshot_id",
        owner_id=snapshot.id,
    )


def ensure_report_job(db: Session, revision: CivilizationReportRevision) -> Job:
    return _insert_generation_job(
        db,
        debate_id=revision.debate_id,
        operation="report.generate",
        owner_column="report_revision_id",
        owner_id=revision.id,
    )


def _snapshot_input(db: Session, snapshot: BarrageInsightSnapshot) -> list[dict[str, Any]]:
    window = _window_row(db, snapshot.debate_id)
    if window is None or str(window.get("id")) != snapshot.window_id:
        raise invalid_state("The interaction window for this insight is unavailable.")
    if window.get("status") != "finalized":
        raise invalid_state("Classroom interaction must be finalized first.")
    rows = _frozen_message_rows(db, window)
    return [{"message_id": _uuid(str(row["id"])), "raw_text": str(row["raw_text"])} for row in rows]


def process_insight_snapshot(
    db: Session,
    snapshot_id: str,
    *,
    policy: Any = mock_barrage_insight_v1,
) -> BarrageInsightSnapshot:
    """Run one insight job with a shared attempt-2 repair and persist its rows."""

    snapshot = db.get(BarrageInsightSnapshot, snapshot_id)
    if snapshot is None:
        raise not_found()
    if snapshot.status == "ready":
        return snapshot
    if snapshot.status == "failed":
        return snapshot
    payload = _snapshot_input(db, snapshot)
    canonical_payload = json.dumps(
        [
            {"message_id": str(item["message_id"]), "raw_text": str(item["raw_text"])}
            for item in payload
        ],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    if snapshot.input_hash != _sha256(canonical_payload):
        # A mismatched frozen hash is an integrity failure, not a provider
        # retry condition.  Fail the derived attempt without exposing any
        # raw classroom content or leaving its Job running.
        if not _job_is_running(db, "barrage_insight.generate", snapshot.id):
            db.rollback()
            current = db.get(BarrageInsightSnapshot, snapshot_id)
            if current is None:
                raise not_found()
            return current
        snapshot.status = "failed"
        snapshot.attempt = min(max(snapshot.attempt, 1), 2)
        snapshot.safe_error_code = "insight_input_integrity_failed"
        snapshot.included_count = 0
        snapshot.filtered_count = 0
        snapshot.updated_at = utc_now()
        _mark_job_failed(
            db,
            "barrage_insight.generate",
            snapshot.id,
            "insight_input_integrity_failed",
            attempt=snapshot.attempt,
        )
        db.flush()
        _mark_debate_completed(db, snapshot.debate_id)
        return snapshot
    try:
        result = policy(payload)
        result = validate_insight_partition([item["message_id"] for item in payload], result)
    except Exception as first_error:
        snapshot.attempt = 2
        snapshot.updated_at = utc_now()
        try:
            result = policy(payload)
            result = validate_insight_partition([item["message_id"] for item in payload], result)
        except Exception as second_error:
            if not _job_is_running(db, "barrage_insight.generate", snapshot.id):
                db.rollback()
                current = db.get(BarrageInsightSnapshot, snapshot_id)
                if current is None:
                    raise not_found() from None
                return current
            snapshot.status = "failed"
            snapshot.attempt = 2
            snapshot.safe_error_code = "insight_generation_failed"
            snapshot.included_count = 0
            # Failed generation has no validated assignment rows; counts are
            # therefore deliberately zero rather than a model-claimed
            # projection of the frozen input.
            snapshot.filtered_count = 0
            snapshot.updated_at = utc_now()
            _mark_job_failed(
                db,
                "barrage_insight.generate",
                snapshot.id,
                "insight_generation_failed",
                attempt=2,
            )
            if isinstance(first_error, PlatformError) or isinstance(second_error, PlatformError):
                # Keep this branch intentionally quiet; provider/policy error
                # details never cross the report API boundary.
                pass
            db.flush()
            _mark_debate_completed(db, snapshot.debate_id)
            return snapshot

    if not _job_is_running(db, "barrage_insight.generate", snapshot.id):
        db.rollback()
        current = db.get(BarrageInsightSnapshot, snapshot_id)
        if current is None:
            raise not_found()
        return current
    _persist_insight_result(db, snapshot, result)
    snapshot.status = "ready"
    snapshot.attempt = min(max(snapshot.attempt, 1), 2)
    snapshot.safe_error_code = None
    snapshot.included_count = result.included_count
    snapshot.filtered_count = result.filtered_count
    snapshot.updated_at = utc_now()
    _mark_job_completed(
        db,
        "barrage_insight.generate",
        snapshot.id,
        attempt=snapshot.attempt,
    )
    db.flush()
    debate = db.get(Debate, snapshot.debate_id)
    if debate is not None and not uses_segment_protocol(debate):
        _create_report_revision_for_insight(db, snapshot, trigger="automatic", requested_by=None)
    elif debate is not None:
        requested = db.scalar(
            select(CivilizationReport).where(CivilizationReport.debate_id == debate.id)
        )
        if requested is not None and requested.generation_status == "generating":
            _create_report_revision_for_insight(db, snapshot, trigger="manual", requested_by=None)
    # Paragraph lessons wait for the explicit Bench Report action.
    db.flush()
    return snapshot


def _persist_insight_result(
    db: Session,
    snapshot: BarrageInsightSnapshot,
    result: MockBarrageInsightResult,
) -> None:
    sequence_rows = (
        db.execute(
            text(
                "SELECT id, sequence FROM barrage_messages "
                "WHERE window_id=:window_id AND debate_id=:debate_id"
            ),
            {"window_id": snapshot.window_id, "debate_id": snapshot.debate_id},
        )
        .mappings()
        .all()
    )
    sequence_by_message = {str(row["id"]): int(row["sequence"]) for row in sequence_rows}
    first_sequence_by_key: dict[str, int] = {}
    for assignment in result.assignments:
        if assignment.disposition != "included" or assignment.item_key is None:
            continue
        sequence = sequence_by_message.get(str(assignment.message_id))
        if sequence is None:
            raise invalid_state("An included insight message has no frozen sequence.")
        previous = first_sequence_by_key.get(assignment.item_key)
        first_sequence_by_key[assignment.item_key] = (
            sequence if previous is None else min(previous, sequence)
        )
    # A generating snapshot has no durable children.  Defensive cleanup keeps
    # a manually repaired test row from producing duplicate assignments.
    db.execute(
        delete(BarrageInsightAssignment).where(BarrageInsightAssignment.snapshot_id == snapshot.id)
    )
    db.execute(
        delete(BarrageInsightItemRow).where(BarrageInsightItemRow.snapshot_id == snapshot.id)
    )
    db.flush()
    item_by_key: dict[str, BarrageInsightItemRow] = {}
    for candidate in result.items:
        order_index = first_sequence_by_key.get(candidate.item_key)
        if order_index is None:
            raise invalid_state("An insight item has no included frozen message.")
        row = BarrageInsightItemRow(
            id=str(uuid4()),
            snapshot_id=snapshot.id,
            window_id=snapshot.window_id,
            debate_id=snapshot.debate_id,
            order_index=order_index,
            category=candidate.category,
            summary=candidate.summary,
        )
        db.add(row)
        item_by_key[candidate.item_key] = row
    db.flush()
    for assignment in result.assignments:
        item = item_by_key.get(assignment.item_key or "")
        db.add(
            BarrageInsightAssignment(
                snapshot_id=snapshot.id,
                window_id=snapshot.window_id,
                debate_id=snapshot.debate_id,
                barrage_message_id=str(assignment.message_id),
                disposition=assignment.disposition,
                item_id=item.id if item is not None else None,
                filter_reason=assignment.filter_reason,
            )
        )
    db.flush()


def _mark_job_completed(
    db: Session,
    operation: str,
    owner_id: str,
    *,
    attempt: int = 1,
) -> None:
    owner = (
        "insight_snapshot_id" if operation.startswith("barrage_insight") else "report_revision_id"
    )
    if owner not in Job.__table__.c:
        db.execute(
            update(Job)
            .where(
                Job.operation == operation,
                Job.idempotency_key == f"{operation}:{owner_id}",
                Job.state == "running",
            )
            .values(state="completed", attempt=attempt, updated_at=utc_now(), safe_error_code=None)
        )
        return
    db.execute(
        update(Job)
        .where(Job.operation == operation, getattr(Job, owner) == owner_id, Job.state == "running")
        .values(state="completed", attempt=attempt, updated_at=utc_now(), safe_error_code=None)
    )


def _mark_job_running(db: Session, operation: str, owner_id: str) -> bool:
    owner = (
        "insight_snapshot_id" if operation.startswith("barrage_insight") else "report_revision_id"
    )
    where = (
        (Job.operation == operation) & (Job.idempotency_key == f"{operation}:{owner_id}")
        if owner not in Job.__table__.c
        else (Job.operation == operation) & (getattr(Job, owner) == owner_id)
    )
    row = db.scalar(select(Job).where(where))
    if row is None:
        raise invalid_state("The generation Job is missing.")
    if row.state != "pending":
        return False
    changed = db.execute(
        update(Job)
        .where(where, Job.state == "pending")
        .values(state="running", attempt=1, updated_at=utc_now())
    )
    return int(getattr(changed, "rowcount", 0)) == 1


def _mark_job_failed(
    db: Session,
    operation: str,
    owner_id: str,
    code: str,
    *,
    attempt: int = 2,
) -> None:
    owner = (
        "insight_snapshot_id" if operation.startswith("barrage_insight") else "report_revision_id"
    )
    where = (
        (Job.operation == operation) & (Job.idempotency_key == f"{operation}:{owner_id}")
        if owner not in Job.__table__.c
        else (Job.operation == operation) & (getattr(Job, owner) == owner_id)
    )
    db.execute(
        update(Job)
        .where(where, Job.state == "running")
        .values(state="failed", attempt=attempt, safe_error_code=code, updated_at=utc_now())
    )
    if operation == "barrage_insight.generate":
        fail_report_waiting_for_insight(db, owner_id)


def fail_report_waiting_for_insight(db: Session, snapshot_id: str) -> None:
    snapshot = db.get(BarrageInsightSnapshot, snapshot_id)
    if snapshot is None:
        return
    debate = db.get(Debate, snapshot.debate_id)
    if debate is None or not uses_segment_protocol(debate):
        return
    report = db.scalar(select(CivilizationReport).where(CivilizationReport.debate_id == debate.id))
    if report is None or report.generation_status != "generating":
        return
    active = db.scalar(
        select(CivilizationReportRevision.id).where(
            CivilizationReportRevision.report_id == report.id,
            CivilizationReportRevision.status == "generating",
        )
    )
    if active is None:
        report.generation_status = "failed"
        report.latest_attempt_status = "failed"
        report.updated_at = utc_now()


def _job_is_running(db: Session, operation: str, owner_id: str) -> bool:
    """Return the current claim state, fencing workers after restart recovery."""

    owner = (
        "insight_snapshot_id" if operation.startswith("barrage_insight") else "report_revision_id"
    )
    if owner not in Job.__table__.c:
        return (
            db.scalar(
                select(Job.id).where(
                    Job.operation == operation,
                    Job.idempotency_key == f"{operation}:{owner_id}",
                    Job.state == "running",
                )
            )
            is not None
        )
    return (
        db.scalar(
            select(Job.id).where(
                Job.operation == operation,
                getattr(Job, owner) == owner_id,
                Job.state == "running",
            )
        )
        is not None
    )


def process_insight_job(db: Session, snapshot_id: str) -> BarrageInsightSnapshot:
    snapshot = db.get(BarrageInsightSnapshot, snapshot_id)
    if snapshot is None:
        raise not_found()
    if not _mark_job_running(db, "barrage_insight.generate", snapshot.id):
        return snapshot
    # The running claim must survive a process crash independently of policy
    # execution so startup recovery can deterministically mark interruption.
    db.commit()
    return process_insight_snapshot(db, snapshot.id)


def _insight_for_snapshot(db: Session, snapshot: BarrageInsightSnapshot) -> ManifestInsight:
    included, filtered, item_counts = _validate_db_insight_partition(
        db,
        snapshot,
        _json_list((_window_row(db, snapshot.debate_id) or {}).get("frozen_barrage_ids_json")),
    )
    items = list(
        db.scalars(
            select(BarrageInsightItemRow)
            .where(BarrageInsightItemRow.snapshot_id == snapshot.id)
            .order_by(BarrageInsightItemRow.order_index, BarrageInsightItemRow.id)
        ).all()
    )
    manifest_items: list[ManifestInsightItem] = []
    for item in items:
        count = item_counts.get(item.id, 0)
        if count < 1:
            raise invalid_state("An insight item has no included message assignment.")
        manifest_items.append(
            ManifestInsightItem(
                item_id=_uuid(item.id),
                order_index=item.order_index,
                category=cast(Any, item.category),
                summary=item.summary,
                count=count,
            )
        )
    if included != sum(item.count for item in manifest_items) or filtered < 0:
        raise invalid_state("Insight counts do not match its assignments.")
    return ManifestInsight(
        snapshot_id=_uuid(snapshot.id),
        revision=snapshot.revision_no,
        included_count=included,
        filtered_count=filtered,
        items=manifest_items,
    )


def _report_context(
    db: Session,
    debate_id: str,
    *,
    insight_snapshot_id: str | None = None,
) -> ReportContext:
    debate = db.get(Debate, debate_id)
    if debate is None:
        raise not_found()
    window = _window_row(db, debate_id)
    if window is None or window.get("status") != "finalized":
        raise invalid_state("Classroom interaction must be finalized before a report.")
    frozen_barrages = _frozen_message_rows(db, window)
    snapshot_query = select(BarrageInsightSnapshot).where(
        BarrageInsightSnapshot.debate_id == debate_id,
        BarrageInsightSnapshot.status == "ready",
    )
    if insight_snapshot_id is not None:
        snapshot_query = snapshot_query.where(BarrageInsightSnapshot.id == insight_snapshot_id)
    else:
        snapshot_query = snapshot_query.order_by(BarrageInsightSnapshot.revision_no.desc())
    snapshot = db.scalar(snapshot_query)
    if snapshot is None:
        raise invalid_state("A ready anonymous classroom insight is required.")

    participants = list(
        db.scalars(
            select(DebateParticipant)
            .where(DebateParticipant.debate_id == debate_id)
            .order_by(DebateParticipant.order_index, DebateParticipant.id)
        ).all()
    )
    participant_by_id = {row.id: row for row in participants}
    if len(participants) < 2:
        raise invalid_state("A report requires at least two debate participants.")

    turns = list(
        db.scalars(
            select(DebateTurn)
            .where(
                DebateTurn.debate_id == debate_id,
                DebateTurn.publication_status == "public",
                DebateTurn.generation_status == "final_ready",
                DebateTurn.preparation_stage == "ready",
            )
            .order_by(DebateTurn.turn_index, DebateTurn.id)
        ).all()
    )
    if not turns:
        raise invalid_state("A report requires public final-ready debate turns.")
    expected_turn_count = planned_turn_count(debate, len(participants))
    if len(turns) != expected_turn_count:
        raise invalid_state("The public final-ready turn set is incomplete.")

    segment_mode = uses_segment_protocol(debate)
    manifest_participants = [
        ManifestParticipant(
            participant_id=_uuid(row.id),
            slot=cast(Any, row.slot),
            order_index=row.order_index,
            agent_name=row.agent_name,
            stance_mode=cast(Any, row.stance_mode),
            initial_stance=cast(Any, row.initial_stance),
            current_stance=cast(Any, row.current_stance),
            # New paragraph turns carry their position in speech text.  The
            # empty compatibility values keep old public manifests readable
            # without synthesizing PositionHistory rows.
            initial_position_summary=(row.initial_position_summary if not segment_mode else ""),
            current_position_summary=(row.current_position_summary if not segment_mode else ""),
        )
        for row in participants
    ]
    participant_names = {row.id: row.agent_name for row in participants}
    segment_sources_by_turn: dict[str, tuple[str, ...]] = {}
    segment_replies_by_turn: dict[str, tuple[tuple[int, str], ...]] = {}
    segment_values_by_turn: dict[str, tuple[object, ...]] = {}
    manifest_turns: list[ManifestTurn | ManifestTurnV2] = []
    turn_context: list[ReportTurnContext] = []
    turn_ids = {row.id for row in turns}
    for row in turns:
        if row.participant_id not in participant_by_id:
            raise invalid_state("A public turn references an unknown participant.")
        if not row.speech:
            raise invalid_state("A public final-ready turn has no speech.")
        if segment_mode:
            source_ids, replies, segment_values = _segment_turn_payload(row)
            segment_sources_by_turn[row.id] = source_ids
            segment_replies_by_turn[row.id] = replies
            segment_values_by_turn[row.id] = segment_values
        turn_class = ManifestTurnV2 if segment_mode else ManifestTurn
        manifest_turns.append(
            turn_class(
                turn_id=_uuid(row.id),
                participant_id=_uuid(row.participant_id),
                round_no=row.round_no,
                turn_index=row.turn_index,
                text_hash=_sha256(row.speech),
                **(
                    {"used_evidence_ids": list(segment_sources_by_turn[row.id])}
                    if segment_mode
                    else {}
                ),
            )
        )
        turn_context.append(
            ReportTurnContext(
                turn_id=_uuid(row.id),
                participant_id=_uuid(row.participant_id),
                participant_name=participant_names[row.participant_id],
                round_no=row.round_no,
                turn_index=row.turn_index,
                speech=row.speech,
            )
        )

    source_rows = list(
        db.scalars(
            select(TurnSource)
            .where(TurnSource.turn_id.in_(turn_ids))
            .order_by(TurnSource.turn_id, TurnSource.rank, TurnSource.id)
        ).all()
    )
    turns_by_id = {row.id: row for row in turns}
    source_context: list[ReportSourceContext] = []
    manifest_sources: list[ManifestTurnSource | ManifestTurnSourceV2] = []
    seen_source_ids: set[str] = set()
    source_by_chunk: dict[tuple[str, str], str] = {}
    evidence_aliases: dict[str, str] = {}
    grading_source_ids_by_turn: dict[str, set[str]] = {}
    for source in source_rows:
        turn = turns_by_id.get(source.turn_id)
        chunk = db.get(KnowledgeChunk, source.chunk_id)
        if (
            turn is None
            or chunk is None
            or source.id in seen_source_ids
            or source.participant_id != turn.participant_id
            or source.snapshot_id != turn.knowledge_snapshot_id
            or chunk.snapshot_id != source.snapshot_id
        ):
            raise invalid_state("A report source is not an immutable used turn source.")
        source_evidence_id = str(source.evidence_id or "").strip()
        if segment_mode:
            expected_ids = set(segment_sources_by_turn.get(source.turn_id, ()))
            if not source_evidence_id or source_evidence_id not in expected_ids:
                raise invalid_state("A segment source is not linked by its paragraph output.")
        else:
            source_evidence_id = str(source.id)
        seen_source_ids.add(source.id)
        grading_source_ids_by_turn.setdefault(str(source.turn_id), set()).add(source_evidence_id)
        chunk_hash = _sha256(chunk.chunk_text)
        source_key = (
            (str(source.snapshot_id), str(source.chunk_id))
            if segment_mode
            else (str(source.id), str(source.id))
        )
        canonical_evidence_id = source_by_chunk.get(source_key)
        if canonical_evidence_id is None:
            canonical_evidence_id = source_evidence_id
            source_by_chunk[source_key] = canonical_evidence_id
            manifest_source_type = ManifestTurnSourceV2 if segment_mode else ManifestTurnSource
            manifest_sources.append(
                manifest_source_type(
                    turn_source_id=_uuid(source.id),
                    turn_id=_uuid(source.turn_id),
                    turn_index=turn.turn_index,
                    rank=source.rank,
                    snapshot_id=_uuid(source.snapshot_id),
                    chunk_id=_uuid(source.chunk_id),
                    chunk_content_hash=chunk_hash,
                    source_filename=source.source_filename,
                    **({"evidence_id": canonical_evidence_id} if segment_mode else {}),
                )
            )
            source_context.append(
                ReportSourceContext(
                    turn_source_id=_uuid(source.id),
                    turn_id=_uuid(source.turn_id),
                    turn_index=turn.turn_index,
                    rank=source.rank,
                    snapshot_id=_uuid(source.snapshot_id),
                    chunk_id=_uuid(source.chunk_id),
                    source_filename=source.source_filename,
                    chunk_text=chunk.chunk_text,
                    evidence_id=canonical_evidence_id,
                )
            )
        evidence_aliases[source_evidence_id] = canonical_evidence_id

    evidence_by_turn: dict[str, list[str]] = {}
    for turn in turns:
        if segment_mode:
            raw_ids = segment_sources_by_turn.get(turn.id, ())
            canonical_ids = tuple(
                dict.fromkeys(evidence_aliases.get(source_id, source_id) for source_id in raw_ids)
            )
            if any(source_id not in evidence_aliases for source_id in raw_ids):
                raise invalid_state("A segment source reference is unavailable to the report.")
            evidence_by_turn[turn.id] = list(canonical_ids)
        else:
            evidence_by_turn[turn.id] = [
                str(source.turn_source_id)
                for source in source_context
                if str(source.turn_id) == turn.id
            ]
    turn_context = [
        ReportTurnContext(
            turn_id=item.turn_id,
            participant_id=item.participant_id,
            participant_name=item.participant_name,
            round_no=item.round_no,
            turn_index=item.turn_index,
            speech=item.speech,
            used_evidence_ids=tuple(evidence_by_turn.get(str(item.turn_id), ())),
        )
        for item in turn_context
    ]
    has_explicit_segment_grade = segment_mode and any(
        getattr(segment, "support_mode", None) is not None
        for values in segment_values_by_turn.values()
        for segment in values
    )
    if segment_mode:
        # Persist the same deduplicated canonical evidence IDs that the
        # ReportRequest will expose.  Keeping a local S alias here would make
        # an immutable v2 manifest disagree with the actual TurnSource row.
        manifest_turns = [
            ManifestTurnV2(
                turn_id=_uuid(turn.id),
                participant_id=_uuid(turn.participant_id),
                round_no=turn.round_no,
                turn_index=turn.turn_index,
                text_hash=_sha256(turn.speech or ""),
                used_evidence_ids=evidence_by_turn.get(turn.id, []),
            )
            for turn in turns
        ]

    score_summary: ReportScoreSummary | None = None
    if has_explicit_segment_grade:
        try:
            score_rows = [
                {
                    "turn_id": str(turn.id),
                    "participant_id": str(turn.participant_id),
                    "segments": segment_values_by_turn.get(turn.id, ()),
                }
                for turn in turns
            ]
            valid_sources = {
                str(turn.id): tuple(grading_source_ids_by_turn.get(str(turn.id), ()))
                for turn in turns
            }
            scores = aggregate_agent_scores(
                score_rows,
                valid_source_ids_by_turn=valid_sources,
            )
        except SegmentGradingError:
            raise invalid_state("A public segment has inconsistent grading data.") from None
        score_by_participant = {item.participant_id: item for item in scores}
        empty_score = AgentGradeSummary("", 0, 0, 0, 0)
        score_agents = [
            ReportAgentScore(
                slot=cast(Any, participant.slot),
                direct_count=(
                    score_by_participant.get(str(participant.id), empty_score).direct_count
                ),
                contextual_count=(
                    score_by_participant.get(str(participant.id), empty_score).contextual_count
                ),
                no_match_count=(
                    score_by_participant.get(str(participant.id), empty_score).no_match_count
                ),
                ungraded_count=(
                    score_by_participant.get(str(participant.id), empty_score).ungraded_count
                ),
                total_points=(
                    score_by_participant.get(str(participant.id), empty_score).total_points
                ),
            )
            for participant in participants
        ]
        score_summary = ReportScoreSummary(
            agents=score_agents,
            direct_count=sum(item.direct_count for item in score_agents),
            contextual_count=sum(item.contextual_count for item in score_agents),
            no_match_count=sum(item.no_match_count for item in score_agents),
            ungraded_count=sum(item.ungraded_count for item in score_agents),
            total_points=sum(item.total_points for item in score_agents),
        )

    classroom_barrages: tuple[ReportBarrageContext, ...] = ()
    reply_context: list[ReportReplyContext] = []
    if segment_mode:
        classroom_barrages, barrage_messages = _segment_final_input(
            db, debate, turns, frozen_barrages
        )
        participant_slots = {row.id: row.slot for row in participants}
        for turn in turns:
            for paragraph_index, barrage_id in segment_replies_by_turn.get(turn.id, ()):
                if (
                    turn.round_no != debate_round_count(debate)
                    or barrage_id not in barrage_messages
                ):
                    raise invalid_state("A segment reply is outside the frozen final input.")
                reply_context.append(
                    ReportReplyContext(
                        barrage_id=barrage_id,
                        slot=str(participant_slots[turn.participant_id]),
                        turn_index=turn.turn_index,
                        paragraph_index=paragraph_index,
                    )
                )

    final_votes = _final_vote_rows(db, debate_id, str(window["id"]))
    _verify_frozen_vote_projection(window, participants, final_votes)
    vote_by_participant: dict[str, int] = {}
    for vote_row in final_votes:
        participant_id = str(vote_row["participant_id"])
        if participant_id not in participant_by_id:
            raise invalid_state("Final votes contain an unknown participant.")
        count = int(vote_row["count"])
        if count < 0:
            raise invalid_state("Final vote counts cannot be negative.")
        vote_by_participant[participant_id] = vote_by_participant.get(participant_id, 0) + count
    manifest_votes = [
        ManifestVote(
            participant_id=_uuid(row.id),
            order_index=row.order_index,
            count=vote_by_participant.get(row.id, 0),
        )
        for row in participants
    ]
    insight_manifest = _insight_for_snapshot(db, snapshot)
    if segment_mode:
        manifest: ReportInputManifestV1 | ReportInputManifestV2 = ReportInputManifestV2(
            debate_id=_uuid(debate_id),
            topic=debate.topic,
            participants=manifest_participants,
            turns=cast(list[ManifestTurnV2], manifest_turns),
            turn_sources=cast(list[ManifestTurnSourceV2], manifest_sources),
            votes=manifest_votes,
            insight=insight_manifest,
            classroom_barrages=[
                ManifestBarrage(
                    barrage_id=item.barrage_id,
                    turn_index=item.turn_index,
                    text=item.text,
                )
                for item in classroom_barrages
            ],
            replies=[
                ManifestReply(
                    barrage_id=item.barrage_id,
                    slot=cast(Any, item.slot),
                    turn_index=item.turn_index,
                    paragraph_index=item.paragraph_index,
                )
                for item in reply_context
            ],
            score_summary=score_summary,
        )
    else:
        manifest = ReportInputManifestV1(
            debate_id=_uuid(debate_id),
            topic=debate.topic,
            participants=manifest_participants,
            turns=manifest_turns,
            turn_sources=manifest_sources,
            votes=manifest_votes,
            insight=insight_manifest,
        )
    return ReportContext(
        debate=debate,
        manifest=manifest,
        turns=tuple(turn_context),
        sources=tuple(source_context),
        vote_total=sum(item.count for item in manifest_votes),
        barrage_total=len(frozen_barrages),
        classroom_barrages=classroom_barrages,
        replies=tuple(reply_context),
        protocol_version="segments_v2" if segment_mode else "legacy_v1",
        score_summary=score_summary,
    )


def _load_report_manifest(value: str) -> ReportInputManifestV1 | ReportInputManifestV2:
    """Load either immutable report manifest version without widening the DTO."""

    try:
        raw = json.loads(value)
    except (TypeError, ValueError):
        raise ValueError("report input manifest is not valid JSON") from None
    if not isinstance(raw, Mapping):
        raise ValueError("report input manifest is not an object")
    model = (
        ReportInputManifestV2
        if raw.get("manifest_version") == "report_input_manifest_v2"
        else ReportInputManifestV1
    )
    return model.model_validate(raw)


def build_report_input_manifest(
    db: Session, debate_id: str
) -> ReportInputManifestV1 | ReportInputManifestV2:
    """Build and validate the exact manifest consumed by Mock Maya."""

    return _report_context(db, debate_id).manifest


def build_real_report_request(context: ReportContext) -> ReportRequest | ReportRequestV2:
    """Project one immutable report context into the closed Real input DTO."""

    participants = tuple(
        ReportParticipant(
            slot=cast(Any, participant.slot),
            agent_name=participant.agent_name,
        )
        for participant in context.manifest.participants
    )
    slot_by_participant = {
        str(item.participant_id): item.slot for item in context.manifest.participants
    }
    speeches = tuple(
        ReportSpeech(
            slot=cast(Any, slot_by_participant.get(str(turn.participant_id), "A")),
            round_no=turn.round_no,
            turn_index=turn.turn_index,
            speech=turn.speech,
            used_evidence_ids=turn.used_evidence_ids,
        )
        for turn in context.turns
    )
    sources = tuple(
        ReportSource(
            evidence_id=(
                source.evidence_id
                if context.protocol_version == "segments_v2" and source.evidence_id
                else str(source.turn_source_id)
            ),
            # Quoted source text, not report syntax. Every excerpt comes from a
            # Markdown evidence file, so passing chunk_text through raw meant a
            # heading or a list bullet failed the outbound boundary check and
            # no real report could be generated at all.
            excerpt=(
                source.chunk_text
                if context.protocol_version == "segments_v2"
                else _safe_fragment(source.chunk_text, limit=2400)
            ),
        )
        for source in context.sources
    )
    counts = {str(vote.participant_id): vote.count for vote in context.manifest.votes}
    votes = tuple(
        # Public slot is the only vote key crossing the provider boundary.
        ReportVote(
            slot=cast(Any, participant.slot),
            count=counts.get(str(participant.participant_id), 0),
        )
        for participant in context.manifest.participants
    )
    insights = tuple(
        ReportInsight(category=item.category, summary=_safe_fragment(item.summary, limit=1600))
        for item in context.manifest.insight.items
    )
    common: dict[str, Any] = {
        "topic": context.manifest.topic or context.debate.topic,
        "participants": participants,
        "speeches": speeches,
        "sources": sources,
        "votes": votes,
        "insights": insights,
        "source_language": debate_output_language(context.debate),
    }
    if context.protocol_version == "segments_v2":
        return ReportRequestV2(
            **common,
            classroom_barrages=tuple(
                ReportBarrage(
                    barrage_id=item.barrage_id,
                    turn_index=item.turn_index,
                    text=item.text,
                )
                for item in context.classroom_barrages
            ),
            replies=tuple(
                ReportReply(
                    barrage_id=item.barrage_id,
                    slot=cast(Any, item.slot),
                    turn_index=item.turn_index,
                    paragraph_index=item.paragraph_index,
                )
                for item in context.replies
            ),
            score_summary=context.score_summary,
        )
    return ReportRequest(**common)


def _safe_fragment(value: str, *, limit: int = 260) -> str:
    """Render user-authored text as plain report text, never Markdown syntax."""

    text_value = " ".join(value.split())[:limit]
    # Citations are emitted only by this module from immutable TurnSource IDs.
    # Brackets, heading markers and HTML delimiters in student/visitor text are
    # therefore rendered as ordinary punctuation rather than report syntax.
    text_value = (
        text_value.replace("[", "(")
        .replace("]", ")")
        .replace("#", "")
        .replace("<", "(")
        .replace(">", ")")
        .replace("`", "'")
    )
    # Emphasis runs are the other half of the same job. Every source this
    # platform carries is a Markdown file, so bold and strikethrough reach here
    # routinely; leaving them made an excerpt read as report syntax and the
    # boundary check reject it.
    text_value = text_value.replace("**", "").replace("__", "").replace("~~", "")
    return _UNSAFE_REPORT_TERMS_RE.sub("outcome", text_value)


def _excerpt(value: str, words: int = 22) -> str:
    tokens = value.split()
    if len(tokens) <= words:
        return _safe_fragment(value)
    return _safe_fragment(" ".join(tokens[:words])) + "..."


def _citation(source: ReportSourceContext) -> str:
    return f"[evidence:{source.evidence_id or source.turn_source_id}]"


def _source_lines(context: ReportContext) -> list[str]:
    if not context.sources:
        return [
            "The public turns did not cite a retained knowledge chunk. The report therefore "
            "does not invent supporting evidence."
        ]
    by_turn: dict[int, list[ReportSourceContext]] = {}
    for source in context.sources:
        by_turn.setdefault(source.turn_index, []).append(source)
    lines: list[str] = []
    for turn_index in sorted(by_turn):
        turn_sources = by_turn[turn_index]
        citations = " ".join(_citation(source) for source in turn_sources)
        if context.protocol_version == "segments_v2":
            lines.append(f"Turn {turn_index + 1} sources: {citations}.")
            continue
        lines.append(
            f"Turn {turn_index + 1} evidence {citations}: "
            f"{_excerpt(turn_sources[0].chunk_text, words=3)}."
        )
    return lines


def _vote_lines_for_manifest(manifest: ReportInputManifestV1 | ReportInputManifestV2) -> list[str]:
    """Return the code-owned per-participant vote lines used by the report."""

    counts = {str(vote.participant_id): vote.count for vote in manifest.votes}
    return [
        f"Participant {participant.slot} received "
        f"{counts.get(str(participant.participant_id), 0)} anonymous vote"
        f"{'' if counts.get(str(participant.participant_id), 0) == 1 else 's'}"
        for participant in manifest.participants
    ]


def _vote_lines(context: ReportContext) -> list[str]:
    return _vote_lines_for_manifest(context.manifest)


def _reply_summary(context: ReportContext) -> str:
    """Describe only persisted paragraph replies, never infer an answer."""

    if context.protocol_version != "segments_v2":
        return ""
    if not context.classroom_barrages:
        return "No classroom messages were available for the final round."
    linked = len({item.barrage_id for item in context.replies})
    return (
        f"Final round: {linked} of {len(context.classroom_barrages)} classroom messages "
        "have a linked response."
    )


def _interaction_total_marker(
    manifest: ReportInputManifestV1 | ReportInputManifestV2, vote_total: int, barrage_total: int
) -> str:
    if isinstance(manifest, ReportInputManifestV2):
        return f"Classroom totals: {vote_total} votes and {barrage_total} messages."
    return (
        f"The code-owned final vote total is {vote_total}, and the frozen barrage "
        f"message total is {barrage_total}."
    )


def mock_maya_report_v1(context: ReportContext) -> ReportSectionOutput:
    """Return deterministic structured sections for the Mock Maya policy.

    Vote counts and citation tokens are inserted from code-owned manifest
    values.  The Mock policy itself only supplies prose sections and never
    fabricates a count, winner, source ID or author mapping.
    """

    manifest = context.manifest
    topic = _excerpt(context.manifest.topic or context.debate.topic, words=12)
    participant_lines = []
    for item in manifest.participants:
        initial_position = _excerpt(
            item.initial_position_summary or "an open starting position", words=8
        )
        final_position = _excerpt(
            item.current_position_summary or "an open final position", words=8
        )
        participant_lines.append(
            f"{_excerpt(item.agent_name, words=4)} ({item.slot}) entered "
            f"{_safe_fragment(item.stance_mode, limit=20)}: initially {initial_position}; "
            f"finally {final_position}."
        )
    turn_lines = [
        f"Turn {turn.turn_index + 1}, {_excerpt(turn.participant_name, words=4)}: "
        f"{_excerpt(turn.speech, words=8)}"
        for turn in context.turns
    ]
    if not turn_lines:
        turn_lines = ["No public final-ready turn was available to summarize."]

    evidence_text = " ".join(_source_lines(context))
    participant_text = " ".join(participant_lines)
    turn_text = " ".join(turn_lines)

    overview = (
        f"The debate considered {topic}. This report describes a mutual-learning process, "
        "not a verdict about which perspective is correct. The sequence and role labels "
        "are retained so a teacher can reconstruct how each contribution entered the "
        "conversation. "
        f"{participant_text} The final position is read as a situated response to the "
        "conversation, rather than as a permanent identity claim."
    )
    evidence = (
        "The public transcript is the primary record of argument. "
        f"{turn_text} "
        f"{evidence_text} The evidence trace is deliberately narrow: only chunks linked "
        "to a public final-ready turn are named. An available document that was not used "
        "by a turn is not silently promoted into support for the report. This distinction "
        "helps learners see the difference between having knowledge available and actually "
        "using a source in a claim."
    )
    convergence = (
        "Several forms of convergence can be observed without reducing disagreement to a "
        "single answer. Participants shared the same topic, responded within a common "
        "turn order, and had an opportunity to make their reasoning more precise after "
        "hearing another perspective. A useful shared practice is visible when an argument "
        "acknowledges a trade-off, answers a concrete concern, or distinguishes evidence "
        "from interpretation. The transcript and position summaries should be read together: "
        "a similar conclusion can arise from different values, while different conclusions "
        "can still share a careful method."
    )
    insight_lines = [
        f"{item.category.title()} classroom theme: {_excerpt(item.summary, words=6)} "
        f"({item.count} message{'' if item.count == 1 else 's'})."
        for item in manifest.insight.items[:4]
    ]
    if len(manifest.insight.items) > len(insight_lines):
        insight_lines.append(
            f"{len(manifest.insight.items) - len(insight_lines)} additional validated themes "
            "remain in the immutable insight snapshot."
        )
    tension = (
        "Continuing tensions are part of the learning outcome. The report keeps critical "
        "questions and minority concerns visible instead of treating agreement as the only "
        "valuable result. "
        + (
            " ".join(insight_lines)
            if insight_lines
            else "No substantive classroom theme was recorded."
        )
        + " These themes indicate where a future class could ask for a clearer definition, "
        "a better comparison, a missing source, or a more explicit account of who bears a "
        "policy trade-off. They do not establish that a frequently repeated view is true."
    )

    vote_lines = _vote_lines(context)
    if not vote_lines:
        vote_lines = ["No participant vote aggregate was recorded."]
    classroom_outcome = (
        "This session had no classroom interaction data."
        if context.vote_total == 0 and context.barrage_total == 0
        else "These aggregates describe participation patterns, not the accuracy or "
        "moral weight of an argument."
    )
    classroom = (
        "Classroom perspectives are reported as aggregates and anonymous themes. "
        f"{_interaction_total_marker(manifest, context.vote_total, context.barrage_total)} "
        + " ".join(vote_lines)
        + " "
        + (
            "Anonymous themes are summarized in the tensions section."
            if insight_lines
            else "No anonymous theme was retained."
        )
        + (f" {_reply_summary(context)}" if _reply_summary(context) else "")
        + " "
        + classroom_outcome
    )
    reflection = (
        "Mutual learning continues when participants can name both what they learned and "
        "what they still need to investigate. A teacher might ask each group to identify one "
        "assumption that another perspective made visible, one evidence gap that deserves a "
        "new source, and one respectful question that could improve the next conversation. "
        "The strongest next step is not to erase tension but to make its terms clearer: "
        "which values are being balanced, whose experience is missing, what evidence could "
        "change a position, and how a response can remain accountable to people affected by "
        "the decision. This report is a compact record for that continuing inquiry."
    )
    return ReportSectionOutput(
        debate_overview=overview,
        evidence_and_arguments=evidence,
        areas_of_convergence=convergence,
        continuing_tensions_and_questions=tension,
        classroom_perspectives=classroom,
        mutual_learning_reflection=reflection,
    )


def render_report_markdown(
    context: ReportContext,
    sections: ReportSectionOutput | None = None,
) -> str:
    """Render the fixed heading order and code-owned citation/count text."""

    result = sections or mock_maya_report_v1(context)
    markdown = "\n\n".join(
        (
            REPORT_HEADINGS[0],
            f"{REPORT_HEADINGS[1]}\n\n{result.debate_overview}",
            f"{REPORT_HEADINGS[2]}\n\n{result.evidence_and_arguments}",
            f"{REPORT_HEADINGS[3]}\n\n{result.areas_of_convergence}",
            f"{REPORT_HEADINGS[4]}\n\n{result.continuing_tensions_and_questions}",
            f"{REPORT_HEADINGS[5]}\n\n{result.classroom_perspectives}",
            f"{REPORT_HEADINGS[6]}\n\n{result.mutual_learning_reflection}",
        )
    )
    while context.protocol_version != "segments_v2" and report_word_count(markdown) < 600:
        markdown = f"{markdown} {_REPORT_PADDING_SENTENCE}"
    return markdown


def render_real_report_markdown(
    context: ReportContext,
    sections: ReportSectionOutput,
) -> str:
    """Render provider prose with server-owned citations and vote aggregates."""

    evidence_suffix = " ".join(_source_lines(context))
    count_marker = _interaction_total_marker(
        context.manifest, context.vote_total, context.barrage_total
    )
    vote_lines = " ".join(_vote_lines(context))
    interaction_suffix = (
        "Classroom perspectives are reported as aggregates and anonymous themes. "
        f"{count_marker} {vote_lines} "
        + (
            "This session had no classroom interaction data."
            if context.vote_total == 0 and context.barrage_total == 0
            else (
                "These aggregates describe participation patterns, not the accuracy or moral "
                "weight of an argument."
            )
        )
        + (f" {_reply_summary(context)}" if _reply_summary(context) else "")
    )
    projected = sections.model_copy(
        update={
            "evidence_and_arguments": (
                f"{sections.evidence_and_arguments} {evidence_suffix}".strip()
            ),
            "classroom_perspectives": (
                f"{sections.classroom_perspectives} {interaction_suffix}".strip()
            ),
        }
    )
    return render_report_markdown(context, projected)


def report_word_count(markdown: str) -> int:
    without_citations = _CITATION_RE.sub("", markdown)
    return len(WORD_RE.findall(without_citations))


class ReportValidationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def validate_report_markdown(
    markdown: str,
    *,
    manifest: ReportInputManifestV1 | ReportInputManifestV2,
    vote_total: int,
    barrage_total: int,
) -> int:
    """Validate heading/citation/word/count safety before a ready commit."""

    if markdown.split("\n\n", 1)[0] != REPORT_HEADINGS[0]:
        raise ReportValidationError("report_title_invalid", "report title heading is not canonical")
    found_headings = [line for line in markdown.splitlines() if line.startswith("#")]
    if found_headings != list(REPORT_HEADINGS):
        raise ReportValidationError("report_headings_invalid", "report headings are not canonical")
    known_source_ids = {
        str(getattr(item, "evidence_id", "") or item.turn_source_id)
        for item in manifest.turn_sources
    }
    citations = _CITATION_RE.findall(markdown)
    citation_keys = (
        citations if isinstance(manifest, ReportInputManifestV2) else [c.lower() for c in citations]
    )
    if any(citation not in known_source_ids for citation in citation_keys):
        raise ReportValidationError(
            "report_citation_unknown", "report contains an unknown evidence citation"
        )
    if set(citation_keys) != known_source_ids:
        raise ReportValidationError(
            "report_citations_mismatch", "report citations do not match used sources"
        )
    if re.search(r"\[evidence:[^\]]+\]", _CITATION_RE.sub("", markdown)):
        raise ReportValidationError(
            "report_citation_malformed", "report contains a malformed evidence citation"
        )
    if _UNSAFE_REPORT_TERMS_RE.search(markdown):
        raise ReportValidationError(
            "report_prohibited_phrase", "report contains a prohibited winner or nickname phrase"
        )
    zero_phrase = "This session had no classroom interaction data."
    if (vote_total == 0 and barrage_total == 0) != (zero_phrase in markdown):
        raise ReportValidationError(
            "report_interaction_phrase_invalid",
            "zero-interaction report phrase does not match frozen counts",
        )
    count = report_word_count(markdown)
    minimum = 1 if isinstance(manifest, ReportInputManifestV2) else 600
    if not minimum <= count <= 900:
        raise ReportValidationError(
            "report_word_count_invalid", "report word count is outside the versioned contract"
        )
    manifest_vote_total = sum(item.count for item in manifest.votes)
    manifest_barrage_total = manifest.insight.included_count + manifest.insight.filtered_count
    if vote_total != manifest_vote_total or barrage_total != manifest_barrage_total:
        raise ReportValidationError(
            "report_counts_mismatch", "report counts do not match the canonical manifest"
        )
    total_marker = _interaction_total_marker(manifest, vote_total, barrage_total)
    if markdown.count(total_marker) != 1:
        raise ReportValidationError(
            "report_interaction_totals_missing", "report is missing canonical interaction totals"
        )
    expected_vote_lines = _vote_lines_for_manifest(manifest)
    if any(markdown.count(line) != 1 for line in expected_vote_lines):
        raise ReportValidationError(
            "report_vote_counts_invalid", "report contains noncanonical participant vote counts"
        )
    return count


def generate_mock_report(context: ReportContext) -> tuple[str, int]:
    markdown = render_report_markdown(context)
    count = validate_report_markdown(
        markdown,
        manifest=context.manifest,
        vote_total=context.vote_total,
        barrage_total=context.barrage_total,
    )
    return markdown, count


def _resume_parked_report_job(db: Session, revision_id: str) -> None:
    """Return a parked or stranded report Job to the queue, if there is one."""

    job = db.scalar(
        select(Job).where(
            Job.operation == REPORT_GENERATE_OPERATION,
            Job.report_revision_id == revision_id,
        )
    )
    if job is None or job.state == "pending":
        return
    # ``running`` is deliberately included: a process that died mid-report
    # leaves one behind, and only a restart fence would otherwise clear it.
    if job.state in {"interrupted", "running"}:
        job.state = "pending"
        job.safe_error_code = None
        job.updated_at = utc_now()


def _create_report_revision_for_insight(
    db: Session,
    snapshot: BarrageInsightSnapshot,
    *,
    trigger: str,
    requested_by: str | None,
) -> CivilizationReportRevision:
    """Create the next immutable report revision for a ready insight."""

    if snapshot.status != "ready":
        raise invalid_state("A ready anonymous insight is required before report generation.")
    report = db.scalar(
        select(CivilizationReport).where(CivilizationReport.debate_id == snapshot.debate_id)
    )
    now = utc_now()
    if report is None:
        report = CivilizationReport(
            id=str(uuid4()),
            debate_id=snapshot.debate_id,
            generation_status="not_started",
            latest_attempt_status="not_started",
            policy_key=MOCK_MAYA_REPORT_POLICY_KEY,
            created_at=now,
            updated_at=now,
        )
        db.add(report)
        db.flush()
    active = db.scalar(
        select(CivilizationReportRevision)
        .where(
            CivilizationReportRevision.report_id == report.id,
            CivilizationReportRevision.status == "generating",
        )
        .order_by(CivilizationReportRevision.revision_no.desc())
    )
    if active is not None:
        # An in-flight revision is reused rather than duplicated, but reuse is
        # only honest if it can still run. A revision whose Job was parked
        # awaiting a provider confirmation used to make Regenerate a permanent
        # no-op: the button returned this same revision every time and nothing
        # would ever pick its Job up again. Pressing Regenerate is a request to
        # continue, so resume the parked Job here.
        _resume_parked_report_job(db, active.id)
        return active
    context = _report_context(db, snapshot.debate_id, insight_snapshot_id=snapshot.id)
    manifest_json = context.manifest.canonical_json()
    now = utc_now()
    revision = CivilizationReportRevision(
        id=str(uuid4()),
        report_id=report.id,
        debate_id=snapshot.debate_id,
        insight_snapshot_id=snapshot.id,
        revision_no=(
            int(
                db.scalar(
                    select(CivilizationReportRevision.revision_no)
                    .where(CivilizationReportRevision.report_id == report.id)
                    .order_by(CivilizationReportRevision.revision_no.desc())
                )
                or 0
            )
            + 1
        ),
        status="generating",
        attempt=1,
        input_manifest_json=manifest_json,
        input_manifest_hash=context.manifest.input_hash(),
        english_markdown=None,
        word_count=None,
        safe_error_code=None,
        trigger=trigger,
        requested_by=requested_by,
        created_at=now,
        updated_at=now,
    )
    db.add(revision)
    report.generation_status = "generating"
    report.latest_attempt_status = "generating"
    report.updated_at = now
    db.flush()
    ensure_report_job(db, revision)
    return revision


@dataclass(frozen=True, slots=True)
class RealReportPreparedOperation:
    """Frozen provider wire plus its immutable report context."""

    revision_id: str
    debate_id: str
    manifest_hash: str
    operation_id: str
    wire: ReportWireRequest
    context: ReportContext

    @property
    def request(self) -> ReportRequest:
        """Compatibility view of the closed report input, without rebuilding wire."""

        return self.wire.report


def _report_provider_policy_hash(provider: RealReportProviderPort) -> str:
    value = getattr(provider, "policy_hash", None)
    if not isinstance(value, str) or not value:
        config = getattr(provider, "config", None)
        value = getattr(config, "policy_hash", None)
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ReportProviderError("report_policy_hash")
    return value


def _report_field_hash(value: object) -> str:
    return _sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _report_manifest(
    db: Session,
    *,
    context: ReportContext,
    request: ReportRequest,
    provider: RealReportProviderPort,
    wire: ReportWireRequest,
) -> ExportManifestV1:
    policy_hash = _report_provider_policy_hash(provider)
    policy = db.scalar(
        select(ProviderPolicySnapshot).where(ProviderPolicySnapshot.policy_hash == policy_hash)
    )
    if policy is None:
        raise ReportProviderError("report_policy_unavailable")
    source_projection = [
        {"evidence_id": source.evidence_id, "excerpt": source.excerpt} for source in request.sources
    ]
    fields: tuple[ExportFieldV1, ...] = (
        ExportFieldV1(
            "topic_and_platform_rules",
            _report_field_hash({"topic": request.topic, "prompt": wire.system_message.content}),
        ),
        ExportFieldV1(
            "public_agent_name",
            _report_field_hash(
                [
                    {"slot": item.slot, "agent_name": item.agent_name}
                    for item in request.participants
                ]
            ),
        ),
        ExportFieldV1(
            "public_predecessor_speech",
            _report_field_hash(
                [
                    {
                        "slot": item.slot,
                        "round_no": item.round_no,
                        "turn_index": item.turn_index,
                        "speech": item.speech,
                        "used_evidence_ids": list(item.used_evidence_ids),
                    }
                    for item in request.speeches
                ]
            ),
        ),
        ExportFieldV1("current_evidence_excerpt", _report_field_hash(source_projection)),
        ExportFieldV1(
            "opaque_local_id",
            _report_field_hash([item.evidence_id for item in request.sources]),
        ),
        ExportFieldV1(
            "anonymous_insight_summary",
            _report_field_hash(
                [{"category": item.category, "summary": item.summary} for item in request.insights]
            ),
        ),
        ExportFieldV1(
            "aggregate_vote_count",
            _report_field_hash(
                [{"slot": item.slot, "count": item.count} for item in request.votes]
            ),
        ),
    )
    if isinstance(request, ReportRequestV2):
        fields = (
            *fields,
            ExportFieldV1(
                LLM_ANONYMOUS_BARRAGE_FIELD_CLASS,
                _report_field_hash(
                    {
                        "barrages": [
                            {
                                "barrage_id": item.barrage_id,
                                "turn_index": item.turn_index,
                                "text": item.text,
                            }
                            for item in request.classroom_barrages
                        ],
                        "replies": [
                            {
                                "barrage_id": item.barrage_id,
                                "slot": item.slot,
                                "turn_index": item.turn_index,
                                "paragraph_index": item.paragraph_index,
                            }
                            for item in request.replies
                        ],
                    }
                ),
            ),
        )
        if request.score_summary is not None:
            fields = (
                *fields,
                ExportFieldV1(
                    "aggregate_evidence_grade",
                    _report_field_hash(request.score_summary.model_dump(mode="json")),
                ),
            )
    estimated_cost = wire.estimated_cost_cny
    budget = wire.budget
    max_tokens = int(getattr(budget, "input_tokens", 0)) + LLM_RESERVED_OUTPUT_TOKEN_CAP
    if max_tokens <= LLM_RESERVED_OUTPUT_TOKEN_CAP:
        raise ReportProviderError("report_budget_invalid")
    if not isinstance(estimated_cost, (Decimal, int, float, str)):
        raise ReportProviderError("report_budget_invalid") from None
    try:
        max_cost = float(estimated_cost)
    except (TypeError, ValueError):
        raise ReportProviderError("report_budget_invalid") from None
    if max_cost <= 0:
        raise ReportProviderError("report_budget_invalid")
    return ExportManifestV1(
        scope_id=context.debate.id,
        provider_operation="llm_maya_report",
        model_key=REAL_REPORT_MODEL,
        policy_hash=policy_hash,
        build_manifest_hash=context.manifest.input_hash(),
        persona_spec_hash=_sha256(
            "real_report_persona_absent_v2"
            if isinstance(request, ReportRequestV2)
            else "real_report_persona_absent_v1"
        ),
        fields=fields,
        operation_revision=2 if isinstance(request, ReportRequestV2) else 1,
        max_attempts=1,
        max_total_tokens=max_tokens,
        max_cost_cny=max_cost,
    )


def prepare_real_report_operation(
    db: Session,
    revision_id: str,
    *,
    runtime: RealReportRuntime,
) -> RealReportPreparedOperation:
    """Persist a report manifest/prepared operation without network I/O."""

    revision = db.get(CivilizationReportRevision, revision_id)
    if revision is None:
        raise not_found()
    if revision.status != "generating":
        raise ReportProviderError("report_revision_not_pending")
    context = _report_context(
        db,
        revision.debate_id,
        insight_snapshot_id=revision.insight_snapshot_id,
    )
    request = build_real_report_request(context)
    wire = runtime.provider.build_request(request)
    manifest = _report_manifest(
        db,
        context=context,
        request=request,
        provider=runtime.provider,
        wire=wire,
    )
    policy_row_id = db.scalar(
        select(ProviderPolicySnapshot.id).where(
            ProviderPolicySnapshot.policy_hash == manifest.policy_hash
        )
    )
    if policy_row_id is None:
        raise ReportProviderError("report_policy_unavailable")
    # One request funded exactly one report for the whole life of a Debate.
    # The product offers a repair attempt and a Regenerate button, so the first
    # failure spent the entire allowance and every later attempt died with
    # BudgetExceeded -- a control sized below the actions it governs is not a
    # control, it is a dead end. Fund the attempts the product actually
    # permits, the way the debate-turn bucket already does.
    budget_ceiling = REPORT_REGENERATION_CAP * REPORT_ATTEMPT_CAP
    raise_budget = getattr(runtime.repository, "raise_scope_budget", None)
    ensure_budget = raise_budget or runtime.repository.ensure_scope_budget
    ensure_budget(
        context.debate.id,
        ProviderScopeBudgetV1(
            max_requests=budget_ceiling,
            max_total_tokens=manifest.max_total_tokens * budget_ceiling,
            max_cost_cny=manifest.max_cost_cny * budget_ceiling,
            budget_bucket=LLM_MAYA_REPORT_BUCKET,
        ),
    )
    manifest_id = runtime.repository.ensure_export_manifest(
        manifest,
        policy_snapshot_id=str(policy_row_id),
        course_id=None,
        group_id=None,
        agent_version_id=None,
    )
    del manifest_id
    existing = db.scalar(
        select(ProviderOperation).where(
            ProviderOperation.scope_id == context.debate.id,
            ProviderOperation.provider_operation == "llm_maya_report",
            ProviderOperation.logical_item_id == revision.id,
            ProviderOperation.attempt_no == 1,
        )
    )
    if existing is not None:
        if existing.export_manifest_hash != manifest.manifest_hash:
            raise ReportProviderError("report_operation_stale")
        return RealReportPreparedOperation(
            revision_id=revision.id,
            debate_id=revision.debate_id,
            manifest_hash=manifest.manifest_hash,
            operation_id=existing.id,
            wire=wire,
            context=context,
        )
    operation_request = ProviderReservationRequestV1(
        operation_id=str(uuid4()),
        scope_id=context.debate.id,
        provider_operation="llm_maya_report",
        logical_item_id=revision.id,
        attempt_no=1,
        request_hash=wire.request_hash,
        max_tokens=manifest.max_total_tokens,
        max_cost_cny=manifest.max_cost_cny,
        policy_hash=manifest.policy_hash,
        export_manifest_hash=manifest.manifest_hash,
        model_key=REAL_REPORT_MODEL,
        budget_bucket=LLM_MAYA_REPORT_BUCKET,
    )
    try:
        operation = runtime.repository.create_prepared(operation_request)
    except Exception as exc:
        raise ReportProviderError("report_operation_prepare_failed") from exc
    return RealReportPreparedOperation(
        revision_id=revision.id,
        debate_id=revision.debate_id,
        manifest_hash=manifest.manifest_hash,
        operation_id=str(operation.id),
        wire=wire,
        context=context,
    )


def _standing_report_consent(
    db: Session,
    *,
    prepared: RealReportPreparedOperation,
    runtime: RealReportRuntime,
) -> bool:
    """Confirm one report disclosure under the operator's standing consent.

    The same owner decision recorded for debate turns, and the same limits: it
    only applies while DEMO_MODE and DEMO_AUTO_CONFIRM_PROVIDER are both on,
    every check that guards a hand confirmation still runs, and a refusal still
    parks the report. It is standing consent, not an absence of consent.
    """

    settings = get_settings()
    if not getattr(settings, "demo_mode", False):
        return False
    if not getattr(settings, "demo_auto_confirm_provider", False):
        return False
    get_manifest_id = getattr(runtime.repository, "get_export_manifest_id", None)
    get_confirmation = getattr(runtime.repository, "get_export_confirmation", None)
    if not callable(get_manifest_id) or not callable(get_confirmation):
        return False
    manifest_row_id = get_manifest_id(prepared.manifest_hash)
    if manifest_row_id is None:
        return False
    # The same report inputs hash to the same manifest, so a retry re-derives a
    # manifest that already carries a confirmation. That confirmation is the
    # consent; re-recording it only violates the ledger's uniqueness.
    if get_confirmation(prepared.manifest_hash) is not None:
        return True
    manifest = db.get(ProviderExportManifest, manifest_row_id)
    if manifest is None:
        return False
    try:
        runtime.repository.save_export_confirmation(
            manifest_row_id,
            ExportConfirmationV1(
                manifest_hash=prepared.manifest_hash,
                policy_hash=str(manifest.policy_hash),
                confirmed_at=utc_now().isoformat(),
                confirmation_revision=int(getattr(manifest, "operation_revision", 1) or 1),
            ),
        )
    except Exception:
        LOGGER.exception("Standing consent could not confirm a report disclosure")
        return False
    # Say which confirmations were standing rather than hand-given, so an audit
    # can tell them apart.
    LOGGER.warning(
        "Report disclosure confirmed by standing Demo consent manifest=%s",
        prepared.manifest_hash,
    )
    return True


def _report_operation_for_call(
    db: Session,
    *,
    prepared: RealReportPreparedOperation,
    manifest_hash: str,
    call_no: int | None,
) -> ProviderOperation:
    """Resolve the exact prepared operation this call is allowed to send.

    ``call_no`` is the scripted acceptance harness's cursor. A teacher pressing
    Regenerate has no acceptance run, so under standing consent the harness
    binding is skipped -- it is a test-plan concern, not a disclosure control.
    Every hash and identity check still applies either way.
    """

    if call_no is not None:
        operation, _run = _bound_report_operation(
            db,
            prepared=prepared,
            manifest_hash=manifest_hash,
            call_no=call_no,
        )
        return operation
    if manifest_hash != prepared.manifest_hash:
        raise ReportProviderError("report_manifest_stale")
    prepared_operation = db.get(ProviderOperation, prepared.operation_id)
    if prepared_operation is None or prepared_operation.export_manifest_hash != manifest_hash:
        raise ReportProviderError("report_operation_missing")
    return prepared_operation


def _pause_real_report_job(db: Session, revision_id: str) -> None:
    job = db.scalar(
        select(Job).where(
            Job.operation == REPORT_GENERATE_OPERATION,
            Job.report_revision_id == revision_id,
        )
    )
    if job is None:
        raise ReportProviderError("report_job_missing")
    job.state = "interrupted"
    job.attempt = max(int(job.attempt or 0), 1)
    job.safe_error_code = "provider_confirmation_required"
    job.updated_at = utc_now()


def _resume_real_report_job(db: Session, revision_id: str) -> None:
    job = db.scalar(
        select(Job).where(
            Job.operation == REPORT_GENERATE_OPERATION,
            Job.report_revision_id == revision_id,
        )
    )
    if job is None:
        raise ReportProviderError("report_job_missing")
    if job.state == "interrupted" and job.safe_error_code == "provider_confirmation_required":
        job.state = "pending"
        job.safe_error_code = None
        job.updated_at = utc_now()
    elif job.state != "pending":
        raise ReportProviderError("report_job_not_pending")


def _bound_report_operation(
    db: Session,
    *,
    prepared: RealReportPreparedOperation,
    manifest_hash: str,
    call_no: int,
) -> tuple[ProviderOperation, DemoAcceptanceRun]:
    if manifest_hash != prepared.manifest_hash:
        raise ReportProviderError("report_manifest_stale")
    operation = db.get(ProviderOperation, prepared.operation_id)
    if operation is None or operation.export_manifest_hash != manifest_hash:
        raise ReportProviderError("report_operation_missing")
    run_id = operation.acceptance_run_id
    if run_id is None or operation.call_no != call_no:
        raise ReportProviderError("report_acceptance_call_required")
    run = db.get(DemoAcceptanceRun, run_id)
    if (
        run is None
        or run.state not in {"prepared", "executing"}
        or run.report_revision_id != prepared.revision_id
        or run.debate_id != prepared.debate_id
    ):
        raise ReportProviderError("report_acceptance_run_mismatch")
    return operation, run


def _mark_real_report_failed(
    db: Session,
    *,
    revision: CivilizationReportRevision,
    code: str,
    runtime: RealReportRuntime,
    operation_state: str | None = None,
) -> CivilizationReportRevision:
    operation = db.get(ProviderOperation, revision.id)
    if operation is None:
        operation = db.scalar(
            select(ProviderOperation).where(
                ProviderOperation.provider_operation == "llm_maya_report",
                ProviderOperation.logical_item_id == revision.id,
                ProviderOperation.attempt_no == 1,
            )
        )
    if operation is not None:
        try:
            current = runtime.repository.get(operation.id)
            state = operation_state or str(getattr(current, "state", operation.state))
            if state in {"sending", "reserved", "prepared"}:
                if code == "report_transport_not_sent":
                    runtime.repository.mark_not_sent(operation.id, safe_error_code=code)
                elif code == "report_acceptance_unknown":
                    runtime.repository.mark_acceptance_unknown(operation.id, safe_error_code=code)
                else:
                    runtime.repository.mark_failed(operation.id, safe_error_code=code)
        except Exception:
            # The report remains failed even if a secondary ledger transition
            # is unavailable; no provider retry or Mock fallback is allowed.
            pass
    revision.status = "failed"
    revision.english_markdown = None
    revision.word_count = None
    revision.safe_error_code = code
    revision.updated_at = utc_now()
    report = db.get(CivilizationReport, revision.report_id)
    if report is not None:
        report.generation_status = "failed"
        report.latest_attempt_status = "failed"
        report.updated_at = utc_now()
    _mark_job_failed(db, REPORT_GENERATE_OPERATION, revision.id, code, attempt=1)
    return revision


def _process_real_report_revision(
    db: Session,
    revision_id: str,
    *,
    runtime: RealReportRuntime,
    manifest_hash: str | None = None,
    call_no: int | None = None,
) -> CivilizationReportRevision:
    revision = db.get(CivilizationReportRevision, revision_id)
    if revision is None:
        raise not_found()
    if revision.status in {"ready", "failed"}:
        return revision
    if not _mark_job_running(db, REPORT_GENERATE_OPERATION, revision.id):
        return revision
    db.commit()
    revision = db.get(CivilizationReportRevision, revision_id)
    if revision is None:
        raise not_found()
    try:
        prepared = prepare_real_report_operation(db, revision.id, runtime=runtime)
    except ReportProviderError as exc:
        _mark_real_report_failed(db, revision=revision, code=exc.code, runtime=runtime)
        return revision
    if manifest_hash is None or call_no is None:
        # The operator's standing Demo consent, already recorded for debate
        # turns in generation_adapter._standing_provider_consent. A report is
        # the same situation: the teacher installed the policy and is the
        # person who would confirm, and parking here stops the lesson rather
        # than informing anyone. Without this the real report could never
        # finish from the teacher's screen at all -- it waited for a
        # /continue that only the scripted acceptance harness can send.
        consented = _standing_report_consent(db, prepared=prepared, runtime=runtime)
        if not consented:
            _pause_real_report_job(db, revision.id)
            db.flush()
            return revision
        manifest_hash = prepared.manifest_hash
        call_no = None
    try:
        operation = _report_operation_for_call(
            db,
            prepared=prepared,
            manifest_hash=manifest_hash,
            call_no=call_no,
        )
        wire = prepared.wire
        if wire.request_hash != operation.request_hash:
            raise ReportProviderError("report_wire_hash_stale")
        max_tokens = wire.budget.input_tokens + LLM_RESERVED_OUTPUT_TOKEN_CAP
        request = ProviderReservationRequestV1(
            operation_id=operation.id,
            scope_id=prepared.debate_id,
            provider_operation="llm_maya_report",
            logical_item_id=prepared.revision_id,
            attempt_no=1,
            request_hash=str(operation.request_hash),
            max_tokens=max_tokens,
            max_cost_cny=float(operation.max_cost_cny),
            policy_hash=str(operation.policy_hash),
            export_manifest_hash=manifest_hash,
            model_key=REAL_REPORT_MODEL,
            budget_bucket=LLM_MAYA_REPORT_BUCKET,
        )
        runtime.repository.assert_hashes_current(request)
        if (
            operation.state != "prepared"
            or operation.request_count != 0
            or operation.charged_request_count != 0
        ):
            raise ReportProviderError("report_operation_not_prepared")
        runtime.repository.reserve(operation.id)
        runtime.repository.transition(operation.id, expected="reserved", state="sending")
        sections = runtime.provider.execute_prepared(wire)
        markdown = render_real_report_markdown(prepared.context, sections)
        count = validate_report_markdown(
            markdown,
            manifest=prepared.context.manifest,
            vote_total=prepared.context.vote_total,
            barrage_total=prepared.context.barrage_total,
        )
    except ReportProviderError as exc:
        _mark_real_report_failed(db, revision=revision, code=exc.code, runtime=runtime)
        return revision
    except ReportValidationError as exc:
        LOGGER.warning("Real report validation failed: %s", exc.code)
        _mark_real_report_failed(db, revision=revision, code=exc.code, runtime=runtime)
        return revision
    except Exception as exc:
        # Record the exception type, never its message: a provider message can
        # carry endpoint or request detail. Without this line a report that
        # died here left only a generic code and no way to tell what broke.
        LOGGER.warning("Real report generation failed: %s", type(exc).__name__)
        _mark_real_report_failed(
            db,
            revision=revision,
            code="report_generation_failed",
            runtime=runtime,
        )
        return revision

    output_hash = _sha256(
        json.dumps(
            sections.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    try:
        revision.status = "ready"
        revision.attempt = 1
        revision.english_markdown = markdown
        revision.word_count = count
        revision.safe_error_code = None
        revision.updated_at = utc_now()
        report = db.get(CivilizationReport, revision.report_id)
        if report is None:
            raise ReportProviderError("report_aggregate_missing")
        report.generation_status = "ready"
        report.latest_attempt_status = "ready"
        report.updated_at = utc_now()
        # The current-success pointer carries a composite foreign key that
        # includes the revision's status, so the revision has to be 'ready' in
        # the database before the pointer row is written. Left to one flush,
        # the child insert can be emitted before the parent update and the
        # whole publication fails on a foreign key -- after the provider call
        # was already made and paid for.
        db.flush()
        pointer = db.scalar(
            select(CivilizationReportCurrentSuccess).where(
                CivilizationReportCurrentSuccess.report_id == report.id
            )
        )
        if pointer is None:
            db.add(
                CivilizationReportCurrentSuccess(
                    report_id=report.id,
                    revision_id=revision.id,
                    debate_id=revision.debate_id,
                    revision_status="ready",
                )
            )
        else:
            pointer.revision_id = revision.id
            pointer.debate_id = revision.debate_id
            pointer.revision_status = "ready"
        _mark_job_completed(db, REPORT_GENERATE_OPERATION, revision.id, attempt=1)
        _mark_debate_completed(db, revision.debate_id)
        # Flush report publication first so a constraint failure is rolled
        # back before the operation can be promoted.  The final operation and
        # reservation state are then staged on this same caller Session.
        db.flush()
        runtime.repository.complete_report_in_session(
            db,
            operation.id,
            response_hash=output_hash,
        )
    except ReportProviderError as exc:
        db.rollback()
        _mark_real_report_failed(db, revision=revision, code=exc.code, runtime=runtime)
    except Exception as exc:
        db.rollback()
        # Type only, never the message: publication touches provider ledger
        # rows whose errors can quote request detail.
        LOGGER.warning(
            "Real report publication failed: %s %s",
            type(exc).__name__,
            getattr(getattr(exc, "orig", None), "args", ("",))[0],
        )
        _mark_real_report_failed(
            db,
            revision=revision,
            code="report_publication_failed",
            runtime=runtime,
        )
    return revision


def continue_real_report_revision(
    db: Session,
    revision_id: str,
    *,
    manifest_hash: str,
    call_no: int,
    runtime: RealReportRuntime,
) -> CivilizationReportRevision:
    """Continue only an already attached, exact report operation."""

    revision = db.get(CivilizationReportRevision, revision_id)
    if revision is None:
        raise not_found()
    _resume_real_report_job(db, revision.id)
    return _process_real_report_revision(
        db,
        revision.id,
        runtime=runtime,
        manifest_hash=manifest_hash,
        call_no=call_no,
    )


def _latest_insight(db: Session, debate_id: str) -> BarrageInsightSnapshot | None:
    return db.scalar(
        select(BarrageInsightSnapshot)
        .where(BarrageInsightSnapshot.debate_id == debate_id)
        .order_by(BarrageInsightSnapshot.revision_no.desc())
    )


def _insight_dto(db: Session, debate_id: str) -> BarrageInsight:
    snapshot = _latest_insight(db, debate_id)
    if snapshot is None:
        return BarrageInsight(status="not_started", included_count=0, filtered_count=0, items=[])
    status = cast(Any, snapshot.status)
    items: list[BarrageInsightItemDTO] = []
    included_count = int(snapshot.included_count or 0)
    filtered_count = int(snapshot.filtered_count or 0)
    if snapshot.status == "ready":
        try:
            included_count, filtered_count, counts = _validate_db_insight_partition(
                db,
                snapshot,
                _json_list((_window_row(db, debate_id) or {}).get("frozen_barrage_ids_json")),
            )
        except PlatformError:
            # A corrupt derived row must not be rendered as a trusted DTO.
            status = "failed"
            included_count = filtered_count = 0
            counts = {}
        for item in db.scalars(
            select(BarrageInsightItemRow)
            .where(BarrageInsightItemRow.snapshot_id == snapshot.id)
            .order_by(BarrageInsightItemRow.order_index, BarrageInsightItemRow.id)
        ).all():
            count = (counts if snapshot.status == "ready" else {}).get(item.id, 0)
            if count:
                items.append(
                    # Pydantic's DTO is intentionally built here rather than
                    # exposing the internal item row or its message mapping.
                    BarrageInsightItemDTO(
                        category=cast(Any, item.category),
                        summary=item.summary,
                        count=count,
                    )
                )
    return BarrageInsight(
        status=status,
        included_count=included_count,
        filtered_count=filtered_count,
        items=items,
    )


def _revision_dto(
    db: Session,
    revision: CivilizationReportRevision,
) -> ReportRevision:
    common = {
        "id": _uuid(revision.id),
        "revision_no": revision.revision_no,
        "status": revision.status,
        "created_at": revision.created_at,
    }
    if revision.status == "generating":
        return GeneratingReportRevision.model_validate(
            {
                **common,
                "english_markdown": None,
                "word_count": None,
                "translated_markdown": None,
                "safe_error_code": None,
            }
        )
    if revision.status == "ready":
        return ReadyReportRevision.model_validate(
            {
                **common,
                "english_markdown": revision.english_markdown or "",
                "word_count": revision.word_count,
                "safe_error_code": None,
            }
        )
    return FailedReportRevision.model_validate(
        {
            **common,
            "english_markdown": None,
            "word_count": None,
            "translated_markdown": None,
            "safe_error_code": revision.safe_error_code or "report_generation_failed",
        }
    )


def _report_dto(db: Session, debate_id: str) -> Report:
    report = db.scalar(select(CivilizationReport).where(CivilizationReport.debate_id == debate_id))
    active: CivilizationReportRevision | None = None
    current: CivilizationReportRevision | None = None
    current_pointer = None
    if report is not None:
        active = db.scalar(
            select(CivilizationReportRevision)
            .where(
                CivilizationReportRevision.report_id == report.id,
                CivilizationReportRevision.status == "generating",
            )
            .order_by(CivilizationReportRevision.revision_no.desc())
        )
        current_pointer = db.scalar(
            select(CivilizationReportCurrentSuccess).where(
                CivilizationReportCurrentSuccess.report_id == report.id
            )
        )
        if current_pointer is not None:
            current = db.get(CivilizationReportRevision, current_pointer.revision_id)
            if current is None or current.status != "ready" or current.debate_id != debate_id:
                current = None
    score_summary: ReportScoreSummary | None = None
    for revision in (current, active):
        if revision is None or not revision.input_manifest_json:
            continue
        try:
            manifest = _load_report_manifest(revision.input_manifest_json)
        except (TypeError, ValueError):
            continue
        if isinstance(manifest, ReportInputManifestV2) and manifest.score_summary is not None:
            score_summary = manifest.score_summary
            break
    return Report(
        debate_id=_uuid(debate_id),
        generation_status=cast(Any, report.generation_status if report else "not_started"),
        latest_attempt_status=cast(Any, report.latest_attempt_status if report else "not_started"),
        insight=_insight_dto(db, debate_id),
        score_summary=score_summary,
        active_revision_id=_uuid(active.id) if active else None,
        current_success_revision=(
            cast(ReadyReportRevision, _revision_dto(db, current)) if current else None
        ),
    )


def get_current_report(db: Session, *, actor_user_id: str, debate_id: str) -> Report:
    _require_teacher(db, actor_user_id, debate_id)
    return _report_dto(db, debate_id)


def list_report_revisions(
    db: Session,
    *,
    actor_user_id: str,
    debate_id: str,
) -> list[ReportRevisionSummary]:
    _require_teacher(db, actor_user_id, debate_id)
    report = db.scalar(select(CivilizationReport).where(CivilizationReport.debate_id == debate_id))
    if report is None:
        return []
    revisions = db.scalars(
        select(CivilizationReportRevision)
        .where(CivilizationReportRevision.report_id == report.id)
        .order_by(CivilizationReportRevision.revision_no.desc())
    ).all()
    return [
        ReportRevisionSummary.model_validate(
            {
                "id": _uuid(revision.id),
                "revision_no": revision.revision_no,
                "status": revision.status,
                "word_count": revision.word_count if revision.status == "ready" else None,
                "safe_error_code": (
                    revision.safe_error_code if revision.status == "failed" else None
                ),
                "created_at": revision.created_at,
            }
        )
        for revision in revisions
    ]


def get_report_revision(
    db: Session,
    *,
    actor_user_id: str,
    debate_id: str,
    revision_id: str,
) -> ReportRevision:
    _require_teacher(db, actor_user_id, debate_id)
    revision = db.scalar(
        select(CivilizationReportRevision).where(
            CivilizationReportRevision.id == revision_id,
            CivilizationReportRevision.debate_id == debate_id,
        )
    )
    if revision is None:
        raise not_found()
    return _revision_dto(db, revision)


def _begin_immediate(db: Session) -> None:
    """Acquire the short SQLite writer lock for a report command."""

    db.rollback()
    db.execute(text("BEGIN IMMEDIATE"))


def _request_hash(debate_id: str) -> str:
    return _sha256(
        json.dumps(
            {"debate_id": debate_id, "operation": REPORT_GENERATE_OPERATION},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def _idempotency_replay_or_claim(
    db: Session,
    *,
    actor_user_id: str,
    key: str,
    request_hash: str,
) -> tuple[IdempotencyRecord, Report | None]:
    existing = db.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.actor_user_id == actor_user_id,
            IdempotencyRecord.operation == REPORT_GENERATE_OPERATION,
            IdempotencyRecord.key == key,
        )
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            raise idempotency_conflict()
        if existing.state == "completed" and existing.response_json:
            try:
                return existing, Report.model_validate(json.loads(existing.response_json))
            except (TypeError, ValueError):
                raise invalid_state("The report idempotency replay is invalid.") from None
        # A concurrent request may still own this key.  Never create a second
        # revision; the caller should retry after the original transaction
        # completes using the same idempotency key.
        raise conflict("idempotency_in_progress", "The report request is still in progress.")

    now = utc_now()
    record = IdempotencyRecord(
        id=str(uuid4()),
        actor_user_id=actor_user_id,
        operation=REPORT_GENERATE_OPERATION,
        key=key,
        request_hash=request_hash,
        state="pending",
        claim_token=str(uuid4()),
        lease_expires_at=now + timedelta(minutes=5),
        status_code=None,
        response_json=None,
        created_at=now,
        updated_at=now,
    )
    db.add(record)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise conflict(
            "idempotency_in_progress", "The report request is still in progress."
        ) from None
    return record, None


def _finish_idempotency(db: Session, record: IdempotencyRecord, report: Report) -> None:
    record.state = "completed"
    record.status_code = 202
    record.response_json = report.model_dump_json()
    record.updated_at = utc_now()


def regenerate_report(
    db: Session,
    *,
    actor_user_id: str,
    debate_id: str,
    idempotency_key: str,
) -> Report:
    """Create one new immutable report revision or an insight retry revision."""

    _require_teacher(db, actor_user_id, debate_id)
    if len(idempotency_key) < 16:
        raise conflict(
            "idempotency_conflict", "Idempotency-Key must contain at least 16 characters."
        )
    request_hash = _request_hash(debate_id)
    _begin_immediate(db)
    # Re-authorize and re-read after obtaining the writer lock.  A membership
    # change between the first read and this command must not grant authority.
    debate = _require_teacher(db, actor_user_id, debate_id)
    if uses_segment_protocol(debate) and not has_complete_finished_playback(db, debate_id):
        raise invalid_state("Conclude the complete classroom before generating its report.")
    record, replay = _idempotency_replay_or_claim(
        db,
        actor_user_id=actor_user_id,
        key=idempotency_key,
        request_hash=request_hash,
    )
    if replay is not None:
        return replay
    window = _window_row(db, debate_id)
    if window is None or window.get("status") != "finalized":
        raise invalid_state("Classroom interaction must be finalized before a report.")
    _frozen_message_rows(db, window)

    latest = _latest_insight(db, debate_id)
    if uses_segment_protocol(debate) and (latest is None or latest.status != "ready"):
        requested = db.scalar(
            select(CivilizationReport).where(CivilizationReport.debate_id == debate_id)
        )
        if requested is None:
            requested = CivilizationReport(
                id=str(uuid4()),
                debate_id=debate_id,
                policy_key=MOCK_MAYA_REPORT_POLICY_KEY,
                generation_status="generating",
                latest_attempt_status="generating",
                created_at=utc_now(),
                updated_at=utc_now(),
            )
            db.add(requested)
        else:
            requested.generation_status = "generating"
            requested.latest_attempt_status = "generating"
            requested.updated_at = utc_now()
    if latest is None or latest.status == "failed":
        next_revision = _next_snapshot_revision(db, debate_id)
        raw_hash = str(window.get("frozen_barrage_input_hash") or "")
        if len(raw_hash) != 64:
            raw_hash = _sha256(
                json.dumps(
                    _json_list(window.get("frozen_barrage_ids_json")),
                    separators=(",", ":"),
                )
            )
        latest = create_insight_snapshot(
            db,
            debate_id=debate_id,
            window_id=str(window["id"]),
            input_hash=raw_hash,
            revision_no=next_revision,
        )
        ensure_insight_job(db, latest)
    elif latest.status == "generating":
        ensure_insight_job(db, latest)
    else:
        _create_report_revision_for_insight(
            db,
            latest,
            trigger="manual",
            requested_by=actor_user_id,
        )
    db.flush()
    report = _report_dto(db, debate_id)
    _finish_idempotency(db, record, report)
    db.flush()
    return report


def process_report_revision(
    db: Session,
    revision_id: str,
    *,
    generator: Any = generate_mock_report,
    runtime: RealReportRuntime | None = None,
    manifest_hash: str | None = None,
    call_no: int | None = None,
) -> CivilizationReportRevision:
    """Run a pending report Job with one shared repair attempt."""

    if runtime is not None:
        return _process_real_report_revision(
            db,
            revision_id,
            runtime=runtime,
            manifest_hash=manifest_hash,
            call_no=call_no,
        )

    revision = db.get(CivilizationReportRevision, revision_id)
    if revision is None:
        raise not_found()
    if revision.status == "ready" or revision.status == "failed":
        return revision
    if not _mark_job_running(db, "report.generate", revision.id):
        return revision
    # Commit the claim before any report input read or Mock generation. A
    # crash after this point leaves an observable running Job for recovery.
    db.commit()
    revision = db.get(CivilizationReportRevision, revision_id)
    if revision is None:
        raise not_found()
    if not _job_is_running(db, "report.generate", revision.id):
        return revision
    try:
        manifest = _load_report_manifest(revision.input_manifest_json)
        context = _report_context(
            db,
            revision.debate_id,
            insight_snapshot_id=revision.insight_snapshot_id,
        )
        if context.manifest.canonical_json() != manifest.canonical_json():
            raise ValueError("report input manifest changed")
        if manifest.input_hash() != revision.input_manifest_hash:
            raise ValueError("report input manifest hash changed")
        markdown, _generator_count = generator(context)
        count = validate_report_markdown(
            markdown,
            manifest=context.manifest,
            vote_total=context.vote_total,
            barrage_total=context.barrage_total,
        )
    except Exception:
        revision.attempt = 2
        revision.updated_at = utc_now()
        try:
            manifest = _load_report_manifest(revision.input_manifest_json)
            context = _report_context(
                db,
                revision.debate_id,
                insight_snapshot_id=revision.insight_snapshot_id,
            )
            if context.manifest.canonical_json() != manifest.canonical_json():
                raise ValueError("report input manifest changed")
            markdown, _generator_count = generator(context)
            count = validate_report_markdown(
                markdown,
                manifest=context.manifest,
                vote_total=context.vote_total,
                barrage_total=context.barrage_total,
            )
        except Exception:
            if not _job_is_running(db, "report.generate", revision.id):
                db.rollback()
                current = db.get(CivilizationReportRevision, revision_id)
                if current is None:
                    raise not_found() from None
                return current
            revision.status = "failed"
            revision.english_markdown = None
            revision.word_count = None
            revision.safe_error_code = "report_generation_failed"
            revision.updated_at = utc_now()
            report = db.get(CivilizationReport, revision.report_id)
            if report is not None:
                report.generation_status = "failed"
                report.latest_attempt_status = "failed"
                report.updated_at = utc_now()
            _mark_job_failed(
                db,
                "report.generate",
                revision.id,
                "report_generation_failed",
                attempt=2,
            )
            db.flush()
            _mark_debate_completed(db, revision.debate_id)
            return revision

    if not _job_is_running(db, "report.generate", revision.id):
        db.rollback()
        current = db.get(CivilizationReportRevision, revision_id)
        if current is None:
            raise not_found()
        return current
    revision.status = "ready"
    revision.attempt = min(max(revision.attempt, 1), 2)
    revision.english_markdown = markdown
    revision.word_count = count
    revision.safe_error_code = None
    revision.updated_at = utc_now()
    report = db.get(CivilizationReport, revision.report_id)
    if report is None:
        raise invalid_state("The report aggregate is missing.")
    report.generation_status = "ready"
    report.latest_attempt_status = "ready"
    report.updated_at = utc_now()
    db.flush()
    pointer = db.scalar(
        select(CivilizationReportCurrentSuccess).where(
            CivilizationReportCurrentSuccess.report_id == report.id
        )
    )
    if pointer is None:
        db.add(
            CivilizationReportCurrentSuccess(
                report_id=report.id,
                revision_id=revision.id,
                debate_id=revision.debate_id,
                revision_status="ready",
            )
        )
    else:
        pointer.revision_id = revision.id
        pointer.debate_id = revision.debate_id
        pointer.revision_status = "ready"
    _mark_job_completed(
        db,
        "report.generate",
        revision.id,
        attempt=revision.attempt,
    )
    db.flush()
    _mark_debate_completed(db, revision.debate_id)
    return revision


def _mark_debate_completed(db: Session, debate_id: str) -> None:
    debate = db.get(Debate, debate_id)
    if debate is not None and debate.status == "debate_finished":
        debate.status = "completed"
        debate.finished_at = debate.finished_at or utc_now()
        debate.updated_at = utc_now()


def process_report_job(
    db: Session,
    revision_id: str,
    *,
    runtime: RealReportRuntime | None = None,
) -> CivilizationReportRevision:
    return process_report_revision(db, revision_id, runtime=runtime)


def download_current_report(
    db: Session,
    *,
    actor_user_id: str,
    debate_id: str,
    language: str = "en",
) -> tuple[str, str]:
    """Return English or exact-hash Mock Chinese report for a safe response."""

    _require_teacher(db, actor_user_id, debate_id)
    report = db.scalar(select(CivilizationReport).where(CivilizationReport.debate_id == debate_id))
    if report is None:
        raise not_found()
    pointer = db.scalar(
        select(CivilizationReportCurrentSuccess).where(
            CivilizationReportCurrentSuccess.report_id == report.id
        )
    )
    if pointer is None:
        raise not_found()
    revision = db.get(CivilizationReportRevision, pointer.revision_id)
    if revision is None or revision.status != "ready" or not revision.english_markdown:
        raise not_found()
    if language != "en":
        raise not_found()
    return revision.english_markdown, f"civilization-mutual-learning-report--{debate_id}.md"


def recover_report_jobs(db: Session) -> int:
    """Fail running M14 jobs after process restart; never rerun ready rows."""

    # Startup recovery is a writer operation.  Serialize it with worker
    # completion so a stale worker cannot race the failed transition.
    _begin_immediate(db)
    rows = list(
        db.scalars(
            select(Job).where(
                Job.operation.in_(("barrage_insight.generate", "report.generate")),
                Job.state == "running",
            )
        ).all()
    )
    recovered = 0
    owner_columns = set(Job.__table__.c.keys())
    for job in rows:
        owner_column = (
            "insight_snapshot_id"
            if job.operation.startswith("barrage_insight")
            else "report_revision_id"
        )
        owner_id = (
            str(getattr(job, owner_column))
            if owner_column in owner_columns and getattr(job, owner_column, None)
            else str(job.idempotency_key or "").rsplit(":", 1)[-1]
        )
        if owner_column == "insight_snapshot_id":
            snapshot = db.get(BarrageInsightSnapshot, owner_id)
            if snapshot is not None and snapshot.status == "generating":
                snapshot.status = "failed"
                snapshot.attempt = min(max(snapshot.attempt, 1), 2)
                snapshot.safe_error_code = "operation_interrupted"
                snapshot.updated_at = utc_now()
                fail_report_waiting_for_insight(db, snapshot.id)
                _mark_debate_completed(db, snapshot.debate_id)
        else:
            revision = db.get(CivilizationReportRevision, owner_id)
            if revision is not None and revision.status == "generating":
                revision.status = "failed"
                revision.attempt = min(max(revision.attempt, 1), 2)
                revision.safe_error_code = "operation_interrupted"
                revision.updated_at = utc_now()
                report = db.get(CivilizationReport, revision.report_id)
                if report is not None:
                    report.generation_status = "failed"
                    report.latest_attempt_status = "failed"
                    report.updated_at = utc_now()
                _mark_debate_completed(db, revision.debate_id)
        job.state = "failed"
        job.attempt = max(int(job.attempt or 0), 1)
        job.safe_error_code = "operation_interrupted"
        job.updated_at = utc_now()
        recovered += 1
    db.flush()
    return recovered


__all__ = [
    "MOCK_BARRAGE_INSIGHT_POLICY_KEY",
    "RealReportPreparedOperation",
    "RealReportRuntime",
    "ReportContext",
    "ReportSourceContext",
    "ReportTurnContext",
    "WORD_RE",
    "build_report_input_manifest",
    "build_real_report_request",
    "create_insight_snapshot",
    "download_current_report",
    "ensure_insight_job",
    "ensure_report_job",
    "generate_mock_report",
    "get_current_report",
    "get_report_revision",
    "list_report_revisions",
    "mock_maya_report_v1",
    "process_insight_job",
    "process_insight_snapshot",
    "process_report_job",
    "process_report_revision",
    "prepare_real_report_operation",
    "continue_real_report_revision",
    "recover_report_jobs",
    "regenerate_report",
    "render_report_markdown",
    "render_real_report_markdown",
    "report_word_count",
    "validate_report_markdown",
]
