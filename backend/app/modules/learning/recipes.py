"""Resolve explicitly declared formal assessment recipes for published Teams."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import conflict, not_found
from app.core.models import AgentVersion, CourseMember, KnowledgeDocument, StoredFile
from app.modules.auth.service import AuthContext
from app.modules.knowledge_sets.models import (
    KnowledgeAsset,
    KnowledgeAssetVersion,
    KnowledgeAssetVersionSource,
    KnowledgeDocumentVersion,
    KnowledgeGenerationRun,
    KnowledgeSet,
    KnowledgeSetMarkdownVersion,
    KnowledgeSetSource,
)
from app.modules.knowledge_sets.schemas import QuestionContent
from app.modules.teams.models import TeamVersionMember
from app.modules.teams.service import resolve_chat_entry

from .models import AssessmentActivity, AssessmentActivityQuestion
from .service import _authorized_provenance

RECIPE_DECLARATION = re.compile(r"(?m)^MAYA-ASSESSMENT-RECIPE:\s*([a-z0-9][a-z0-9._-]{0,119})\s*$")
SUPPORTED_RECIPE_ID = "mayaform.diagnostic.v1"
QUESTION_SCOPE_DECLARATION = "MAYA-ASSESSMENT-QUESTIONS: all-current-authorized"
COMPLETION_DECLARATION = "MAYA-ASSESSMENT-COMPLETION: every-selected-question-resolved"
ASSESSMENT_ROLE_DECLARATION = re.compile(
    r"(?m)^MAYA-ASSESSMENT-ROLE:\s*(evaluator|boundary_summarizer)\s*$"
)


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def declared_recipe(agent_md: str) -> str | None:
    """Return a registered recipe only for the explicit, stable template marker."""

    match = RECIPE_DECLARATION.search(agent_md)
    if match is None:
        return None
    recipe_id = match.group(1)
    if recipe_id != SUPPORTED_RECIPE_ID:
        raise conflict(
            "assessment_recipe_unsupported",
            "This published Team uses an unsupported assessment recipe.",
        )
    declarations = {line.strip() for line in agent_md.splitlines()}
    if QUESTION_SCOPE_DECLARATION not in declarations or COMPLETION_DECLARATION not in declarations:
        raise conflict(
            "assessment_recipe_incomplete",
            "This Leader template must declare its Question selection and completion rules "
            "before assessment can start.",
        )
    return recipe_id


def declared_assessment_role(agent_md: str) -> str | None:
    """Read an executor role from the immutable AgentVersion's explicit template."""

    roles = ASSESSMENT_ROLE_DECLARATION.findall(agent_md)
    if len(roles) > 1:
        raise conflict(
            "assessment_executor_role_invalid",
            "A Team member can have only one assessment execution role.",
        )
    return roles[0] if roles else None


def _question_sources_current(
    db: Session, set_row: KnowledgeSet, version: KnowledgeAssetVersion
) -> bool:
    if version.set_authorization_epoch != set_row.authorization_epoch:
        return False
    references = db.scalars(
        select(KnowledgeAssetVersionSource).where(
            KnowledgeAssetVersionSource.asset_version_id == version.id
        )
    ).all()
    for reference in references:
        binding = db.get(KnowledgeSetSource, reference.source_binding_id)
        document = db.get(KnowledgeDocument, reference.document_id)
        stored_file = db.get(StoredFile, reference.stored_file_id)
        if (
            binding is None
            or not binding.is_active
            or binding.knowledge_set_id != set_row.id
            or binding.document_id != reference.document_id
            or binding.stored_file_id != reference.stored_file_id
            or binding.source_content_hash != reference.source_content_hash
            or binding.source_file_sha256 != reference.source_file_sha256
            or binding.source_authorization_epoch != reference.source_authorization_epoch
            or document is None
            or document.workspace_state != "active"
            or document.content_hash != reference.source_content_hash
            or document.stored_file_id != reference.stored_file_id
            or document.authorization_epoch != reference.source_authorization_epoch
            or stored_file is None
            or stored_file.sha256 != reference.source_file_sha256
            or stored_file.state == "deleted"
            or _hash(reference.source_location_json) != reference.source_location_hash
        ):
            return False
    return True


def question_sources_readable(
    db: Session, set_row: KnowledgeSet, version: KnowledgeAssetVersion
) -> bool:
    """Recheck current ACL epochs while permitting a readable historical source version."""

    if (
        set_row.deleted_at is not None
        or version.set_authorization_epoch != set_row.authorization_epoch
    ):
        return False
    references = db.scalars(
        select(KnowledgeAssetVersionSource).where(
            KnowledgeAssetVersionSource.asset_version_id == version.id
        )
    ).all()
    for reference in references:
        binding = db.get(KnowledgeSetSource, reference.source_binding_id)
        document = db.get(KnowledgeDocument, reference.document_id)
        stored_file = db.get(StoredFile, reference.stored_file_id)
        # This row proves immutable content identity; its epoch is when that
        # file was recorded, while current access is checked against the
        # document and binding below.
        historic_receipt = db.scalar(
            select(KnowledgeDocumentVersion.id).where(
                KnowledgeDocumentVersion.document_id == reference.document_id,
                KnowledgeDocumentVersion.stored_file_id == reference.stored_file_id,
                KnowledgeDocumentVersion.content_hash == reference.source_content_hash,
                KnowledgeDocumentVersion.file_sha256 == reference.source_file_sha256,
            )
        )
        source_is_current = (
            binding is not None
            and document is not None
            and binding.stored_file_id == reference.stored_file_id
            and binding.source_content_hash == reference.source_content_hash
            and binding.source_file_sha256 == reference.source_file_sha256
            and document.stored_file_id == reference.stored_file_id
            and document.content_hash == reference.source_content_hash
        )
        if (
            binding is None
            or not binding.is_active
            or binding.knowledge_set_id != set_row.id
            or binding.document_id != reference.document_id
            or binding.source_authorization_epoch != reference.source_authorization_epoch
            or document is None
            or document.workspace_state != "active"
            or document.authorization_epoch != reference.source_authorization_epoch
            or stored_file is None
            or stored_file.sha256 != reference.source_file_sha256
            or stored_file.state == "deleted"
            or (not source_is_current and historic_receipt is None)
            or _hash(reference.source_location_json) != reference.source_location_hash
        ):
            return False
    return True


def _canonical_markdown_asset_versions(
    db: Session, set_row: KnowledgeSet
) -> list[tuple[KnowledgeAsset, KnowledgeAssetVersion]] | None:
    """Return the current Markdown projection's immutable Assets, if one exists."""

    if set_row.current_markdown_version_seq < 1:
        return None
    markdown_version = db.scalar(
        select(KnowledgeSetMarkdownVersion).where(
            KnowledgeSetMarkdownVersion.knowledge_set_id == set_row.id,
            KnowledgeSetMarkdownVersion.version_seq == set_row.current_markdown_version_seq,
        )
    )
    if (
        markdown_version is None
        or _hash(markdown_version.markdown) != markdown_version.content_hash
    ):
        raise conflict(
            "assessment_question_catalog_invalid", "The current Question catalog is unavailable."
        )
    try:
        version_ids = json.loads(markdown_version.asset_version_ids_json)
    except (TypeError, ValueError):
        raise conflict(
            "assessment_question_catalog_invalid", "The current Question catalog is unavailable."
        ) from None
    if (
        not isinstance(version_ids, list)
        or any(not isinstance(version_id, str) for version_id in version_ids)
        or _canonical(version_ids) != markdown_version.asset_version_ids_json
        or len(version_ids) != len(set(version_ids))
    ):
        raise conflict(
            "assessment_question_catalog_invalid", "The current Question catalog is unavailable."
        )
    result: list[tuple[KnowledgeAsset, KnowledgeAssetVersion]] = []
    for version_id in version_ids:
        version = db.get(KnowledgeAssetVersion, version_id)
        asset = db.get(KnowledgeAsset, version.asset_id) if version is not None else None
        if (
            version is None
            or asset is None
            or asset.knowledge_set_id != set_row.id
            or _hash(version.content_json) != version.content_hash
        ):
            raise conflict(
                "assessment_question_catalog_invalid",
                "The current Question catalog is unavailable.",
            )
        if asset.kind == "question":
            result.append((asset, version))
    return result


def _has_generation_history(db: Session, set_row: KnowledgeSet) -> bool:
    return (
        set_row.generation_intent_seq > 0
        or db.scalar(
            select(KnowledgeGenerationRun.id)
            .where(KnowledgeGenerationRun.knowledge_set_id == set_row.id)
            .limit(1)
        )
        is not None
    )


def _manual_or_legacy_question_version(
    db: Session, set_row: KnowledgeSet, asset: KnowledgeAsset, version: KnowledgeAssetVersion
) -> KnowledgeAssetVersion | None:
    if not _has_generation_history(db, set_row) or (
        version.generation_job_id is None and version.origin != "ai"
    ):
        return version
    return db.scalar(
        select(KnowledgeAssetVersion)
        .where(
            KnowledgeAssetVersion.asset_id == asset.id,
            KnowledgeAssetVersion.generation_job_id.is_(None),
            KnowledgeAssetVersion.origin.in_(("manual", "legacy")),
        )
        .order_by(KnowledgeAssetVersion.version_seq.desc())
        .limit(1)
    )


def current_question_version_for_asset(
    db: Session,
    set_row: KnowledgeSet,
    asset_id: str,
) -> KnowledgeAssetVersion | None:
    """Return the current canonical Question version, or None if removed."""

    if set_row.deleted_at is not None:
        raise conflict("assessment_resource_revoked", "The Question Set is no longer available.")
    projected = _canonical_markdown_asset_versions(db, set_row)
    if projected is not None:
        for asset, version in projected:
            if asset.id == asset_id:
                if not question_sources_readable(db, set_row, version):
                    raise conflict(
                        "assessment_question_source_stale",
                        "A selected Question source is no longer authorized.",
                    )
                try:
                    QuestionContent.model_validate_json(version.content_json)
                except (ValidationError, ValueError):
                    raise conflict(
                        "assessment_question_invalid", "The current Question is unavailable."
                    ) from None
                return version
        return None

    fallback_asset = db.get(KnowledgeAsset, asset_id)
    if (
        fallback_asset is None
        or fallback_asset.knowledge_set_id != set_row.id
        or fallback_asset.kind != "question"
    ):
        return None
    fallback_version = db.scalar(
        select(KnowledgeAssetVersion).where(
            KnowledgeAssetVersion.asset_id == fallback_asset.id,
            KnowledgeAssetVersion.version_seq == fallback_asset.current_version_seq,
        )
    )
    if fallback_version is not None:
        fallback_version = _manual_or_legacy_question_version(
            db, set_row, fallback_asset, fallback_version
        )
    if fallback_version is None:
        return None
    if fallback_version is None or not _question_sources_current(db, set_row, fallback_version):
        raise conflict(
            "assessment_question_source_stale",
            "A selected Question source is no longer authorized.",
        )
    try:
        QuestionContent.model_validate_json(fallback_version.content_json)
    except (ValidationError, ValueError):
        raise conflict(
            "assessment_question_invalid", "The current Question is unavailable."
        ) from None
    return fallback_version


def _selected_questions(
    db: Session,
    set_ids: tuple[str, ...],
) -> list[tuple[str, str, int, str]]:
    selected: list[tuple[str, str, int, str]] = []
    for set_id in set_ids:
        set_row = db.get(KnowledgeSet, set_id)
        if set_row is None or set_row.deleted_at is not None:
            raise not_found()
        projected = _canonical_markdown_asset_versions(db, set_row)
        assets: list[tuple[KnowledgeAsset, KnowledgeAssetVersion]]
        if projected is None:
            assets = []
            current_heads = db.execute(
                select(KnowledgeAsset, KnowledgeAssetVersion)
                .join(
                    KnowledgeAssetVersion,
                    (KnowledgeAssetVersion.asset_id == KnowledgeAsset.id)
                    & (KnowledgeAssetVersion.version_seq == KnowledgeAsset.current_version_seq),
                )
                .where(
                    KnowledgeAsset.knowledge_set_id == set_id,
                    KnowledgeAsset.kind == "question",
                    KnowledgeAsset.current_version_seq >= 1,
                )
                .order_by(KnowledgeAsset.created_at, KnowledgeAsset.id)
            ).all()
            for asset, version in current_heads:
                available_version = _manual_or_legacy_question_version(db, set_row, asset, version)
                if available_version is not None:
                    assets.append((asset, available_version))
        else:
            assets = projected
        for asset, version in assets:
            if asset.kind != "question":
                continue
            if not question_sources_readable(db, set_row, version):
                raise conflict(
                    "assessment_question_source_stale",
                    "A selected Question source is no longer authorized.",
                )
            try:
                QuestionContent.model_validate_json(version.content_json)
            except (ValidationError, ValueError):
                raise conflict(
                    "assessment_question_invalid",
                    "A selected Question version is not available for this activity.",
                ) from None
            selected.append((set_row.id, asset.id, set_row.authorization_epoch, version.id))
    return selected


def refresh_assessment_activity_questions(
    db: Session,
    actor: AuthContext,
    conversation_id: str,
    activity: AssessmentActivity,
    *,
    force_new_revision: bool = False,
    allow_empty: bool = False,
    selected_knowledge_set_ids: tuple[str, ...] | None = None,
) -> list[AssessmentActivityQuestion]:
    """Append a new immutable Question selection revision from the live canonical Markdown."""

    conversation, _provenance = _authorized_provenance(db, actor, conversation_id)
    if (
        conversation.entry_kind != "maya_team"
        or conversation.origin != "published_course_team"
        or conversation.publication_id != activity.publication_id
        or conversation.team_id != activity.team_id
        or conversation.team_version_id != activity.team_version_id
        or conversation.course_id != activity.course_id
    ):
        raise not_found()
    if selected_knowledge_set_ids is None:
        selection = resolve_chat_entry(
            db,
            actor,
            conversation.team_id,
            conversation.team_version_id,
            require_publication=True,
        )
        if (
            selection.publication_id != activity.publication_id
            or selection.course_id != activity.course_id
            or selection.team_id != activity.team_id
            or selection.team_version_id != activity.team_version_id
        ):
            raise not_found()
        set_ids = tuple(
            dict.fromkeys(
                tuple(
                    set_id
                    for member in selection.members
                    for set_id in member.own_knowledge_set_ids
                )
                + selection.shared_knowledge_set_ids
            )
        )
    else:
        # Knowledge-update callers validate the persisted Team execution grant
        # before passing the original conversation's exact frozen bindings.
        set_ids = tuple(dict.fromkeys(selected_knowledge_set_ids))
    questions = _selected_questions(db, set_ids)
    if not questions and not allow_empty:
        raise conflict(
            "assessment_questions_unavailable",
            "This assessment recipe has no current authorized Questions.",
        )

    current_rows = list(
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
    current_manifest = [
        (
            row.knowledge_set_id,
            row.asset_id,
            row.authorization_epoch,
            row.question_version_id,
            row.required,
        )
        for row in current_rows
    ]
    requested_manifest = [(*question, True) for question in questions]
    if current_manifest == requested_manifest and not force_new_revision:
        return current_rows

    new_revision = activity.question_selection_revision + 1
    question_manifest = [
        {
            "knowledge_set_id": set_id,
            "asset_id": asset_id,
            "authorization_epoch": authorization_epoch,
            "question_version_id": question_version_id,
            "required": True,
        }
        for set_id, asset_id, authorization_epoch, question_version_id in questions
    ]
    new_hash = _hash(_canonical(question_manifest))
    with db.begin_nested():
        updated = db.execute(
            update(AssessmentActivity)
            .where(
                AssessmentActivity.id == activity.id,
                AssessmentActivity.question_selection_revision
                == activity.question_selection_revision,
            )
            .values(
                question_selection_revision=new_revision,
                questions_hash=new_hash,
            )
            .execution_options(synchronize_session=False)
        )
        if getattr(updated, "rowcount", 0) != 1:
            raise conflict(
                "assessment_question_catalog_changed",
                "The Question catalog changed; retry the assessment action.",
            )
        for ordinal, (set_id, asset_id, authorization_epoch, question_version_id) in enumerate(
            questions
        ):
            db.add(
                AssessmentActivityQuestion(
                    id=str(uuid4()),
                    activity_id=activity.id,
                    selection_revision=new_revision,
                    knowledge_set_id=set_id,
                    asset_id=asset_id,
                    question_version_id=question_version_id,
                    authorization_epoch=authorization_epoch,
                    ordinal=ordinal,
                    required=True,
                )
            )
        db.flush()
    activity.question_selection_revision = new_revision
    activity.questions_hash = new_hash
    return list(
        db.scalars(
            select(AssessmentActivityQuestion)
            .where(
                AssessmentActivityQuestion.activity_id == activity.id,
                AssessmentActivityQuestion.selection_revision == new_revision,
            )
            .order_by(AssessmentActivityQuestion.ordinal)
        ).all()
    )


def ensure_assessment_activity(
    db: Session,
    actor: AuthContext,
    conversation_id: str,
) -> AssessmentActivity | None:
    """Lazily bind a formal activity only to an explicitly marked published recipe.

    The conversation, publication, Leader version, Team-owned Knowledge Set
    bindings, and current Question versions are all resolved on the server. The
    student request never chooses any of those identities.
    """

    conversation, _provenance = _authorized_provenance(db, actor, conversation_id)
    if (
        conversation.entry_kind != "maya_team"
        or conversation.origin != "published_course_team"
        or conversation.publication_id is None
        or conversation.team_id is None
        or conversation.team_version_id is None
        or conversation.withdrawn_at is not None
    ):
        return None

    membership = db.get(CourseMember, (conversation.course_id, str(actor.user.id)))
    if membership is None or actor.user.status != "active":
        raise not_found()
    if membership.role != "student":
        return None
    leader_row = db.scalar(
        select(TeamVersionMember).where(
            TeamVersionMember.team_version_id == conversation.team_version_id,
            TeamVersionMember.is_leader.is_(True),
        )
    )
    if leader_row is None:
        raise not_found()
    leader_version = db.get(AgentVersion, leader_row.agent_version_id)
    if leader_version is None:
        raise not_found()
    recipe_id = declared_recipe(leader_version.agent_md)
    if recipe_id is None:
        return None

    existing = db.scalar(
        select(AssessmentActivity).where(
            AssessmentActivity.publication_id == conversation.publication_id,
            AssessmentActivity.team_version_id == conversation.team_version_id,
            AssessmentActivity.recipe_id == recipe_id,
            AssessmentActivity.recipe_version_id == leader_version.id,
        )
    )
    if existing is not None:
        return existing

    selection = resolve_chat_entry(
        db,
        actor,
        conversation.team_id,
        conversation.team_version_id,
        require_publication=True,
    )
    if (
        selection.publication_id != conversation.publication_id
        or selection.course_id != conversation.course_id
        or selection.team_id != conversation.team_id
        or selection.team_version_id != conversation.team_version_id
    ):
        raise not_found()

    declared_roles: dict[str, tuple[str, str]] = {}
    for member in db.scalars(
        select(TeamVersionMember).where(
            TeamVersionMember.team_version_id == selection.team_version_id
        )
    ).all():
        version = db.get(AgentVersion, member.agent_version_id)
        if version is None or version.state != "published" or version.agent_id != member.agent_id:
            raise not_found()
        role = declared_assessment_role(version.agent_md)
        if role is None:
            continue
        if role in declared_roles:
            raise conflict(
                "assessment_executor_role_ambiguous",
                "The published Team must bind exactly one member to each assessment role.",
            )
        declared_roles[role] = (member.id, version.id)
    evaluator = declared_roles.get("evaluator")
    boundary = declared_roles.get("boundary_summarizer")
    if evaluator is None or boundary is None or evaluator[0] == boundary[0]:
        raise conflict(
            "assessment_executor_role_missing",
            "The published Team must bind separate evaluator and boundary summarizer members.",
        )

    set_ids = tuple(
        dict.fromkeys(
            tuple(set_id for member in selection.members for set_id in member.own_knowledge_set_ids)
            + selection.shared_knowledge_set_ids
        )
    )
    questions = _selected_questions(db, set_ids)
    if not questions:
        raise conflict(
            "assessment_questions_unavailable",
            "This assessment recipe has no current authorized Questions.",
        )

    activity_id = str(uuid4())
    manifest = [
        {
            "knowledge_set_id": set_id,
            "asset_id": asset_id,
            "authorization_epoch": authorization_epoch,
            "question_version_id": question_version_id,
            "required": True,
        }
        for set_id, asset_id, authorization_epoch, question_version_id in questions
    ]
    activity = AssessmentActivity(
        id=activity_id,
        course_id=conversation.course_id,
        team_id=conversation.team_id,
        team_version_id=conversation.team_version_id,
        publication_id=conversation.publication_id,
        recipe_id=recipe_id,
        recipe_version_id=leader_version.id,
        evaluator_team_member_id=evaluator[0],
        evaluator_agent_version_id=evaluator[1],
        boundary_team_member_id=boundary[0],
        boundary_agent_version_id=boundary[1],
        publisher_user_id=conversation.team_owner_user_id or "",
        questions_hash=_hash(_canonical(manifest)),
        question_selection_revision=1,
        created_at=datetime.now(UTC),
    )
    try:
        with db.begin_nested():
            db.add(activity)
            db.flush()
            for ordinal, (
                set_id,
                asset_id,
                authorization_epoch,
                question_version_id,
            ) in enumerate(questions):
                db.add(
                    AssessmentActivityQuestion(
                        id=str(uuid4()),
                        activity_id=activity.id,
                        selection_revision=1,
                        knowledge_set_id=set_id,
                        asset_id=asset_id,
                        question_version_id=question_version_id,
                        authorization_epoch=authorization_epoch,
                        ordinal=ordinal,
                        required=True,
                    )
                )
            db.flush()
    except IntegrityError:
        existing = db.scalar(
            select(AssessmentActivity).where(
                AssessmentActivity.publication_id == conversation.publication_id,
                AssessmentActivity.team_version_id == conversation.team_version_id,
                AssessmentActivity.recipe_id == recipe_id,
                AssessmentActivity.recipe_version_id == leader_version.id,
            )
        )
        if existing is None:
            raise
        return existing
    return activity


__all__ = [
    "SUPPORTED_RECIPE_ID",
    "current_question_version_for_asset",
    "declared_recipe",
    "ensure_assessment_activity",
    "refresh_assessment_activity_questions",
]
