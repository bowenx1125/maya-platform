"""M14 persistence, report input boundaries and Mock generation service.

This file intentionally consumes interaction data through SQL projections
rather than importing M13's implementation details.  The only values that
cross the anonymous boundary are frozen ``message_id`` and ``raw_text``;
nickname rows are never selected by the insight policy or report builder.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import delete, inspect, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import (
    PlatformError,
    conflict,
    forbidden,
    idempotency_conflict,
    invalid_state,
    not_found,
)
from app.core.models import CourseMember, IdempotencyRecord, Job, KnowledgeChunk
from app.modules.debates.models import Debate, DebateParticipant, DebateTurn, TurnSource
from app.modules.debates.playback.eligibility import has_complete_finished_playback

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
from .schemas import (
    BarrageInsight,
    FailedReportRevision,
    GeneratingReportRevision,
    ManifestInsight,
    ManifestInsightItem,
    ManifestParticipant,
    ManifestTurn,
    ManifestTurnSource,
    ManifestVote,
    MockBarrageInsightResult,
    ReadyReportRevision,
    Report,
    ReportInputManifestV1,
    ReportRevision,
    ReportRevisionSummary,
    ReportSectionOutput,
)
from .schemas import (
    BarrageInsightItem as BarrageInsightItemDTO,
)

WORD_RE = re.compile(r"[A-Za-z0-9]+(?:['’\-][A-Za-z0-9]+)*")
REPORT_GENERATE_OPERATION = "report.generate"
REPORT_HEADINGS = (
    "# Civilization Mutual Learning Report",
    "## Debate Overview",
    "## Evidence and Arguments",
    "## Areas of Convergence",
    "## Continuing Tensions and Questions",
    "## Classroom Perspectives",
    "## Mutual Learning Reflection",
)
_CITATION_RE = re.compile(
    r"\[evidence:([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89aAbB][0-9a-fA-F]{3}-[0-9a-fA-F]{12})\]"
)
_UNSAFE_REPORT_TERMS_RE = re.compile(
    r"\b(?:winner|winners|won|winning|vote\s+for\s+me|please\s+vote|nickname)\b",
    re.IGNORECASE,
)
_REPORT_PADDING_SENTENCE = (
    "This record supports careful comparison, source checking, respectful questioning, "
    "and revision after dialogue."
)


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


@dataclass(frozen=True)
class ReportTurnContext:
    turn_id: UUID
    participant_id: UUID
    participant_name: str
    round_no: int
    turn_index: int
    speech: str


@dataclass(frozen=True)
class ReportContext:
    debate: Debate
    manifest: ReportInputManifestV1
    turns: tuple[ReportTurnContext, ...]
    sources: tuple[ReportSourceContext, ...]
    vote_total: int
    barrage_total: int


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
    # The first automatic pipeline creates a report revision after insight is
    # ready.  A later report route may create another immutable revision.
    _create_report_revision_for_insight(db, snapshot, trigger="automatic", requested_by=None)
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
    expected_turn_count = len(participants) * 2
    if len(turns) != expected_turn_count:
        raise invalid_state("The public final-ready turn set is incomplete.")

    manifest_participants = [
        ManifestParticipant(
            participant_id=_uuid(row.id),
            slot=cast(Any, row.slot),
            order_index=row.order_index,
            agent_name=row.agent_name,
            stance_mode=cast(Any, row.stance_mode),
            initial_stance=cast(Any, row.initial_stance),
            current_stance=cast(Any, row.current_stance),
            initial_position_summary=row.initial_position_summary,
            current_position_summary=row.current_position_summary,
        )
        for row in participants
    ]
    participant_names = {row.id: row.agent_name for row in participants}
    manifest_turns: list[ManifestTurn] = []
    turn_context: list[ReportTurnContext] = []
    turn_ids = {row.id for row in turns}
    for row in turns:
        if row.participant_id not in participant_by_id:
            raise invalid_state("A public turn references an unknown participant.")
        if not row.speech:
            raise invalid_state("A public final-ready turn has no speech.")
        manifest_turns.append(
            ManifestTurn(
                turn_id=_uuid(row.id),
                participant_id=_uuid(row.participant_id),
                round_no=row.round_no,
                turn_index=row.turn_index,
                text_hash=_sha256(row.speech),
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
    manifest_sources: list[ManifestTurnSource] = []
    seen_source_ids: set[str] = set()
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
        seen_source_ids.add(source.id)
        chunk_hash = _sha256(chunk.chunk_text)
        manifest_sources.append(
            ManifestTurnSource(
                turn_source_id=_uuid(source.id),
                turn_id=_uuid(source.turn_id),
                turn_index=turn.turn_index,
                rank=source.rank,
                snapshot_id=_uuid(source.snapshot_id),
                chunk_id=_uuid(source.chunk_id),
                chunk_content_hash=chunk_hash,
                source_filename=source.source_filename,
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
    )


def build_report_input_manifest(db: Session, debate_id: str) -> ReportInputManifestV1:
    """Build and validate the exact manifest consumed by Mock Maya."""

    return _report_context(db, debate_id).manifest


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
    return _UNSAFE_REPORT_TERMS_RE.sub("outcome", text_value)


def _excerpt(value: str, words: int = 22) -> str:
    tokens = value.split()
    if len(tokens) <= words:
        return _safe_fragment(value)
    return _safe_fragment(" ".join(tokens[:words])) + "..."


def _citation(source: ReportSourceContext) -> str:
    return f"[evidence:{source.turn_source_id}]"


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
        lines.append(
            f"Turn {turn_index + 1} evidence {citations}: "
            f"{_excerpt(turn_sources[0].chunk_text, words=3)}."
        )
    return lines


def _vote_lines_for_manifest(manifest: ReportInputManifestV1) -> list[str]:
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
        f"The code-owned final vote total is {context.vote_total}, and the frozen barrage "
        f"message total is {context.barrage_total}. "
        + " ".join(vote_lines)
        + " "
        + (
            "Anonymous themes are summarized in the tensions section."
            if insight_lines
            else "No anonymous theme was retained."
        )
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
    while report_word_count(markdown) < 600:
        markdown = f"{markdown} {_REPORT_PADDING_SENTENCE}"
    return markdown


def report_word_count(markdown: str) -> int:
    without_citations = _CITATION_RE.sub("", markdown)
    return len(WORD_RE.findall(without_citations))


def validate_report_markdown(
    markdown: str,
    *,
    manifest: ReportInputManifestV1,
    vote_total: int,
    barrage_total: int,
) -> int:
    """Validate heading/citation/word/count safety before a ready commit."""

    if markdown.split("\n\n", 1)[0] != REPORT_HEADINGS[0]:
        raise ValueError("report title heading is not canonical")
    found_headings = [line for line in markdown.splitlines() if line.startswith("#")]
    if found_headings != list(REPORT_HEADINGS):
        raise ValueError("report headings are not canonical")
    known_source_ids = {str(item.turn_source_id) for item in manifest.turn_sources}
    citations = _CITATION_RE.findall(markdown)
    if any(citation.lower() not in known_source_ids for citation in citations):
        raise ValueError("report contains an unknown evidence citation")
    if {citation.lower() for citation in citations} != known_source_ids:
        raise ValueError("report citations do not match used sources")
    if re.search(r"\[evidence:[^\]]+\]", _CITATION_RE.sub("", markdown)):
        raise ValueError("report contains a malformed evidence citation")
    if _UNSAFE_REPORT_TERMS_RE.search(markdown):
        raise ValueError("report contains a prohibited winner or nickname phrase")
    zero_phrase = "This session had no classroom interaction data."
    if (vote_total == 0 and barrage_total == 0) != (zero_phrase in markdown):
        raise ValueError("zero-interaction report phrase does not match frozen counts")
    count = report_word_count(markdown)
    if not 600 <= count <= 900:
        raise ValueError("report word count is outside the 600-900 contract")
    manifest_vote_total = sum(item.count for item in manifest.votes)
    manifest_barrage_total = manifest.insight.included_count + manifest.insight.filtered_count
    if vote_total != manifest_vote_total or barrage_total != manifest_barrage_total:
        raise ValueError("report counts do not match the canonical manifest")
    total_marker = (
        f"The code-owned final vote total is {vote_total}, and the frozen barrage "
        f"message total is {barrage_total}."
    )
    if markdown.count(total_marker) != 1:
        raise ValueError("report is missing canonical interaction totals")
    expected_vote_lines = _vote_lines_for_manifest(manifest)
    if any(markdown.count(line) != 1 for line in expected_vote_lines):
        raise ValueError("report contains noncanonical participant vote counts")
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


def _latest_insight(db: Session, debate_id: str) -> BarrageInsightSnapshot | None:
    return db.scalar(
        select(BarrageInsightSnapshot)
        .where(BarrageInsightSnapshot.debate_id == debate_id)
        .order_by(BarrageInsightSnapshot.revision_no.desc())
    )


def _translated_markdown(
    db: Session,
    revision: CivilizationReportRevision,
) -> str | None:
    """Read only an exact-hash ready translation created by M15, if present."""

    if not _has_table(db, "translation_entries"):
        return None
    try:
        value = db.execute(
            text(
                "SELECT translated_text FROM translation_entries "
                "WHERE report_revision_id=:revision_id "
                "AND source_text_hash=:source_hash AND target_language='zh-Hans' "
                "AND policy_key='mock_translation_v1' AND quality_key='test_representation' "
                "AND status='ready' "
                "AND translated_text IS NOT NULL ORDER BY id LIMIT 1"
            ),
            {"revision_id": revision.id, "source_hash": _sha256(revision.english_markdown or "")},
        ).scalar_one_or_none()
    except Exception:
        # M15 may not yet have installed its table in an isolated test DB.
        return None
    return str(value) if value is not None else None


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
                "translated_markdown": _translated_markdown(db, revision),
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
    return Report(
        debate_id=_uuid(debate_id),
        generation_status=cast(Any, report.generation_status if report else "not_started"),
        latest_attempt_status=cast(Any, report.latest_attempt_status if report else "not_started"),
        insight=_insight_dto(db, debate_id),
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
    _require_teacher(db, actor_user_id, debate_id)
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
    report = _report_dto(db, debate_id)
    _finish_idempotency(db, record, report)
    db.flush()
    return report


def process_report_revision(
    db: Session,
    revision_id: str,
    *,
    generator: Any = generate_mock_report,
) -> CivilizationReportRevision:
    """Run a pending report Job with one shared repair attempt."""

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
        manifest = ReportInputManifestV1.model_validate(json.loads(revision.input_manifest_json))
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
            manifest = ReportInputManifestV1.model_validate(
                json.loads(revision.input_manifest_json)
            )
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


def process_report_job(db: Session, revision_id: str) -> CivilizationReportRevision:
    return process_report_revision(db, revision_id)


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
    if language == "en":
        return revision.english_markdown, f"civilization-mutual-learning-report--{debate_id}.md"
    if language != "zh-Hans":
        raise not_found()
    translated = _translated_markdown(db, revision)
    if translated is None:
        raise not_found()
    return translated, f"civilization-mutual-learning-report--{debate_id}--zh-Hans.md"


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
    "ReportContext",
    "ReportSourceContext",
    "ReportTurnContext",
    "WORD_RE",
    "build_report_input_manifest",
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
    "recover_report_jobs",
    "regenerate_report",
    "render_report_markdown",
    "report_word_count",
    "validate_report_markdown",
]
