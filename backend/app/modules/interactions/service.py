"""Transactional M13 classroom interaction service.

The anonymous routes use a fresh short-lived SQLAlchemy Session and issue
``BEGIN IMMEDIATE`` before their first domain read.  This is important for
SQLite: a submit/close race must be serialized by the same writer lock that
freezes the final snapshot.  No anonymous row has a User, Session or device
foreign key.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, cast
from uuid import UUID, uuid4

from sqlalchemy import and_, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import (
    PlatformError,
    conflict,
    forbidden,
    idempotency_conflict,
    invalid_state,
    not_found,
    unprocessable,
)
from app.core.models import CourseMember, IdempotencyRecord
from app.modules.debates.models import (
    Debate,
    DebateEvent,
    DebateParticipant,
    DebateTurn,
    PlaybackState,
)
from app.modules.debates.playback.eligibility import has_complete_finished_playback

from .models import (
    BarrageMessage,
    ClassroomInteractionWindow,
    InteractionFinalBarrage,
    InteractionFinalVoteCount,
    Vote,
)
from .schemas import (
    BarrageMessage as BarrageMessageDTO,
)
from .schemas import (
    BarrageRequest,
    BarrageSubmitted,
    PublicInteractionForm,
    PublicInteractionParticipant,
    TeacherInteractionClosed,
    TeacherInteractionFinalized,
    TeacherInteractionOpen,
    VoteAggregate,
    VoteRequest,
    VoteSubmitted,
)
from .tokens import ClassroomToken, issue_token, parse_token

IDEMPOTENCY_LEASE = timedelta(seconds=30)
OPEN_OPERATION = "interaction.open"
CLOSE_OPERATION = "interaction.close"
_SAFE_WINDOW_STATUSES = {"closed", "open", "finalized"}
TeacherInteractionProjection = (
    TeacherInteractionClosed | TeacherInteractionOpen | TeacherInteractionFinalized
)


class InsightEnqueuer(Protocol):
    """M14 injection seam used by close without importing the report module."""

    def enqueue_after_interaction_close(
        self,
        session: Session,
        *,
        window: ClassroomInteractionWindow,
        input_hash: str,
    ) -> None:
        """Create the typed insight snapshot/job in the caller's transaction."""


class NullInsightEnqueuer:
    """Safe local fallback for M13-focused tests before M14 is composed."""

    def enqueue_after_interaction_close(
        self,
        session: Session,
        *,
        window: ClassroomInteractionWindow,
        input_hash: str,
    ) -> None:
        del session, window, input_hash


@dataclass(frozen=True)
class PostCommitInteractionEvent:
    """Durable event values handed to the post-commit publisher seam."""

    event_id: str
    debate_id: str
    sequence: int
    event_type: str
    event_version: int
    occurred_at: datetime
    payload: dict[str, Any]


class PostCommitEventPublisher(Protocol):
    """Publish an already committed event without owning a DB Session."""

    def publish(self, event: PostCommitInteractionEvent) -> object:
        """Publish after commit; exceptions must not roll back the response."""


def _now() -> datetime:
    return datetime.now(UTC)


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _request_hash(operation: str, debate_id: str, body: Mapping[str, Any]) -> str:
    return _hash({"operation": operation, "debate_id": debate_id, "body": dict(body)})


def _as_uuid(value: str | UUID) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))


def _json_hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def ensure_closed_window(
    session: Session,
    *,
    debate_id: str,
    course_id: str,
    timestamp: datetime | None = None,
) -> ClassroomInteractionWindow:
    """Create the one closed window while a Debate creation transaction owns the lock.

    The route layer intentionally never calls this helper lazily.  The main
    composition/​Debate-creation path should call it in the same final writer
    transaction, while migration 0007 backfills historical Debates.
    """

    existing = session.scalar(
        select(ClassroomInteractionWindow).where(
            ClassroomInteractionWindow.debate_id == debate_id,
        )
    )
    if existing is not None:
        if existing.course_id != course_id:
            raise invalid_state("The interaction window is scoped to another course.")
        return existing
    now = timestamp or _now()
    window = ClassroomInteractionWindow(
        id=str(uuid4()),
        debate_id=debate_id,
        course_id=course_id,
        status="closed",
        token_nonce=None,
        revision=0,
        opened_by=None,
        opened_at=None,
        finalized_by=None,
        finalized_at=None,
        frozen_barrage_ids_json=None,
        frozen_barrage_input_hash=None,
        frozen_vote_totals_json=None,
        frozen_vote_input_hash=None,
        frozen_barrage_count=None,
        frozen_vote_count=None,
        created_at=now,
        updated_at=now,
    )
    session.add(window)
    session.flush()
    return window


def create_closed_window(
    session: Session,
    debate: Debate,
    *,
    timestamp: datetime | None = None,
) -> ClassroomInteractionWindow:
    """Main-owned Debate writer hook for the mandatory initial window.

    Call this after the new ``Debate`` row has been added and before that
    writer transaction commits.  It accepts the domain row directly so the
    Debate and course scope cannot drift apart in a caller-provided pair.
    Routes intentionally never call this helper lazily.
    """

    return ensure_closed_window(
        session,
        debate_id=str(debate.id),
        course_id=str(debate.course_id),
        timestamp=timestamp,
    )


def _public_origin(settings: Settings) -> str:
    origin = settings.classroom_public_origin
    if origin is None:
        raise PlatformError(
            "classroom_public_url_unavailable",
            "A private-LAN classroom URL is not configured.",
            503,
        )
    return origin.rstrip("/")


def _public_url(settings: Settings, window: ClassroomInteractionWindow) -> str:
    if window.token_nonce is None:
        raise invalid_state("The classroom interaction token is unavailable.")
    token = issue_token(window.id, bytes(window.token_nonce), settings.secret_bytes)
    return f"{_public_origin(settings)}/classroom/{token}"


def _window_token(settings: Settings, token: str) -> ClassroomToken:
    parsed = parse_token(token, settings.secret_bytes)
    if parsed is None:
        raise not_found()
    return parsed


def _require_teacher(
    session: Session,
    actor_user_id: str,
    debate_id: str,
    *,
    require_complete_finished: bool = False,
) -> Debate:
    debate = session.get(Debate, debate_id)
    if debate is None:
        raise not_found()
    role = session.scalar(
        select(CourseMember.role).where(
            CourseMember.course_id == debate.course_id,
            CourseMember.user_id == actor_user_id,
        )
    )
    if role is None:
        # Cross-course probing remains indistinguishable from a missing object.
        raise not_found()
    if role != "teacher":
        raise forbidden()
    # A partial Finish is product-level ``debate_finished`` but playback
    # remains stopped. Read projections opt into the complete public two-round
    # plan gate; the open mutation keeps its own invalid_state response.
    if debate.status == "stopped" or (
        require_complete_finished
        and debate.status in {"debate_finished", "completed"}
        and not has_complete_finished_playback(session, debate_id)
    ):
        raise not_found()
    return debate


def _window_for_debate(session: Session, debate_id: str) -> ClassroomInteractionWindow:
    window = session.scalar(
        select(ClassroomInteractionWindow).where(
            ClassroomInteractionWindow.debate_id == debate_id,
        )
    )
    if window is None:
        # Migration 0007 and Debate creation own window creation.  A route
        # must never silently create a second source of truth.
        raise invalid_state("The classroom interaction window is unavailable.")
    if window.status not in _SAFE_WINDOW_STATUSES:
        raise invalid_state("The classroom interaction window has an invalid state.")
    return window


def _participants(session: Session, debate_id: str) -> list[DebateParticipant]:
    return list(
        session.scalars(
            select(DebateParticipant)
            .where(DebateParticipant.debate_id == debate_id)
            .order_by(DebateParticipant.order_index, DebateParticipant.id)
        ).all()
    )


def _votes(session: Session, window_id: str) -> list[Vote]:
    return list(
        session.scalars(select(Vote).where(Vote.window_id == window_id).order_by(Vote.id)).all()
    )


def _barrages(session: Session, window_id: str) -> list[BarrageMessage]:
    return list(
        session.scalars(
            select(BarrageMessage)
            .where(BarrageMessage.window_id == window_id)
            .order_by(BarrageMessage.sequence, BarrageMessage.id)
        ).all()
    )


def _aggregates(
    session: Session,
    debate_id: str,
    window_id: str,
) -> list[VoteAggregate]:
    participants = _participants(session, debate_id)
    votes = _votes(session, window_id)
    counts: dict[str, int] = {str(item.id): 0 for item in participants}
    for vote in votes:
        if vote.participant_id in counts:
            counts[vote.participant_id] += 1
    total = sum(counts.values())
    output: list[VoteAggregate] = []
    for participant in participants:
        count = counts[str(participant.id)]
        # The contract uses one deterministic decimal place.  Avoid binary
        # representation drift by rounding the integer ratio before storing
        # the JSON projection.
        percentage = round((count * 1000 / total) if total else 0) / 10
        output.append(
            VoteAggregate(
                participant_id=_as_uuid(participant.id),
                count=count,
                percentage=percentage,
            )
        )
    return output


def _barrage_dtos(session: Session, window_id: str) -> list[BarrageMessageDTO]:
    return [
        BarrageMessageDTO(
            id=_as_uuid(row.id),
            nickname=row.nickname,
            raw_text=row.raw_text,
            sequence=row.sequence,
            submitted_at=row.submitted_at,
        )
        for row in _barrages(session, window_id)
    ]


def _final_aggregates(
    session: Session,
    debate_id: str,
    window_id: str,
) -> list[VoteAggregate]:
    participants = _participants(session, debate_id)
    final_counts = {
        row.participant_id: row.count
        for row in session.scalars(
            select(InteractionFinalVoteCount).where(
                InteractionFinalVoteCount.window_id == window_id,
                InteractionFinalVoteCount.debate_id == debate_id,
            )
        ).all()
    }
    if set(final_counts) != {row.id for row in participants}:
        raise invalid_state("The finalized vote snapshot is incomplete.")
    total = sum(final_counts.values())
    return [
        VoteAggregate(
            participant_id=_as_uuid(participant.id),
            count=final_counts[participant.id],
            percentage=(round(final_counts[participant.id] * 1000 / total) / 10 if total else 0),
        )
        for participant in participants
    ]


def _final_barrage_rows(
    session: Session,
    debate_id: str,
    window_id: str,
) -> list[BarrageMessage]:
    return list(
        session.scalars(
            select(BarrageMessage)
            .join(
                InteractionFinalBarrage,
                and_(
                    InteractionFinalBarrage.barrage_message_id == BarrageMessage.id,
                    InteractionFinalBarrage.window_id == BarrageMessage.window_id,
                    InteractionFinalBarrage.debate_id == BarrageMessage.debate_id,
                ),
            )
            .where(
                InteractionFinalBarrage.window_id == window_id,
                InteractionFinalBarrage.debate_id == debate_id,
            )
            .order_by(InteractionFinalBarrage.sequence, BarrageMessage.id)
        ).all()
    )


def _final_barrage_dtos(
    session: Session,
    debate_id: str,
    window_id: str,
) -> list[BarrageMessageDTO]:
    return [
        BarrageMessageDTO(
            id=_as_uuid(row.id),
            nickname=row.nickname,
            raw_text=row.raw_text,
            sequence=row.sequence,
            submitted_at=row.submitted_at,
        )
        for row in _final_barrage_rows(session, debate_id, window_id)
    ]


def _verify_final_projection(
    window: ClassroomInteractionWindow,
    votes: list[VoteAggregate],
    barrages: list[BarrageMessage],
) -> None:
    vote_totals = [
        {"participant_id": str(item.participant_id), "count": item.count} for item in votes
    ]
    barrage_ids = [row.id for row in barrages]
    barrage_inputs = [{"message_id": row.id, "raw_text": row.raw_text} for row in barrages]
    if (
        window.frozen_vote_count != sum(item.count for item in votes)
        or window.frozen_barrage_count != len(barrages)
        or window.frozen_vote_totals_json != _canonical(vote_totals)
        or window.frozen_vote_input_hash != _json_hash(vote_totals)
        or window.frozen_barrage_ids_json != _canonical(barrage_ids)
        or window.frozen_barrage_input_hash != _json_hash(barrage_inputs)
    ):
        raise invalid_state("The finalized classroom interaction snapshot is inconsistent.")


def _teacher_projection(
    session: Session,
    settings: Settings,
    window: ClassroomInteractionWindow,
) -> TeacherInteractionClosed | TeacherInteractionOpen | TeacherInteractionFinalized:
    if window.status == "closed":
        votes = _aggregates(session, window.debate_id, window.id)
        barrages = _barrage_dtos(session, window.id)
        return TeacherInteractionClosed(
            status="closed", public_url=None, votes=votes, barrages=barrages
        )
    if window.status == "open":
        votes = _aggregates(session, window.debate_id, window.id)
        barrages = _barrage_dtos(session, window.id)
        return TeacherInteractionOpen(
            status="open", public_url=_public_url(settings, window), votes=votes, barrages=barrages
        )
    votes = _final_aggregates(session, window.debate_id, window.id)
    final_barrages = _final_barrage_rows(session, window.debate_id, window.id)
    _verify_final_projection(window, votes, final_barrages)
    return TeacherInteractionFinalized(
        status="finalized",
        public_url=None,
        votes=votes,
        barrages=[
            BarrageMessageDTO(
                id=_as_uuid(row.id),
                nickname=row.nickname,
                raw_text=row.raw_text,
                sequence=row.sequence,
                submitted_at=row.submitted_at,
            )
            for row in final_barrages
        ],
    )


def _claim_authenticated_idempotency(
    session: Session,
    *,
    actor_user_id: str,
    operation: str,
    key: str,
    request_hash: str,
) -> tuple[IdempotencyRecord, dict[str, Any] | None]:
    """Claim or replay a key under the caller's existing writer lock."""

    if len(key) < 16:
        raise conflict(
            "idempotency_conflict", "Idempotency-Key must contain at least 16 characters."
        )
    existing = session.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.actor_user_id == actor_user_id,
            IdempotencyRecord.operation == operation,
            IdempotencyRecord.key == key,
        )
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            raise idempotency_conflict()
        if existing.state == "completed" and existing.response_json:
            try:
                value = json.loads(existing.response_json)
            except (TypeError, ValueError):
                raise invalid_state("The idempotency response is unavailable.") from None
            if not isinstance(value, dict):
                raise invalid_state("The idempotency response is unavailable.")
            return existing, value
        if existing.state == "pending":
            if existing.lease_expires_at.replace(tzinfo=UTC) > _now():
                raise conflict(
                    "invalid_state",
                    "An identical request is already in progress; retry shortly.",
                    {"retry_after_seconds": 1},
                )
            # A stale claim is safe to take over because this transaction
            # holds the writer lock and no side effect can commit alongside it.
            existing.claim_token = secrets.token_urlsafe(32)
            existing.lease_expires_at = _now() + IDEMPOTENCY_LEASE
            existing.updated_at = _now()
            return existing, None
        if existing.state == "abandoned":
            existing.state = "pending"
            existing.claim_token = secrets.token_urlsafe(32)
            existing.lease_expires_at = _now() + IDEMPOTENCY_LEASE
            existing.updated_at = _now()
            return existing, None
        raise invalid_state("The idempotency record has an invalid state.")

    now = _now()
    record = IdempotencyRecord(
        id=str(uuid4()),
        actor_user_id=actor_user_id,
        operation=operation,
        key=key,
        request_hash=request_hash,
        state="pending",
        claim_token=secrets.token_urlsafe(32),
        lease_expires_at=now + IDEMPOTENCY_LEASE,
        status_code=None,
        response_json=None,
        created_at=now,
        updated_at=now,
    )
    session.add(record)
    session.flush()
    return record, None


def _finish_idempotency(
    session: Session,
    record: IdempotencyRecord,
    *,
    status_code: int,
    response_payload: Mapping[str, Any],
) -> None:
    response_json = _canonical(dict(response_payload))
    changed = session.execute(
        update(IdempotencyRecord)
        .where(
            IdempotencyRecord.id == record.id,
            IdempotencyRecord.state == "pending",
            IdempotencyRecord.claim_token == record.claim_token,
        )
        .values(
            state="completed",
            status_code=status_code,
            response_json=response_json,
            updated_at=_now(),
        )
    )
    if int(getattr(changed, "rowcount", 0)) != 1:
        raise invalid_state("The idempotency claim is no longer owned by this request.")


def _event(
    session: Session,
    debate: Debate,
    event_type: str,
    payload: Mapping[str, Any],
) -> PostCommitInteractionEvent:
    previous_sequence = int(debate.last_sequence)
    sequence = previous_sequence + 1
    occurred_at = _now()
    payload_dict = dict(payload)
    event_id = str(uuid4())
    # BEGIN IMMEDIATE already serializes writers, while this explicit CAS
    # keeps the invariant visible to SQLite and protects a future caller that
    # accidentally reuses a stale Debate identity map.
    changed = session.execute(
        update(Debate)
        .where(Debate.id == debate.id, Debate.last_sequence == previous_sequence)
        .values(last_sequence=sequence, updated_at=occurred_at)
    )
    if int(getattr(changed, "rowcount", 0)) != 1:
        raise conflict("stale_sequence", "The debate event sequence is stale.")
    debate.last_sequence = sequence
    session.add(
        DebateEvent(
            id=event_id,
            debate_id=debate.id,
            sequence=sequence,
            event_type=event_type,
            event_version=1,
            payload_json=_canonical(payload_dict),
            occurred_at=occurred_at,
        )
    )
    return PostCommitInteractionEvent(
        event_id=event_id,
        debate_id=debate.id,
        sequence=sequence,
        event_type=event_type,
        event_version=1,
        occurred_at=occurred_at,
        payload=payload_dict,
    )


def _transition_window(
    session: Session,
    window: ClassroomInteractionWindow,
    *,
    expected_status: str,
    next_status: str,
    values: Mapping[str, Any],
) -> None:
    """Apply a visible lifecycle transition with an explicit status/revision CAS."""

    expected_revision = int(window.revision)
    changed = session.execute(
        update(ClassroomInteractionWindow)
        .where(
            ClassroomInteractionWindow.id == window.id,
            ClassroomInteractionWindow.status == expected_status,
            ClassroomInteractionWindow.revision == expected_revision,
        )
        .values(status=next_status, revision=expected_revision + 1, **dict(values))
    )
    if int(getattr(changed, "rowcount", 0)) != 1:
        raise conflict("stale_interaction", "The classroom interaction state is stale.")
    # Keep the identity map aligned with the CAS write for the rest of this
    # transaction and for the returned projection.
    session.expire(window)
    session.refresh(window)


def _publish(
    publisher: PostCommitEventPublisher | Callable[[PostCommitInteractionEvent], object] | None,
    event: PostCommitInteractionEvent,
) -> None:
    if publisher is None:
        return
    try:
        callback: Any = publisher.publish if hasattr(publisher, "publish") else publisher
        result = callback(event)
        # A sync route cannot safely attach a socket-lifetime Session to an
        # async event hub.  Main can inject a sync bridge; an accidental
        # awaitable is deliberately closed/ignored rather than affecting a
        # transaction that has already committed.
        if inspect.isawaitable(result):
            close = getattr(result, "close", None)
            if callable(close):
                close()
    except Exception:
        # Event delivery is best effort after the durable event commit.  The
        # next snapshot/reconnect reads the authoritative row and catches up.
        return


def _open_eligibility(session: Session, debate: Debate) -> None:
    if debate.status != "debate_finished":
        raise conflict(
            "invalid_state",
            "Classroom interaction can open only after the debate finishes.",
        )
    turns = list(
        session.scalars(
            select(DebateTurn)
            .where(DebateTurn.debate_id == debate.id)
            .order_by(DebateTurn.turn_index, DebateTurn.id)
        ).all()
    )
    participants = _participants(session, debate.id)
    expected_turn_count = len(participants) * 2
    expected_indexes = list(range(expected_turn_count))
    participant_ids = {row.id for row in participants}
    participant_rounds = {(row.participant_id, row.round_no) for row in turns}
    expected_rounds = {
        (participant.id, round_no) for participant in participants for round_no in (1, 2)
    }
    if (
        len(participants) < 2
        or len(turns) != expected_turn_count
        or [row.turn_index for row in turns] != expected_indexes
        or {row.participant_id for row in turns} != participant_ids
        or participant_rounds != expected_rounds
        or any(
            row.generation_status != "final_ready" or row.publication_status != "public"
            for row in turns
        )
    ):
        raise conflict(
            "invalid_state",
            "Every planned debate turn must be public and final-ready first.",
        )
    playback = session.scalar(select(PlaybackState).where(PlaybackState.debate_id == debate.id))
    if playback is None or playback.status != "completed":
        raise conflict("invalid_state", "The debate playback is not terminal yet.")
    for field in (
        "controller_epoch",
        "controller_owner_connection",
        "pending_action",
        "pending_ticket_hash",
        "pending_media_command_id",
    ):
        if getattr(playback, field, None) is not None:
            raise conflict("invalid_state", "The debate playback still has active authority.")


def _begin_writer(session_factory: Callable[[], Session]) -> Session:
    session = session_factory()
    try:
        # This must be the first SQL statement on this short-lived connection.
        session.execute(text("BEGIN IMMEDIATE"))
        return session
    except Exception:
        session.close()
        raise


def _abort(session: Session) -> None:
    if session.in_transaction():
        session.rollback()
    session.close()


class InteractionService:
    """M13 service with no dependency on the M14 implementation."""

    def __init__(
        self,
        *,
        session_factory: Callable[[], Session],
        settings: Settings,
        event_publisher: PostCommitEventPublisher
        | Callable[[PostCommitInteractionEvent], object]
        | None = None,
        insight_enqueuer: InsightEnqueuer | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.settings = settings
        self.event_publisher = event_publisher
        self.insight_enqueuer = insight_enqueuer or NullInsightEnqueuer()

    def get_teacher_interaction(
        self, *, actor_user_id: str, debate_id: str
    ) -> TeacherInteractionProjection:
        with self.session_factory() as session:
            _require_teacher(
                session,
                actor_user_id,
                debate_id,
                require_complete_finished=True,
            )
            window = _window_for_debate(session, debate_id)
            return _teacher_projection(session, self.settings, window)

    def open_interaction(
        self, *, actor_user_id: str, debate_id: str, idempotency_key: str
    ) -> TeacherInteractionProjection:
        # Validate URL configuration before changing any window state.
        _public_origin(self.settings)
        request_hash = _request_hash(OPEN_OPERATION, debate_id, {})
        session = _begin_writer(self.session_factory)
        event: PostCommitInteractionEvent | None = None
        try:
            debate = _require_teacher(session, actor_user_id, debate_id)
            record, replay = _claim_authenticated_idempotency(
                session,
                actor_user_id=actor_user_id,
                operation=OPEN_OPERATION,
                key=idempotency_key,
                request_hash=request_hash,
            )
            window = _window_for_debate(session, debate_id)
            if replay is not None:
                session.commit()
                result = _teacher_projection(session, self.settings, window)
                session.close()
                return result
            if window.status == "finalized":
                raise conflict("invalid_state", "A finalized classroom interaction cannot reopen.")
            if window.status == "open":
                # Another idempotency key cannot reopen/rotate the capability.
                raise conflict("invalid_state", "The classroom interaction is already open.")
            _open_eligibility(session, debate)
            timestamp = _now()
            nonce = secrets.token_bytes(32)
            _transition_window(
                session,
                window,
                expected_status="closed",
                next_status="open",
                values={
                    "token_nonce": nonce,
                    "opened_by": actor_user_id,
                    "opened_at": timestamp,
                    "updated_at": timestamp,
                },
            )
            event = _event(
                session,
                debate,
                "interaction.opened",
                {
                    "window_id": str(window.id),
                    "aggregate_zeros": [
                        {"participant_id": str(row.participant_id), "count": 0, "percentage": 0}
                        for row in _aggregates(session, debate_id, window.id)
                    ],
                    "status": "open",
                },
            )
            result = _teacher_projection(session, self.settings, window)
            stored = result.model_dump(mode="json")
            stored["public_url"] = None
            _finish_idempotency(session, record, status_code=200, response_payload=stored)
            session.commit()
        except Exception:
            _abort(session)
            raise
        else:
            session.close()
            if event is not None:
                _publish(self.event_publisher, event)
            return result

    def close_interaction(
        self, *, actor_user_id: str, debate_id: str, idempotency_key: str
    ) -> TeacherInteractionProjection:
        request_hash = _request_hash(CLOSE_OPERATION, debate_id, {})
        session = _begin_writer(self.session_factory)
        event: PostCommitInteractionEvent | None = None
        try:
            debate = _require_teacher(session, actor_user_id, debate_id)
            record, replay = _claim_authenticated_idempotency(
                session,
                actor_user_id=actor_user_id,
                operation=CLOSE_OPERATION,
                key=idempotency_key,
                request_hash=request_hash,
            )
            window = _window_for_debate(session, debate_id)
            if replay is not None:
                result = _teacher_projection(session, self.settings, window)
                session.commit()
                session.close()
                return result
            if window.status != "open":
                raise conflict("invalid_state", "Only an open classroom interaction can close.")
            votes = _votes(session, window.id)
            barrages = _barrages(session, window.id)
            aggregates = _aggregates(session, debate_id, window.id)
            vote_totals = [
                {"participant_id": str(item.participant_id), "count": item.count}
                for item in aggregates
            ]
            barrage_ids = [str(item.id) for item in barrages]
            barrage_inputs = [
                {"message_id": str(item.id), "raw_text": item.raw_text} for item in barrages
            ]
            vote_input_hash = _json_hash(vote_totals)
            barrage_input_hash = _json_hash(barrage_inputs)
            combined_input_hash = _json_hash({"votes": vote_totals, "barrages": barrage_inputs})
            # Normalized final rows are the immutable read model.  Include
            # zero-count participants so the closed snapshot preserves the
            # exact participant ordering and percentage denominator.
            for aggregate in aggregates:
                session.add(
                    InteractionFinalVoteCount(
                        window_id=window.id,
                        debate_id=window.debate_id,
                        participant_id=str(aggregate.participant_id),
                        count=aggregate.count,
                    )
                )
            for barrage in barrages:
                session.add(
                    InteractionFinalBarrage(
                        window_id=window.id,
                        debate_id=window.debate_id,
                        barrage_message_id=barrage.id,
                        sequence=barrage.sequence,
                    )
                )
            session.flush()
            timestamp = _now()
            _transition_window(
                session,
                window,
                expected_status="open",
                next_status="finalized",
                values={
                    "finalized_by": actor_user_id,
                    "finalized_at": timestamp,
                    "frozen_barrage_ids_json": _canonical(barrage_ids),
                    "frozen_barrage_input_hash": barrage_input_hash,
                    "frozen_vote_totals_json": _canonical(vote_totals),
                    "frozen_vote_input_hash": vote_input_hash,
                    "frozen_barrage_count": len(barrages),
                    "frozen_vote_count": len(votes),
                    "updated_at": timestamp,
                },
            )
            self.insight_enqueuer.enqueue_after_interaction_close(
                session,
                window=window,
                # Insight consumes only the frozen anonymous barrage text;
                # keep its typed snapshot hash aligned with the raw-text
                # boundary.  The event below still carries the combined
                # vote+barrage hash for the teacher-stage catch-up signal.
                input_hash=barrage_input_hash,
            )
            event = _event(
                session,
                debate,
                "interaction.closed",
                {
                    "totals": {
                        "total_votes": len(votes),
                        "total_barrages": len(barrages),
                    },
                    "message_count": len(barrages),
                    "input_hash": combined_input_hash,
                },
            )
            result = _teacher_projection(session, self.settings, window)
            stored = result.model_dump(mode="json")
            _finish_idempotency(session, record, status_code=202, response_payload=stored)
            session.commit()
        except Exception:
            _abort(session)
            raise
        else:
            session.close()
            if event is not None:
                _publish(self.event_publisher, event)
            return result

    def public_form(self, *, access_token: str) -> PublicInteractionForm:
        parsed = _window_token(self.settings, access_token)
        with self.session_factory() as session:
            window = session.scalar(
                select(ClassroomInteractionWindow).where(
                    ClassroomInteractionWindow.id == str(parsed.window_id),
                    ClassroomInteractionWindow.token_nonce == parsed.nonce,
                )
            )
            if window is None:
                raise not_found()
            if window.status == "finalized":
                raise PlatformError(
                    "interaction_finalized",
                    "Classroom interaction collection has ended.",
                    410,
                )
            if window.status != "open":
                raise not_found()
            participants = _participants(session, window.debate_id)
            debate = session.get(Debate, window.debate_id)
            if debate is None:
                raise not_found()
            return PublicInteractionForm(
                topic=debate.topic,
                participants=[
                    PublicInteractionParticipant(
                        participant_id=_as_uuid(row.id),
                        slot=cast(Any, row.slot),
                        name=row.agent_name,
                    )
                    for row in participants
                ],
            )

    def submit_vote(
        self,
        *,
        access_token: str,
        payload: VoteRequest,
    ) -> VoteSubmitted:
        parsed = _window_token(self.settings, access_token)
        session = _begin_writer(self.session_factory)
        event: PostCommitInteractionEvent | None = None
        try:
            window = session.scalar(
                select(ClassroomInteractionWindow).where(
                    ClassroomInteractionWindow.id == str(parsed.window_id),
                    ClassroomInteractionWindow.token_nonce == parsed.nonce,
                )
            )
            if window is None:
                raise not_found()
            existing = session.scalar(
                select(Vote).where(
                    Vote.window_id == window.id,
                    Vote.client_submission_id == str(payload.client_submission_id),
                )
            )
            if existing is not None:
                if existing.participant_id != str(payload.participant_id):
                    raise idempotency_conflict()
                session.commit()
                session.close()
                return VoteSubmitted(vote_submitted=True)
            if window.status == "finalized":
                raise PlatformError(
                    "interaction_finalized",
                    "Classroom interaction collection has ended.",
                    410,
                )
            if window.status != "open":
                raise not_found()
            participant = session.scalar(
                select(DebateParticipant).where(
                    DebateParticipant.id == str(payload.participant_id),
                    DebateParticipant.debate_id == window.debate_id,
                )
            )
            if participant is None:
                raise unprocessable(
                    "participant_not_in_debate",
                    "The selected participant is not part of this debate.",
                )
            vote = Vote(
                id=str(uuid4()),
                window_id=window.id,
                debate_id=window.debate_id,
                participant_id=str(payload.participant_id),
                client_submission_id=str(payload.client_submission_id),
                submitted_at=_now(),
            )
            session.add(vote)
            session.flush()
            debate = session.get(Debate, window.debate_id)
            if debate is None:
                raise not_found()
            aggregate = next(
                row
                for row in _aggregates(session, window.debate_id, window.id)
                if str(row.participant_id) == str(participant.id)
            )
            event = _event(
                session,
                debate,
                "interaction.vote_created",
                {
                    "participant_id": str(participant.id),
                    "slot": participant.slot,
                    "new_count": aggregate.count,
                    "percentage": aggregate.percentage,
                    "total_votes": len(_votes(session, window.id)),
                },
            )
            session.commit()
        except IntegrityError:
            _abort(session)
            # A concurrent duplicate can only occur if a different process
            # ignored the writer lock; expose the same deterministic replay
            # semantics after reopening a short read.
            with self.session_factory() as retry:
                row = retry.scalar(
                    select(Vote).where(
                        Vote.window_id == str(parsed.window_id),
                        Vote.client_submission_id == str(payload.client_submission_id),
                    )
                )
                if row is not None and row.participant_id == str(payload.participant_id):
                    return VoteSubmitted(vote_submitted=True)
            raise idempotency_conflict() from None
        except Exception:
            _abort(session)
            raise
        else:
            session.close()
            if event is not None:
                _publish(self.event_publisher, event)
            return VoteSubmitted(vote_submitted=True)

    def submit_barrage(
        self,
        *,
        access_token: str,
        payload: BarrageRequest,
    ) -> BarrageSubmitted:
        parsed = _window_token(self.settings, access_token)
        session = _begin_writer(self.session_factory)
        event: PostCommitInteractionEvent | None = None
        try:
            window = session.scalar(
                select(ClassroomInteractionWindow).where(
                    ClassroomInteractionWindow.id == str(parsed.window_id),
                    ClassroomInteractionWindow.token_nonce == parsed.nonce,
                )
            )
            if window is None:
                raise not_found()
            existing = session.scalar(
                select(BarrageMessage).where(
                    BarrageMessage.window_id == window.id,
                    BarrageMessage.client_submission_id == str(payload.client_submission_id),
                )
            )
            if existing is not None:
                if existing.nickname != payload.nickname or existing.raw_text != payload.raw_text:
                    raise idempotency_conflict()
                session.commit()
                session.close()
                return BarrageSubmitted(barrage_submitted=True)
            if window.status == "finalized":
                raise PlatformError(
                    "interaction_finalized",
                    "Classroom interaction collection has ended.",
                    410,
                )
            if window.status != "open":
                raise not_found()
            if not payload.nickname.strip() or not payload.raw_text.strip():
                raise unprocessable("barrage_blank", "Nickname and barrage text must not be blank.")
            next_sequence = (
                int(
                    session.scalar(
                        select(func.coalesce(func.max(BarrageMessage.sequence), 0)).where(
                            BarrageMessage.window_id == window.id
                        )
                    )
                    or 0
                )
                + 1
            )
            barrage = BarrageMessage(
                id=str(uuid4()),
                window_id=window.id,
                debate_id=window.debate_id,
                nickname=payload.nickname,
                raw_text=payload.raw_text,
                client_submission_id=str(payload.client_submission_id),
                sequence=next_sequence,
                submitted_at=_now(),
            )
            session.add(barrage)
            session.flush()
            debate = session.get(Debate, window.debate_id)
            if debate is None:
                raise not_found()
            event = _event(
                session,
                debate,
                "interaction.barrage_created",
                {
                    "message_id": barrage.id,
                    "nickname": barrage.nickname,
                    "raw_text": barrage.raw_text,
                    "sequence": barrage.sequence,
                },
            )
            session.commit()
        except IntegrityError:
            _abort(session)
            with self.session_factory() as retry:
                row = retry.scalar(
                    select(BarrageMessage).where(
                        BarrageMessage.window_id == str(parsed.window_id),
                        BarrageMessage.client_submission_id == str(payload.client_submission_id),
                    )
                )
                if (
                    row is not None
                    and row.nickname == payload.nickname
                    and row.raw_text == payload.raw_text
                ):
                    return BarrageSubmitted(barrage_submitted=True)
            raise idempotency_conflict() from None
        except Exception:
            _abort(session)
            raise
        else:
            session.close()
            if event is not None:
                _publish(self.event_publisher, event)
            return BarrageSubmitted(barrage_submitted=True)


def service_from_context(
    *,
    session_factory: Callable[[], Session],
    settings: Settings,
    event_publisher: PostCommitEventPublisher
    | Callable[[PostCommitInteractionEvent], object]
    | None = None,
    insight_enqueuer: InsightEnqueuer | None = None,
) -> InteractionService:
    """Composition helper kept small so main can inject M14/event adapters."""

    return InteractionService(
        session_factory=session_factory,
        settings=settings,
        event_publisher=event_publisher,
        insight_enqueuer=insight_enqueuer,
    )


__all__ = [
    "ClassroomInteractionWindow",
    "CLOSE_OPERATION",
    "create_closed_window",
    "InsightEnqueuer",
    "InteractionService",
    "NullInsightEnqueuer",
    "PostCommitEventPublisher",
    "PostCommitInteractionEvent",
    "OPEN_OPERATION",
    "ensure_closed_window",
    "service_from_context",
]
