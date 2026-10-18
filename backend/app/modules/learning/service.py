"""Owner-scoped, append-only learning records and versioned Assessments."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Literal, cast
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import conflict, idempotency_conflict, not_found, stale_revision, unprocessable
from app.core.models import CourseMember
from app.core.read_memo import memoized
from app.modules.auth.service import AuthContext
from app.modules.knowledge.services import course_member_role, scoped_group_role_for_user
from app.modules.teams.models import CourseTeamPublication, Team, TeamVersion
from app.modules.workspace.models import Conversation

from .models import (
    LearningAssessment,
    LearningAssessmentMutation,
    LearningAssessmentRevision,
    LearningRecord,
)
from .schemas import (
    AssessmentDTO,
    AssessmentRevisionDTO,
    AssessmentWriteReceipt,
    CreateAssessmentRequest,
    EditAssessmentRequest,
    LearningProvenance,
    LearningRecordDTO,
    LearningRecordRequest,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _canonical(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError):
        raise unprocessable(
            "invalid_learning_payload", "The learning payload is not valid JSON."
        ) from None


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _authorized_provenance(
    db: Session,
    actor: AuthContext,
    conversation_id: str | UUID,
) -> tuple[Conversation, LearningProvenance]:
    def check() -> tuple[str, LearningProvenance]:
        conversation, provenance = _read_authorized_provenance(db, actor, conversation_id)
        return conversation.id, provenance

    key = ("authorized_provenance", str(actor.user.id), actor.user.status, str(conversation_id))
    checked_id, provenance = memoized(db, key, check, across_sessions=True)
    # The check is shared by the request; the row is always this Session's own.
    conversation = db.get(Conversation, checked_id)
    if conversation is None:
        return _read_authorized_provenance(db, actor, conversation_id)
    return conversation, provenance.model_copy()


def _read_authorized_provenance(
    db: Session,
    actor: AuthContext,
    conversation_id: str | UUID,
) -> tuple[Conversation, LearningProvenance]:
    user_id = str(actor.user.id)
    conversation = db.scalar(
        select(Conversation).where(
            Conversation.id == str(conversation_id),
            Conversation.user_id == user_id,
            Conversation.withdrawn_at.is_(None),
        )
    )
    if conversation is None:
        raise not_found()
    if db.get(CourseMember, (conversation.course_id, user_id)) is None:
        raise not_found()
    if actor.user.status != "active":
        raise not_found()

    team_id: str | None = None
    team_version_id: str | None = None
    if conversation.entry_kind == "agent":
        if (
            conversation.origin != "single_agent"
            or conversation.team_id is not None
            or conversation.team_version_id is not None
        ):
            raise not_found()
    elif conversation.entry_kind in {"team", "maya_team"}:
        team_id = conversation.team_id
        team_version_id = conversation.team_version_id
        if not team_id or not team_version_id or conversation.team_authorization_epoch is None:
            raise not_found()
        team, version = db.execute(
            select(Team, TeamVersion)
            .join(TeamVersion, TeamVersion.team_id == Team.id)
            .where(
                Team.id == team_id,
                TeamVersion.id == team_version_id,
                Team.course_id == conversation.course_id,
                Team.owner_user_id == conversation.team_owner_user_id,
                Team.deleted_at.is_(None),
                Team.authorization_epoch == conversation.team_authorization_epoch,
                TeamVersion.authorization_epoch == conversation.team_authorization_epoch,
                TeamVersion.display_name == conversation.team_name_snapshot,
            )
        ).first() or (None, None)
        if team is None or version is None:
            raise not_found()
        if conversation.entry_kind == "team":
            if conversation.origin != "custom_team" or conversation.publication_id is not None:
                raise not_found()
            if (
                team.group_id is not None
                and scoped_group_role_for_user(db, user_id, team.group_id) != "student"
            ):
                raise not_found()
            if team.owner_user_id != user_id and (
                team.ownership_scope != "group"
                or team.visibility != "public"
                or team.group_id is None
            ):
                raise not_found()
        else:
            if conversation.origin != "published_course_team" or not conversation.publication_id:
                raise not_found()
            if (
                team.ownership_scope != "personal"
                or team.visibility != "public"
                or course_member_role(db, team.owner_user_id, team.course_id) != "teacher"
            ):
                raise not_found()
            publication = db.scalar(
                select(CourseTeamPublication).where(
                    CourseTeamPublication.id == conversation.publication_id,
                    CourseTeamPublication.team_id == team_id,
                    CourseTeamPublication.team_version_id == team_version_id,
                    CourseTeamPublication.course_id == conversation.course_id,
                    CourseTeamPublication.publisher_user_id == conversation.team_owner_user_id,
                    CourseTeamPublication.authorization_epoch == conversation.publication_epoch,
                    CourseTeamPublication.state.in_(("published", "retained")),
                )
            )
            if publication is None:
                raise not_found()
    else:
        raise not_found()
    if conversation.origin not in {
        "single_agent",
        "custom_team",
        "published_course_team",
    } or conversation.chat_visibility not in {"private", "public"}:
        raise not_found()

    provenance = LearningProvenance(
        actor_user_id=UUID(user_id),
        course_id=UUID(conversation.course_id),
        conversation_id=UUID(conversation.id),
        team_id=UUID(team_id) if team_id else None,
        team_version_id=UUID(team_version_id) if team_version_id else None,
        origin=cast(
            Literal["single_agent", "custom_team", "published_course_team"],
            conversation.origin,
        ),
        chat_visibility=cast(Literal["private", "public"], conversation.chat_visibility),
        activity_id=None,
        attempt_id=None,
    )
    return conversation, provenance


def _record_dto(row: LearningRecord) -> LearningRecordDTO:
    if (
        row.record_kind not in {"answer", "skip", "hint", "evidence"}
        or row.origin not in {"single_agent", "custom_team", "published_course_team"}
        or row.chat_visibility not in {"private", "public"}
    ):
        raise conflict("learning_state_invalid", "The saved learning record is invalid.")
    return LearningRecordDTO(
        id=UUID(row.id),
        client_event_id=UUID(row.client_event_id),
        kind=cast(Literal["answer", "skip", "hint", "evidence"], row.record_kind),
        payload=json.loads(row.payload_json),
        provenance=LearningProvenance(
            actor_user_id=UUID(row.actor_user_id),
            course_id=UUID(row.course_id),
            conversation_id=UUID(row.conversation_id),
            team_id=UUID(row.team_id) if row.team_id else None,
            team_version_id=UUID(row.team_version_id) if row.team_version_id else None,
            origin=cast(
                Literal["single_agent", "custom_team", "published_course_team"],
                row.origin,
            ),
            chat_visibility=cast(Literal["private", "public"], row.chat_visibility),
            activity_id=UUID(row.activity_id) if row.activity_id else None,
            attempt_id=UUID(row.attempt_id) if row.attempt_id else None,
        ),
        created_at=row.created_at,
    )


def record_learning_event(
    db: Session,
    actor: AuthContext,
    conversation_id: str | UUID,
    request: LearningRecordRequest,
) -> LearningRecordDTO:
    """Append an answer, skip, hint, or evidence fact with a scoped replay key."""

    conversation, provenance = _authorized_provenance(db, actor, conversation_id)
    if request.kind in {"answer", "skip", "hint"}:
        from .attempts import get_assessment_runtime_context

        active_attempt = get_assessment_runtime_context(db, actor, conversation.id)
        if active_attempt is not None:
            raise conflict(
                "assessment_attempt_tool_required",
                "Use the current assessment action for this active attempt.",
            )
    payload = request.model_dump(mode="json", exclude={"client_event_id"})
    payload_json = _canonical(payload)
    payload_hash = _hash({"conversation_id": str(conversation_id), "payload": payload})
    existing = db.scalar(
        select(LearningRecord).where(
            LearningRecord.actor_user_id == str(actor.user.id),
            LearningRecord.conversation_id == str(conversation_id),
            LearningRecord.client_event_id == str(request.client_event_id),
        )
    )
    if existing is not None:
        if existing.payload_hash != payload_hash:
            raise idempotency_conflict()
        return _record_dto(existing)

    row = LearningRecord(
        id=str(uuid4()),
        actor_user_id=str(provenance.actor_user_id),
        course_id=str(provenance.course_id),
        conversation_id=str(provenance.conversation_id),
        team_id=str(provenance.team_id) if provenance.team_id else None,
        team_version_id=str(provenance.team_version_id) if provenance.team_version_id else None,
        origin=provenance.origin,
        chat_visibility=provenance.chat_visibility,
        activity_id=None,
        attempt_id=None,
        record_kind=request.kind,
        client_event_id=str(request.client_event_id),
        payload_json=payload_json,
        payload_hash=payload_hash,
        created_at=_now(),
    )
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError:
        replay = db.scalar(
            select(LearningRecord).where(
                LearningRecord.actor_user_id == str(actor.user.id),
                LearningRecord.conversation_id == str(conversation_id),
                LearningRecord.client_event_id == str(request.client_event_id),
            )
        )
        if replay is None:
            raise
        if replay.payload_hash != payload_hash:
            raise idempotency_conflict() from None
        return _record_dto(replay)
    db.refresh(row)
    return _record_dto(row)


def read_learning_records(
    db: Session,
    actor: AuthContext,
    conversation_id: str | UUID,
) -> list[LearningRecordDTO]:
    conversation, _provenance = _authorized_provenance(db, actor, conversation_id)
    from .attempts import get_assessment_runtime_context

    active_attempt = get_assessment_runtime_context(db, actor, conversation.id)
    if active_attempt is not None:
        return []
    rows = db.scalars(
        select(LearningRecord)
        .where(
            LearningRecord.actor_user_id == str(actor.user.id),
            LearningRecord.conversation_id == str(conversation_id),
        )
        .order_by(LearningRecord.created_at, LearningRecord.id)
    ).all()
    return [_record_dto(row) for row in rows]


def _revision_dto(row: LearningAssessmentRevision) -> AssessmentRevisionDTO:
    if row.origin not in {
        "single_agent",
        "custom_team",
        "published_course_team",
    } or row.chat_visibility not in {"private", "public"}:
        raise conflict("assessment_state_invalid", "The saved Assessment revision is invalid.")
    return AssessmentRevisionDTO(
        id=UUID(row.id),
        revision_seq=row.revision_seq,
        previous_revision_id=UUID(row.previous_revision_id) if row.previous_revision_id else None,
        content=json.loads(row.content_json),
        content_hash=row.content_hash,
        revision_source=cast(
            Literal["user_authored", "model_evaluation", "practice_agent_edit"],
            row.revision_source,
        ),
        provenance=LearningProvenance(
            actor_user_id=UUID(row.actor_user_id),
            course_id=UUID(row.course_id),
            conversation_id=UUID(row.conversation_id),
            team_id=UUID(row.team_id) if row.team_id else None,
            team_version_id=UUID(row.team_version_id) if row.team_version_id else None,
            origin=cast(
                Literal["single_agent", "custom_team", "published_course_team"],
                row.origin,
            ),
            chat_visibility=cast(Literal["private", "public"], row.chat_visibility),
            activity_id=UUID(row.activity_id) if row.activity_id else None,
            attempt_id=None,
        ),
        created_at=row.created_at,
    )


def _assessment_dto(db: Session, head: LearningAssessment) -> AssessmentDTO:
    revisions = db.scalars(
        select(LearningAssessmentRevision)
        .where(LearningAssessmentRevision.assessment_id == head.id)
        .order_by(LearningAssessmentRevision.revision_seq)
    ).all()
    current = next(
        (row for row in revisions if row.revision_seq == head.current_revision_seq),
        None,
    )
    if current is None:
        raise conflict(
            "assessment_state_invalid", "The current Assessment revision is unavailable."
        )
    return AssessmentDTO(
        id=UUID(head.id),
        owner_user_id=UUID(head.owner_user_id),
        course_id=UUID(head.course_id),
        current_revision_seq=head.current_revision_seq,
        current=_revision_dto(current),
        revisions=[_revision_dto(row) for row in revisions],
        created_at=head.created_at,
        updated_at=head.updated_at,
    )


def _write_receipt(
    assessment_id: str, revision: LearningAssessmentRevision
) -> AssessmentWriteReceipt:
    return AssessmentWriteReceipt(
        assessment_id=UUID(assessment_id), revision=_revision_dto(revision)
    )


def _find_mutation(
    db: Session,
    actor_user_id: str,
    conversation_id: str,
    client_event_id: str,
) -> LearningAssessmentMutation | None:
    return db.scalar(
        select(LearningAssessmentMutation).where(
            LearningAssessmentMutation.actor_user_id == actor_user_id,
            LearningAssessmentMutation.conversation_id == conversation_id,
            LearningAssessmentMutation.client_event_id == client_event_id,
        )
    )


def _replay_assessment_mutation(
    db: Session,
    mutation: LearningAssessmentMutation,
    request_hash: str,
) -> AssessmentWriteReceipt:
    if mutation.request_hash != request_hash:
        raise idempotency_conflict()
    revision = db.get(LearningAssessmentRevision, mutation.revision_id)
    if revision is None:
        raise conflict("assessment_state_invalid", "The saved Assessment revision is unavailable.")
    return _write_receipt(mutation.assessment_id, revision)


def _revision_row(
    *,
    assessment_id: str,
    revision_seq: int,
    previous_revision_id: str | None,
    actor_user_id: str,
    provenance: LearningProvenance,
    content_json: str,
    content_hash: str,
    timestamp: datetime,
) -> LearningAssessmentRevision:
    return LearningAssessmentRevision(
        id=str(uuid4()),
        assessment_id=assessment_id,
        revision_seq=revision_seq,
        previous_revision_id=previous_revision_id,
        actor_user_id=actor_user_id,
        course_id=str(provenance.course_id),
        conversation_id=str(provenance.conversation_id),
        team_id=str(provenance.team_id) if provenance.team_id else None,
        team_version_id=str(provenance.team_version_id) if provenance.team_version_id else None,
        origin=provenance.origin,
        chat_visibility=provenance.chat_visibility,
        activity_id=None,
        revision_source="user_authored",
        content_json=content_json,
        content_hash=content_hash,
        created_at=timestamp,
    )


def create_assessment(
    db: Session,
    actor: AuthContext,
    conversation_id: str | UUID,
    request: CreateAssessmentRequest,
) -> AssessmentWriteReceipt:
    """Create an owner-only Assessment with immutable revision 1."""

    _conversation, provenance = _authorized_provenance(db, actor, conversation_id)
    content_json = _canonical(request.content)
    request_hash = _hash(
        {
            "operation": "create",
            "conversation_id": str(conversation_id),
            "content": request.content,
        }
    )
    existing = _find_mutation(
        db,
        str(actor.user.id),
        str(conversation_id),
        str(request.client_event_id),
    )
    if existing is not None:
        return _replay_assessment_mutation(db, existing, request_hash)

    timestamp = _now()
    assessment_id = str(uuid4())
    head = LearningAssessment(
        id=assessment_id,
        owner_user_id=str(actor.user.id),
        course_id=str(provenance.course_id),
        created_conversation_id=str(provenance.conversation_id),
        current_revision_seq=1,
        created_at=timestamp,
        updated_at=timestamp,
    )
    revision = _revision_row(
        assessment_id=assessment_id,
        revision_seq=1,
        previous_revision_id=None,
        actor_user_id=str(actor.user.id),
        provenance=provenance,
        content_json=content_json,
        content_hash=_hash(request.content),
        timestamp=timestamp,
    )
    mutation = LearningAssessmentMutation(
        id=str(uuid4()),
        actor_user_id=str(actor.user.id),
        conversation_id=str(conversation_id),
        client_event_id=str(request.client_event_id),
        operation="create",
        request_hash=request_hash,
        assessment_id=assessment_id,
        revision_id=revision.id,
        created_at=timestamp,
    )
    try:
        with db.begin_nested():
            db.add(head)
            db.flush()
            db.add(revision)
            db.flush()
            db.add(mutation)
            db.flush()
    except IntegrityError:
        replay = _find_mutation(
            db,
            str(actor.user.id),
            str(conversation_id),
            str(request.client_event_id),
        )
        if replay is None:
            raise
        return _replay_assessment_mutation(db, replay, request_hash)
    db.refresh(revision)
    return _write_receipt(assessment_id, revision)


def read_assessment(
    db: Session,
    actor: AuthContext,
    conversation_id: str | UUID,
    assessment_id: str | UUID,
) -> AssessmentDTO:
    _conversation, provenance = _authorized_provenance(db, actor, conversation_id)
    head = db.get(LearningAssessment, str(assessment_id))
    if (
        head is None
        or head.owner_user_id != str(actor.user.id)
        or head.course_id != str(provenance.course_id)
        or head.attempt_id is not None
    ):
        raise not_found()
    return _assessment_dto(db, head)


def edit_assessment(
    db: Session,
    actor: AuthContext,
    conversation_id: str | UUID,
    assessment_id: str | UUID,
    request: EditAssessmentRequest,
) -> AssessmentWriteReceipt:
    """Append one immutable Assessment revision with head CAS and request replay."""

    _conversation, provenance = _authorized_provenance(db, actor, conversation_id)
    assessment = db.get(LearningAssessment, str(assessment_id))
    if (
        assessment is None
        or assessment.owner_user_id != str(actor.user.id)
        or assessment.course_id != str(provenance.course_id)
        or assessment.attempt_id is not None
        or assessment.created_conversation_id != str(conversation_id)
    ):
        raise not_found()

    content_json = _canonical(request.content)
    request_hash = _hash(
        {
            "operation": "edit",
            "assessment_id": str(assessment_id),
            "conversation_id": str(conversation_id),
            "expected_revision": request.expected_revision,
            "content": request.content,
        }
    )
    existing = _find_mutation(
        db,
        str(actor.user.id),
        str(conversation_id),
        str(request.client_event_id),
    )
    if existing is not None:
        return _replay_assessment_mutation(db, existing, request_hash)

    timestamp = _now()
    try:
        with db.begin_nested():
            cas = db.execute(
                update(LearningAssessment)
                .where(
                    LearningAssessment.id == str(assessment_id),
                    LearningAssessment.owner_user_id == str(actor.user.id),
                    LearningAssessment.course_id == str(provenance.course_id),
                    LearningAssessment.current_revision_seq == request.expected_revision,
                )
                .values(
                    current_revision_seq=request.expected_revision + 1,
                    updated_at=timestamp,
                )
                .execution_options(synchronize_session=False)
            )
            if getattr(cas, "rowcount", 0) != 1:
                current = db.scalar(
                    select(LearningAssessment.current_revision_seq).where(
                        LearningAssessment.id == str(assessment_id)
                    )
                )
                raise stale_revision(current)

            previous = db.scalar(
                select(LearningAssessmentRevision).where(
                    LearningAssessmentRevision.assessment_id == str(assessment_id),
                    LearningAssessmentRevision.revision_seq == request.expected_revision,
                )
            )
            if previous is None:
                raise conflict(
                    "assessment_state_invalid",
                    "The previous Assessment revision is unavailable.",
                )
            revision = _revision_row(
                assessment_id=str(assessment_id),
                revision_seq=request.expected_revision + 1,
                previous_revision_id=previous.id,
                actor_user_id=str(actor.user.id),
                provenance=provenance,
                content_json=content_json,
                content_hash=_hash(request.content),
                timestamp=timestamp,
            )
            mutation = LearningAssessmentMutation(
                id=str(uuid4()),
                actor_user_id=str(actor.user.id),
                conversation_id=str(conversation_id),
                client_event_id=str(request.client_event_id),
                operation="edit",
                request_hash=request_hash,
                assessment_id=str(assessment_id),
                revision_id=revision.id,
                created_at=timestamp,
            )
            db.add(revision)
            db.flush()
            db.add(mutation)
            db.flush()
    except IntegrityError:
        replay = _find_mutation(
            db,
            str(actor.user.id),
            str(conversation_id),
            str(request.client_event_id),
        )
        if replay is None:
            raise
        return _replay_assessment_mutation(db, replay, request_hash)
    db.expire(assessment)
    db.refresh(revision)
    return _write_receipt(str(assessment_id), revision)


__all__ = [
    "create_assessment",
    "edit_assessment",
    "read_assessment",
    "read_learning_records",
    "record_learning_event",
]
