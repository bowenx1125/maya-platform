"""Server-minted least-privilege scopes for formal Assessment and Boundary Tools."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Literal
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import conflict, idempotency_conflict, not_found, stale_revision
from app.core.models import (
    Agent,
    AgentVersion,
    CourseMember,
    ProviderOperation,
    User,
)
from app.modules.auth.service import AuthContext
from app.modules.knowledge.services import course_member_role
from app.modules.knowledge_sets.models import (
    KnowledgeAsset,
    KnowledgeAssetVersion,
    KnowledgeSet,
)
from app.modules.knowledge_sets.schemas import QuestionContent
from app.modules.runtime_tools.models import RuntimeModelCallStage
from app.modules.runtime_tools.registry import ToolCallIdentity
from app.modules.teams.models import (
    CourseTeamPublication,
    Team,
    TeamMemberInvokeGrant,
    TeamVersion,
    TeamVersionMember,
)
from app.modules.workspace.models import (
    Conversation,
    ConversationParticipant,
    ConversationTurn,
    TeamProviderCall,
    TeamTurnResult,
)

from .models import (
    AssessmentActivity,
    AssessmentActivityQuestion,
    AssessmentAttempt,
    AssessmentAttemptEvent,
    AssessmentAttemptQuestion,
    LearningAssessment,
    LearningAssessmentMutation,
    LearningAssessmentResourceGrant,
    LearningAssessmentRevision,
    LearningBoundary,
    LearningBoundaryEvidence,
    LearningBoundaryRevision,
    LearningRecord,
)
from .recipes import (
    declared_assessment_role,
    declared_recipe,
    ensure_assessment_activity,
    question_sources_readable,
)
from .schemas import AssessmentEvaluationContent, BoundarySummaryContent, LearningProvenance
from .service import _authorized_provenance, _canonical, _hash, _now

ExecutionPurpose = Literal["assessment_evaluate", "boundary_summarize"]


@dataclass(frozen=True)
class RuntimeExecutionScope:
    """Internal payload limited to one authenticated participant and attempt."""

    purpose: ExecutionPurpose
    actor_user_id: str
    course_id: str
    conversation_id: str
    activity_id: str
    attempt_id: str
    executor_participant_id: str
    executor_team_member_id: str
    executor_agent_version_id: str
    model_call_id: str
    tool_call_id: str
    question_payloads: tuple[tuple[str, str], ...]
    effective_answer_payloads: tuple[tuple[str, str], ...]
    evidence_learning_record_ids: tuple[str, ...]
    assessment_revision_id: str | None
    assessment_revision_json: str | None


@dataclass(frozen=True)
class AssessmentExecutorContext:
    """Internal pre-dispatch data; it conveys no Tool write authority."""

    purpose: ExecutionPurpose
    turn_id: str
    result_id: str
    participant_id: str
    team_member_id: str
    agent_version_id: str
    activity_id: str
    attempt_id: str
    task_payload_json: str


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _current_attempt_question_rows(
    db: Session, attempt: AssessmentAttempt
) -> list[AssessmentAttemptQuestion]:
    from .attempts import _attempt_question_rows

    return _attempt_question_rows(db, attempt.id)


def _accepted_tool_call_name(
    db: Session,
    identity: ToolCallIdentity,
    *,
    expected_tool_name: str,
) -> None:
    team_stage = db.get(TeamProviderCall, identity.model_call_id)
    single_stage = (
        db.get(RuntimeModelCallStage, identity.model_call_id) if team_stage is None else None
    )
    stage = team_stage or single_stage
    result = db.get(TeamTurnResult, team_stage.result_id) if team_stage is not None else None
    turn = db.get(ConversationTurn, identity.turn_id)
    conversation = db.get(Conversation, identity.conversation_id)
    operation = db.get(ProviderOperation, stage.operation_id) if stage is not None else None
    if (
        stage is None
        or turn is None
        or conversation is None
        or operation is None
        or operation.state not in {"accepted", "succeeded"}
        or operation.request_hash != stage.request_hash
        or operation.staged_response_hash != stage.accepted_response_hash
        or _digest(stage.request_json) != stage.request_hash
        or stage.accepted_response_json is None
        or stage.accepted_response_hash is None
        or _digest(stage.accepted_response_json) != stage.accepted_response_hash
        or turn.conversation_id != conversation.id
        or turn.state != "pending"
        or conversation.active_request_id != turn.id
        or (
            team_stage is not None
            and (
                result is None
                or result.conversation_id != conversation.id
                or result.turn_id != turn.id
                or result.participant_id != identity.participant_id
                or result.state not in {"running", "ready"}
            )
        )
        or (
            single_stage is not None
            and (
                single_stage.conversation_id != conversation.id
                or single_stage.turn_id != turn.id
                or single_stage.executor_agent_version_id != identity.participant_id
            )
        )
    ):
        raise conflict("assessment_execution_unverified", "The current Tool call is unavailable.")
    try:
        response = json.loads(stage.accepted_response_json)
    except ValueError:
        raise conflict(
            "assessment_execution_unverified", "The current Tool call is unavailable."
        ) from None
    message = response
    choices = response.get("choices") if isinstance(response, dict) else None
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        candidate = choices[0].get("message")
        if isinstance(candidate, dict):
            message = candidate
    calls = message.get("tool_calls", []) if isinstance(message, dict) else []
    for call in calls if isinstance(calls, list) else []:
        if not isinstance(call, dict) or call.get("id") != identity.tool_call_id:
            continue
        function = call.get("function")
        if isinstance(function, dict) and function.get("name") == expected_tool_name:
            return
        break
    raise conflict("assessment_execution_unverified", "The current Tool call is unavailable.")


def _activity_executor(
    db: Session,
    activity: AssessmentActivity,
    purpose: ExecutionPurpose,
) -> tuple[str, str]:
    if purpose == "assessment_evaluate":
        member_id = activity.evaluator_team_member_id
        agent_version_id = activity.evaluator_agent_version_id
        expected_role = "evaluator"
    else:
        member_id = activity.boundary_team_member_id
        agent_version_id = activity.boundary_agent_version_id
        expected_role = "boundary_summarizer"
    member = db.get(TeamVersionMember, member_id)
    version = db.get(AgentVersion, agent_version_id)
    if (
        member is None
        or member.team_version_id != activity.team_version_id
        or member.agent_version_id != agent_version_id
        or version is None
        or version.agent_id != member.agent_id
        or version.state != "published"
        or declared_assessment_role(version.agent_md) != expected_role
    ):
        raise conflict("assessment_executor_revoked", "This assessment executor is unavailable.")
    return member_id, agent_version_id


def _assert_live_activity(
    db: Session,
    actor: AuthContext,
    conversation: Conversation,
    activity: AssessmentActivity,
) -> None:
    if (
        actor.user.status != "active"
        or conversation.withdrawn_at is not None
        or conversation.user_id != str(actor.user.id)
        or conversation.entry_kind != "maya_team"
        or conversation.origin != "published_course_team"
        or conversation.team_id != activity.team_id
        or conversation.team_version_id != activity.team_version_id
        or conversation.publication_id != activity.publication_id
        or conversation.course_id != activity.course_id
    ):
        raise not_found()
    member = db.get(CourseMember, (activity.course_id, str(actor.user.id)))
    team = db.get(Team, activity.team_id)
    version = db.get(TeamVersion, activity.team_version_id)
    publication = db.get(CourseTeamPublication, activity.publication_id)
    if (
        member is None
        or member.role != "student"
        or team is None
        or team.deleted_at is not None
        or team.course_id != activity.course_id
        or team.owner_user_id != activity.publisher_user_id
        or team.ownership_scope != "personal"
        or team.visibility != "public"
        or version is None
        or version.team_id != activity.team_id
        or version.authorization_epoch != team.authorization_epoch
        or version.version_seq != team.current_version_seq
        or conversation.team_authorization_epoch != team.authorization_epoch
        or publication is None
        or publication.course_id != activity.course_id
        or publication.team_id != activity.team_id
        or publication.team_version_id != activity.team_version_id
        or publication.publisher_user_id != activity.publisher_user_id
        or publication.authorization_epoch != team.authorization_epoch
        or publication.state != "published"
        or conversation.publication_epoch != publication.authorization_epoch
    ):
        raise conflict(
            "assessment_activity_unavailable", "This published assessment is unavailable."
        )
    leader = db.scalar(
        select(TeamVersionMember).where(
            TeamVersionMember.team_version_id == activity.team_version_id,
            TeamVersionMember.is_leader.is_(True),
        )
    )
    recipe_version = db.get(AgentVersion, activity.recipe_version_id)
    if (
        leader is None
        or leader.agent_version_id != activity.recipe_version_id
        or recipe_version is None
        or recipe_version.state != "published"
        or declared_recipe(recipe_version.agent_md) != activity.recipe_id
    ):
        raise conflict(
            "assessment_activity_unavailable", "This published assessment is unavailable."
        )
    _activity_executor(db, activity, "assessment_evaluate")
    _activity_executor(db, activity, "boundary_summarize")


def _authorize_executor_participant(
    db: Session,
    conversation: Conversation,
    activity: AssessmentActivity,
    purpose: ExecutionPurpose,
    participant_id: str,
) -> ConversationParticipant:
    participant = db.get(ConversationParticipant, participant_id)
    if participant is None or participant.conversation_id != conversation.id:
        raise not_found()
    expected_member_id, expected_agent_version_id = _activity_executor(db, activity, purpose)
    agent = db.get(Agent, participant.agent_id)
    if (
        participant.team_version_id != activity.team_version_id
        or participant.team_member_id != expected_member_id
        or participant.agent_version_id != expected_agent_version_id
        or agent is None
        or agent.authorization_epoch != participant.agent_authorization_epoch
    ):
        raise conflict(
            "assessment_executor_not_authorized", "This participant cannot edit this result."
        )
    member = db.get(TeamVersionMember, expected_member_id)
    grant = (
        db.get(TeamMemberInvokeGrant, participant.invoke_grant_id)
        if participant.invoke_grant_id
        else None
    )
    if (
        member is None
        or member.team_version_id != activity.team_version_id
        or member.agent_id != participant.agent_id
        or member.agent_version_id != expected_agent_version_id
        or grant is None
        or grant.publication_id != activity.publication_id
        or grant.team_version_id != activity.team_version_id
        or grant.team_member_id != member.id
        or grant.agent_id != member.agent_id
        or grant.agent_version_id != expected_agent_version_id
        or grant.authorization_epoch != conversation.publication_epoch
    ):
        raise conflict(
            "assessment_executor_not_authorized", "This participant cannot edit this result."
        )
    return participant


def _authorize_practice_assessment_edit(
    db: Session,
    actor: AuthContext,
    identity: ToolCallIdentity,
    assessment: LearningAssessment,
) -> tuple[LearningProvenance, str | None, str]:
    _accepted_tool_call_name(db, identity, expected_tool_name="edit_assessment")
    conversation, provenance = _authorized_provenance(db, actor, identity.conversation_id)
    if (
        assessment.attempt_id is not None
        or assessment.owner_user_id != str(actor.user.id)
        or assessment.course_id != conversation.course_id
        or assessment.created_conversation_id != conversation.id
    ):
        raise not_found()

    participant_id: str | None = None
    team_member_id: str | None = None
    if conversation.entry_kind in {"team", "maya_team"}:
        participant = db.get(ConversationParticipant, identity.participant_id)
        if (
            participant is None
            or participant.conversation_id != conversation.id
            or participant.team_version_id != conversation.team_version_id
        ):
            raise not_found()
        member = db.get(TeamVersionMember, participant.team_member_id)
        agent = db.get(Agent, participant.agent_id)
        version = db.get(AgentVersion, participant.agent_version_id)
        if (
            member is None
            or member.team_version_id != conversation.team_version_id
            or member.agent_id != participant.agent_id
            or member.agent_version_id != participant.agent_version_id
            or version is None
            or version.agent_id != participant.agent_id
            or version.state != "published"
            or agent is None
            or agent.authorization_epoch != participant.agent_authorization_epoch
        ):
            raise conflict(
                "assessment_executor_not_authorized", "This participant cannot edit this result."
            )
        participant_id = participant.id
        team_member_id = member.id
        agent_version_id = version.id
        agent_epoch = participant.agent_authorization_epoch
    elif conversation.entry_kind == "agent":
        version = db.get(AgentVersion, identity.participant_id)
        agent = db.get(Agent, version.agent_id) if version is not None else None
        if (
            version is None
            or version.id != conversation.agent_version_id
            or version.state != "published"
            or agent is None
            or agent.authorization_epoch != conversation.agent_authorization_epoch
        ):
            raise conflict(
                "assessment_executor_not_authorized", "This participant cannot edit this result."
            )
        agent_version_id = version.id
        agent_epoch = agent.authorization_epoch
    else:
        raise not_found()

    grant = db.scalar(
        select(LearningAssessmentResourceGrant).where(
            LearningAssessmentResourceGrant.assessment_id == assessment.id,
            LearningAssessmentResourceGrant.owner_user_id == assessment.owner_user_id,
            LearningAssessmentResourceGrant.course_id == assessment.course_id,
            LearningAssessmentResourceGrant.conversation_id == conversation.id,
            LearningAssessmentResourceGrant.participant_id == participant_id,
            LearningAssessmentResourceGrant.team_member_id == team_member_id,
            LearningAssessmentResourceGrant.agent_version_id == agent_version_id,
            LearningAssessmentResourceGrant.agent_authorization_epoch == agent_epoch,
            LearningAssessmentResourceGrant.operation == "edit",
            LearningAssessmentResourceGrant.revoked_at.is_(None),
        )
    )
    if grant is None:
        raise conflict("assessment_edit_not_authorized", "This Assessment is not editable here.")
    return provenance, team_member_id, agent_version_id


def _pinned_question_currently_readable(
    db: Session,
    attempt_question: AssessmentAttemptQuestion,
) -> tuple[str, str]:
    source = db.get(AssessmentActivityQuestion, attempt_question.activity_question_id)
    if source is None or source.activity_id != attempt_question.activity_id:
        raise conflict("assessment_resource_revoked", "A pinned Question is no longer available.")
    set_row = db.get(KnowledgeSet, source.knowledge_set_id)
    asset = db.get(KnowledgeAsset, source.asset_id)
    version = db.get(KnowledgeAssetVersion, attempt_question.question_version_id)
    if version is None:
        raise conflict("assessment_resource_revoked", "A pinned Question is no longer available.")
    try:
        version_content = QuestionContent.model_validate_json(version.content_json)
    except ValueError:
        raise conflict("assessment_resource_invalid", "A pinned Question is unavailable.") from None
    normalized_content = _canonical(version_content.model_dump(mode="json"))
    if (
        set_row is None
        or set_row.deleted_at is not None
        or set_row.authorization_epoch != source.authorization_epoch
        or asset is None
        or asset.knowledge_set_id != source.knowledge_set_id
        or asset.kind != "question"
        or version is None
        or version.asset_id != asset.id
        or version.set_authorization_epoch != source.authorization_epoch
        or _digest(version.content_json) != version.content_hash
        or attempt_question.content_json is None
        or _digest(attempt_question.content_json) != attempt_question.content_hash
        or attempt_question.content_json != normalized_content
    ):
        raise conflict("assessment_resource_revoked", "A pinned Question is no longer available.")
    if not question_sources_readable(db, set_row, version):
        raise conflict("assessment_resource_revoked", "A pinned Question is no longer available.")
    try:
        QuestionContent.model_validate_json(attempt_question.content_json)
    except ValueError:
        raise conflict("assessment_resource_invalid", "A pinned Question is unavailable.") from None
    return version.id, attempt_question.content_json


def _scope_answers(
    db: Session,
    attempt: AssessmentAttempt,
    question_rows: list[AssessmentAttemptQuestion],
) -> tuple[tuple[tuple[str, str], ...], tuple[str, ...]]:
    effective: list[tuple[str, str]] = []
    evidence_ids: list[str] = []
    current_question_ids = {question.id for question in question_rows}
    events = db.execute(
        select(AssessmentAttemptEvent, LearningRecord)
        .join(LearningRecord, LearningRecord.id == AssessmentAttemptEvent.learning_record_id)
        .where(
            AssessmentAttemptEvent.attempt_id == attempt.id,
            AssessmentAttemptEvent.activity_id == attempt.activity_id,
            AssessmentAttemptEvent.actor_user_id == attempt.actor_user_id,
            AssessmentAttemptEvent.event_kind.in_(("answer", "skip")),
            LearningRecord.attempt_id == attempt.id,
            LearningRecord.activity_id == attempt.activity_id,
            LearningRecord.actor_user_id == attempt.actor_user_id,
            LearningRecord.conversation_id == attempt.source_conversation_id,
            LearningRecord.record_kind.in_(("answer", "skip")),
        )
        .order_by(LearningRecord.created_at, LearningRecord.id)
    ).all()
    events_by_question: dict[str, list[tuple[AssessmentAttemptEvent, LearningRecord]]] = {}
    for event, record in events:
        if event.question_id not in current_question_ids:
            continue
        try:
            payload = json.loads(record.payload_json)
        except (TypeError, ValueError):
            raise conflict(
                "assessment_answer_unavailable", "A saved response is unavailable."
            ) from None
        if not isinstance(payload, dict):
            raise conflict("assessment_answer_unavailable", "A saved response is unavailable.")
        question = db.get(AssessmentAttemptQuestion, event.question_id)
        conversation = db.get(Conversation, record.conversation_id)
        if (
            question is None
            or question.attempt_id != attempt.id
            or event.question_id != question.id
            or event.event_kind != record.record_kind
            or conversation is None
            or conversation.withdrawn_at is not None
            or conversation.course_id != record.course_id
            or conversation.team_id != record.team_id
            or conversation.team_version_id != record.team_version_id
            or conversation.chat_visibility != record.chat_visibility
            or record.origin != "published_course_team"
            or record.payload_hash != _hash(_canonical({"attempt_id": attempt.id, **payload}))
            or payload.get("kind") != record.record_kind
        ):
            continue
        events_by_question.setdefault(question.id, []).append((event, record))
    for question in question_rows:
        if question.status != "resolved" or question.resolution not in {"answered", "skipped"}:
            raise conflict(
                "assessment_answers_incomplete", "The assessment still has unresolved Questions."
            )
        question_events = events_by_question.get(question.id, [])
        evidence_ids.extend(record.id for _event, record in question_events)
        has_answer = any(record.record_kind == "answer" for _event, record in question_events)
        has_skip = any(record.record_kind == "skip" for _event, record in question_events)
        if (question.resolution == "answered" and not has_answer) or (
            question.resolution == "skipped" and not has_skip
        ):
            raise conflict("assessment_answer_unavailable", "A saved response is unavailable.")
        if question.resolution == "answered":
            record_id = question.effective_answer_record_id
            record = db.get(LearningRecord, record_id) if record_id else None
            if (
                record is None
                or record.id not in {row.id for _event, row in question_events}
                or record.attempt_id != attempt.id
                or record.activity_id != attempt.activity_id
                or record.actor_user_id != attempt.actor_user_id
                or record.conversation_id != attempt.source_conversation_id
                or record.record_kind != "answer"
            ):
                raise conflict("assessment_answer_unavailable", "A saved answer is unavailable.")
            try:
                payload = json.loads(record.payload_json)
            except (TypeError, ValueError):
                raise conflict(
                    "assessment_answer_unavailable", "A saved answer is unavailable."
                ) from None
            if payload.get("kind") != "answer" or record.payload_hash != _hash(
                _canonical({"attempt_id": attempt.id, **payload})
            ):
                raise conflict("assessment_answer_unavailable", "A saved answer is unavailable.")
            effective.append((record.id, record.payload_json))
    return tuple(effective), tuple(sorted(set(evidence_ids)))


def _evaluation_covers_questions(
    revision: LearningAssessmentRevision, question_rows: list[AssessmentAttemptQuestion]
) -> bool:
    """A follow-up round makes the previous evaluation incomplete until it is redone."""

    try:
        content = AssessmentEvaluationContent.model_validate_json(revision.content_json)
    except ValueError:
        return False
    offset = question_rows[0].ordinal if question_rows else 0
    return {item.question_ordinal for item in content.questions} == {
        row.ordinal - offset for row in question_rows
    }


def _assessment_for_attempt(
    db: Session, attempt: AssessmentAttempt
) -> tuple[LearningAssessment, LearningAssessmentRevision] | None:
    activity = db.get(AssessmentActivity, attempt.activity_id)
    if activity is None:
        return None
    assessment = db.scalar(
        select(LearningAssessment).where(
            LearningAssessment.attempt_id == attempt.id,
            LearningAssessment.owner_user_id == attempt.actor_user_id,
            LearningAssessment.course_id == activity.course_id,
        )
    )
    if assessment is None:
        return None
    revision = db.scalar(
        select(LearningAssessmentRevision).where(
            LearningAssessmentRevision.assessment_id == assessment.id,
            LearningAssessmentRevision.revision_seq == assessment.current_revision_seq,
            LearningAssessmentRevision.revision_source == "model_evaluation",
            LearningAssessmentRevision.attempt_id == attempt.id,
        )
    )
    return (assessment, revision) if revision is not None else None


def _boundary_for_attempt(
    db: Session, attempt: AssessmentAttempt
) -> tuple[LearningBoundary, LearningBoundaryRevision] | None:
    boundary = db.scalar(
        select(LearningBoundary).where(
            LearningBoundary.attempt_id == attempt.id,
            LearningBoundary.owner_user_id == attempt.actor_user_id,
        )
    )
    if boundary is None or boundary.current_revision_seq < 1:
        return None
    revision = db.scalar(
        select(LearningBoundaryRevision).where(
            LearningBoundaryRevision.boundary_id == boundary.id,
            LearningBoundaryRevision.revision_seq == boundary.current_revision_seq,
        )
    )
    return (boundary, revision) if revision is not None else None


def attempt_has_final_evidence(db: Session, attempt: AssessmentAttempt) -> bool:
    """Only a saved evaluator revision and an evidence-linked Boundary can close an attempt."""

    activity = db.get(AssessmentActivity, attempt.activity_id)
    assessment = _assessment_for_attempt(db, attempt)
    boundary = _boundary_for_attempt(db, attempt)
    if not (
        activity is not None
        and assessment is not None
        and assessment[1].evaluator_team_member_id == activity.evaluator_team_member_id
        and assessment[1].evaluator_agent_version_id == activity.evaluator_agent_version_id
        and boundary is not None
        and boundary[1].summarizer_team_member_id == activity.boundary_team_member_id
        and boundary[1].summarizer_agent_version_id == activity.boundary_agent_version_id
        and _digest(assessment[1].content_json) == assessment[1].content_hash
        and _digest(boundary[1].content_json) == boundary[1].content_hash
    ):
        return False
    question_rows = _current_attempt_question_rows(db, attempt)
    if (
        not question_rows
        or any(
            question.presented_at is None or question.content_json is None
            for question in question_rows
        )
        or not _evaluation_covers_questions(assessment[1], question_rows)
    ):
        return False
    for question in question_rows:
        _pinned_question_currently_readable(db, question)
    _effective_answers, answer_evidence_ids = _scope_answers(db, attempt, question_rows)
    saved_evidence = db.scalars(
        select(LearningBoundaryEvidence).where(
            LearningBoundaryEvidence.boundary_revision_id == boundary[1].id,
            LearningBoundaryEvidence.attempt_id == attempt.id,
        )
    ).all()
    saved_answer_ids = {
        row.learning_record_id for row in saved_evidence if row.learning_record_id is not None
    }
    saved_assessment_ids = {
        row.assessment_revision_id
        for row in saved_evidence
        if row.assessment_revision_id is not None
    }
    return (
        saved_answer_ids == set(answer_evidence_ids)
        and saved_assessment_ids == {assessment[1].id}
        and len(saved_evidence) == len(saved_answer_ids) + len(saved_assessment_ids)
    )


def get_assessment_executor_context(
    db: Session,
    actor: AuthContext,
    conversation_id: str,
    *,
    turn_id: str,
    participant_id: str,
    purpose: ExecutionPurpose,
    result_id: str | None = None,
) -> AssessmentExecutorContext | None:
    """Build private model input for the assigned executor before Tool dispatch.

    The pending run and exact running member result are checked here. This context
    carries no write capability; an accepted Tool call is still re-authorized by
    ``mint_runtime_execution_scope`` immediately before saving a result.
    """

    conversation, _ = _authorized_provenance(db, actor, conversation_id)
    activity = ensure_assessment_activity(db, actor, conversation.id)
    if activity is None:
        return None
    attempt = db.scalar(
        select(AssessmentAttempt).where(
            AssessmentAttempt.source_conversation_id == conversation.id,
            AssessmentAttempt.actor_user_id == str(actor.user.id),
            AssessmentAttempt.activity_id == activity.id,
            AssessmentAttempt.status.in_(("in_progress", "paused")),
        )
    )
    if attempt is None:
        return None
    if attempt.status != "in_progress":
        raise conflict("assessment_attempt_paused", "Resume the assessment before evaluating it.")
    turn = db.get(ConversationTurn, turn_id)
    if (
        turn is None
        or turn.conversation_id != conversation.id
        or turn.state != "pending"
        or conversation.active_request_id != turn.id
    ):
        raise conflict("tool_run_inactive", "This assessment task is no longer active.")
    running_results = list(
        db.scalars(
            select(TeamTurnResult).where(
                TeamTurnResult.turn_id == turn.id,
                TeamTurnResult.conversation_id == conversation.id,
                TeamTurnResult.participant_id == participant_id,
                TeamTurnResult.state == "running",
            )
        ).all()
    )
    if len(running_results) != 1 or (result_id is not None and running_results[0].id != result_id):
        raise conflict("assessment_execution_unverified", "This assessment task is unavailable.")
    participant = _authorize_executor_participant(
        db, conversation, activity, purpose, participant_id
    )
    _assert_live_activity(db, actor, conversation, activity)
    question_rows = _current_attempt_question_rows(db, attempt)
    if not question_rows or any(not question.required for question in question_rows):
        raise conflict("assessment_recipe_invalid", "The assessment Question set is unavailable.")
    selection_ordinal_offset = question_rows[0].ordinal
    if any(
        question.presented_at is None or question.status != "resolved" for question in question_rows
    ):
        raise conflict(
            "assessment_answers_incomplete", "The assessment still has unresolved Questions."
        )
    pinned = [
        (question, _pinned_question_currently_readable(db, question)) for question in question_rows
    ]
    effective_answers, _evidence_ids = _scope_answers(db, attempt, question_rows)
    answers_by_record_id = {
        record_id: json.loads(payload_json) for record_id, payload_json in effective_answers
    }
    material: list[dict[str, Any]] = []
    for attempt_question, (_version_id, question_json) in pinned:
        question = QuestionContent.model_validate_json(question_json)
        answer_record_id = attempt_question.effective_answer_record_id
        answer_payload = answers_by_record_id.get(answer_record_id) if answer_record_id else None
        answer_text = answer_payload.get("answer_text") if answer_payload else None
        entry: dict[str, Any] = {
            "question_ordinal": attempt_question.ordinal - selection_ordinal_offset,
            "prompt": question.prompt,
            "answer_text": answer_text,
            "skipped": attempt_question.resolution == "skipped",
        }
        if purpose == "assessment_evaluate":
            entry["reference_answer"] = question.reference_answer
            entry["rubric"] = question.rubric.model_dump(mode="json")
        material.append(entry)

    from .attempts import follow_up_candidates, unasked_questions

    if purpose == "assessment_evaluate":
        task_payload: dict[str, Any] = {
            "questions": material,
            "follow_up_candidates": [
                {"ref": row.id, "prompt": content.prompt}
                for row, content in follow_up_candidates(db, attempt)
            ],
        }
    else:
        evaluation = _assessment_for_attempt(db, attempt)
        if evaluation is None or not _evaluation_covers_questions(evaluation[1], question_rows):
            raise conflict(
                "assessment_evaluation_missing", "Save the Assessment before updating the Boundary."
            )
        task_payload = {
            "responses": material,
            "assessment": json.loads(evaluation[1].content_json),
            "not_asked": [content.prompt for _row, content in unasked_questions(db, attempt)],
        }
    return AssessmentExecutorContext(
        purpose=purpose,
        turn_id=turn.id,
        result_id=running_results[0].id,
        participant_id=participant.id,
        team_member_id=participant.team_member_id,
        agent_version_id=participant.agent_version_id,
        activity_id=activity.id,
        attempt_id=attempt.id,
        task_payload_json=_canonical(task_payload),
    )


def mint_runtime_execution_scope(
    db: Session,
    actor: AuthContext,
    identity: ToolCallIdentity,
    *,
    purpose: ExecutionPurpose,
    tool_name: Literal["edit_assessment", "update_learning_boundary"],
) -> RuntimeExecutionScope:
    """Validate actual SDK identity and return only its assigned attempt evidence."""

    expected_tool = {
        "assessment_evaluate": "edit_assessment",
        "boundary_summarize": "update_learning_boundary",
    }[purpose]
    if tool_name != expected_tool:
        raise not_found()
    _accepted_tool_call_name(db, identity, expected_tool_name=expected_tool)
    conversation, _provenance = _authorized_provenance(db, actor, identity.conversation_id)
    attempt = db.scalar(
        select(AssessmentAttempt).where(
            AssessmentAttempt.source_conversation_id == conversation.id,
            AssessmentAttempt.actor_user_id == str(actor.user.id),
            AssessmentAttempt.status == "in_progress",
        )
    )
    if attempt is None:
        raise conflict("assessment_attempt_not_active", "No active assessment can be edited.")
    activity = db.get(AssessmentActivity, attempt.activity_id)
    if activity is None:
        raise not_found()
    _assert_live_activity(db, actor, conversation, activity)
    participant = _authorize_executor_participant(
        db, conversation, activity, purpose, identity.participant_id
    )

    question_rows = _current_attempt_question_rows(db, attempt)
    if not question_rows or any(not row.required for row in question_rows):
        raise conflict("assessment_recipe_invalid", "The assessment Question set is unavailable.")
    question_payloads = tuple(
        _pinned_question_currently_readable(db, question) for question in question_rows
    )
    effective_answers, evidence_ids = _scope_answers(db, attempt, question_rows)
    evaluation = _assessment_for_attempt(db, attempt)
    if purpose == "boundary_summarize" and (
        evaluation is None or not _evaluation_covers_questions(evaluation[1], question_rows)
    ):
        raise conflict(
            "assessment_evaluation_missing", "Save the Assessment before updating the Boundary."
        )
    return RuntimeExecutionScope(
        purpose=purpose,
        actor_user_id=attempt.actor_user_id,
        course_id=activity.course_id,
        conversation_id=conversation.id,
        activity_id=activity.id,
        attempt_id=attempt.id,
        executor_participant_id=participant.id,
        executor_team_member_id=participant.team_member_id,
        executor_agent_version_id=participant.agent_version_id,
        model_call_id=identity.model_call_id,
        tool_call_id=identity.tool_call_id,
        question_payloads=question_payloads,
        effective_answer_payloads=effective_answers,
        evidence_learning_record_ids=evidence_ids,
        assessment_revision_id=evaluation[1].id if evaluation else None,
        assessment_revision_json=evaluation[1].content_json if evaluation else None,
    )


def authorize_assessment_edit(
    db: Session,
    actor: AuthContext,
    _conversation: Conversation,
    payload: Any,
    identity: ToolCallIdentity,
) -> None:
    assessment_id = getattr(payload, "assessment_id", None)
    if assessment_id is None:
        mint_runtime_execution_scope(
            db,
            actor,
            identity,
            purpose="assessment_evaluate",
            tool_name="edit_assessment",
        )
        return
    assessment = db.get(LearningAssessment, str(assessment_id))
    if assessment is None:
        raise not_found()
    if assessment.attempt_id is not None:
        scope = mint_runtime_execution_scope(
            db,
            actor,
            identity,
            purpose="assessment_evaluate",
            tool_name="edit_assessment",
        )
        if assessment.attempt_id != scope.attempt_id:
            raise not_found()
        return
    _authorize_practice_assessment_edit(db, actor, identity, assessment)


def authorize_assessment_edit_replay(
    db: Session,
    actor: AuthContext,
    conversation: Conversation,
    payload: Any,
    identity: ToolCallIdentity,
    saved_result: dict[str, Any],
) -> None:
    """Replay a saved formal evaluation read-only after it opened a follow-up round."""

    if saved_result != {"ok": True, "result": {"saved": True}}:
        raise conflict("tool_receipt_invalid", "The saved Assessment result is unavailable.")
    _accepted_tool_call_name(db, identity, expected_tool_name="edit_assessment")
    revision = db.scalar(
        select(LearningAssessmentRevision).where(
            LearningAssessmentRevision.source_model_call_id == identity.model_call_id,
            LearningAssessmentRevision.source_tool_call_id == identity.tool_call_id,
        )
    )
    if revision is None or revision.attempt_id is None:
        authorize_assessment_edit(db, actor, conversation, payload, identity)
        return
    attempt = db.get(AssessmentAttempt, revision.attempt_id)
    if (
        attempt is None
        or attempt.actor_user_id != actor.user.id
        or attempt.source_conversation_id != conversation.id
        or revision.conversation_id != conversation.id
        or attempt.status not in {"in_progress", "completed"}
    ):
        raise conflict("tool_run_inactive", "This Assessment result cannot be replayed now.")
    activity = db.get(AssessmentActivity, attempt.activity_id)
    if activity is None:
        raise not_found()
    _assert_live_activity(db, actor, conversation, activity)


def authorize_boundary_update(
    db: Session,
    actor: AuthContext,
    _conversation: Conversation,
    _payload: Any,
    identity: ToolCallIdentity,
) -> None:
    mint_runtime_execution_scope(
        db,
        actor,
        identity,
        purpose="boundary_summarize",
        tool_name="update_learning_boundary",
    )


def authorize_boundary_update_replay(
    db: Session,
    actor: AuthContext,
    conversation: Conversation,
    _payload: Any,
    identity: ToolCallIdentity,
    saved_result: dict[str, Any],
) -> None:
    """Allow a completed Boundary Tool's exact successful receipt to replay read-only."""

    from .attempts import project_completed_assessment_for_boundary_call

    if saved_result != {"ok": True, "result": {"saved": True}}:
        raise conflict("tool_receipt_invalid", "The saved Boundary result is unavailable.")
    _accepted_tool_call_name(db, identity, expected_tool_name="update_learning_boundary")
    projection = project_completed_assessment_for_boundary_call(
        db,
        str(actor.user.id),
        conversation.id,
        model_call_id=identity.model_call_id,
        tool_call_id=identity.tool_call_id,
    )
    if projection is None or projection.context.attempt.status != "completed":
        raise conflict("tool_run_inactive", "This Boundary result cannot be replayed now.")
    revision = db.scalar(
        select(LearningBoundaryRevision).where(
            LearningBoundaryRevision.source_model_call_id == identity.model_call_id,
            LearningBoundaryRevision.source_tool_call_id == identity.tool_call_id,
        )
    )
    attempt = db.get(AssessmentAttempt, revision.attempt_id) if revision is not None else None
    activity = db.get(AssessmentActivity, attempt.activity_id) if attempt is not None else None
    if attempt is None or activity is None:
        raise conflict("tool_run_inactive", "This Boundary result cannot be replayed now.")
    _assert_live_activity(db, actor, conversation, activity)
    if not attempt_has_final_evidence(db, attempt):
        raise conflict(
            "assessment_resource_revoked", "The finalized assessment evidence is no longer current."
        )


def _assessment_mutation_id(tool_call_id: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"maya-assessment-tool:{tool_call_id}"))


def write_formal_assessment(
    db: Session,
    actor: AuthContext,
    identity: ToolCallIdentity,
    content: dict[str, Any],
    follow_up_question_refs: list[str] | None = None,
) -> dict[str, bool]:
    scope = mint_runtime_execution_scope(
        db,
        actor,
        identity,
        purpose="assessment_evaluate",
        tool_name="edit_assessment",
    )
    evaluation = AssessmentEvaluationContent.model_validate(content)
    target_attempt = db.get(AssessmentAttempt, scope.attempt_id)
    if target_attempt is None:
        raise not_found()
    questions = _current_attempt_question_rows(db, target_attempt)
    selection_ordinal_offset = questions[0].ordinal if questions else 0
    expected_ordinals = {
        question.ordinal - selection_ordinal_offset for question in questions if question.required
    }
    provided_ordinals = [item.question_ordinal for item in evaluation.questions]
    if set(provided_ordinals) != expected_ordinals or len(provided_ordinals) != len(
        set(provided_ordinals)
    ):
        raise conflict(
            "assessment_result_incomplete",
            "The Assessment result must cover every Question in this attempt exactly once.",
        )
    for item in evaluation.questions:
        question = next(
            row
            for row in questions
            if row.ordinal - selection_ordinal_offset == item.question_ordinal
        )
        _version_id, question_json = _pinned_question_currently_readable(db, question)
        parsed = QuestionContent.model_validate_json(question_json)
        maximum = parsed.rubric.total_points
        if maximum is None and parsed.rubric.criteria:
            maximum = sum(criterion.points for criterion in parsed.rubric.criteria)
        if (
            item.points_awarded is not None
            and maximum is not None
            and item.points_awarded > maximum
        ):
            raise conflict(
                "assessment_score_out_of_range",
                "A Question score exceeds the points in its pinned Rubric.",
            )
    from .attempts import append_follow_up_questions, validated_follow_ups

    refs = list(follow_up_question_refs or [])
    normalized_evaluation = evaluation.model_dump(mode="json")
    content_json = _canonical(normalized_evaluation)
    request_hash = _hash(
        {
            "attempt_id": scope.attempt_id,
            "model_call_id": scope.model_call_id,
            "tool_call_id": scope.tool_call_id,
            "content": normalized_evaluation,
            **({"follow_up_question_refs": refs} if refs else {}),
        }
    )
    event_id = _assessment_mutation_id(identity.tool_call_id)
    mutation = db.scalar(
        select(LearningAssessmentMutation).where(
            LearningAssessmentMutation.actor_user_id == scope.actor_user_id,
            LearningAssessmentMutation.conversation_id == scope.conversation_id,
            LearningAssessmentMutation.client_event_id == event_id,
        )
    )
    if mutation is not None:
        if mutation.request_hash != request_hash:
            raise idempotency_conflict()
        revision = db.get(LearningAssessmentRevision, mutation.revision_id)
        if revision is None or revision.attempt_id != scope.attempt_id:
            raise conflict(
                "assessment_state_invalid", "The saved Assessment result is unavailable."
            )
        return {"saved": True}

    attempt = db.get(AssessmentAttempt, scope.attempt_id)
    activity = db.get(AssessmentActivity, scope.activity_id)
    if attempt is None or activity is None:
        raise not_found()
    follow_ups = validated_follow_ups(db, attempt, refs)
    provenance = _authorized_provenance(db, actor, scope.conversation_id)[1]
    timestamp = _now()
    assessment = db.scalar(
        select(LearningAssessment).where(LearningAssessment.attempt_id == attempt.id)
    )
    operation = "create"
    if assessment is None:
        assessment = LearningAssessment(
            id=str(uuid4()),
            owner_user_id=scope.actor_user_id,
            course_id=scope.course_id,
            created_conversation_id=scope.conversation_id,
            attempt_id=scope.attempt_id,
            current_revision_seq=1,
            created_at=timestamp,
            updated_at=timestamp,
        )
        db.add(assessment)
        next_revision_seq = 1
    else:
        operation = "edit"
        next_revision_seq = assessment.current_revision_seq + 1
    previous = (
        db.scalar(
            select(LearningAssessmentRevision).where(
                LearningAssessmentRevision.assessment_id == assessment.id,
                LearningAssessmentRevision.revision_seq == assessment.current_revision_seq,
            )
        )
        if operation == "edit"
        else None
    )
    revision = LearningAssessmentRevision(
        id=str(uuid4()),
        assessment_id=assessment.id,
        revision_seq=next_revision_seq,
        previous_revision_id=previous.id if previous else None,
        actor_user_id=scope.actor_user_id,
        course_id=scope.course_id,
        conversation_id=scope.conversation_id,
        team_id=str(provenance.team_id) if provenance.team_id else None,
        team_version_id=str(provenance.team_version_id) if provenance.team_version_id else None,
        origin=provenance.origin,
        chat_visibility=provenance.chat_visibility,
        activity_id=scope.activity_id,
        attempt_id=scope.attempt_id,
        revision_source="model_evaluation",
        evaluator_team_member_id=scope.executor_team_member_id,
        evaluator_agent_version_id=scope.executor_agent_version_id,
        source_model_call_id=scope.model_call_id,
        source_tool_call_id=scope.tool_call_id,
        content_json=content_json,
        content_hash=_hash(normalized_evaluation),
        created_at=timestamp,
    )
    mutation = LearningAssessmentMutation(
        id=str(uuid4()),
        actor_user_id=scope.actor_user_id,
        conversation_id=scope.conversation_id,
        client_event_id=event_id,
        operation=operation,
        request_hash=request_hash,
        assessment_id=assessment.id,
        revision_id=revision.id,
        created_at=timestamp,
    )
    assessment.current_revision_seq = next_revision_seq
    assessment.updated_at = timestamp
    db.flush()
    db.add(revision)
    db.flush()
    db.add(mutation)
    db.flush()
    append_follow_up_questions(db, actor, attempt, follow_ups)
    return {"saved": True}


def write_assessment_revision(
    db: Session,
    actor: AuthContext,
    identity: ToolCallIdentity,
    content: dict[str, Any],
    *,
    assessment_id: str | UUID | None = None,
    follow_up_question_refs: list[str] | None = None,
) -> dict[str, bool]:
    """Write the formal target or the explicitly granted synthetic target."""

    if assessment_id is None:
        return write_formal_assessment(db, actor, identity, content, follow_up_question_refs)
    assessment = db.get(LearningAssessment, str(assessment_id))
    if assessment is None:
        raise not_found()
    if assessment.attempt_id is not None:
        scope = mint_runtime_execution_scope(
            db,
            actor,
            identity,
            purpose="assessment_evaluate",
            tool_name="edit_assessment",
        )
        if assessment.attempt_id != scope.attempt_id:
            raise not_found()
        return write_formal_assessment(db, actor, identity, content, follow_up_question_refs)
    if follow_up_question_refs:
        raise conflict(
            "assessment_follow_up_invalid",
            "Follow-up Questions apply only to an active formal attempt.",
        )
    provenance, member_id, agent_version_id = _authorize_practice_assessment_edit(
        db, actor, identity, assessment
    )
    return _write_practice_assessment_revision(
        db,
        actor,
        identity,
        assessment,
        provenance,
        member_id,
        agent_version_id,
        content,
    )


def _write_practice_assessment_revision(
    db: Session,
    actor: AuthContext,
    identity: ToolCallIdentity,
    assessment: LearningAssessment,
    provenance: LearningProvenance,
    team_member_id: str | None,
    agent_version_id: str,
    content: dict[str, Any],
) -> dict[str, bool]:
    evaluation = AssessmentEvaluationContent.model_validate(content)
    normalized = evaluation.model_dump(mode="json")
    content_json = _canonical(normalized)
    event_id = _assessment_mutation_id(identity.tool_call_id)
    request_hash = _hash(
        {
            "assessment_id": assessment.id,
            "model_call_id": identity.model_call_id,
            "tool_call_id": identity.tool_call_id,
            "content": normalized,
        }
    )
    existing = db.scalar(
        select(LearningAssessmentMutation).where(
            LearningAssessmentMutation.actor_user_id == str(actor.user.id),
            LearningAssessmentMutation.conversation_id == identity.conversation_id,
            LearningAssessmentMutation.client_event_id == event_id,
        )
    )
    if existing is not None:
        if existing.request_hash != request_hash or existing.assessment_id != assessment.id:
            raise idempotency_conflict()
        revision = db.get(LearningAssessmentRevision, existing.revision_id)
        if revision is None or revision.revision_source != "practice_agent_edit":
            raise conflict(
                "assessment_state_invalid", "The saved Assessment revision is unavailable."
            )
        return {"saved": True}

    timestamp = _now()
    expected_revision = assessment.current_revision_seq
    next_revision = expected_revision + 1
    revision = LearningAssessmentRevision(
        id=str(uuid4()),
        assessment_id=assessment.id,
        revision_seq=next_revision,
        previous_revision_id=None,
        actor_user_id=str(actor.user.id),
        course_id=str(provenance.course_id),
        conversation_id=str(provenance.conversation_id),
        team_id=str(provenance.team_id) if provenance.team_id else None,
        team_version_id=str(provenance.team_version_id) if provenance.team_version_id else None,
        origin=provenance.origin,
        chat_visibility=provenance.chat_visibility,
        activity_id=None,
        attempt_id=None,
        revision_source="practice_agent_edit",
        editor_team_member_id=team_member_id,
        editor_agent_version_id=agent_version_id,
        source_model_call_id=identity.model_call_id,
        source_tool_call_id=identity.tool_call_id,
        content_json=content_json,
        content_hash=_hash(normalized),
        created_at=timestamp,
    )
    mutation = LearningAssessmentMutation(
        id=str(uuid4()),
        actor_user_id=str(actor.user.id),
        conversation_id=identity.conversation_id,
        client_event_id=event_id,
        operation="edit",
        request_hash=request_hash,
        assessment_id=assessment.id,
        revision_id=revision.id,
        created_at=timestamp,
    )
    try:
        with db.begin_nested():
            changed = db.execute(
                update(LearningAssessment)
                .where(
                    LearningAssessment.id == assessment.id,
                    LearningAssessment.owner_user_id == str(actor.user.id),
                    LearningAssessment.course_id == str(provenance.course_id),
                    LearningAssessment.attempt_id.is_(None),
                    LearningAssessment.current_revision_seq == expected_revision,
                )
                .values(current_revision_seq=next_revision, updated_at=timestamp)
                .execution_options(synchronize_session=False)
            )
            if getattr(changed, "rowcount", 0) != 1:
                current = db.scalar(
                    select(LearningAssessment.current_revision_seq).where(
                        LearningAssessment.id == assessment.id
                    )
                )
                raise stale_revision(current)
            previous = db.scalar(
                select(LearningAssessmentRevision).where(
                    LearningAssessmentRevision.assessment_id == assessment.id,
                    LearningAssessmentRevision.revision_seq == expected_revision,
                )
            )
            if previous is None:
                raise conflict(
                    "assessment_state_invalid", "The previous Assessment revision is unavailable."
                )
            revision.previous_revision_id = previous.id
            db.add(revision)
            db.flush()
            db.add(mutation)
            db.flush()
    except IntegrityError:
        replay = db.scalar(
            select(LearningAssessmentMutation).where(
                LearningAssessmentMutation.actor_user_id == str(actor.user.id),
                LearningAssessmentMutation.conversation_id == identity.conversation_id,
                LearningAssessmentMutation.client_event_id == event_id,
            )
        )
        if replay is None:
            raise
        if replay.request_hash != request_hash or replay.assessment_id != assessment.id:
            raise idempotency_conflict() from None
        return {"saved": True}
    return {"saved": True}


def write_formal_boundary(
    db: Session,
    actor: AuthContext,
    identity: ToolCallIdentity,
    content: dict[str, Any],
) -> dict[str, bool]:
    scope = mint_runtime_execution_scope(
        db,
        actor,
        identity,
        purpose="boundary_summarize",
        tool_name="update_learning_boundary",
    )
    summary = BoundarySummaryContent.model_validate(content)
    normalized_summary = summary.model_dump(mode="json")
    content_json = _canonical(normalized_summary)
    prior = db.scalar(
        select(LearningBoundaryRevision).where(
            LearningBoundaryRevision.source_tool_call_id == scope.tool_call_id
        )
    )
    if prior is not None:
        if (
            prior.attempt_id != scope.attempt_id
            or prior.content_hash != _hash(normalized_summary)
            or prior.source_model_call_id != scope.model_call_id
        ):
            raise idempotency_conflict()
        from .attempts import finalize_assessment_after_boundary_save

        finalize_assessment_after_boundary_save(
            db,
            actor,
            scope.conversation_id,
            attempt_id=scope.attempt_id,
            boundary_revision_id=prior.id,
            model_call_id=scope.model_call_id,
            tool_call_id=scope.tool_call_id,
        )
        return {"saved": True}
    attempt = db.get(AssessmentAttempt, scope.attempt_id)
    activity = db.get(AssessmentActivity, scope.activity_id)
    if attempt is None or activity is None:
        raise not_found()
    boundary = db.scalar(select(LearningBoundary).where(LearningBoundary.attempt_id == attempt.id))
    timestamp = _now()
    if boundary is None:
        boundary = LearningBoundary(
            id=str(uuid4()),
            attempt_id=attempt.id,
            activity_id=activity.id,
            owner_user_id=attempt.actor_user_id,
            course_id=activity.course_id,
            conversation_id=attempt.source_conversation_id,
            current_revision_seq=1,
            created_at=timestamp,
            updated_at=timestamp,
        )
        db.add(boundary)
        db.flush()
    else:
        previous_seq = boundary.current_revision_seq
        update_result = db.execute(
            update(LearningBoundary)
            .where(
                LearningBoundary.id == boundary.id,
                LearningBoundary.current_revision_seq == previous_seq,
            )
            .values(current_revision_seq=previous_seq + 1, updated_at=timestamp)
            .execution_options(synchronize_session=False)
        )
        if getattr(update_result, "rowcount", 0) != 1:
            raise stale_revision(
                db.scalar(
                    select(LearningBoundary.current_revision_seq).where(
                        LearningBoundary.id == boundary.id
                    )
                )
            )
        boundary.current_revision_seq = previous_seq + 1
        boundary.updated_at = timestamp
    sequence = boundary.current_revision_seq
    previous_revision = db.scalar(
        select(LearningBoundaryRevision).where(
            LearningBoundaryRevision.boundary_id == boundary.id,
            LearningBoundaryRevision.revision_seq == sequence - 1,
        )
    )
    revision = LearningBoundaryRevision(
        id=str(uuid4()),
        boundary_id=boundary.id,
        attempt_id=attempt.id,
        revision_seq=sequence or 1,
        previous_revision_id=previous_revision.id if previous_revision else None,
        actor_user_id=attempt.actor_user_id,
        summarizer_team_member_id=scope.executor_team_member_id,
        summarizer_agent_version_id=scope.executor_agent_version_id,
        source_model_call_id=scope.model_call_id,
        source_tool_call_id=scope.tool_call_id,
        content_json=content_json,
        content_hash=_hash(normalized_summary),
        created_at=timestamp,
    )
    db.add(revision)
    db.flush()
    evidence_ids = set(scope.evidence_learning_record_ids)
    for record_id in sorted(evidence_ids):
        db.add(
            LearningBoundaryEvidence(
                id=str(uuid4()),
                boundary_revision_id=revision.id,
                attempt_id=attempt.id,
                learning_record_id=record_id,
                assessment_revision_id=None,
                created_at=timestamp,
            )
        )
    if scope.assessment_revision_id is None:
        raise conflict(
            "assessment_evaluation_missing", "Save the Assessment before updating the Boundary."
        )
    db.add(
        LearningBoundaryEvidence(
            id=str(uuid4()),
            boundary_revision_id=revision.id,
            attempt_id=attempt.id,
            learning_record_id=None,
            assessment_revision_id=scope.assessment_revision_id,
            created_at=timestamp,
        )
    )
    db.flush()
    from .attempts import finalize_assessment_after_boundary_save

    finalize_assessment_after_boundary_save(
        db,
        actor,
        scope.conversation_id,
        attempt_id=scope.attempt_id,
        boundary_revision_id=revision.id,
        model_call_id=scope.model_call_id,
        tool_call_id=scope.tool_call_id,
    )
    return {"saved": True}


def read_own_formal_attempt(
    db: Session,
    actor: AuthContext,
    current_conversation_id: str,
    *,
    attempt_id: str | UUID,
) -> dict[str, Any]:
    """Use the target attempt's stage to project own learning evidence across chats."""

    current_conversation, _ = _authorized_provenance(db, actor, current_conversation_id)
    target = db.get(AssessmentAttempt, str(attempt_id))
    target_conversation = (
        db.get(Conversation, target.source_conversation_id) if target is not None else None
    )
    if (
        target is None
        or target_conversation is None
        or target.actor_user_id != str(actor.user.id)
        or target_conversation.withdrawn_at is not None
        or target_conversation.user_id != str(actor.user.id)
        or target_conversation.course_id != current_conversation.course_id
    ):
        raise not_found()
    question_rows = _current_attempt_question_rows(db, target)
    selection_ordinal_offset = question_rows[0].ordinal if question_rows else 0
    progress = {
        "status": target.status,
        "question_count": sum(row.required for row in question_rows),
        "presented_count": sum(
            row.required and row.presented_at is not None for row in question_rows
        ),
        "resolved_count": sum(row.required and row.status == "resolved" for row in question_rows),
        "answered_count": sum(
            row.required and row.resolution == "answered" for row in question_rows
        ),
        "skipped_count": sum(row.required and row.resolution == "skipped" for row in question_rows),
    }
    questions = []
    for question in question_rows:
        if question.presented_at is None or question.content_json is None:
            continue
        _version_id, question_json = _pinned_question_currently_readable(db, question)
        content = QuestionContent.model_validate_json(question_json)
        questions.append(
            {
                "ordinal": question.ordinal - selection_ordinal_offset,
                "prompt": content.prompt,
                "status": question.status,
                "resolution": question.resolution,
            }
        )
    active_question_ids = {question.id for question in question_rows}
    events = (
        db.execute(
            select(AssessmentAttemptEvent, LearningRecord, AssessmentAttemptQuestion)
            .join(
                LearningRecord,
                LearningRecord.id == AssessmentAttemptEvent.learning_record_id,
            )
            .join(
                AssessmentAttemptQuestion,
                AssessmentAttemptQuestion.id == AssessmentAttemptEvent.question_id,
            )
            .where(
                AssessmentAttemptEvent.attempt_id == target.id,
                AssessmentAttemptEvent.activity_id == target.activity_id,
                AssessmentAttemptEvent.actor_user_id == target.actor_user_id,
                AssessmentAttemptEvent.event_kind == "answer",
                LearningRecord.attempt_id == target.id,
                LearningRecord.activity_id == target.activity_id,
                LearningRecord.record_kind == "answer",
                LearningRecord.actor_user_id == target.actor_user_id,
                LearningRecord.course_id == target_conversation.course_id,
                LearningRecord.conversation_id == target_conversation.id,
                LearningRecord.team_id == target.team_id,
                LearningRecord.team_version_id == target_conversation.team_version_id,
                LearningRecord.origin == "published_course_team",
                LearningRecord.chat_visibility == target.chat_visibility,
                AssessmentAttemptQuestion.id.in_(active_question_ids),
            )
            .order_by(LearningRecord.created_at, LearningRecord.id)
        ).all()
        if active_question_ids
        else []
    )
    answers = [
        {
            "question_ordinal": question.ordinal - selection_ordinal_offset,
            "answer_text": json.loads(record.payload_json).get("answer_text", ""),
            "created_at": record.created_at.isoformat(),
        }
        for _event, record, question in events
    ]
    if target.status in {"in_progress", "paused"}:
        return {
            "progress": progress,
            "questions": questions,
            "answers": answers,
            "assessment": None,
            "boundary": None,
        }
    result = _assessment_for_attempt(db, target)
    boundary = _boundary_for_attempt(db, target)
    return {
        "progress": progress,
        "questions": questions,
        "answers": answers,
        "assessment": json.loads(result[1].content_json) if result is not None else None,
        "boundary": json.loads(boundary[1].content_json) if boundary is not None else None,
    }


def _teacher_public_attempt(
    db: Session,
    actor: AuthContext,
    current_conversation: Conversation,
    attempt_id: str,
) -> tuple[AssessmentAttempt, AssessmentActivity]:
    if (
        actor.user.status != "active"
        or course_member_role(db, str(actor.user.id), current_conversation.course_id) != "teacher"
    ):
        raise not_found()
    attempt = db.get(AssessmentAttempt, attempt_id)
    source_conversation = (
        db.get(Conversation, attempt.source_conversation_id) if attempt is not None else None
    )
    activity = db.get(AssessmentActivity, attempt.activity_id) if attempt is not None else None
    student = db.get(User, attempt.actor_user_id) if attempt is not None else None
    student_membership = (
        db.get(CourseMember, (current_conversation.course_id, attempt.actor_user_id))
        if attempt is not None
        else None
    )
    if (
        attempt is None
        or source_conversation is None
        or activity is None
        or student is None
        or student.status != "active"
        or student_membership is None
        or student_membership.role != "student"
        or attempt.chat_visibility != "public"
        or attempt.team_id != activity.team_id
        or attempt.recipe_id != activity.recipe_id
        or current_conversation.course_id != activity.course_id
        or source_conversation.user_id != attempt.actor_user_id
        or source_conversation.course_id != activity.course_id
        or source_conversation.withdrawn_at is not None
        or source_conversation.chat_visibility != "public"
        or source_conversation.origin != "published_course_team"
        or source_conversation.entry_kind != "maya_team"
        or source_conversation.team_id != activity.team_id
        or source_conversation.team_version_id != activity.team_version_id
        or source_conversation.publication_id != activity.publication_id
        or activity.course_id != current_conversation.course_id
    ):
        raise not_found()
    from .reports import _validated_activity

    _validated_activity(
        db,
        actor,
        course_id=activity.course_id,
        activity_id=activity.id,
    )
    for question in (
        row for row in _current_attempt_question_rows(db, attempt) if row.presented_at is not None
    ):
        _pinned_question_currently_readable(db, question)
    return attempt, activity


def read_authorized_assessment(
    db: Session,
    actor: AuthContext,
    current_conversation_id: str,
    *,
    assessment_id: str | UUID,
) -> dict[str, Any]:
    current_conversation, _ = _authorized_provenance(db, actor, current_conversation_id)
    assessment = db.get(LearningAssessment, str(assessment_id))
    if (
        assessment is None
        or assessment.attempt_id is None
        or assessment.course_id != current_conversation.course_id
    ):
        raise not_found()
    if assessment.owner_user_id == str(actor.user.id):
        return read_own_formal_assessment(
            db,
            actor,
            current_conversation_id,
            assessment_id=assessment.id,
        )
    attempt, activity = _teacher_public_attempt(
        db, actor, current_conversation, assessment.attempt_id
    )
    if (
        assessment.owner_user_id != attempt.actor_user_id
        or assessment.created_conversation_id != attempt.source_conversation_id
    ):
        raise not_found()
    result = _assessment_for_attempt(db, attempt)
    if result is None:
        raise not_found()
    revision = result[1]
    if (
        revision.activity_id != activity.id
        or revision.course_id != activity.course_id
        or revision.conversation_id != attempt.source_conversation_id
        or revision.team_id != activity.team_id
        or revision.team_version_id != activity.team_version_id
        or revision.origin != "published_course_team"
        or revision.chat_visibility != "public"
        or revision.evaluator_team_member_id != activity.evaluator_team_member_id
        or revision.evaluator_agent_version_id != activity.evaluator_agent_version_id
        or revision.source_model_call_id is None
        or revision.source_tool_call_id is None
        or _digest(revision.content_json) != revision.content_hash
    ):
        raise not_found()
    evaluation = AssessmentEvaluationContent.model_validate_json(revision.content_json)
    return {
        "status": attempt.status,
        "assessment": evaluation.model_dump(mode="json"),
        "revision": revision.revision_seq,
    }


def read_authorized_boundary(
    db: Session,
    actor: AuthContext,
    current_conversation_id: str,
    *,
    boundary_id: str | UUID,
) -> dict[str, Any]:
    current_conversation, _ = _authorized_provenance(db, actor, current_conversation_id)
    boundary = db.get(LearningBoundary, str(boundary_id))
    if boundary is None or boundary.course_id != current_conversation.course_id:
        raise not_found()
    if boundary.owner_user_id == str(actor.user.id):
        return read_own_formal_boundary(
            db,
            actor,
            current_conversation_id,
            boundary_id=boundary.id,
        )
    attempt, activity = _teacher_public_attempt(
        db, actor, current_conversation, boundary.attempt_id
    )
    if (
        boundary.owner_user_id != attempt.actor_user_id
        or boundary.activity_id != activity.id
        or boundary.conversation_id != attempt.source_conversation_id
        or not attempt_has_final_evidence(db, attempt)
    ):
        raise not_found()
    saved = _boundary_for_attempt(db, attempt)
    if saved is None:
        raise not_found()
    revision = saved[1]
    if (
        revision.summarizer_team_member_id != activity.boundary_team_member_id
        or revision.summarizer_agent_version_id != activity.boundary_agent_version_id
        or revision.source_model_call_id is None
        or revision.source_tool_call_id is None
        or _digest(revision.content_json) != revision.content_hash
    ):
        raise not_found()
    summary = BoundarySummaryContent.model_validate_json(revision.content_json)
    return {
        "status": attempt.status,
        "boundary": summary.model_dump(mode="json"),
        "revision": revision.revision_seq,
    }


def read_own_formal_assessment(
    db: Session,
    actor: AuthContext,
    current_conversation_id: str,
    *,
    assessment_id: str | UUID,
) -> dict[str, Any]:
    current_conversation, _ = _authorized_provenance(db, actor, current_conversation_id)
    assessment = db.get(LearningAssessment, str(assessment_id))
    if (
        assessment is None
        or assessment.attempt_id is None
        or assessment.owner_user_id != str(actor.user.id)
        or assessment.course_id != current_conversation.course_id
    ):
        raise not_found()
    return read_own_formal_attempt(
        db,
        actor,
        current_conversation_id,
        attempt_id=assessment.attempt_id,
    )


def read_own_formal_boundary(
    db: Session,
    actor: AuthContext,
    current_conversation_id: str,
    *,
    boundary_id: str | UUID,
) -> dict[str, Any]:
    current_conversation, _ = _authorized_provenance(db, actor, current_conversation_id)
    boundary = db.get(LearningBoundary, str(boundary_id))
    if (
        boundary is None
        or boundary.owner_user_id != str(actor.user.id)
        or boundary.course_id != current_conversation.course_id
    ):
        raise not_found()
    return read_own_formal_attempt(
        db,
        actor,
        current_conversation_id,
        attempt_id=boundary.attempt_id,
    )


__all__ = [
    "AssessmentExecutorContext",
    "RuntimeExecutionScope",
    "attempt_has_final_evidence",
    "authorize_assessment_edit",
    "authorize_boundary_update",
    "get_assessment_executor_context",
    "mint_runtime_execution_scope",
    "read_authorized_assessment",
    "read_authorized_boundary",
    "read_own_formal_assessment",
    "read_own_formal_boundary",
    "read_own_formal_attempt",
    "write_assessment_revision",
    "write_formal_assessment",
    "write_formal_boundary",
]
