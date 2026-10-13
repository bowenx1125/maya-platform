"""Durable assessment attempts and a closed student-safe runtime protocol."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Literal, cast
from uuid import UUID, uuid4, uuid5

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import PlatformError, conflict, idempotency_conflict, not_found
from app.core.models import CourseMember, SessionRecord, User
from app.modules.auth.service import AuthContext
from app.modules.knowledge_sets.models import KnowledgeAsset, KnowledgeAssetVersion, KnowledgeSet
from app.modules.knowledge_sets.schemas import QuestionContent
from app.modules.runtime_tools.registry import ToolCallIdentity
from app.modules.workspace.models import (
    Conversation,
    ConversationParticipant,
    ConversationParticipantSet,
    ConversationSharedSet,
    ConversationTurn,
    TeamProviderCall,
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
    _question_sources_current,
    current_question_version_for_asset,
    ensure_assessment_activity,
    question_sources_readable,
    refresh_assessment_activity_questions,
)
from .schemas import (
    AssessmentAnswerDTO,
    AssessmentAttemptSummary,
    AssessmentOwnerAnswerDTO,
    AssessmentProgressProjection,
    AssessmentRuntimeContext,
    AssessmentRuntimeDecision,
    AssessmentRuntimeQuestion,
    AssessmentRuntimeResponseKey,
    AssessmentRuntimeResult,
    AssessmentStudentAction,
)
from .service import _authorized_provenance, _canonical, _hash, _now


def _active_attempt(
    db: Session,
    *,
    actor_user_id: str,
    team_id: str,
    recipe_id: str,
) -> AssessmentAttempt | None:
    attempt = db.scalar(
        select(AssessmentAttempt)
        .join(Conversation, Conversation.id == AssessmentAttempt.source_conversation_id)
        .where(
            AssessmentAttempt.actor_user_id == actor_user_id,
            AssessmentAttempt.team_id == team_id,
            AssessmentAttempt.recipe_id == recipe_id,
            AssessmentAttempt.status.in_(("in_progress", "paused")),
            Conversation.withdrawn_at.is_(None),
        )
        .order_by(AssessmentAttempt.started_at, AssessmentAttempt.id)
    )
    if attempt is not None:
        return attempt
    withdrawn = db.scalar(
        select(AssessmentAttempt.source_conversation_id)
        .join(Conversation, Conversation.id == AssessmentAttempt.source_conversation_id)
        .where(
            AssessmentAttempt.actor_user_id == actor_user_id,
            AssessmentAttempt.team_id == team_id,
            AssessmentAttempt.recipe_id == recipe_id,
            AssessmentAttempt.status.in_(("in_progress", "paused")),
            Conversation.withdrawn_at.is_not(None),
        )
        .limit(1)
    )
    if withdrawn is not None:
        withdraw_conversation_attempts(db, str(withdrawn))
        return _active_attempt(
            db, actor_user_id=actor_user_id, team_id=team_id, recipe_id=recipe_id
        )
    return None


def find_active_assessment_conversation(
    db: Session,
    *,
    actor_user_id: str,
    course_id: str,
    team_id: str,
    recipe_id: str,
) -> Conversation | None:
    """Find the owner's live formal source Chat without reading its private content."""
    return db.scalar(
        select(Conversation)
        .join(AssessmentAttempt, AssessmentAttempt.source_conversation_id == Conversation.id)
        .join(AssessmentActivity, AssessmentActivity.id == AssessmentAttempt.activity_id)
        .where(
            AssessmentAttempt.actor_user_id == actor_user_id,
            AssessmentAttempt.team_id == team_id,
            AssessmentAttempt.status.in_(("in_progress", "paused")),
            AssessmentActivity.recipe_id == recipe_id,
            Conversation.user_id == actor_user_id,
            Conversation.course_id == course_id,
            Conversation.team_id == team_id,
            Conversation.entry_kind == "maya_team",
            Conversation.origin == "published_course_team",
            Conversation.withdrawn_at.is_(None),
        )
        .order_by(AssessmentAttempt.started_at.desc(), AssessmentAttempt.id.desc())
        .limit(1)
    )


def _attempt_question_rows(db: Session, attempt_id: str) -> list[AssessmentAttemptQuestion]:
    attempt = db.get(AssessmentAttempt, attempt_id)
    if attempt is None:
        return []
    return list(
        db.scalars(
            select(AssessmentAttemptQuestion)
            .join(
                AssessmentActivityQuestion,
                AssessmentActivityQuestion.id == AssessmentAttemptQuestion.activity_question_id,
            )
            .where(AssessmentAttemptQuestion.attempt_id == attempt_id)
            .where(
                AssessmentActivityQuestion.selection_revision == attempt.question_selection_revision
            )
            .order_by(AssessmentAttemptQuestion.ordinal, AssessmentAttemptQuestion.id)
        ).all()
    )


def _summary(attempt: AssessmentAttempt) -> AssessmentAttemptSummary:
    return AssessmentAttemptSummary(
        id=UUID(attempt.id),
        activity_id=UUID(attempt.activity_id),
        conversation_id=UUID(attempt.source_conversation_id),
        chat_visibility=cast(Literal["private", "public"], attempt.chat_visibility),
        status=cast(Literal["in_progress", "paused", "completed", "abandoned"], attempt.status),
        revision=attempt.revision,
    )


def _selection_ordinal(
    question_rows: list[AssessmentAttemptQuestion], question: AssessmentAttemptQuestion
) -> int:
    return question.ordinal - question_rows[0].ordinal if question_rows else question.ordinal


def _progress(db: Session, attempt: AssessmentAttempt) -> AssessmentProgressProjection:
    questions = _attempt_question_rows(db, attempt.id)
    required = [row for row in questions if row.required]
    unresolved = next((row for row in required if row.status != "resolved"), None)
    return AssessmentProgressProjection(
        attempt_id=UUID(attempt.id),
        status=cast(Literal["in_progress", "paused", "completed", "abandoned"], attempt.status),
        question_count=len(required),
        presented_count=sum(row.presented_at is not None for row in required),
        resolved_count=sum(row.status == "resolved" for row in required),
        answered_count=sum(row.resolution == "answered" for row in required),
        skipped_count=sum(row.resolution == "skipped" for row in required),
        current_ordinal=(
            _selection_ordinal(questions, unresolved) if unresolved is not None else None
        ),
        current_question_version_id=(
            UUID(unresolved.question_version_id)
            if unresolved is not None and unresolved.question_version_id
            else None
        ),
    )


def _verify_question_source(
    db: Session,
    activity_question: AssessmentActivityQuestion,
    *,
    question_version_id: str | None = None,
    require_current: bool,
) -> tuple[KnowledgeAssetVersion, QuestionContent]:
    set_row = db.get(KnowledgeSet, activity_question.knowledge_set_id)
    asset = db.get(KnowledgeAsset, activity_question.asset_id)
    if (
        set_row is None
        or set_row.deleted_at is not None
        or set_row.authorization_epoch != activity_question.authorization_epoch
        or asset is None
        or asset.knowledge_set_id != activity_question.knowledge_set_id
        or asset.kind != "question"
        or asset.current_version_seq < 1
    ):
        raise conflict(
            "assessment_resource_revoked",
            "A Question resource is no longer available. Resume after access is restored "
            "or abandon this attempt.",
        )
    if question_version_id is not None:
        version = db.get(KnowledgeAssetVersion, question_version_id)
        if version is None or version.asset_id != asset.id:
            raise conflict(
                "assessment_question_version_invalid", "The pinned Question version is unavailable."
            )
    else:
        version = db.scalar(
            select(KnowledgeAssetVersion).where(
                KnowledgeAssetVersion.asset_id == asset.id,
                KnowledgeAssetVersion.version_seq == asset.current_version_seq,
            )
        )
    if (
        version is None
        or version.set_authorization_epoch != activity_question.authorization_epoch
        or hashlib.sha256(version.content_json.encode("utf-8")).hexdigest() != version.content_hash
        or not question_sources_readable(db, set_row, version)
        or (require_current and version.version_seq != asset.current_version_seq)
        or (require_current and not _question_sources_current(db, set_row, version))
    ):
        raise conflict(
            "assessment_question_source_stale",
            "This Question is no longer current for the activity. Refresh its authorized "
            "sources before continuing.",
        )
    try:
        content = QuestionContent.model_validate_json(version.content_json)
    except ValueError:
        raise conflict(
            "assessment_question_invalid", "The pinned Question version is invalid."
        ) from None
    return version, content


def _context(
    db: Session, attempt: AssessmentAttempt, current_conversation_id: str
) -> AssessmentRuntimeContext:
    questions = _attempt_question_rows(db, attempt.id)
    required = [row for row in questions if row.required]
    unresolved = next((row for row in required if row.status != "resolved"), None)
    current: AssessmentRuntimeQuestion | None = None
    if unresolved is not None:
        if unresolved.content_json is not None:
            activity_question = db.get(AssessmentActivityQuestion, unresolved.activity_question_id)
            if activity_question is None or unresolved.question_version_id is None:
                raise conflict("assessment_state_invalid", "The pinned Question is unavailable.")
            version, pinned_content = _verify_question_source(
                db,
                activity_question,
                question_version_id=unresolved.question_version_id,
                require_current=False,
            )
            canonical_content = _canonical(pinned_content.model_dump(mode="json"))
            if (
                canonical_content != unresolved.content_json
                or hashlib.sha256(canonical_content.encode("utf-8")).hexdigest()
                != unresolved.content_hash
            ):
                raise conflict("assessment_state_invalid", "The pinned Question is unavailable.")
            content = QuestionContent.model_validate_json(unresolved.content_json)
            version_id = version.id
        else:
            activity_question = db.get(AssessmentActivityQuestion, unresolved.activity_question_id)
            if activity_question is None or activity_question.question_version_id is None:
                raise conflict("assessment_state_invalid", "The current Question is unavailable.")
            set_row = db.get(KnowledgeSet, activity_question.knowledge_set_id)
            if set_row is None:
                raise conflict(
                    "assessment_resource_revoked", "The current Question is unavailable."
                )
            current_version = current_question_version_for_asset(
                db, set_row, activity_question.asset_id
            )
            version_id = (
                current_version.id
                if current_version is not None
                else (activity_question.question_version_id)
            )
            version, content = _verify_question_source(
                db,
                activity_question,
                question_version_id=version_id,
                require_current=False,
            )
            version_id = version.id
        if version_id is not None:
            current = AssessmentRuntimeQuestion(
                ordinal=_selection_ordinal(questions, unresolved),
                question_version_id=UUID(version_id),
                prompt=content.prompt,
            )
    return AssessmentRuntimeContext(
        attempt=_summary(attempt),
        progress=_progress(db, attempt),
        current_question=current,
        canonical_conversation_id=UUID(attempt.source_conversation_id),
        redirect_to_original_conversation=current_conversation_id != attempt.source_conversation_id,
    )


def owner_attempt_context(
    db: Session, actor_user_id: str, conversation_id: str, attempt_id: str
) -> AssessmentRuntimeContext | None:
    """Re-read the owner's in-progress attempt after a server step changed it."""

    attempt = db.get(AssessmentAttempt, attempt_id)
    if (
        attempt is None
        or attempt.actor_user_id != actor_user_id
        or attempt.source_conversation_id != conversation_id
        or attempt.status != "in_progress"
    ):
        return None
    try:
        return _context(db, attempt, conversation_id)
    except PlatformError:
        return None


def has_open_question(db: Session, actor_user_id: str, conversation_id: str) -> bool:
    attempt = db.scalar(
        select(AssessmentAttempt).where(
            AssessmentAttempt.source_conversation_id == conversation_id,
            AssessmentAttempt.actor_user_id == actor_user_id,
            AssessmentAttempt.status == "in_progress",
        )
    )
    return attempt is not None and any(
        row.required and row.status != "resolved" for row in _attempt_question_rows(db, attempt.id)
    )


def _lifecycle_context(
    db: Session, attempt: AssessmentAttempt, current_conversation_id: str
) -> AssessmentRuntimeContext:
    """Project lifecycle state without reopening the Question or its sources."""

    return AssessmentRuntimeContext(
        attempt=_summary(attempt),
        progress=_progress(db, attempt),
        current_question=None,
        canonical_conversation_id=UUID(attempt.source_conversation_id),
        redirect_to_original_conversation=current_conversation_id != attempt.source_conversation_id,
    )


def _lifecycle_request_hash(
    *,
    activity_id: str,
    classification: str,
    user_message: str,
) -> str:
    """Hash lifecycle intent independently of the active attempt pointer.

    A successful redo changes that pointer. The client event still identifies
    the original action, so its durable request hash must remain stable when the
    same event is replayed against the replacement attempt.
    """

    return _hash(
        _canonical(
            {
                "activity_id": activity_id,
                "classification": classification,
                "message_hash": _hash(user_message),
            }
        )
    )


def get_assessment_runtime_context(
    db: Session,
    actor: AuthContext,
    conversation_id: str,
) -> AssessmentRuntimeContext | None:
    """Return assessment mode only for a server-resolved recipe and existing attempt."""

    conversation, _provenance = _authorized_provenance(db, actor, conversation_id)
    activity = ensure_assessment_activity(db, actor, conversation.id)
    if activity is None:
        return None
    attempt = _active_attempt(
        db,
        actor_user_id=str(actor.user.id),
        team_id=activity.team_id,
        recipe_id=activity.recipe_id,
    )
    if attempt is None:
        return None
    return _context(db, attempt, conversation.id)


def get_assessment_lifecycle_context(
    db: Session,
    actor: AuthContext,
    conversation_id: str,
) -> AssessmentRuntimeContext | None:
    """Read owner-safe lifecycle state without reopening Question or source ACLs."""
    conversation, _provenance = _authorized_provenance(db, actor, conversation_id)
    member = db.get(CourseMember, (conversation.course_id, str(actor.user.id)))
    if (
        member is None
        or member.role != "student"
        or conversation.entry_kind != "maya_team"
        or conversation.origin != "published_course_team"
    ):
        return None
    attempt = db.scalar(
        select(AssessmentAttempt)
        .where(
            AssessmentAttempt.source_conversation_id == conversation.id,
            AssessmentAttempt.actor_user_id == str(actor.user.id),
            AssessmentAttempt.team_id == conversation.team_id,
            AssessmentAttempt.status.in_(("in_progress", "paused")),
        )
        .order_by(AssessmentAttempt.started_at.desc(), AssessmentAttempt.id.desc())
        .limit(1)
    )
    if attempt is None:
        return None
    activity = db.get(AssessmentActivity, attempt.activity_id)
    if (
        activity is None
        or activity.course_id != conversation.course_id
        or activity.team_id != conversation.team_id
        or activity.team_version_id != conversation.team_version_id
        or activity.publication_id != conversation.publication_id
    ):
        raise not_found()
    return _lifecycle_context(db, attempt, conversation.id)


def _add_attempt_questions(
    db: Session,
    attempt: AssessmentAttempt,
    sources: list[AssessmentActivityQuestion],
) -> None:
    previous_max_ordinal = db.scalar(
        select(func.max(AssessmentAttemptQuestion.ordinal)).where(
            AssessmentAttemptQuestion.attempt_id == attempt.id
        )
    )
    ordinal_offset = int(previous_max_ordinal) + 1 if previous_max_ordinal is not None else 0
    for index, source in enumerate(sources):
        db.add(
            AssessmentAttemptQuestion(
                id=str(uuid4()),
                attempt_id=attempt.id,
                activity_id=attempt.activity_id,
                activity_question_id=source.id,
                question_version_id=None,
                # The legacy per-attempt ordinal uniqueness constraint is kept
                # intact; current projections normalize each selection to zero.
                ordinal=ordinal_offset + index,
                required=source.required,
                content_json=None,
                content_hash=None,
                status="not_presented",
                resolution=None,
                presented_at=None,
                resolved_at=None,
                effective_answer_record_id=None,
            )
        )


# Owner decision (2026-10-13): after the questions, the test follows up on the
# ones answered wrongly, asking for the student's reasoning. The teacher writes
# each follow-up in the Knowledge and marks it in its hidden Rubric with a
# criterion label such as "Follow-up for Question 3; at most 1; also when all
# correct" (or "追问第 3 题；最多 1 道；全对时也问"):
# - "at most" caps how many Questions one test follows up on; every item for
#   a chosen Question is asked, so a reason and a confidence step go together;
# - the order of the items in the Knowledge is the priority order;
# - "also when all correct" items are asked when nothing was answered wrongly.
_FOLLOW_UP_LABEL = re.compile(
    r"^\s*(?:follow[- ]?up\s+(?:for|on)\s+(?:question\s*|q)?(?P<en>\d+)"
    r"(?:\s*[;；,，]\s*at\s+most\s+(?P<en_limit>\d+))?"
    r"(?P<en_all>\s*[;；,，]\s*also\s+when\s+all\s+(?:are\s+)?correct)?"
    r"|追问\s*第?\s*(?P<zh>\d+)\s*题"
    r"(?:\s*[;；,，]\s*最多\s*(?P<zh_limit>\d+)\s*道?)?"
    r"(?P<zh_all>\s*[;；,，]\s*全对时也问)?)\s*[.。]?\s*$",
    re.IGNORECASE,
)


def follow_up_target(content: QuestionContent) -> tuple[int, int | None, bool] | None:
    """The Question this item follows up on, its cap and its all-correct mark."""

    for criterion in content.rubric.criteria:
        match = _FOLLOW_UP_LABEL.match(criterion.label)
        if match is None:
            continue
        number = match.group("en") or match.group("zh")
        limit = match.group("en_limit") or match.group("zh_limit")
        when_all_correct = bool(match.group("en_all") or match.group("zh_all"))
        return int(number), int(limit) if limit else None, when_all_correct
    return None


def _is_follow_up_item(db: Session, row: AssessmentActivityQuestion) -> bool:
    try:
        _version, content = _verify_question_source(db, row, require_current=False)
    except PlatformError:
        return False
    return follow_up_target(content) is not None


def _copy_activity_questions(
    db: Session,
    activity: AssessmentActivity,
    attempt: AssessmentAttempt,
) -> None:
    source_rows = list(
        db.scalars(
            select(AssessmentActivityQuestion)
            .where(
                AssessmentActivityQuestion.activity_id == activity.id,
                AssessmentActivityQuestion.selection_revision
                == activity.question_selection_revision,
            )
            .order_by(AssessmentActivityQuestion.ordinal)
        ).all()
    )
    # Owner decision (2026-10-12): the test asks every Question in the Knowledge.
    # How many there are, and of what kind, is the question-writing Agent's
    # choice, not a server count. Follow-up items wait for a wrong answer.
    _add_attempt_questions(
        db, attempt, [row for row in source_rows if not _is_follow_up_item(db, row)]
    )


def follow_up_candidates(
    db: Session, attempt: AssessmentAttempt
) -> list[tuple[AssessmentActivityQuestion, QuestionContent]]:
    """Unasked Questions the evaluator may choose until the learner submits."""

    if attempt.status != "in_progress" or attempt.submitted_at is not None:
        return []
    return unasked_questions(db, attempt)


def unasked_questions(
    db: Session, attempt: AssessmentAttempt
) -> list[tuple[AssessmentActivityQuestion, QuestionContent]]:
    """Readable catalog Questions this attempt has not asked yet."""

    asked = set(
        db.scalars(
            select(AssessmentAttemptQuestion.activity_question_id).where(
                AssessmentAttemptQuestion.attempt_id == attempt.id
            )
        ).all()
    )
    candidates: list[tuple[AssessmentActivityQuestion, QuestionContent]] = []
    for row in db.scalars(
        select(AssessmentActivityQuestion)
        .where(
            AssessmentActivityQuestion.activity_id == attempt.activity_id,
            AssessmentActivityQuestion.selection_revision == attempt.question_selection_revision,
            AssessmentActivityQuestion.required.is_(True),
        )
        .order_by(AssessmentActivityQuestion.ordinal)
    ).all():
        if row.id in asked:
            continue
        try:
            _version, content = _verify_question_source(db, row, require_current=False)
        except PlatformError:
            continue
        if follow_up_target(content) is not None:
            # Asked only after a wrong answer, never chosen as a new topic.
            continue
        candidates.append((row, content))
    return candidates


def wrong_answer_follow_ups(
    db: Session,
    attempt: AssessmentAttempt,
    scored: dict[int, tuple[float | None, float | None]],
) -> list[AssessmentActivityQuestion]:
    """Follow-up items for the Questions this evaluation scored below full marks.

    ``scored`` maps each asked Question's number in the Knowledge (from 1) to
    its awarded and maximum points. A skipped Question has no reasoning to ask
    about. Only one follow-up round runs, and none after the student ends
    early.
    """

    if attempt.status != "in_progress" or attempt.submitted_at is not None:
        return []
    asked_rows = _attempt_question_rows(db, attempt.id)
    sources = {
        row.id: row
        for row in db.scalars(
            select(AssessmentActivityQuestion).where(
                AssessmentActivityQuestion.activity_id == attempt.activity_id,
                AssessmentActivityQuestion.selection_revision
                == attempt.question_selection_revision,
            )
        ).all()
    }
    if any(
        (source := sources.get(row.activity_question_id)) is not None
        and _is_follow_up_item(db, source)
        for row in asked_rows
    ):
        return []
    items: list[tuple[tuple[int, int | None, bool], AssessmentActivityQuestion]] = []
    for source in sorted(sources.values(), key=lambda item: item.ordinal):
        if not source.required:
            continue
        try:
            _version, content = _verify_question_source(db, source, require_current=False)
        except PlatformError:
            continue
        target = follow_up_target(content)
        if target is not None:
            items.append((target, source))
    if not items:
        return []

    def wrong(number: int) -> bool:
        awarded, maximum = scored.get(number, (None, None))
        return awarded is not None and maximum is not None and maximum > 0 and awarded < maximum

    eligible = [(target, source) for target, source in items if wrong(target[0])]
    if not eligible and not any(wrong(number) for number in scored):
        eligible = [(target, source) for target, source in items if target[2]]
    limits = [target[1] for target, _source in items if target[1] is not None]
    chosen: list[int] = []
    for target, _source in eligible:
        if target[0] not in chosen:
            chosen.append(target[0])
    if limits:
        chosen = chosen[: min(limits)]
    return [source for target, source in eligible if target[0] in chosen]


def awaits_follow_up_round(db: Session, attempt_id: str) -> bool:
    """Whether scoring this round may still open follow-ups, none asked yet.

    Owner decision (2026-10-13): follow-ups come before the test ends and is
    scored. The scoring that picks them is not shown as the final scoring.
    """

    attempt = db.get(AssessmentAttempt, attempt_id)
    if attempt is None or attempt.status != "in_progress" or attempt.submitted_at is not None:
        return False
    sources = {
        row.id: row
        for row in db.scalars(
            select(AssessmentActivityQuestion).where(
                AssessmentActivityQuestion.activity_id == attempt.activity_id,
                AssessmentActivityQuestion.selection_revision
                == attempt.question_selection_revision,
            )
        ).all()
    }
    follow_ups = {row_id for row_id, row in sources.items() if _is_follow_up_item(db, row)}
    if not follow_ups:
        return False
    asked = {row.activity_question_id for row in _attempt_question_rows(db, attempt.id)}
    return not asked & follow_ups


def knowledge_question_number(db: Session, attempt_question: AssessmentAttemptQuestion) -> int:
    """This Question's number in its Knowledge, counting from 1."""

    source = db.get(AssessmentActivityQuestion, attempt_question.activity_question_id)
    if source is None:
        return 0
    first = db.scalar(
        select(func.min(AssessmentActivityQuestion.ordinal)).where(
            AssessmentActivityQuestion.activity_id == source.activity_id,
            AssessmentActivityQuestion.selection_revision == source.selection_revision,
        )
    )
    return source.ordinal - int(first or 0) + 1


def validated_follow_ups(
    db: Session, attempt: AssessmentAttempt, refs: list[str]
) -> list[AssessmentActivityQuestion]:
    if not refs:
        return []
    offered = {row.id: row for row, _content in follow_up_candidates(db, attempt)}
    if len(set(refs)) != len(refs) or any(ref not in offered for ref in refs):
        raise conflict(
            "assessment_follow_up_invalid",
            "Follow-up Questions must be chosen from the offered candidates.",
        )
    return [offered[ref] for ref in refs]


def append_follow_up_questions(
    db: Session,
    actor: AuthContext,
    attempt: AssessmentAttempt,
    follow_ups: list[AssessmentActivityQuestion],
) -> bool:
    """Start the next round with evaluator-chosen Questions from the offered remainder."""

    if not follow_ups:
        return False
    _add_attempt_questions(db, attempt, follow_ups)
    attempt.revision += 1
    attempt.updated_at = _now()
    db.flush()
    context = _context(db, attempt, attempt.source_conversation_id)
    if context.current_question is not None:
        mark_attempt_question_presented(
            db,
            actor,
            attempt.source_conversation_id,
            question_version_id=context.current_question.question_version_id,
        )
    return True


def invalidate_assessment_attempts_for_knowledge_update(
    db: Session,
    *,
    knowledge_set_id: str,
    actor_user_id: str,
) -> int:
    """Move only live formal attempts bound to this exact frozen Knowledge Set."""
    knowledge_set = db.get(KnowledgeSet, knowledge_set_id)
    actor_membership = (
        db.get(CourseMember, (knowledge_set.course_id, actor_user_id))
        if knowledge_set is not None
        else None
    )
    if actor_membership is None or actor_membership.role != "teacher":
        return 0
    shared_binding = select(ConversationSharedSet.conversation_id).where(
        ConversationSharedSet.conversation_id == Conversation.id,
        ConversationSharedSet.knowledge_set_id == knowledge_set_id,
    )
    participant_binding = (
        select(ConversationParticipantSet.participant_id)
        .join(
            ConversationParticipant,
            ConversationParticipant.id == ConversationParticipantSet.participant_id,
        )
        .where(
            ConversationParticipant.conversation_id == Conversation.id,
            ConversationParticipantSet.knowledge_set_id == knowledge_set_id,
        )
    )
    attempts = db.scalars(
        select(AssessmentAttempt)
        .join(AssessmentActivity, AssessmentActivity.id == AssessmentAttempt.activity_id)
        .join(Conversation, Conversation.id == AssessmentAttempt.source_conversation_id)
        .where(
            AssessmentAttempt.status.in_(("in_progress", "paused")),
            AssessmentAttempt.actor_user_id == Conversation.user_id,
            AssessmentAttempt.team_id == AssessmentActivity.team_id,
            AssessmentAttempt.recipe_id == AssessmentActivity.recipe_id,
            Conversation.course_id == AssessmentActivity.course_id,
            Conversation.team_id == AssessmentActivity.team_id,
            Conversation.team_version_id == AssessmentActivity.team_version_id,
            Conversation.publication_id == AssessmentActivity.publication_id,
            Conversation.entry_kind == "maya_team",
            Conversation.origin == "published_course_team",
            Conversation.withdrawn_at.is_(None),
            (shared_binding.exists() | participant_binding.exists()),
        )
        .order_by(AssessmentAttempt.id)
        .with_for_update()
    ).all()
    invalidated = 0
    refreshed_activities: dict[str, tuple[int, bool, tuple[str, ...]]] = {}
    for attempt in attempts:
        conversation = db.get(Conversation, attempt.source_conversation_id)
        activity = db.get(AssessmentActivity, attempt.activity_id)
        learner = db.get(User, attempt.actor_user_id)
        membership = (
            db.get(CourseMember, (activity.course_id, attempt.actor_user_id))
            if activity is not None
            else None
        )
        if (
            conversation is None
            or activity is None
            or learner is None
            or learner.status != "active"
            or membership is None
            or membership.role != "student"
            or conversation.user_id != attempt.actor_user_id
            or conversation.entry_kind != "maya_team"
            or conversation.origin != "published_course_team"
            or conversation.withdrawn_at is not None
            or conversation.course_id != activity.course_id
            or conversation.team_id != activity.team_id
            or conversation.team_version_id != activity.team_version_id
            or conversation.publication_id != activity.publication_id
        ):
            continue

        from app.modules.teams.service import resolve_frozen_chat_selection
        from app.modules.workspace.team_conversation import frozen_team_selection
        from app.modules.workspace.team_runtime import (
            persist_assessment_knowledge_update_notice,
        )

        selection = frozen_team_selection(db, conversation)
        target_binding_ids = {member.binding_id for member in selection.members}
        student_actor = AuthContext("", cast(SessionRecord, None), learner, "")
        try:
            resolve_frozen_chat_selection(db, student_actor, selection, target_binding_ids)
        except PlatformError as error:
            if error.status_code == 404:
                continue
            raise
        selected_set_ids = tuple(
            dict.fromkeys(
                tuple(
                    set_id
                    for member in selection.members
                    for set_id in member.own_knowledge_set_ids
                )
                + selection.shared_knowledge_set_ids
            )
        )
        if knowledge_set_id not in selected_set_ids:
            continue

        refreshed = refreshed_activities.get(activity.id)
        if refreshed is None:
            refresh_assessment_activity_questions(
                db,
                student_actor,
                conversation.id,
                activity,
                force_new_revision=True,
                allow_empty=True,
                selected_knowledge_set_ids=selected_set_ids,
            )
            next_selection_revision = activity.question_selection_revision
            has_questions = (
                db.scalar(
                    select(AssessmentActivityQuestion.id)
                    .where(
                        AssessmentActivityQuestion.activity_id == activity.id,
                        AssessmentActivityQuestion.selection_revision == next_selection_revision,
                        AssessmentActivityQuestion.required.is_(True),
                    )
                    .limit(1)
                )
                is not None
            )
            refreshed_activities[activity.id] = (
                next_selection_revision,
                has_questions,
                selected_set_ids,
            )
        else:
            _next_selection_revision, has_questions, original_set_ids = refreshed
            if selected_set_ids != original_set_ids:
                raise conflict(
                    "assessment_team_selection_changed",
                    "The published assessment Team selection changed.",
                )

        persist_assessment_knowledge_update_notice(
            db,
            attempt=attempt,
            conversation=conversation,
            has_questions=has_questions,
        )
        _delete_unfinished_attempt(db, attempt)
        invalidated += 1
    return invalidated


def _delete_unfinished_attempt(db: Session, attempt: AssessmentAttempt) -> None:
    """Drop a live attempt after the Leader has said to answer again.

    Completed attempts are not passed here. A report revision that already
    cites the row cannot lose it, so that case stops instead of guessing.
    """

    from .models import AssessmentCourseReportEvidence

    cited = db.scalar(
        select(AssessmentCourseReportEvidence.attempt_id)
        .where(AssessmentCourseReportEvidence.attempt_id == attempt.id)
        .limit(1)
    )
    if cited is not None:
        raise conflict(
            "assessment_attempt_reported",
            "This unfinished attempt is already in a saved report.",
        )
    attempt_id = attempt.id
    _discard_abandoned_learning(db, attempt_id)
    db.execute(
        delete(AssessmentAttemptEvent).where(AssessmentAttemptEvent.attempt_id == attempt_id)
    )
    db.flush()
    db.delete(attempt)
    db.flush()


def _event(
    *,
    attempt: AssessmentAttempt,
    actor_user_id: str,
    client_event_id: str,
    event_kind: str,
    classification: str | None,
    request_hash: str,
    question_id: str | None = None,
    learning_record_id: str | None = None,
    replacement_attempt_id: str | None = None,
) -> AssessmentAttemptEvent:
    return AssessmentAttemptEvent(
        id=str(uuid4()),
        attempt_id=attempt.id,
        activity_id=attempt.activity_id,
        actor_user_id=actor_user_id,
        client_event_id=client_event_id,
        event_kind=event_kind,
        classification=classification,
        question_id=question_id,
        learning_record_id=learning_record_id,
        replacement_attempt_id=replacement_attempt_id,
        request_hash=request_hash,
        created_at=_now(),
    )


def _attempt_for_start_replay(
    db: Session,
    *,
    actor_user_id: str,
    team_id: str,
    recipe_id: str,
    client_event_id: str,
) -> AssessmentAttempt | None:
    return db.scalar(
        select(AssessmentAttempt)
        .join(AssessmentAttemptEvent, AssessmentAttemptEvent.attempt_id == AssessmentAttempt.id)
        .where(
            AssessmentAttempt.actor_user_id == actor_user_id,
            AssessmentAttempt.team_id == team_id,
            AssessmentAttempt.recipe_id == recipe_id,
            AssessmentAttemptEvent.actor_user_id == actor_user_id,
            AssessmentAttemptEvent.client_event_id == client_event_id,
            AssessmentAttemptEvent.event_kind == "start",
        )
        .order_by(AssessmentAttempt.started_at.desc())
    )


def start_or_resume_attempt(
    db: Session,
    actor: AuthContext,
    conversation_id: str,
    *,
    client_event_id: str | UUID,
) -> AssessmentRuntimeContext | None:
    """Start one attempt or return the existing canonical attempt for this recipe."""

    conversation, _provenance = _authorized_provenance(db, actor, conversation_id)
    activity = ensure_assessment_activity(db, actor, conversation.id)
    if activity is None:
        return None
    event_id = str(client_event_id)
    actor_id = str(actor.user.id)
    replay = _attempt_for_start_replay(
        db,
        actor_user_id=actor_id,
        team_id=activity.team_id,
        recipe_id=activity.recipe_id,
        client_event_id=event_id,
    )
    if replay is not None:
        return _context(db, replay, conversation.id)
    active = _active_attempt(
        db,
        actor_user_id=actor_id,
        team_id=activity.team_id,
        recipe_id=activity.recipe_id,
    )
    if active is not None:
        return _context(db, active, conversation.id)
    refresh_assessment_activity_questions(db, actor, conversation.id, activity)
    if not db.scalars(
        select(AssessmentActivityQuestion.id).where(
            AssessmentActivityQuestion.activity_id == activity.id,
            AssessmentActivityQuestion.selection_revision == activity.question_selection_revision,
            AssessmentActivityQuestion.required.is_(True),
        )
    ).first():
        raise conflict(
            "assessment_questions_unavailable",
            "This assessment recipe has no current authorized Questions.",
        )

    timestamp = _now()
    attempt = AssessmentAttempt(
        id=str(uuid4()),
        activity_id=activity.id,
        team_id=activity.team_id,
        recipe_id=activity.recipe_id,
        actor_user_id=actor_id,
        source_conversation_id=conversation.id,
        chat_visibility=conversation.chat_visibility,
        status="in_progress",
        revision=0,
        question_selection_revision=activity.question_selection_revision,
        started_at=timestamp,
        updated_at=timestamp,
        completed_at=None,
        abandoned_at=None,
        abandonment_reason=None,
    )
    request_hash = _hash(
        _canonical(
            {
                "event_kind": "start",
                "activity_id": activity.id,
                "source_conversation_id": conversation.id,
                "chat_visibility": conversation.chat_visibility,
            }
        )
    )
    try:
        with db.begin_nested():
            db.add(attempt)
            db.flush()
            _copy_activity_questions(db, activity, attempt)
            db.add(
                _event(
                    attempt=attempt,
                    actor_user_id=actor_id,
                    client_event_id=event_id,
                    event_kind="start",
                    classification="start_request",
                    request_hash=request_hash,
                )
            )
            db.flush()
    except IntegrityError:
        replay = _attempt_for_start_replay(
            db,
            actor_user_id=actor_id,
            team_id=activity.team_id,
            recipe_id=activity.recipe_id,
            client_event_id=event_id,
        )
        active = _active_attempt(
            db,
            actor_user_id=actor_id,
            team_id=activity.team_id,
            recipe_id=activity.recipe_id,
        )
        winner = replay or active
        if winner is None:
            raise
        return _context(db, winner, conversation.id)
    return _context(db, attempt, conversation.id)


def mark_attempt_question_presented(
    db: Session,
    actor: AuthContext,
    conversation_id: str,
    *,
    question_version_id: str | UUID,
) -> AssessmentRuntimeContext:
    """Freeze the exact full Question/Rubric version delivered to the student."""

    context = get_assessment_runtime_context(db, actor, conversation_id)
    if context is None:
        raise not_found()
    if context.redirect_to_original_conversation:
        raise conflict(
            "assessment_resume_original_conversation",
            "Continue this assessment in its original conversation.",
        )
    attempt = db.get(AssessmentAttempt, str(context.attempt.id))
    if attempt is None or attempt.status != "in_progress":
        raise conflict(
            "assessment_attempt_not_active",
            "Resume the current attempt before presenting a Question.",
        )
    question = next(
        (
            row
            for row in _attempt_question_rows(db, attempt.id)
            if row.required and row.status != "resolved"
        ),
        None,
    )
    if question is None:
        raise conflict("assessment_question_unavailable", "No unanswered Question is available.")
    requested_version_id = str(question_version_id)
    activity_question = db.get(AssessmentActivityQuestion, question.activity_question_id)
    if activity_question is None:
        raise conflict("assessment_question_unavailable", "The current Question is unavailable.")
    if question.status == "presented":
        if question.question_version_id != requested_version_id:
            raise conflict(
                "assessment_question_already_presented", "This Question version is already pinned."
            )
        return _context(db, attempt, conversation_id)
    version, content = _verify_question_source(
        db,
        activity_question,
        question_version_id=requested_version_id,
        require_current=False,
    )
    question.question_version_id = version.id
    question.content_json = _canonical(content.model_dump(mode="json"))
    question.content_hash = hashlib.sha256(question.content_json.encode("utf-8")).hexdigest()
    question.presented_at = _now()
    question.status = "presented"
    attempt.revision += 1
    attempt.updated_at = _now()
    db.flush()
    return _context(db, attempt, conversation_id)


def _raw_answers(db: Session, attempt: AssessmentAttempt) -> list[AssessmentAnswerDTO]:
    question_rows = _attempt_question_rows(db, attempt.id)
    question_ids = {row.id for row in question_rows}
    if not question_ids:
        return []
    ordinal_offset = question_rows[0].ordinal
    rows = db.execute(
        select(LearningRecord, AssessmentAttemptQuestion)
        .join(
            AssessmentAttemptEvent,
            AssessmentAttemptEvent.learning_record_id == LearningRecord.id,
        )
        .join(
            AssessmentAttemptQuestion,
            AssessmentAttemptQuestion.id == AssessmentAttemptEvent.question_id,
        )
        .where(
            LearningRecord.attempt_id == attempt.id,
            LearningRecord.record_kind == "answer",
            AssessmentAttemptQuestion.id.in_(question_ids),
        )
        .order_by(LearningRecord.created_at, LearningRecord.id)
    ).all()
    return [
        AssessmentAnswerDTO(
            question_ordinal=question.ordinal - ordinal_offset,
            question_version_id=UUID(question.question_version_id or ""),
            answer_text=str(json.loads(record.payload_json)["answer_text"]),
            created_at=record.created_at,
        )
        for record, question in rows
    ]


def read_attempt_answers(
    db: Session,
    actor: AuthContext,
    conversation_id: str,
) -> list[AssessmentAnswerDTO]:
    """Return only the authenticated learner's own raw/effective answers."""

    conversation, _ = _authorized_provenance(db, actor, conversation_id)
    activity = ensure_assessment_activity(db, actor, conversation.id)
    if activity is None:
        return []
    attempt = _active_attempt(
        db,
        actor_user_id=str(actor.user.id),
        team_id=activity.team_id,
        recipe_id=activity.recipe_id,
    )
    if attempt is None:
        return []
    if attempt.source_conversation_id != conversation.id:
        raise conflict(
            "assessment_resume_original_conversation",
            "Continue this assessment in its original conversation.",
        )
    return _raw_answers(db, attempt)


def _event_replay(
    db: Session,
    *,
    activity_id: str,
    actor_user_id: str,
    client_event_id: str,
    request_hash: str,
    current_conversation_id: str,
) -> AssessmentRuntimeResult | None:
    event = db.scalar(
        select(AssessmentAttemptEvent).where(
            AssessmentAttemptEvent.activity_id == activity_id,
            AssessmentAttemptEvent.actor_user_id == actor_user_id,
            AssessmentAttemptEvent.client_event_id == client_event_id,
        )
    )
    if event is None:
        return None
    if event.request_hash != request_hash:
        raise idempotency_conflict()
    target = db.get(AssessmentAttempt, event.replacement_attempt_id or event.attempt_id)
    if target is None:
        raise conflict("assessment_state_invalid", "The saved attempt event is invalid.")
    context = (
        _lifecycle_context(db, target, current_conversation_id)
        if event.classification
        in {"abandon_request", "redo_request", "pause_request", "resume_request"}
        else _context(db, target, current_conversation_id)
    )
    response_key = cast(
        Literal[
            "assessment.abandoned",
            "assessment.abandoned_and_restarted",
            "assessment.paused",
            "assessment.resumed",
            "assessment.completed",
            "assessment.started",
            "assessment.progress",
        ],
        {
            "abandon_request": "assessment.abandoned",
            "redo_request": "assessment.abandoned_and_restarted",
            "pause_request": "assessment.paused",
            "resume_request": "assessment.resumed",
            "complete_request": "assessment.completed",
            "start_request": "assessment.started",
        }.get(event.classification or "", "assessment.progress"),
    )
    return AssessmentRuntimeResult(
        disposition="redirected"
        if current_conversation_id != target.source_conversation_id
        else "transitioned",
        response_key="assessment.redirect"
        if current_conversation_id != target.source_conversation_id
        else response_key,
        context=context,
    )


def _record_answer_or_skip(
    db: Session,
    *,
    actor: AuthContext,
    attempt: AssessmentAttempt,
    question: AssessmentAttemptQuestion,
    event_id: str,
    kind: Literal["answer", "skip"],
    payload: dict[str, Any],
    classification: str,
    request_hash: str,
) -> LearningRecord:
    conversation, provenance = _authorized_provenance(db, actor, attempt.source_conversation_id)
    if conversation.chat_visibility != attempt.chat_visibility:
        raise not_found()
    timestamp = _now()
    record = LearningRecord(
        id=str(uuid4()),
        actor_user_id=str(actor.user.id),
        course_id=conversation.course_id,
        conversation_id=conversation.id,
        team_id=str(provenance.team_id) if provenance.team_id else None,
        team_version_id=str(provenance.team_version_id) if provenance.team_version_id else None,
        origin=provenance.origin,
        chat_visibility=provenance.chat_visibility,
        activity_id=attempt.activity_id,
        attempt_id=attempt.id,
        record_kind=kind,
        client_event_id=event_id,
        payload_json=_canonical({"kind": kind, **payload}),
        payload_hash=_hash(_canonical({"attempt_id": attempt.id, "kind": kind, **payload})),
        created_at=timestamp,
    )
    db.add(record)
    db.flush()
    question.status = "resolved"
    question.resolution = "answered" if kind == "answer" else "skipped"
    question.resolved_at = timestamp
    question.effective_answer_record_id = record.id if kind == "answer" else None
    attempt.revision += 1
    attempt.updated_at = timestamp
    db.add(
        _event(
            attempt=attempt,
            actor_user_id=str(actor.user.id),
            client_event_id=event_id,
            event_kind=kind,
            classification=classification,
            question_id=question.id,
            learning_record_id=record.id,
            request_hash=request_hash,
        )
    )
    return record


def _submit_unfinished_attempt(
    db: Session,
    actor: AuthContext,
    attempt: AssessmentAttempt,
    *,
    event_id: str,
) -> None:
    """End the test now: shown Questions become skips and unshown ones leave the attempt.

    The submission mark stops further follow-up rounds, so evaluation and the
    Boundary summary run on what was actually asked; the rest stays unverified.
    """

    rows = [row for row in _attempt_question_rows(db, attempt.id) if row.required]
    if not any(row.presented_at is not None for row in rows):
        return
    if attempt.submitted_at is None:
        attempt.submitted_at = _now()
        attempt.updated_at = attempt.submitted_at
    for row in rows:
        if row.status == "resolved":
            continue
        if row.presented_at is None:
            db.delete(row)
            continue
        _record_answer_or_skip(
            db,
            actor=actor,
            attempt=attempt,
            question=row,
            event_id=str(uuid5(UUID(event_id), f"submit:{row.id}")),
            kind="skip",
            payload={"question_version_id": row.question_version_id, "reason": "submitted"},
            classification="complete_request",
            request_hash=_hash(
                _canonical({"attempt_id": attempt.id, "question_id": row.id, "submit": event_id})
            ),
        )
    db.flush()


def _discard_abandoned_learning(db: Session, attempt_id: str) -> None:
    """Delete a student-abandoned attempt's learning records in its transaction.

    The attempt row and its lifecycle events stay so replay, redo chains, report
    counts and Provider accounting still resolve. Late results cannot recreate
    the records because evaluation scopes require an in-progress attempt.
    """

    db.flush()
    assessment_ids = select(LearningAssessment.id).where(
        LearningAssessment.attempt_id == attempt_id
    )
    for statement in (
        delete(LearningBoundaryEvidence).where(LearningBoundaryEvidence.attempt_id == attempt_id),
        delete(LearningBoundaryRevision).where(LearningBoundaryRevision.attempt_id == attempt_id),
        delete(LearningBoundary).where(LearningBoundary.attempt_id == attempt_id),
        delete(LearningAssessmentMutation).where(
            LearningAssessmentMutation.assessment_id.in_(assessment_ids)
        ),
        delete(LearningAssessmentResourceGrant).where(
            LearningAssessmentResourceGrant.assessment_id.in_(assessment_ids)
        ),
        delete(LearningAssessmentRevision).where(
            LearningAssessmentRevision.assessment_id.in_(assessment_ids)
        ),
        delete(LearningAssessment).where(LearningAssessment.attempt_id == attempt_id),
        delete(AssessmentAttemptEvent).where(
            AssessmentAttemptEvent.attempt_id == attempt_id,
            AssessmentAttemptEvent.event_kind.in_(("answer", "skip")),
        ),
        delete(AssessmentAttemptQuestion).where(AssessmentAttemptQuestion.attempt_id == attempt_id),
        delete(LearningRecord).where(LearningRecord.attempt_id == attempt_id),
    ):
        db.execute(statement)


def _new_replacement_attempt(
    db: Session,
    old: AssessmentAttempt,
    *,
    actor_user_id: str,
    event_id: str,
    request_hash: str,
) -> AssessmentAttempt:
    activity = db.get(AssessmentActivity, old.activity_id)
    if activity is None:
        raise conflict("assessment_state_invalid", "The activity source is unavailable.")
    old.status = "abandoned"
    old.abandoned_at = _now()
    old.abandonment_reason = "user_redo"
    old.updated_at = old.abandoned_at
    old.revision += 1
    new = AssessmentAttempt(
        id=str(uuid4()),
        activity_id=old.activity_id,
        team_id=old.team_id,
        recipe_id=old.recipe_id,
        actor_user_id=actor_user_id,
        source_conversation_id=old.source_conversation_id,
        chat_visibility=old.chat_visibility,
        status="in_progress",
        revision=0,
        question_selection_revision=activity.question_selection_revision,
        started_at=_now(),
        updated_at=_now(),
        completed_at=None,
        abandoned_at=None,
        abandonment_reason=None,
    )
    db.add(new)
    db.flush()
    _copy_activity_questions(db, activity, new)
    db.flush()
    db.add(
        _event(
            attempt=old,
            actor_user_id=actor_user_id,
            client_event_id=event_id,
            event_kind="abandon",
            classification="redo_request",
            replacement_attempt_id=new.id,
            request_hash=request_hash,
        )
    )
    db.add(
        _event(
            attempt=new,
            actor_user_id=actor_user_id,
            client_event_id=str(uuid4()),
            event_kind="start",
            classification="start_request",
            request_hash=request_hash,
        )
    )
    _discard_abandoned_learning(db, old.id)
    return new


def _apply_lifecycle_transition(
    db: Session,
    actor: AuthContext,
    conversation: Conversation,
    activity: AssessmentActivity,
    attempt: AssessmentAttempt,
    *,
    event_id: str,
    classification: Literal["pause_request", "resume_request", "abandon_request", "redo_request"],
    user_message: str,
) -> AssessmentRuntimeResult:
    from .execution import _assert_live_activity

    if attempt.source_conversation_id != conversation.id:
        return AssessmentRuntimeResult(
            disposition="redirected",
            response_key="assessment.redirect",
            context=_lifecycle_context(db, attempt, conversation.id),
        )
    if classification in {"pause_request", "abandon_request"}:
        member = db.get(CourseMember, (activity.course_id, str(actor.user.id)))
        if (
            member is None
            or member.role != "student"
            or activity.course_id != conversation.course_id
            or activity.team_id != conversation.team_id
            or activity.team_version_id != conversation.team_version_id
            or activity.publication_id != conversation.publication_id
        ):
            raise not_found()
    else:
        _assert_live_activity(db, actor, conversation, activity)
    request_hash = _lifecycle_request_hash(
        activity_id=activity.id,
        classification=classification,
        user_message=user_message,
    )
    replay = _event_replay(
        db,
        activity_id=activity.id,
        actor_user_id=str(actor.user.id),
        client_event_id=event_id,
        request_hash=request_hash,
        current_conversation_id=conversation.id,
    )
    if replay is not None:
        return replay

    if attempt.status not in {"in_progress", "paused"}:
        raise conflict("assessment_attempt_not_active", "This assessment attempt has ended.")

    if classification == "resume_request":
        # Recheck source access before unpausing. If it was revoked while the
        # learner was away, keep the attempt paused so they can abandon safely.
        _context(db, attempt, conversation.id)
    elif classification == "redo_request":
        current = _context(db, attempt, conversation.id)
        if current.redirect_to_original_conversation:
            return AssessmentRuntimeResult(
                disposition="redirected", response_key="assessment.redirect", context=current
            )
        refresh_assessment_activity_questions(db, actor, conversation.id, activity)

    event_kind: Literal["pause", "resume", "abandon"]
    response_key: Literal[
        "assessment.paused",
        "assessment.resumed",
        "assessment.abandoned",
        "assessment.abandoned_and_restarted",
    ]
    if classification == "redo_request":
        try:
            with db.begin_nested():
                replacement = _new_replacement_attempt(
                    db,
                    attempt,
                    actor_user_id=str(actor.user.id),
                    event_id=event_id,
                    request_hash=request_hash,
                )
                db.flush()
        except IntegrityError:
            replay = _event_replay(
                db,
                activity_id=activity.id,
                actor_user_id=str(actor.user.id),
                client_event_id=event_id,
                request_hash=request_hash,
                current_conversation_id=conversation.id,
            )
            if replay is not None:
                return replay
            raise conflict(
                "assessment_event_conflict", "The assessment request could not be saved."
            ) from None
        return AssessmentRuntimeResult(
            disposition="transitioned",
            response_key="assessment.abandoned_and_restarted",
            context=_context(db, replacement, conversation.id),
        )

    if classification == "pause_request":
        event_kind, response_key = "pause", "assessment.paused"
    elif classification == "resume_request":
        event_kind, response_key = "resume", "assessment.resumed"
    else:
        event_kind, response_key = "abandon", "assessment.abandoned"

    try:
        with db.begin_nested():
            timestamp = _now()
            state_values: dict[str, Any] = {
                "status": attempt.status,
                "revision": attempt.revision,
            }
            if event_kind == "pause" and attempt.status == "in_progress":
                state_values.update(
                    status="paused",
                    updated_at=timestamp,
                    revision=attempt.revision + 1,
                )
            elif event_kind == "resume" and attempt.status == "paused":
                state_values.update(
                    status="in_progress",
                    updated_at=timestamp,
                    revision=attempt.revision + 1,
                )
            elif event_kind == "abandon":
                state_values.update(
                    status="abandoned",
                    abandoned_at=timestamp,
                    abandonment_reason="user_abandoned",
                    updated_at=timestamp,
                    revision=attempt.revision + 1,
                )
            saved_state = db.execute(
                update(AssessmentAttempt)
                .where(
                    AssessmentAttempt.id == attempt.id,
                    AssessmentAttempt.status == attempt.status,
                    AssessmentAttempt.revision == attempt.revision,
                )
                .values(**state_values)
                .execution_options(synchronize_session=False)
            )
            if getattr(saved_state, "rowcount", 0) != 1:
                replay = _event_replay(
                    db,
                    activity_id=activity.id,
                    actor_user_id=str(actor.user.id),
                    client_event_id=event_id,
                    request_hash=request_hash,
                    current_conversation_id=conversation.id,
                )
                if replay is not None:
                    return replay
                raise conflict(
                    "assessment_event_conflict", "The assessment request could not be saved."
                )
            db.refresh(attempt)
            db.add(
                _event(
                    attempt=attempt,
                    actor_user_id=str(actor.user.id),
                    client_event_id=event_id,
                    event_kind=event_kind,
                    classification=classification,
                    request_hash=request_hash,
                )
            )
            db.flush()
            if event_kind == "abandon":
                _discard_abandoned_learning(db, attempt.id)
    except IntegrityError:
        replay = _event_replay(
            db,
            activity_id=activity.id,
            actor_user_id=str(actor.user.id),
            client_event_id=event_id,
            request_hash=request_hash,
            current_conversation_id=conversation.id,
        )
        if replay is not None:
            return replay
        raise conflict(
            "assessment_event_conflict", "The assessment request could not be saved."
        ) from None
    return AssessmentRuntimeResult(
        disposition="transitioned",
        response_key=response_key,
        context=_lifecycle_context(db, attempt, conversation.id),
    )


def apply_attempt_lifecycle_action(
    db: Session,
    actor: AuthContext,
    attempt_id: str | UUID,
    *,
    client_event_id: str | UUID,
    action: Literal["pause", "resume", "abandon", "redo"],
) -> AssessmentRuntimeResult | None:
    """Apply an explicit attempt control without requiring a Chat/provider turn."""

    attempt = db.get(AssessmentAttempt, str(attempt_id))
    if attempt is None or attempt.actor_user_id != str(actor.user.id):
        raise not_found()
    conversation, _provenance = _authorized_provenance(db, actor, attempt.source_conversation_id)
    activity = ensure_assessment_activity(db, actor, conversation.id)
    if activity is None or activity.id != attempt.activity_id:
        return None
    classification = cast(
        Literal["pause_request", "resume_request", "abandon_request", "redo_request"],
        {
            "pause": "pause_request",
            "resume": "resume_request",
            "abandon": "abandon_request",
            "redo": "redo_request",
        }[action],
    )
    return _apply_lifecycle_transition(
        db,
        actor,
        conversation,
        activity,
        attempt,
        event_id=str(client_event_id),
        classification=classification,
        user_message=f"Explicit assessment action: {action}.",
    )


def apply_current_attempt_lifecycle_action(
    db: Session,
    actor: AuthContext,
    conversation_id: str,
    *,
    client_event_id: str | UUID,
    action: Literal["pause", "resume", "abandon", "redo"],
) -> AssessmentRuntimeResult | None:
    """Resolve an existing owner attempt without refreshing Question sources."""

    conversation, _provenance = _authorized_provenance(db, actor, conversation_id)
    attempt = db.scalar(
        select(AssessmentAttempt)
        .where(
            AssessmentAttempt.source_conversation_id == conversation.id,
            AssessmentAttempt.actor_user_id == str(actor.user.id),
            AssessmentAttempt.team_id == conversation.team_id,
            AssessmentAttempt.status.in_(("in_progress", "paused")),
        )
        .order_by(AssessmentAttempt.started_at.desc(), AssessmentAttempt.id.desc())
        .limit(1)
    )
    if attempt is None:
        return None
    activity = db.get(AssessmentActivity, attempt.activity_id)
    if (
        activity is None
        or activity.course_id != conversation.course_id
        or activity.team_id != conversation.team_id
        or activity.team_version_id != conversation.team_version_id
        or activity.publication_id != conversation.publication_id
    ):
        raise not_found()
    return _apply_lifecycle_transition(
        db,
        actor,
        conversation,
        activity,
        attempt,
        event_id=str(client_event_id),
        classification=cast(
            Literal["pause_request", "resume_request", "abandon_request", "redo_request"],
            {
                "pause": "pause_request",
                "resume": "resume_request",
                "abandon": "abandon_request",
                "redo": "redo_request",
            }[action],
        ),
        user_message=f"Explicit assessment action: {action}.",
    )


# A whole message that can only be an answer: option letters ("b", "A C",
# "选C", "I pick B") or a number (a Likert point, a student ID).
_BARE_ANSWER = re.compile(
    r"^(?:(?:我|i)\s*)?(?:选择?|选的是|choose|pick|answer)?\s*"
    r"(?:[A-Fa-f](?:\s*[,，、/和 ]\s*[A-Fa-f])*|\d{1,20})\s*[。.!！]?$",
    re.IGNORECASE,
)
# Lifecycle requests stay the model's call; anything else said about a bare
# answer was a misreading.
_ANSWER_OVERRIDABLE = frozenset(
    {
        "start_request",
        "resume_request",
        "progress_request",
        "answers_request",
        "restricted_request",
        "off_topic",
    }
)


def _bare_answer_action(
    db: Session,
    actor: AuthContext,
    conversation_id: str,
    user_text: str,
    action: AssessmentStudentAction,
) -> AssessmentStudentAction:
    """Record a bare answer to the open Question whatever the model called it.

    Bug (2026-10-13): late in a long test the Leader called answers such as
    "3" or "b" something else, so they were not saved and the same Question
    came back again and again.
    """

    if action.classification not in _ANSWER_OVERRIDABLE:
        return action
    text = user_text.strip()
    if not _BARE_ANSWER.fullmatch(text):
        return action
    context = get_assessment_runtime_context(db, actor, conversation_id)
    if (
        context is None
        or context.attempt.status != "in_progress"
        or context.current_question is None
    ):
        return action
    return AssessmentStudentAction(classification="answer_only", answer_span=text)


def apply_assessment_action(
    db: Session,
    actor: AuthContext,
    conversation_id: str,
    *,
    identity: ToolCallIdentity,
    action: AssessmentStudentAction,
) -> AssessmentRuntimeResult | None:
    """Apply a student Tool action against the accepted call's saved user turn."""

    from .execution import _accepted_tool_call_name

    if identity.conversation_id != str(conversation_id):
        raise not_found()
    conversation, _provenance = _authorized_provenance(db, actor, conversation_id)
    _accepted_tool_call_name(db, identity, expected_tool_name="assessment_action")
    source_independent_action = _revoked_source_owner_action_call(db, identity)
    if source_independent_action and (
        action.classification not in {"abandon_request", "progress_request", "answers_request"}
        or action.answer_span is not None
    ):
        raise conflict(
            "assessment_source_revoked_action_only",
            "Only owner progress, saved answers, or explicit abandonment are available while "
            "the Question source is unavailable.",
        )
    turn = db.get(ConversationTurn, identity.turn_id)
    if (
        turn is None
        or turn.conversation_id != conversation.id
        or turn.state != "pending"
        or conversation.active_request_id != turn.id
    ):
        raise conflict("tool_run_inactive", "Resume the current run before applying this action.")
    if source_independent_action and action.classification in {
        "progress_request",
        "answers_request",
    }:
        context = get_assessment_lifecycle_context(db, actor, conversation.id)
        if context is None:
            raise conflict("assessment_attempt_not_active", "There is no active owner attempt.")
        context = context.model_copy(
            update={
                "progress": context.progress.model_copy(
                    update={"current_ordinal": None, "current_question_version_id": None}
                ),
                "current_question": None,
            }
        )
        answers = (
            [
                AssessmentOwnerAnswerDTO(
                    answer_text=answer.answer_text,
                    created_at=answer.created_at,
                )
                for answer in read_attempt_answers(db, actor, conversation.id)
            ]
            if action.classification == "answers_request"
            else []
        )
        return AssessmentRuntimeResult(
            disposition="read",
            response_key=(
                "assessment.answers"
                if action.classification == "answers_request"
                else "assessment.progress"
            ),
            context=context,
            answers=answers,
        )
    activity = ensure_assessment_activity(db, actor, conversation.id)
    if activity is None:
        return None
    action = _bare_answer_action(db, actor, conversation.id, turn.user_text, action)

    version_id: UUID | None = None
    if action.classification in {
        "answer_only",
        "answer_with_restricted_request",
        "skip_request",
    }:
        context = get_assessment_runtime_context(db, actor, conversation.id)
        if context is None:
            raise conflict(
                "assessment_not_started", "Start this assessment before submitting an answer."
            )
        question = next(
            (
                row
                for row in reversed(_attempt_question_rows(db, str(context.attempt.id)))
                if row.required
                and row.presented_at is not None
                and row.presented_at <= turn.created_at
            ),
            None,
        )
        if question is None or question.question_version_id is None:
            raise conflict(
                "assessment_question_not_presented",
                "Continue from the question that was presented for this message.",
            )
        version_id = UUID(question.question_version_id)

    event_id = uuid5(UUID(turn.id), "assessment:action")
    result = apply_assessment_decision(
        db,
        actor,
        conversation.id,
        user_message=turn.user_text,
        decision=AssessmentRuntimeDecision(
            client_event_id=event_id,
            classification=action.classification,
            answer_span=action.answer_span,
            question_version_id=version_id,
        ),
    )
    if result is None:
        return None
    current_question = result.context.current_question
    if (
        result.context.attempt.status == "in_progress"
        and current_question is not None
        and not result.context.redirect_to_original_conversation
    ):
        shown = mark_attempt_question_presented(
            db,
            actor,
            conversation.id,
            question_version_id=current_question.question_version_id,
        )
        result = result.model_copy(update={"context": shown})
    return result


def _revoked_source_owner_action_call(db: Session, identity: ToolCallIdentity) -> bool:
    stage = db.get(TeamProviderCall, identity.model_call_id)
    turn = db.get(ConversationTurn, identity.turn_id)
    if stage is None or turn is None:
        return False
    try:
        request = json.loads(stage.request_json)
    except (TypeError, ValueError):
        return False
    messages = request.get("messages") if isinstance(request, dict) else None
    if not isinstance(messages, list) or len(messages) != 2:
        return False
    from app.modules.workspace.assessment_protocol import (
        ASSESSMENT_SOURCE_REVOKED_OWNER_ACTIONS_PROTOCOL,
    )

    system, user = messages
    return (
        isinstance(system, dict)
        and system.get("role") == "system"
        and system.get("content") == ASSESSMENT_SOURCE_REVOKED_OWNER_ACTIONS_PROTOCOL
        and isinstance(user, dict)
        and user.get("role") == "user"
        and user.get("content") == turn.user_text
    )


def _boundary_completion_event_id(
    attempt: AssessmentAttempt, *, model_call_id: str, tool_call_id: str
) -> str:
    return str(
        uuid5(
            UUID(attempt.id),
            f"assessment:server-complete:{model_call_id}:{tool_call_id}",
        )
    )


def _boundary_completion_request_hash(
    attempt: AssessmentAttempt,
    revision: LearningBoundaryRevision,
    *,
    model_call_id: str,
    tool_call_id: str,
) -> str:
    return _hash(
        _canonical(
            {
                "attempt_id": attempt.id,
                "activity_id": attempt.activity_id,
                "boundary_revision_id": revision.id,
                "model_call_id": model_call_id,
                "tool_call_id": tool_call_id,
            }
        )
    )


def finalize_assessment_after_boundary_save(
    db: Session,
    actor: AuthContext,
    conversation_id: str,
    *,
    attempt_id: str,
    boundary_revision_id: str,
    model_call_id: str,
    tool_call_id: str,
) -> AssessmentRuntimeResult:
    """Complete only after the exact live Boundary call closes all saved evidence.

    The caller owns the transaction containing the Boundary revision, evidence,
    runtime-tool receipt, and this terminal event. A failed fence therefore
    rolls the whole save back.
    """

    conversation, _provenance = _authorized_provenance(db, actor, conversation_id)
    attempt = db.get(AssessmentAttempt, attempt_id)
    activity = db.get(AssessmentActivity, attempt.activity_id) if attempt is not None else None
    revision = db.get(LearningBoundaryRevision, boundary_revision_id)
    if (
        attempt is None
        or activity is None
        or revision is None
        or attempt.source_conversation_id != conversation.id
        or attempt.actor_user_id != str(actor.user.id)
        or revision.attempt_id != attempt.id
        or revision.source_model_call_id != model_call_id
        or revision.source_tool_call_id != tool_call_id
    ):
        raise not_found()

    from .execution import _assert_live_activity, _boundary_for_attempt, attempt_has_final_evidence

    _assert_live_activity(db, actor, conversation, activity)
    boundary_current = _boundary_for_attempt(db, attempt)
    if (
        boundary_current is None
        or boundary_current[1].id != revision.id
        or not attempt_has_final_evidence(db, attempt)
    ):
        raise conflict(
            "assessment_final_evidence_missing",
            "The assessment result is not ready to complete.",
        )

    event_id = _boundary_completion_event_id(
        attempt, model_call_id=model_call_id, tool_call_id=tool_call_id
    )
    request_hash = _boundary_completion_request_hash(
        attempt, revision, model_call_id=model_call_id, tool_call_id=tool_call_id
    )
    prior = db.scalar(
        select(AssessmentAttemptEvent).where(
            AssessmentAttemptEvent.activity_id == activity.id,
            AssessmentAttemptEvent.actor_user_id == str(actor.user.id),
            AssessmentAttemptEvent.client_event_id == event_id,
            AssessmentAttemptEvent.event_kind == "complete",
        )
    )
    if prior is not None:
        if prior.attempt_id != attempt.id or prior.request_hash != request_hash:
            raise idempotency_conflict()
        if attempt.status != "completed":
            raise conflict("assessment_state_invalid", "The assessment completion is unavailable.")
        return AssessmentRuntimeResult(
            disposition="transitioned",
            response_key="assessment.completed",
            context=_lifecycle_context(db, attempt, conversation.id),
        )

    if attempt.status != "in_progress":
        raise conflict("assessment_attempt_inactive", "This assessment is no longer active.")
    timestamp = _now()
    expected_revision = attempt.revision
    changed = db.execute(
        update(AssessmentAttempt)
        .where(
            AssessmentAttempt.id == attempt.id,
            AssessmentAttempt.status == "in_progress",
            AssessmentAttempt.revision == expected_revision,
        )
        .values(
            status="completed",
            completed_at=timestamp,
            updated_at=timestamp,
            revision=expected_revision + 1,
        )
        .execution_options(synchronize_session=False)
    )
    if getattr(changed, "rowcount", 0) != 1:
        raise conflict("assessment_attempt_inactive", "This assessment is no longer active.")
    attempt.status = "completed"
    attempt.completed_at = timestamp
    attempt.updated_at = timestamp
    attempt.revision = expected_revision + 1
    db.add(
        _event(
            attempt=attempt,
            actor_user_id=str(actor.user.id),
            client_event_id=event_id,
            event_kind="complete",
            classification=None,
            request_hash=request_hash,
        )
    )
    db.flush()
    return AssessmentRuntimeResult(
        disposition="transitioned",
        response_key="assessment.completed",
        context=_lifecycle_context(db, attempt, conversation.id),
    )


def project_completed_assessment_for_boundary_call(
    db: Session,
    actor_user_id: str,
    conversation_id: str,
    *,
    model_call_id: str,
    tool_call_id: str,
) -> AssessmentRuntimeResult | None:
    """Project completion only when this accepted Boundary call caused it."""

    conversation = db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == actor_user_id,
            Conversation.withdrawn_at.is_(None),
        )
    )
    if conversation is None:
        return None
    revision = db.scalar(
        select(LearningBoundaryRevision).where(
            LearningBoundaryRevision.source_model_call_id == model_call_id,
            LearningBoundaryRevision.source_tool_call_id == tool_call_id,
        )
    )
    if revision is None:
        return None
    attempt = db.get(AssessmentAttempt, revision.attempt_id)
    if (
        attempt is None
        or attempt.source_conversation_id != conversation.id
        or attempt.actor_user_id != actor_user_id
        or attempt.status != "completed"
    ):
        return None
    event_id = _boundary_completion_event_id(
        attempt, model_call_id=model_call_id, tool_call_id=tool_call_id
    )
    request_hash = _boundary_completion_request_hash(
        attempt, revision, model_call_id=model_call_id, tool_call_id=tool_call_id
    )
    event = db.scalar(
        select(AssessmentAttemptEvent).where(
            AssessmentAttemptEvent.attempt_id == attempt.id,
            AssessmentAttemptEvent.activity_id == attempt.activity_id,
            AssessmentAttemptEvent.actor_user_id == actor_user_id,
            AssessmentAttemptEvent.client_event_id == event_id,
            AssessmentAttemptEvent.event_kind == "complete",
        )
    )
    if event is None or event.request_hash != request_hash:
        return None
    boundary = db.get(LearningBoundary, revision.boundary_id)
    if boundary is None or boundary.current_revision_seq != revision.revision_seq:
        return None
    return AssessmentRuntimeResult(
        disposition="transitioned",
        response_key="assessment.completed",
        context=_lifecycle_context(db, attempt, conversation.id),
    )


def project_attempt_lifecycle_for_latest_turn(
    db: Session,
    actor_user_id: str,
    conversation_id: str,
    turn_id: str,
    *,
    previous: AssessmentRuntimeResult | None,
) -> AssessmentRuntimeResult | None:
    """Refresh owner-only lifecycle status on the newest persisted Chat turn."""

    conversation = db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == actor_user_id,
            Conversation.withdrawn_at.is_(None),
        )
    )
    if conversation is None:
        return None
    latest_turn_id = db.scalar(
        select(ConversationTurn.id)
        .where(ConversationTurn.conversation_id == conversation.id)
        .order_by(ConversationTurn.position.desc(), ConversationTurn.id.desc())
        .limit(1)
    )
    if latest_turn_id != turn_id:
        return None
    attempt = db.scalar(
        select(AssessmentAttempt)
        .where(
            AssessmentAttempt.source_conversation_id == conversation.id,
            AssessmentAttempt.actor_user_id == actor_user_id,
        )
        .order_by(AssessmentAttempt.started_at.desc(), AssessmentAttempt.id.desc())
        .limit(1)
    )
    if attempt is None or attempt.updated_at is None:
        return None
    turn = db.get(ConversationTurn, turn_id)
    if turn is None:
        return None
    attempt_updated = attempt.updated_at
    turn_created = turn.created_at
    if attempt_updated.tzinfo is None and turn_created.tzinfo is not None:
        attempt_updated = attempt_updated.replace(tzinfo=turn_created.tzinfo)
    elif turn_created.tzinfo is None and attempt_updated.tzinfo is not None:
        turn_created = turn_created.replace(tzinfo=attempt_updated.tzinfo)
    if attempt_updated < turn_created:
        return None

    response_key: AssessmentRuntimeResponseKey
    if attempt.status == "in_progress":
        if previous is None or previous.context.attempt.status != "paused":
            return None
        response_key = "assessment.resumed"
    elif attempt.status == "paused":
        response_key = "assessment.paused"
    elif attempt.status == "completed":
        response_key = "assessment.completed"
    else:
        response_key = "assessment.abandoned"
    return AssessmentRuntimeResult(
        disposition="transitioned",
        response_key=response_key,
        context=_lifecycle_context(db, attempt, conversation.id),
    )


def apply_assessment_decision(
    db: Session,
    actor: AuthContext,
    conversation_id: str,
    *,
    user_message: str,
    decision: AssessmentRuntimeDecision,
) -> AssessmentRuntimeResult | None:
    """Apply one closed semantic action; never forward model prose to an active attempt."""

    conversation, _ = _authorized_provenance(db, actor, conversation_id)
    event_id = str(decision.client_event_id)
    is_lifecycle_action = decision.classification in {
        "pause_request",
        "resume_request",
        "abandon_request",
        "redo_request",
    }
    lifecycle_hash: str | None = None
    actor_id = str(actor.user.id)
    if is_lifecycle_action:
        if decision.answer_span is not None or decision.question_version_id is not None:
            raise conflict("assessment_decision_invalid", "The assessment action is not valid.")
        prior_events = db.scalars(
            select(AssessmentAttemptEvent)
            .join(AssessmentAttempt, AssessmentAttempt.id == AssessmentAttemptEvent.attempt_id)
            .where(
                AssessmentAttempt.source_conversation_id == conversation.id,
                AssessmentAttempt.actor_user_id == actor_id,
                AssessmentAttemptEvent.actor_user_id == actor_id,
                AssessmentAttemptEvent.client_event_id == event_id,
            )
            .order_by(AssessmentAttemptEvent.created_at.desc(), AssessmentAttemptEvent.id)
        ).all()
        if len(prior_events) > 1:
            raise idempotency_conflict()
        if prior_events:
            prior_event = prior_events[0]
            lifecycle_hash = _lifecycle_request_hash(
                activity_id=prior_event.activity_id,
                classification=decision.classification,
                user_message=user_message,
            )
            replay = _event_replay(
                db,
                activity_id=prior_event.activity_id,
                actor_user_id=actor_id,
                client_event_id=event_id,
                request_hash=lifecycle_hash,
                current_conversation_id=conversation.id,
            )
            if replay is not None:
                return replay

    if decision.classification in {"pause_request", "abandon_request"}:
        activity = db.scalar(
            select(AssessmentActivity)
            .join(AssessmentAttempt, AssessmentAttempt.activity_id == AssessmentActivity.id)
            .where(
                AssessmentAttempt.source_conversation_id == conversation.id,
                AssessmentAttempt.actor_user_id == str(actor.user.id),
                AssessmentAttempt.team_id == conversation.team_id,
                AssessmentAttempt.status.in_(("in_progress", "paused")),
            )
            .order_by(AssessmentAttempt.started_at.desc(), AssessmentAttempt.id.desc())
            .limit(1)
        )
    else:
        activity = ensure_assessment_activity(db, actor, conversation.id)
    if activity is None:
        return None
    if is_lifecycle_action:
        if lifecycle_hash is None:
            lifecycle_hash = _lifecycle_request_hash(
                activity_id=activity.id,
                classification=decision.classification,
                user_message=user_message,
            )
            replay = _event_replay(
                db,
                activity_id=activity.id,
                actor_user_id=actor_id,
                client_event_id=event_id,
                request_hash=lifecycle_hash,
                current_conversation_id=conversation.id,
            )
            if replay is not None:
                return replay

    attempt = _active_attempt(
        db,
        actor_user_id=str(actor.user.id),
        team_id=activity.team_id,
        recipe_id=activity.recipe_id,
    )
    if attempt is None:
        if decision.classification == "start_request":
            if decision.answer_span is not None or decision.question_version_id is not None:
                raise conflict("assessment_decision_invalid", "The assessment action is not valid.")
            context = start_or_resume_attempt(
                db,
                actor,
                conversation.id,
                client_event_id=decision.client_event_id,
            )
            if context is None:
                return None
            return AssessmentRuntimeResult(
                disposition="transitioned",
                response_key="assessment.started",
                context=context,
            )
        return None

    if is_lifecycle_action:
        assert lifecycle_hash is not None
        return _apply_lifecycle_transition(
            db,
            actor,
            conversation,
            activity,
            attempt,
            event_id=event_id,
            classification=cast(
                Literal["pause_request", "resume_request", "abandon_request", "redo_request"],
                decision.classification,
            ),
            user_message=user_message,
        )

    current = _context(db, attempt, conversation.id)
    if current.redirect_to_original_conversation:
        return AssessmentRuntimeResult(
            disposition="redirected", response_key="assessment.redirect", context=current
        )

    allowed_answers = {"answer_only", "answer_with_restricted_request"}
    is_answer = decision.classification in allowed_answers
    is_skip = decision.classification == "skip_request"
    if is_answer:
        answer_span = decision.answer_span
        if (
            not answer_span
            or not answer_span.strip()
            or answer_span not in user_message
            or decision.question_version_id is None
        ):
            return AssessmentRuntimeResult(
                disposition="redirected", response_key="assessment.redirect", context=current
            )
    elif is_skip:
        if decision.answer_span is not None or decision.question_version_id is None:
            raise conflict("assessment_decision_invalid", "The assessment action is not valid.")
    elif decision.answer_span is not None or decision.question_version_id is not None:
        raise conflict("assessment_decision_invalid", "The assessment action is not valid.")

    if decision.classification == "start_request":
        return AssessmentRuntimeResult(
            disposition="redirected", response_key="assessment.redirect", context=current
        )

    request_hash = _hash(
        _canonical(
            {
                "attempt_id": attempt.id,
                "classification": decision.classification,
                "answer_span": decision.answer_span,
                "question_version_id": str(decision.question_version_id)
                if decision.question_version_id
                else None,
                "message_hash": _hash(user_message),
            }
        )
    )
    replay = _event_replay(
        db,
        activity_id=attempt.activity_id,
        actor_user_id=str(actor.user.id),
        client_event_id=event_id,
        request_hash=request_hash,
        current_conversation_id=conversation.id,
    )
    if replay is not None:
        return replay

    if decision.classification == "restart_request":
        with db.begin_nested():
            db.add(
                _event(
                    attempt=attempt,
                    actor_user_id=str(actor.user.id),
                    client_event_id=event_id,
                    event_kind="restart",
                    classification=decision.classification,
                    request_hash=request_hash,
                )
            )
            db.flush()
        return AssessmentRuntimeResult(
            disposition="read",
            response_key="assessment.restart_requires_choice",
            context=current,
        )

    if is_answer or is_skip:
        if attempt.status != "in_progress":
            return AssessmentRuntimeResult(
                disposition="redirected", response_key="assessment.redirect", context=current
            )
        question_rows = _attempt_question_rows(db, attempt.id)
        expected_question_version = (
            str(decision.question_version_id) if decision.question_version_id else None
        )
        if is_answer:
            question = next(
                (
                    row
                    for row in question_rows
                    if row.presented_at is not None
                    and row.question_version_id == expected_question_version
                ),
                None,
            )
        else:
            question = next(
                (row for row in question_rows if row.required and row.status != "resolved"),
                None,
            )
        if (
            question is None
            or question.presented_at is None
            or question.question_version_id != expected_question_version
            or (is_skip and question.status == "resolved")
        ):
            return AssessmentRuntimeResult(
                disposition="redirected", response_key="assessment.redirect", context=current
            )
        payload = (
            {
                "answer_text": decision.answer_span,
                "question_version_id": question.question_version_id,
            }
            if is_answer
            else {"question_version_id": question.question_version_id}
        )
        try:
            with db.begin_nested():
                _record_answer_or_skip(
                    db,
                    actor=actor,
                    attempt=attempt,
                    question=question,
                    event_id=event_id,
                    kind="answer" if is_answer else "skip",
                    payload=payload,
                    classification=decision.classification,
                    request_hash=request_hash,
                )
                db.flush()
        except IntegrityError:
            replay = _event_replay(
                db,
                activity_id=attempt.activity_id,
                actor_user_id=str(actor.user.id),
                client_event_id=event_id,
                request_hash=request_hash,
                current_conversation_id=conversation.id,
            )
            if replay is not None:
                return replay
            raise conflict(
                "assessment_event_conflict", "The assessment request could not be saved."
            ) from None
        next_context = _context(db, attempt, conversation.id)
        return AssessmentRuntimeResult(
            disposition="recorded",
            response_key=(
                "assessment.answer_recorded_restricted_request"
                if decision.classification == "answer_with_restricted_request"
                else "assessment.answer_recorded"
            )
            if is_answer
            else "assessment.progress",
            context=next_context,
        )

    response_key: AssessmentRuntimeResponseKey = "assessment.redirect"
    disposition: Literal["recorded", "transitioned", "read", "redirected"] = "redirected"
    with db.begin_nested():
        timestamp = _now()
        if decision.classification == "complete_request" and attempt.status == "in_progress":
            _submit_unfinished_attempt(db, actor, attempt, event_id=event_id)
            required = [row for row in _attempt_question_rows(db, attempt.id) if row.required]
            if required and all(
                row.status == "resolved" and row.presented_at is not None for row in required
            ):
                from .execution import attempt_has_final_evidence

                if not attempt_has_final_evidence(db, attempt):
                    response_key, disposition = "assessment.results_pending", "read"
                else:
                    expected_revision = attempt.revision
                    expected_selection_revision = attempt.question_selection_revision
                    changed = db.execute(
                        update(AssessmentAttempt)
                        .where(
                            AssessmentAttempt.id == attempt.id,
                            AssessmentAttempt.status == "in_progress",
                            AssessmentAttempt.revision == expected_revision,
                            AssessmentAttempt.question_selection_revision
                            == expected_selection_revision,
                        )
                        .values(
                            status="completed",
                            completed_at=timestamp,
                            updated_at=timestamp,
                            revision=expected_revision + 1,
                        )
                        .execution_options(synchronize_session=False)
                    )
                    if getattr(changed, "rowcount", 0) != 1:
                        raise conflict(
                            "assessment_attempt_inactive",
                            "This assessment changed before it could complete.",
                        )
                    attempt.status = "completed"
                    attempt.completed_at = timestamp
                    attempt.updated_at = timestamp
                    attempt.revision = expected_revision + 1
                    db.add(
                        _event(
                            attempt=attempt,
                            actor_user_id=str(actor.user.id),
                            client_event_id=event_id,
                            event_kind="complete",
                            classification=decision.classification,
                            request_hash=request_hash,
                        )
                    )
                    response_key, disposition = "assessment.completed", "transitioned"
        elif decision.classification in {"progress_request", "off_topic"}:
            response_key, disposition = "assessment.progress", "read"
        elif decision.classification == "restricted_request":
            disposition = "read"
        elif decision.classification == "answers_request":
            response_key, disposition = "assessment.answers", "read"
        db.flush()
    next_context = _context(db, attempt, conversation.id)
    answers = (
        [
            AssessmentOwnerAnswerDTO(
                answer_text=answer.answer_text,
                created_at=answer.created_at,
            )
            for answer in _raw_answers(db, attempt)
        ]
        if decision.classification == "answers_request"
        else []
    )
    return AssessmentRuntimeResult(
        disposition=disposition,
        response_key=cast(
            Literal[
                "assessment.answer_recorded",
                "assessment.answer_recorded_restricted_request",
                "assessment.paused",
                "assessment.resumed",
                "assessment.completed",
                "assessment.abandoned",
                "assessment.started",
                "assessment.abandoned_and_restarted",
                "assessment.progress",
                "assessment.answers",
                "assessment.results_pending",
                "assessment.redirect",
            ],
            response_key,
        ),
        context=next_context,
        answers=answers,
    )


def withdraw_conversation_attempts(db: Session, conversation_id: str) -> int:
    """End attempts rooted in a withdrawn Chat without deleting answer evidence."""

    rows = db.scalars(
        select(AssessmentAttempt).where(
            AssessmentAttempt.source_conversation_id == conversation_id,
            AssessmentAttempt.status.in_(("in_progress", "paused")),
        )
    ).all()
    count = 0
    for attempt in rows:
        timestamp = _now()
        attempt.status = "abandoned"
        attempt.abandoned_at = timestamp
        attempt.abandonment_reason = "chat_withdrawn"
        attempt.updated_at = timestamp
        attempt.revision += 1
        event_id = str(uuid4())
        db.add(
            _event(
                attempt=attempt,
                actor_user_id=attempt.actor_user_id,
                client_event_id=event_id,
                event_kind="withdraw",
                classification=None,
                request_hash=_hash(
                    _canonical(
                        {
                            "attempt_id": attempt.id,
                            "conversation_id": conversation_id,
                            "reason": "chat_withdrawn",
                        }
                    )
                ),
            )
        )
        count += 1
    db.flush()
    return count


__all__ = [
    "apply_attempt_lifecycle_action",
    "apply_assessment_decision",
    "apply_current_attempt_lifecycle_action",
    "get_assessment_runtime_context",
    "mark_attempt_question_presented",
    "read_attempt_answers",
    "start_or_resume_attempt",
    "withdraw_conversation_attempts",
]
