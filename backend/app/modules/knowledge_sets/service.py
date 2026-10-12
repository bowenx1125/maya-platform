"""ACL, CAS and immutable-version operations for manual Knowledge Sets."""

from __future__ import annotations

import hashlib
import html
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast
from uuid import UUID, uuid4, uuid5

from pydantic import TypeAdapter
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.core.errors import PlatformError, invalid_state, not_found, stale_revision, unprocessable
from app.core.models import (
    Agent,
    AgentVersion,
    FileReference,
    Group,
    KnowledgeDocument,
    StoredFile,
)
from app.modules.auth.service import AuthContext
from app.modules.knowledge.files import FileBoundaryError
from app.modules.knowledge.markdown import MarkdownInputError, normalize_markdown
from app.modules.knowledge.services import (
    _agent_workspace_role,
    can_read_source,
    course_member_role,
    document_file_content,
    observes_private_agent,
    scoped_group_role_for_user,
    visible_agent,
)
from app.modules.knowledge_sets.models import (
    AgentKnowledgeSet,
    KnowledgeAsset,
    KnowledgeAssetVersion,
    KnowledgeAssetVersionSource,
    KnowledgeDocumentVersion,
    KnowledgeGenerationRun,
    KnowledgeGenerationSourceReceipt,
    KnowledgeSet,
    KnowledgeSetMarkdownVersion,
    KnowledgeSetSource,
)
from app.modules.knowledge_sets.schemas import (
    AssetCitation,
    AssetContent,
    AssetVersionFullDTO,
    AssetVersionStudentDTO,
    BrainformKnowledgeSummary,
    ConceptContent,
    CreateKnowledgeSetRequest,
    KnowledgeAssetFullDTO,
    KnowledgeAssetStudentDTO,
    KnowledgeGraph,
    KnowledgeGraphEdge,
    KnowledgeGraphNode,
    KnowledgeMarkdownDocument,
    KnowledgeSetDetail,
    KnowledgeSetRevocation,
    KnowledgeSetSourceDTO,
    KnowledgeSetSummary,
    QuestionContent,
    RegenerateKnowledgeResponse,
    Rubric,
    RubricCriterion,
    SaveKnowledgeMarkdownRequest,
    StudentAssetContent,
    StudentQuestionContent,
)
from app.modules.teams.models import Team, TeamVersion, TeamVersionSet

SetRole = Literal["owner", "student", "teacher"]


@dataclass(frozen=True)
class SetAccess:
    knowledge_set: KnowledgeSet
    role: SetRole

    @property
    def can_edit(self) -> bool:
        return self.role == "owner"


@dataclass(frozen=True)
class RuntimeKnowledgeProjection:
    canonical_markdown: str | None
    assets: tuple[dict[str, Any], ...]
    full_access: bool


def now_utc() -> datetime:
    return datetime.now(UTC)


def _uid(value: str) -> UUID:
    return UUID(value)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _begin_knowledge_write_transaction(db: Session) -> None:
    """Acquire SQLite's writer lock unless this Session already owns it."""

    if db.get_bind().dialect.name != "sqlite":
        return
    from app.modules.knowledge_sets.generation import _start_immediate

    connection = db.connection().connection.driver_connection
    if connection is None or not connection.in_transaction:
        _start_immediate(db)


def save_knowledge_markdown_version(
    db: Session,
    *,
    set_id: str,
    expected_version_seq: int,
    markdown: str,
    actor_user_id: str,
    origin: Literal["manual", "ai"],
    generation_run_id: str | None = None,
    generation_intent_seq: int | None = None,
    source_manifest_hash: str | None = None,
    generator_agent_version_id: str | None = None,
    asset_version_ids: list[str] | None = None,
    student_projection_markdown: str = "",
    invalidate_attempts: bool = True,
) -> KnowledgeSetMarkdownVersion:
    """Append one immutable Markdown version and atomically advance its Set head."""

    set_row = db.scalar(select(KnowledgeSet).where(KnowledgeSet.id == set_id).with_for_update())
    if set_row is None or set_row.deleted_at is not None or set_row.owner_user_id != actor_user_id:
        raise not_found()
    if set_row.current_markdown_version_seq != expected_version_seq:
        raise stale_revision(set_row.current_markdown_version_seq)
    if origin == "ai" and (
        generation_intent_seq is None
        or set_row.generation_intent_seq != generation_intent_seq
        or generation_run_id is None
    ):
        raise stale_revision(set_row.current_markdown_version_seq)

    markdown_hash = _sha256(markdown)
    if expected_version_seq > 0:
        current = db.scalar(
            select(KnowledgeSetMarkdownVersion).where(
                KnowledgeSetMarkdownVersion.knowledge_set_id == set_id,
                KnowledgeSetMarkdownVersion.version_seq == expected_version_seq,
            )
        )
        if current is None:
            raise invalid_state("The current Knowledge Markdown version is unavailable.")
        if origin == "manual" and current.content_hash == markdown_hash:
            return current

    next_seq = expected_version_seq + 1
    conditions = [
        KnowledgeSet.id == set_id,
        KnowledgeSet.current_markdown_version_seq == expected_version_seq,
    ]
    if origin == "ai":
        conditions.append(KnowledgeSet.generation_intent_seq == generation_intent_seq)
    advanced = db.execute(
        update(KnowledgeSet)
        .where(*conditions)
        .values(
            current_markdown_version_seq=next_seq,
            content_revision=KnowledgeSet.content_revision + 1,
            updated_at=now_utc(),
        )
        .execution_options(synchronize_session=False)
    )
    if getattr(advanced, "rowcount", 0) != 1:
        current_seq = db.scalar(
            select(KnowledgeSet.current_markdown_version_seq).where(KnowledgeSet.id == set_id)
        )
        raise stale_revision(current_seq)
    set_row.current_markdown_version_seq = next_seq
    set_row.content_revision += 1
    set_row.updated_at = now_utc()

    row = KnowledgeSetMarkdownVersion(
        id=str(uuid4()),
        knowledge_set_id=set_id,
        version_seq=next_seq,
        markdown=markdown,
        student_projection_markdown=student_projection_markdown,
        asset_version_ids_json=_canonical_json(asset_version_ids or []),
        content_hash=markdown_hash,
        origin=origin,
        generation_run_id=generation_run_id,
        generation_intent_seq=generation_intent_seq,
        source_manifest_hash=source_manifest_hash,
        created_by_user_id=actor_user_id,
        generator_agent_version_id=generator_agent_version_id,
        created_at=now_utc(),
    )
    db.add(row)
    db.flush()
    expected_version_ids = set(asset_version_ids or [])
    if expected_version_ids:
        available_version_ids = set(
            db.scalars(
                select(KnowledgeAssetVersion.id)
                .join(KnowledgeAsset, KnowledgeAsset.id == KnowledgeAssetVersion.asset_id)
                .where(
                    KnowledgeAsset.knowledge_set_id == set_id,
                    KnowledgeAssetVersion.id.in_(expected_version_ids),
                )
            ).all()
        )
        if available_version_ids != expected_version_ids:
            raise invalid_state("A projected Knowledge Asset version is unavailable.")
    if invalidate_attempts:
        from app.modules.learning.attempts import (
            invalidate_assessment_attempts_for_knowledge_update,
        )

        invalidate_assessment_attempts_for_knowledge_update(
            db,
            knowledge_set_id=set_id,
            actor_user_id=actor_user_id,
        )
    return row


def _clean_display_name(value: str) -> str:
    result = unicodedata.normalize("NFKC", value).strip()
    if not result or any(ord(character) < 0x20 for character in result):
        raise unprocessable("invalid_knowledge_set_name", "A Set name is required.")
    return result


def _set_role_for_user(db: Session, user_id: str, row: KnowledgeSet) -> SetRole | None:
    if row.deleted_at is not None:
        return None
    if course_member_role(db, user_id, row.course_id) is None:
        return None
    if row.ownership_scope == "personal":
        return "owner" if row.owner_user_id == user_id else None
    if row.group_id is None:
        return None
    group_role = scoped_group_role_for_user(db, user_id, row.group_id)
    if group_role is None:
        return None
    if row.owner_user_id == user_id and group_role == "student":
        return "owner"
    if row.visibility != "public":
        return None
    # A course Teacher is read-only; a group member sees a student projection.
    return cast(SetRole, group_role)


def _set_role(db: Session, context: AuthContext, row: KnowledgeSet) -> SetRole | None:
    return _set_role_for_user(db, context.user.id, row)


def _source_matches_current(
    db: Session,
    context: AuthContext | str,
    row: KnowledgeSetSource,
    *,
    role: SetRole,
    for_write: bool = False,
) -> bool:
    actor_user_id = context.user.id if isinstance(context, AuthContext) else context
    document = db.get(KnowledgeDocument, row.document_id)
    stored_file = db.get(StoredFile, row.stored_file_id)
    set_row = db.get(KnowledgeSet, row.knowledge_set_id)
    if document is None or stored_file is None or set_row is None:
        return False
    if (
        document.course_id
        != db.scalar(select(KnowledgeSet.course_id).where(KnowledgeSet.id == row.knowledge_set_id))
        or document.stored_file_id != row.stored_file_id
        or document.content_hash != row.source_content_hash
        or stored_file.sha256 != row.source_file_sha256
        or stored_file.state == "deleted"
    ):
        return False
    if (
        set_row.ownership_scope == "personal"
        and document.ownership_scope == "group"
        and document.group_id is not None
        and scoped_group_role_for_user(db, actor_user_id, document.group_id) != "student"
    ):
        # Course Teachers may read a Public Group source as a summary, but a
        # personal Set's bound reference remains tied to active Group access.
        return False
    if for_write or role != "owner":
        if (
            document.workspace_state != "active"
            or document.authorization_epoch != row.source_authorization_epoch
        ):
            return False
    return can_read_source(
        db,
        context,
        document,
        require_active=(for_write or role != "owner"),
    )


def _set_sources_readable(
    db: Session, context: AuthContext | str, row: KnowledgeSet, role: SetRole
) -> bool:
    if role == "owner":
        return True
    sources = db.scalars(
        select(KnowledgeSetSource).where(
            KnowledgeSetSource.knowledge_set_id == row.id,
            KnowledgeSetSource.is_active.is_(True),
        )
    ).all()
    return all(_source_matches_current(db, context, source, role=role) for source in sources)


def _access(db: Session, context: AuthContext, set_id: str) -> SetAccess:
    row = db.get(KnowledgeSet, set_id)
    if row is None:
        raise not_found()
    role = _set_role(db, context, row)
    if role is None or not _set_sources_readable(db, context, row, role):
        raise not_found()
    return SetAccess(row, role)


def _editable_access(db: Session, context: AuthContext, set_id: str) -> SetAccess:
    access = _access(db, context, set_id)
    if not access.can_edit:
        raise not_found()
    return access


def _active_sources(db: Session, set_id: str) -> list[KnowledgeSetSource]:
    return list(
        db.scalars(
            select(KnowledgeSetSource)
            .where(
                KnowledgeSetSource.knowledge_set_id == set_id,
                KnowledgeSetSource.is_active.is_(True),
            )
            .order_by(KnowledgeSetSource.order_index, KnowledgeSetSource.id)
        ).all()
    )


def _summary(
    db: Session, context: AuthContext, row: KnowledgeSet, *, can_edit: bool
) -> KnowledgeSetSummary:
    role = _set_role(db, context, row)
    generated_by_agent_id: str | None = None
    if can_edit:
        generated_by_agent_id = db.scalar(
            select(KnowledgeGenerationRun.agent_id)
            .where(
                KnowledgeGenerationRun.knowledge_set_id == row.id,
                KnowledgeGenerationRun.owner_user_id == context.user.id,
            )
            .order_by(KnowledgeGenerationRun.created_at.desc())
            .limit(1)
        )
    active_sources = _active_sources(db, row.id)
    source_count = sum(
        1
        for source in active_sources
        if can_edit
        or (role is not None and _source_matches_current(db, context, source, role=role))
    )
    asset_count = 0
    if role is not None:
        markdown_version = _current_markdown_version(db, row)
        if markdown_version is not None:
            asset_count = len(_markdown_asset_version_ids(markdown_version))
        else:
            assets = db.scalars(
                select(KnowledgeAsset).where(
                    KnowledgeAsset.knowledge_set_id == row.id,
                    KnowledgeAsset.current_version_seq >= 1,
                )
            ).all()
            for asset in assets:
                current_version = db.scalar(
                    select(KnowledgeAssetVersion).where(
                        KnowledgeAssetVersion.asset_id == asset.id,
                        KnowledgeAssetVersion.version_seq == asset.current_version_seq,
                    )
                )
                if current_version is not None and _asset_version_sources_readable(
                    db, context, row, role, current_version
                ):
                    asset_count += 1
    return KnowledgeSetSummary(
        id=_uid(row.id),
        owner_user_id=_uid(row.owner_user_id) if can_edit else None,
        generated_by_agent_id=(UUID(generated_by_agent_id) if generated_by_agent_id else None),
        course_id=_uid(row.course_id),
        group_id=_uid(row.group_id) if row.group_id else None,
        ownership_scope=row.ownership_scope,  # type: ignore[arg-type]
        visibility=row.visibility,  # type: ignore[arg-type]
        display_name=row.display_name,
        metadata_revision=row.metadata_revision if can_edit else None,
        content_revision=row.content_revision if can_edit else None,
        authorization_epoch=row.authorization_epoch if can_edit else None,
        source_count=source_count,
        asset_count=asset_count,
        can_edit=can_edit,
        created_at=row.created_at if can_edit else None,
        updated_at=row.updated_at if can_edit else None,
    )


def _source_dto(
    db: Session,
    context: AuthContext,
    set_row: KnowledgeSet,
    role: SetRole,
    source: KnowledgeSetSource,
) -> KnowledgeSetSourceDTO:
    available = _source_matches_current(db, context, source, role=role, for_write=True)
    if not available:
        return KnowledgeSetSourceDTO(
            id=_uid(source.id),
            document_id=None,
            source_filename=None,
            char_count=None,
            content_hash=None,
            authorization_epoch=None,
            order_index=source.order_index,
            is_active=source.is_active,
            available=False,
        )
    document = db.get(KnowledgeDocument, source.document_id)
    return KnowledgeSetSourceDTO(
        id=_uid(source.id),
        document_id=_uid(source.document_id),
        source_filename=source.source_filename,
        char_count=document.char_count if document is not None else 0,
        content_hash=source.source_content_hash,
        authorization_epoch=(source.source_authorization_epoch if role == "owner" else None),
        order_index=source.order_index,
        is_active=source.is_active,
        available=True,
    )


def list_knowledge_sets(
    db: Session, context: AuthContext, course_id: str
) -> list[KnowledgeSetSummary]:
    if course_member_role(db, context.user.id, course_id) is None:
        raise not_found()
    rows = db.scalars(
        select(KnowledgeSet)
        .where(KnowledgeSet.course_id == course_id, KnowledgeSet.deleted_at.is_(None))
        .order_by(KnowledgeSet.created_at, KnowledgeSet.id)
    ).all()
    result: list[KnowledgeSetSummary] = []
    for row in rows:
        role = _set_role(db, context, row)
        if role is not None and _set_sources_readable(db, context, row, role):
            result.append(_summary(db, context, row, can_edit=role == "owner"))
    return result


def _current_markdown_version(
    db: Session, set_row: KnowledgeSet
) -> KnowledgeSetMarkdownVersion | None:
    if set_row.current_markdown_version_seq < 1:
        return None
    return db.scalar(
        select(KnowledgeSetMarkdownVersion).where(
            KnowledgeSetMarkdownVersion.knowledge_set_id == set_row.id,
            KnowledgeSetMarkdownVersion.version_seq == set_row.current_markdown_version_seq,
        )
    )


def _markdown_asset_version_ids(version: KnowledgeSetMarkdownVersion) -> list[str]:
    try:
        values = json.loads(version.asset_version_ids_json)
    except (TypeError, ValueError):
        return []
    return (
        values
        if isinstance(values, list) and all(isinstance(value, str) for value in values)
        else []
    )


def _student_projection_is_available(
    db: Session,
    context: AuthContext | str,
    set_row: KnowledgeSet,
    version: KnowledgeSetMarkdownVersion,
    *,
    source_role: SetRole = "student",
) -> bool:
    """Require trusted structured provenance and current ACL for student Markdown."""

    if version.origin not in {"ai", "legacy", "manual"} or not version.student_projection_markdown:
        return False
    if not _student_markdown_has_body(version.student_projection_markdown):
        return False
    asset_version_ids = _markdown_asset_version_ids(version)
    if len(asset_version_ids) != len(set(asset_version_ids)):
        return False
    if not asset_version_ids:
        if version.origin != "manual" or version.source_manifest_hash is not None:
            return False
        # A hand-authored document with no structured source history can still
        # be safely projected. Sets with source history need asset provenance
        # or a generation receipt before derived text is visible to Students.
        return (
            db.scalar(
                select(KnowledgeSetSource.id)
                .where(KnowledgeSetSource.knowledge_set_id == set_row.id)
                .limit(1)
            )
            is None
        )
    versions = db.scalars(
        select(KnowledgeAssetVersion).where(KnowledgeAssetVersion.id.in_(asset_version_ids))
    ).all()
    if {asset_version.id for asset_version in versions} != set(asset_version_ids):
        return False
    for asset_version in versions:
        asset = db.get(KnowledgeAsset, asset_version.asset_id)
        if (
            asset is None
            or asset.knowledge_set_id != set_row.id
            or not _asset_version_sources_readable(db, context, set_row, source_role, asset_version)
        ):
            return False
    return True


def _student_markdown_has_body(markdown: str) -> bool:
    setext = re.compile(r"^\s{0,3}(?:=+|-+)\s*$")
    for line in markdown.splitlines():
        value = line.strip()
        if not value or re.match(r"^#{1,6}\s+", value) or setext.fullmatch(value):
            continue
        return True
    return False


def _markdown_sources_readable_to_teacher(
    db: Session,
    context: AuthContext | str,
    set_row: KnowledgeSet,
    version: KnowledgeSetMarkdownVersion,
) -> bool:
    """Gate full derived Markdown by the source ACLs recorded for its version."""

    asset_version_ids = _markdown_asset_version_ids(version)
    if len(asset_version_ids) != len(set(asset_version_ids)):
        return False
    if asset_version_ids:
        asset_versions = db.scalars(
            select(KnowledgeAssetVersion).where(KnowledgeAssetVersion.id.in_(asset_version_ids))
        ).all()
        if {item.id for item in asset_versions} != set(asset_version_ids):
            return False
        for asset_version in asset_versions:
            asset = db.get(KnowledgeAsset, asset_version.asset_id)
            if (
                asset is None
                or asset.knowledge_set_id != set_row.id
                or not _asset_version_sources_readable(
                    db,
                    context,
                    set_row,
                    "teacher",
                    asset_version,
                )
            ):
                return False

    if version.origin == "legacy":
        # Legacy Markdown is rendered from immutable structured versions. A
        # missing provenance map cannot prove that a course reader may receive
        # its full text after source access changes.
        return bool(asset_version_ids)
    if version.origin == "manual":
        if version.source_manifest_hash is None:
            has_source_history = db.scalar(
                select(KnowledgeSetSource.id)
                .where(KnowledgeSetSource.knowledge_set_id == set_row.id)
                .limit(1)
            )
            return has_source_history is None
        matching_runs = db.scalars(
            select(KnowledgeGenerationRun).where(
                KnowledgeGenerationRun.knowledge_set_id == set_row.id,
                KnowledgeGenerationRun.source_manifest_hash == version.source_manifest_hash,
            )
        ).all()
        return any(
            _generation_run_sources_readable(db, context, set_row, run) for run in matching_runs
        )
    if version.origin != "ai":
        return True
    if (
        version.generation_run_id is None
        or version.generation_intent_seq is None
        or version.source_manifest_hash is None
    ):
        return False

    run = db.get(KnowledgeGenerationRun, version.generation_run_id)
    if (
        run is None
        or run.knowledge_set_id != set_row.id
        or run.intent_generation != version.generation_intent_seq
        or run.source_manifest_hash != version.source_manifest_hash
    ):
        return False
    return _generation_run_sources_readable(db, context, set_row, run)


def _generation_run_sources_readable(
    db: Session,
    context: AuthContext | str,
    set_row: KnowledgeSet,
    run: KnowledgeGenerationRun,
) -> bool:
    if run.knowledge_set_id != set_row.id:
        return False
    try:
        manifest = json.loads(run.source_manifest_json)
    except (TypeError, ValueError):
        return False
    if not isinstance(manifest, list):
        return False
    receipts = db.scalars(
        select(KnowledgeGenerationSourceReceipt).where(
            KnowledgeGenerationSourceReceipt.run_id == run.id
        )
    ).all()

    def receipt_key(row: KnowledgeGenerationSourceReceipt) -> tuple[object, ...]:
        return (
            row.source_binding_id,
            row.document_id,
            row.stored_file_id,
            row.source_content_hash,
            row.source_file_sha256,
            row.source_authorization_epoch,
            row.source_index_revision,
        )

    expected: set[tuple[object, ...]] = set()
    for item in manifest:
        if not isinstance(item, dict):
            return False
        required = (
            item.get("binding_id"),
            item.get("document_id"),
            item.get("stored_file_id"),
            item.get("content_hash"),
            item.get("file_sha256"),
            item.get("authorization_epoch"),
            item.get("index_revision"),
        )
        if not all(value is not None for value in required):
            return False
        expected.add(required)
    if len(expected) != len(manifest) or {receipt_key(row) for row in receipts} != expected:
        return False

    for receipt in receipts:
        binding = db.get(KnowledgeSetSource, receipt.source_binding_id)
        if (
            binding is None
            or binding.knowledge_set_id != set_row.id
            or binding.document_id != receipt.document_id
            or not binding.is_active
            or not _source_matches_current(
                db,
                context,
                binding,
                role="teacher",
                for_write=False,
            )
        ):
            return False
    return True


def _latest_generation_for_set(db: Session, set_id: str) -> KnowledgeGenerationRun | None:
    return db.scalar(
        select(KnowledgeGenerationRun)
        .where(KnowledgeGenerationRun.knowledge_set_id == set_id)
        .order_by(KnowledgeGenerationRun.created_at.desc(), KnowledgeGenerationRun.id.desc())
        .limit(1)
    )


def knowledge_set_has_generation_history(db: Session, set_row: KnowledgeSet) -> bool:
    return (
        set_row.generation_intent_seq > 0
        or db.scalar(
            select(KnowledgeGenerationRun.id)
            .where(KnowledgeGenerationRun.knowledge_set_id == set_row.id)
            .limit(1)
        )
        is not None
    )


def _visible_source_agents(db: Session, context: AuthContext, set_row: KnowledgeSet) -> list[Agent]:
    candidates = db.scalars(
        select(AgentKnowledgeSet.agent_id)
        .where(AgentKnowledgeSet.knowledge_set_id == set_row.id)
        .order_by(AgentKnowledgeSet.order_index, AgentKnowledgeSet.agent_id)
    ).all()
    visible: list[Agent] = []
    for agent_id in dict.fromkeys(candidates):
        try:
            scoped = visible_agent(db, context, agent_id)
        except PlatformError as error:
            if error.status_code == 404:
                continue
            raise
        if scoped.agent.course_id == set_row.course_id:
            visible.append(scoped.agent)
    return visible


def _visible_source_agent(db: Session, context: AuthContext, set_row: KnowledgeSet) -> Agent:
    agents = _visible_source_agents(db, context, set_row)
    if agents:
        return agents[0]
    raise not_found()


def _current_asset_versions(
    db: Session, set_row: KnowledgeSet
) -> list[tuple[KnowledgeAsset, KnowledgeAssetVersion]]:
    rows = db.execute(
        select(KnowledgeAsset, KnowledgeAssetVersion)
        .join(
            KnowledgeAssetVersion,
            (KnowledgeAssetVersion.asset_id == KnowledgeAsset.id)
            & (KnowledgeAssetVersion.version_seq == KnowledgeAsset.current_version_seq),
        )
        .where(
            KnowledgeAsset.knowledge_set_id == set_row.id,
            KnowledgeAsset.current_version_seq >= 1,
        )
        .order_by(KnowledgeAsset.created_at, KnowledgeAsset.id)
    ).all()
    return [(asset, version) for asset, version in rows]


def _markdown_from_current_assets(
    set_row: KnowledgeSet,
    versions: list[tuple[KnowledgeAsset, KnowledgeAssetVersion]],
) -> tuple[str, list[str]] | None:
    """Render the same Question Markdown Brainform already edits.

    A hand-written question bank has to use that shape or a later save cannot
    keep the questions as assessment content.
    """

    questions: list[QuestionContent] = []
    version_ids: list[str] = []
    for asset, version in versions:
        if asset.kind != "question":
            return None
        try:
            content = QuestionContent.model_validate_json(version.content_json)
        except ValueError:
            return None
        if not content.rubric.criteria:
            return None
        questions.append(content)
        version_ids.append(version.id)
    if not questions:
        return None
    blocks: list[str] = []
    for index, content in enumerate(questions, start=1):
        block = f"### Question {index}\n\n{content.prompt}"
        block += "\n\n#### Rubric\n\n" + "\n".join(
            f"- **{criterion.label}** ({criterion.points:g}): {criterion.guidance}"
            for criterion in content.rubric.criteria
        )
        if content.rubric.total_points is not None:
            block += f"\n\nTotal: {content.rubric.total_points:g} points"
        if content.reference_answer is not None:
            block += f"\n\n#### Reference answer\n\n{content.reference_answer}"
        blocks.append(block)
    markdown = f"# {set_row.display_name}\n\n## Questions\n\n" + "\n\n".join(blocks)
    return markdown, version_ids


def _promote_manual_asset_markdown(
    db: Session, set_row: KnowledgeSet, actor_user_id: str
) -> KnowledgeSetMarkdownVersion | None:
    """Give a question bank its Brainform document without treating it as a new edit.

    The assets are already the canonical questions. Opening them for review
    must not look like a teacher changed the bank.
    """

    if set_row.current_markdown_version_seq > 0 or _latest_generation_for_set(db, set_row.id):
        return _current_markdown_version(db, set_row)
    rendered = _markdown_from_current_assets(set_row, _current_asset_versions(db, set_row))
    if rendered is None:
        return None
    markdown, version_ids = rendered
    _begin_knowledge_write_transaction(db)
    return save_knowledge_markdown_version(
        db,
        set_id=set_row.id,
        expected_version_seq=0,
        markdown=markdown,
        actor_user_id=actor_user_id,
        origin="manual",
        asset_version_ids=version_ids,
        student_projection_markdown=_student_safe_markdown(markdown, None),
        invalidate_attempts=False,
    )


def _visible_team_knowledge_labels(
    db: Session, context: AuthContext, set_row: KnowledgeSet
) -> list[str]:
    names = db.scalars(
        select(Team.display_name)
        .join(
            TeamVersion,
            (TeamVersion.team_id == Team.id)
            & (TeamVersion.version_seq == Team.current_version_seq),
        )
        .join(
            TeamVersionSet,
            (TeamVersionSet.team_version_id == TeamVersion.id)
            & (TeamVersionSet.knowledge_set_id == set_row.id),
        )
        .where(
            Team.deleted_at.is_(None),
            Team.course_id == set_row.course_id,
            Team.current_version_seq >= 1,
            or_(Team.owner_user_id == context.user.id, Team.visibility == "public"),
        )
        .order_by(Team.created_at, Team.id)
    ).all()
    return list(dict.fromkeys(names))


def list_brainform_knowledge(
    db: Session, context: AuthContext, course_id: str
) -> list[BrainformKnowledgeSummary]:
    """List readable Knowledge, including a Team's shared question bank.

    An Agent binding is one consumer. A Team share is another. A question bank
    that was written as assets still becomes the Brainform document so it can
    be reviewed before a Team checks it.
    """

    summaries = list_knowledge_sets(db, context, course_id)
    candidates: list[tuple[int, BrainformKnowledgeSummary]] = []
    for summary in summaries:
        set_row = db.get(KnowledgeSet, str(summary.id))
        if set_row is None:
            continue
        role = _set_role(db, context, set_row)
        # A Teacher's own Brainform holds no student material; a group's
        # public Knowledge is read during an Accounts visit to that group.
        if role is None or role == "teacher":
            continue
        run = _latest_generation_for_set(db, set_row.id)
        if role == "owner" and run is None and set_row.current_markdown_version_seq == 0:
            _promote_manual_asset_markdown(db, set_row, context.user.id)
        markdown_version = _current_markdown_version(db, set_row)
        if markdown_version is None and run is None:
            continue
        source_agents = _visible_source_agents(db, context, set_row)
        team_labels = [] if source_agents else _visible_team_knowledge_labels(db, context, set_row)
        if not source_agents and not team_labels:
            continue
        generation_state = run.state if run is not None else None
        safe_error_code = run.safe_error_code if run is not None and summary.can_edit else None
        if run is not None and run.state in {"pending", "running"}:
            from app.modules.knowledge_sets.generation import _current_generation_authorized

            if not _current_generation_authorized(db, run):
                generation_state = "blocked"
                safe_error_code = "authorization_revoked" if summary.can_edit else None
        content_hash = None
        if markdown_version is not None:
            if role in {"owner", "teacher"}:
                content_hash = markdown_version.content_hash
            elif _student_projection_is_available(db, context, set_row, markdown_version):
                content_hash = _sha256(markdown_version.student_projection_markdown)
        consumers: list[tuple[str | None, str]] = [
            (source_agent.id, source_agent.name) for source_agent in source_agents
        ] or [(None, label) for label in team_labels]
        for agent_id, label in consumers:
            generation_job_id = None
            run_agent = db.get(Agent, run.agent_id) if run is not None else None
            run_agent_version = (
                db.get(AgentVersion, run.agent_version_id) if run is not None else None
            )
            if (
                agent_id is not None
                and run is not None
                and run_agent is not None
                and run_agent_version is not None
                and run_agent_version.agent_id == run.agent_id
                and summary.can_edit
                and run.owner_user_id == context.user.id
                and run.course_id == course_id
                and course_member_role(db, context.user.id, course_id) == "teacher"
                and run_agent.course_id == course_id
                and run_agent.owner_user_id == context.user.id
                and _agent_workspace_role(db, context.user.id, run_agent) == "owner"
            ):
                generation_job_id = _uid(run.job_id)
            row = BrainformKnowledgeSummary(
                agent_id=_uid(agent_id) if agent_id is not None else None,
                canonical_set_id=summary.id,
                source_agent_display_name=label,
                knowledge_display_name=summary.display_name,
                generation_job_id=generation_job_id,
                can_read=True,
                can_edit=summary.can_edit,
                version_seq=markdown_version.version_seq if markdown_version is not None else None,
                content_hash=content_hash,
                generation_state=cast(Any, generation_state),
                safe_error_code=safe_error_code,
            )
            # Keep every readable consumer; the generator sorts first only
            # within the Set it originally generated.
            priority = 0 if run is not None and run.agent_id == agent_id else 1
            candidates.append((priority, row))
    candidates.sort(
        key=lambda entry: (
            entry[0],
            str(entry[1].agent_id),
            entry[1].source_agent_display_name,
            str(entry[1].canonical_set_id),
        )
    )
    seen_relations: set[tuple[str, str, str]] = set()
    result: list[BrainformKnowledgeSummary] = []
    for _priority, row in candidates:
        relation = (
            str(row.canonical_set_id),
            str(row.agent_id),
            row.source_agent_display_name,
        )
        if relation in seen_relations:
            continue
        seen_relations.add(relation)
        result.append(row)
    return result


def get_brainform_markdown(
    db: Session, context: AuthContext, set_id: str
) -> KnowledgeMarkdownDocument:
    access = _access(db, context, set_id)
    if access.role == "owner" and _latest_generation_for_set(db, access.knowledge_set.id) is None:
        _promote_manual_asset_markdown(db, access.knowledge_set, context.user.id)
    version = _current_markdown_version(db, access.knowledge_set)
    if version is None:
        raise not_found()
    try:
        agent = _visible_source_agent(db, context, access.knowledge_set)
        consumer_agent_id: UUID | None = _uid(agent.id)
        consumer_label = agent.name
    except PlatformError as error:
        if error.status_code != 404:
            raise
        labels = _visible_team_knowledge_labels(db, context, access.knowledge_set)
        if not labels:
            raise not_found() from error
        consumer_agent_id = None
        consumer_label = labels[0]
    if access.role == "teacher" and not _markdown_sources_readable_to_teacher(
        db,
        context,
        access.knowledge_set,
        version,
    ):
        raise not_found()
    full = access.role in {"owner", "teacher"}
    projection_available = _student_projection_is_available(
        db, context, access.knowledge_set, version
    )
    markdown = (
        version.markdown
        if full
        else version.student_projection_markdown
        if projection_available
        else ""
    )
    return KnowledgeMarkdownDocument(
        audience="full" if full else "student",
        agent_id=consumer_agent_id,
        canonical_set_id=_uid(set_id),
        source_agent_display_name=consumer_label,
        knowledge_display_name=access.knowledge_set.display_name,
        version_seq=version.version_seq,
        content_hash=version.content_hash if full else _sha256(markdown),
        markdown=markdown,
        projection_available=full or projection_available,
        can_read=True,
        can_edit=access.can_edit,
        created_at=version.created_at,
    )


def runtime_knowledge_projection(
    db: Session,
    set_id: str,
    actor_user_id: str,
    *,
    execution_owner_user_id: str | None = None,
) -> RuntimeKnowledgeProjection:
    """Load current canonical content under direct read or a frozen Team grant.

    Team callers pass the owner of the already-validated frozen selection. That
    identity only rechecks the resource grant; the returned audience still
    follows the current actor's direct read role and otherwise uses the trusted
    student projection.
    """

    set_row = db.get(KnowledgeSet, set_id)
    if set_row is None or set_row.deleted_at is not None:
        raise not_found()
    actor_role = _set_role_for_user(db, actor_user_id, set_row)
    source_user_id = actor_user_id
    source_role = actor_role
    if source_role is None and execution_owner_user_id is not None:
        source_user_id = execution_owner_user_id
        source_role = _set_role_for_user(db, source_user_id, set_row)
    if source_role is None or not _set_sources_readable(db, source_user_id, set_row, source_role):
        raise not_found()

    full_access = actor_role in {"owner", "teacher"}
    markdown_version = _current_markdown_version(db, set_row)
    if markdown_version is not None:
        if full_access:
            if actor_role == "teacher" and not _markdown_sources_readable_to_teacher(
                db, actor_user_id, set_row, markdown_version
            ):
                raise not_found()
            markdown = markdown_version.markdown
            content_is_full = True
        elif _student_projection_is_available(
            db,
            source_user_id,
            set_row,
            markdown_version,
            source_role=source_role,
        ):
            markdown = markdown_version.student_projection_markdown
            content_is_full = False
        else:
            # A present canonical version is authoritative even when its
            # student-safe projection cannot be proven. Never fall back to
            # independently advanced Asset heads in that case.
            return RuntimeKnowledgeProjection(canonical_markdown="", assets=(), full_access=False)

        version_ids = _markdown_asset_version_ids(markdown_version)
        if len(version_ids) != len(set(version_ids)):
            if not content_is_full:
                return RuntimeKnowledgeProjection(
                    canonical_markdown="", assets=(), full_access=False
                )
            version_ids = []
        versions = (
            db.scalars(
                select(KnowledgeAssetVersion).where(KnowledgeAssetVersion.id.in_(version_ids))
            ).all()
            if version_ids
            else []
        )
        by_id = {version.id: version for version in versions}
        if set(by_id) != set(version_ids):
            if not content_is_full:
                return RuntimeKnowledgeProjection(
                    canonical_markdown="", assets=(), full_access=False
                )
            version_ids = []
        assets: list[dict[str, Any]] = []
        for version_id in version_ids:
            asset_version = by_id[version_id]
            asset = db.get(KnowledgeAsset, asset_version.asset_id)
            if asset is None or asset.knowledge_set_id != set_row.id:
                if not content_is_full:
                    return RuntimeKnowledgeProjection(
                        canonical_markdown="", assets=(), full_access=False
                    )
                continue
            content = json.loads(asset_version.content_json)
            if not content_is_full:
                content = _student_content(content).model_dump(mode="json")
            assets.append(
                {
                    "asset_id": asset.id,
                    "version_id": asset_version.id,
                    "content": content,
                }
            )
        return RuntimeKnowledgeProjection(
            canonical_markdown=markdown,
            assets=tuple(assets),
            full_access=full_access,
        )

    has_generation_history = knowledge_set_has_generation_history(db, set_row)
    current_assets = db.execute(
        select(KnowledgeAsset, KnowledgeAssetVersion)
        .join(
            KnowledgeAssetVersion,
            (KnowledgeAssetVersion.asset_id == KnowledgeAsset.id)
            & (KnowledgeAssetVersion.version_seq == KnowledgeAsset.current_version_seq),
        )
        .where(KnowledgeAsset.knowledge_set_id == set_row.id)
        .order_by(KnowledgeAsset.created_at, KnowledgeAsset.id)
    )
    assets = []
    for asset, current_version in current_assets:
        fallback_version: KnowledgeAssetVersion | None = current_version
        if has_generation_history and (
            current_version.generation_job_id is not None or current_version.origin == "ai"
        ):
            # Per-item AI versions stay durable for history, but do not become
            # runtime content until a complete canonical Markdown head points
            # at them. Preserve an earlier manually authored head if present.
            fallback_version = db.scalar(
                select(KnowledgeAssetVersion)
                .where(
                    KnowledgeAssetVersion.asset_id == asset.id,
                    KnowledgeAssetVersion.generation_job_id.is_(None),
                    KnowledgeAssetVersion.origin.in_(("manual", "legacy")),
                )
                .order_by(KnowledgeAssetVersion.version_seq.desc())
                .limit(1)
            )
            if fallback_version is None:
                continue
        if fallback_version is None:
            continue
        if not _asset_version_sources_readable(
            db, source_user_id, set_row, source_role, fallback_version
        ):
            raise not_found()
        content = json.loads(fallback_version.content_json)
        if not full_access:
            content = _student_content(content).model_dump(mode="json")
        assets.append(
            {
                "asset_id": asset.id,
                "version_id": fallback_version.id,
                "content": content,
            }
        )
    return RuntimeKnowledgeProjection(
        canonical_markdown=None,
        assets=tuple(assets),
        full_access=full_access,
    )


_QUESTION_HEADING = re.compile(r"^(?:Question\s+|Q)(\d+)\s*$", re.IGNORECASE)
_RUBRIC_CRITERION = re.compile(
    r"^-\s+\*\*(?P<label>.+?)\*\*\s+\((?P<points>(?:\d+(?:\.\d*)?|\.\d+))\):\s*(?P<guidance>.*)$"
)
_RUBRIC_TOTAL = re.compile(
    r"^Total:\s*(?P<points>(?:\d+(?:\.\d*)?|\.\d+))\s+points?\.?$",
    re.IGNORECASE,
)


def _markdown_headings(markdown: str) -> list[tuple[int, int, str]]:
    """Return ATX and Setext headings outside fenced code blocks."""

    fence: tuple[str, int] | None = None
    visible_lines: list[str | None] = []
    for line in markdown.splitlines():
        fence_match = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if fence is not None:
            visible_lines.append(None)
            if fence_match and fence_match.group(1)[0] == fence[0]:
                marker = fence_match.group(1)
                if len(marker) >= fence[1] and line[fence_match.end() :].strip() == "":
                    fence = None
            continue
        if fence_match:
            visible_lines.append(None)
            marker = fence_match.group(1)
            fence = (marker[0], len(marker))
            continue
        visible_lines.append(line)

    headings: list[tuple[int, int, str]] = []
    setext = re.compile(r"^\s{0,3}(=+|-+)\s*$")
    atx = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
    for index, visible_line in enumerate(visible_lines):
        if visible_line is None:
            continue
        heading = atx.match(visible_line)
        if heading:
            headings.append((index, len(heading.group(1)), heading.group(2).strip()))
        underline = setext.fullmatch(visible_line)
        if underline is None or index == 0:
            continue
        title = visible_lines[index - 1]
        if title is None or not title.strip() or atx.fullmatch(title):
            continue
        headings.append((index - 1, 1 if underline.group(1).startswith("=") else 2, title.strip()))
    headings.sort(key=lambda item: item[0])
    return headings


def _parse_markdown_questions(markdown: str) -> list[QuestionContent] | None:
    """Parse only the explicit generated Question/Rubric Markdown shape.

    Unrecognized or incomplete sections remain lossless document text but do
    not become active assessment content.
    """

    lines = markdown.splitlines()
    headings = _markdown_headings(markdown)
    question_sections = [
        heading for heading in headings if heading[1] == 2 and heading[2].casefold() == "questions"
    ]
    if not question_sections:
        return []
    if len(question_sections) != 1:
        return None
    section_index = question_sections[0][0]
    section_end = next(
        (index for index, level, _title in headings if index > section_index and level == 2),
        len(lines),
    )
    section_headings = [
        (index, level, title)
        for index, level, title in headings
        if section_index < index < section_end
    ]
    question_headings = [(index, title) for index, level, title in section_headings if level == 3]
    if not question_headings:
        return []
    numbered: list[tuple[int, int]] = []
    for index, title in question_headings:
        match = _QUESTION_HEADING.fullmatch(title)
        if match is None:
            return None
        numbered.append((index, int(match.group(1))))
    if [number for _index, number in numbered] != list(range(1, len(numbered) + 1)):
        return None

    questions: list[QuestionContent] = []
    for item_index, (heading_index, _number) in enumerate(numbered):
        block_end = numbered[item_index + 1][0] if item_index + 1 < len(numbered) else section_end
        block_headings = [
            (index, level, title)
            for index, level, title in section_headings
            if heading_index < index < block_end
        ]
        nested_headings = [
            (index, level, title.casefold()) for index, level, title in block_headings
        ]
        if any(
            level != 4 or title not in {"rubric", "reference answer"}
            for _index, level, title in nested_headings
        ):
            return None
        subsection_headings = [(index, title) for index, _level, title in nested_headings]
        rubric_heads = [index for index, title in subsection_headings if title == "rubric"]
        answer_heads = [
            index for index, title in subsection_headings if title == "reference answer"
        ]
        if len(rubric_heads) != 1 or len(answer_heads) > 1:
            return None
        prompt_end = min([*rubric_heads, *answer_heads], default=block_end)
        prompt = "\n".join(lines[heading_index + 1 : prompt_end]).strip()
        if not prompt:
            return None

        rubric_start = rubric_heads[0] + 1
        rubric_end = next(
            (index for index, _title in subsection_headings if index > rubric_heads[0]),
            block_end,
        )
        criteria: list[RubricCriterion] = []
        total_points: float | None = None
        for line in lines[rubric_start:rubric_end]:
            value = line.strip()
            if not value:
                continue
            total = _RUBRIC_TOTAL.fullmatch(value)
            if total is not None:
                if total_points is not None:
                    return None
                total_points = float(total.group("points"))
                continue
            criterion = _RUBRIC_CRITERION.fullmatch(value)
            if criterion is None or not criterion.group("label").strip():
                return None
            criteria.append(
                RubricCriterion(
                    label=criterion.group("label").strip(),
                    points=float(criterion.group("points")),
                    guidance=criterion.group("guidance").strip(),
                )
            )
        if not criteria or (
            total_points is not None
            and abs(total_points - sum(item.points for item in criteria)) > 0.000001
        ):
            return None

        reference_answer: str | None = None
        if answer_heads:
            answer_start = answer_heads[0] + 1
            answer_end = next(
                (index for index, _title in subsection_headings if index > answer_heads[0]),
                block_end,
            )
            reference_answer = "\n".join(lines[answer_start:answer_end]).strip() or None
        try:
            questions.append(
                QuestionContent(
                    kind="question",
                    prompt=prompt,
                    reference_answer=reference_answer,
                    rubric=Rubric(criteria=criteria, total_points=total_points),
                )
            )
        except ValueError:
            return None
    return questions


def _current_question_projection(
    db: Session,
    set_row: KnowledgeSet,
    markdown_version: KnowledgeSetMarkdownVersion | None,
) -> list[tuple[KnowledgeAsset, KnowledgeAssetVersion, QuestionContent]]:
    if markdown_version is None:
        return []
    current: list[tuple[KnowledgeAsset, KnowledgeAssetVersion, QuestionContent]] = []
    for version_id in _markdown_asset_version_ids(markdown_version):
        version = db.get(KnowledgeAssetVersion, version_id)
        asset = db.get(KnowledgeAsset, version.asset_id) if version is not None else None
        if (
            version is None
            or asset is None
            or asset.knowledge_set_id != set_row.id
            or asset.kind != "question"
        ):
            continue
        try:
            content = QuestionContent.model_validate_json(version.content_json)
        except ValueError:
            continue
        current.append((asset, version, content))
    return current


def _question_version_references(
    db: Session,
    set_row: KnowledgeSet,
    version: KnowledgeAssetVersion,
) -> list[tuple[KnowledgeSetSource, AssetCitation]]:
    references: list[tuple[KnowledgeSetSource, AssetCitation]] = []
    for source in _version_sources(db, version.id):
        binding = db.get(KnowledgeSetSource, source.source_binding_id)
        if binding is None or binding.knowledge_set_id != set_row.id:
            continue
        try:
            citation = AssetCitation.model_validate(
                {
                    "source_binding_id": source.source_binding_id,
                    "location": json.loads(source.source_location_json),
                }
            )
        except (TypeError, ValueError):
            continue
        references.append((binding, citation))
    return references


_DANGEROUS_HTML_OPEN = re.compile(
    r"<\s*(?P<tag>script|style|iframe|object|embed|svg|math|form|textarea|button)\b",
    re.IGNORECASE,
)
_STUDENT_HIDDEN_HEADING_TITLES = frozenset(
    {"rubric", "reference answer", "private answer", "model answer", "answer key"}
)


def _student_safe_markdown(markdown: str, parsed_questions: list[QuestionContent] | None) -> str:
    """Keep authored notes while removing answer/rubric and unsafe HTML sections."""

    lines = markdown.splitlines()
    headings = _markdown_headings(markdown)
    removed_lines: set[int] = set()

    def section_end(start: int, level: int) -> int:
        return next(
            (
                index
                for index, next_level, _title in headings
                if index > start and next_level <= level
            ),
            len(lines),
        )

    def remove_range(start: int, end: int) -> None:
        removed_lines.update(range(start, end))

    def is_sensitive_heading(title: str) -> bool:
        return title.casefold().strip() in _STUDENT_HIDDEN_HEADING_TITLES

    def question_section_end(start: int) -> int:
        for index, level, title in headings:
            if index <= start:
                continue
            if level == 2:
                return index
            if level == 1 and not is_sensitive_heading(title):
                return index
        return len(lines)

    question_sections = [
        (index, question_section_end(index))
        for index, level, title in headings
        if level == 2 and title.casefold() == "questions"
    ]
    sensitive_headings = [
        (index, level)
        for index, level, title in headings
        if level >= 1 and is_sensitive_heading(title)
    ]

    if parsed_questions is None:
        for start, end in question_sections:
            remove_range(start, end)
        for index, level in sensitive_headings:
            if any(start <= index < end for start, end in question_sections):
                continue
            remove_range(index, section_end(index, level))
        if not question_sections:
            for index, level, _title in headings:
                if level != 2:
                    continue
                end = section_end(index, level)
                descendants = [
                    (child_level, child_title)
                    for child_index, child_level, child_title in headings
                    if index < child_index < end
                ]
                has_sensitive = any(
                    is_sensitive_heading(child_title) for _level, child_title in descendants
                )
                has_question = any(child_level == 3 for child_level, _child_title in descendants)
                if has_sensitive and has_question:
                    remove_range(index, end)
    elif parsed_questions:
        for index, level in sensitive_headings:
            if any(start <= index < end for start, end in question_sections):
                remove_range(index, section_end(index, level))
    else:
        for start, end in question_sections:
            question_descendants = [
                (index, level, title) for index, level, title in headings if start < index < end
            ]
            question_like = any(
                _QUESTION_HEADING.fullmatch(title) is not None or is_sensitive_heading(title)
                for _index, _level, title in question_descendants
            )
            if question_like:
                remove_range(start, end)
        if not question_sections:
            for index, level, _title in headings:
                if level != 2:
                    continue
                end = section_end(index, level)
                descendants = [
                    (child_level, child_title)
                    for child_index, child_level, child_title in headings
                    if index < child_index < end
                ]
                has_sensitive = any(
                    is_sensitive_heading(child_title) for _level, child_title in descendants
                )
                has_question = any(child_level == 3 for child_level, _child_title in descendants)
                if has_sensitive and has_question:
                    remove_range(index, end)

    sanitized_lines: list[str] = []
    fence: tuple[str, int] | None = None
    hidden_html_tag: str | None = None
    for line_index, line in enumerate(lines):
        if line_index in removed_lines:
            sanitized_lines.append("")
            continue
        fence_match = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if fence is not None:
            sanitized_lines.append(line)
            if (
                fence_match
                and fence_match.group(1)[0] == fence[0]
                and len(fence_match.group(1)) >= fence[1]
                and line[fence_match.end() :].strip() == ""
            ):
                fence = None
            continue
        if fence_match:
            sanitized_lines.append(line)
            marker = fence_match.group(1)
            fence = (marker[0], len(marker))
            continue

        remaining = line
        visible = ""
        while remaining:
            if hidden_html_tag is not None:
                closing = re.search(
                    rf"</\s*{re.escape(hidden_html_tag)}\s*>", remaining, re.IGNORECASE
                )
                if closing is None:
                    remaining = ""
                    break
                remaining = remaining[closing.end() :]
                hidden_html_tag = None
                continue
            opening = _DANGEROUS_HTML_OPEN.search(remaining)
            if opening is None:
                visible += remaining
                break
            visible += remaining[: opening.start()]
            hidden_html_tag = opening.group("tag").casefold()
            closing = re.search(
                rf"</\s*{re.escape(hidden_html_tag)}\s*>",
                remaining[opening.end() :],
                re.IGNORECASE,
            )
            if closing is None:
                remaining = ""
            else:
                remaining = remaining[opening.end() + closing.end() :]
                hidden_html_tag = None
        sanitized_lines.append(html.escape(visible, quote=False))

    result = "\n".join(sanitized_lines).strip()
    return result if _student_markdown_has_body(result) else ""


def _without_question_section(markdown: str) -> str:
    lines = markdown.splitlines()
    headings = _markdown_headings(markdown)
    question_sections = [
        index for index, level, title in headings if level == 2 and title.casefold() == "questions"
    ]
    if len(question_sections) != 1:
        return markdown.strip()
    start = question_sections[0]
    end = next(
        (index for index, level, _title in headings if index > start and level == 2),
        len(lines),
    )
    return "\n".join([*lines[:start], *lines[end:]]).strip()


def _replace_question_section(markdown: str, replacement: str) -> str:
    lines = markdown.splitlines()
    headings = _markdown_headings(markdown)
    question_sections = [
        index for index, level, title in headings if level == 2 and title.casefold() == "questions"
    ]
    if len(question_sections) > 1:
        return replacement
    if not question_sections:
        if not replacement:
            return markdown.strip()
        return "\n\n".join(part for part in (markdown.strip(), replacement) if part)
    start = question_sections[0]
    end = next(
        (index for index, level, _title in headings if index > start and level == 2),
        len(lines),
    )
    updated = [*lines[:start], *replacement.splitlines(), *lines[end:]]
    return "\n".join(updated).strip()


def _save_manual_question_projection(
    db: Session,
    *,
    set_row: KnowledgeSet,
    current_markdown: KnowledgeSetMarkdownVersion | None,
    markdown: str,
    actor_user_id: str,
) -> tuple[list[str], str]:
    parsed = _parse_markdown_questions(markdown)
    if parsed is None:
        return [], _student_safe_markdown(markdown, parsed)
    if not parsed:
        return [], _student_safe_markdown(markdown, parsed)

    previous = _current_question_projection(db, set_row, current_markdown)
    version_ids: list[str] = []
    projected_questions: list[QuestionContent] = []
    for index, parsed_question in enumerate(parsed):
        asset: KnowledgeAsset
        references: list[tuple[KnowledgeSetSource, AssetCitation]] = []
        if index < len(previous):
            asset, previous_version, previous_content = previous[index]
            if previous_content.prompt == parsed_question.prompt:
                parsed_question = parsed_question.model_copy(
                    update={
                        "concept_ids": previous_content.concept_ids,
                        "citations": previous_content.citations,
                    }
                )
                references = _question_version_references(db, set_row, previous_version)
            expected_seq = asset.current_version_seq
            next_seq = expected_seq + 1
            advanced = db.execute(
                update(KnowledgeAsset)
                .where(
                    KnowledgeAsset.id == asset.id,
                    KnowledgeAsset.knowledge_set_id == set_row.id,
                    KnowledgeAsset.current_version_seq == expected_seq,
                )
                .values(current_version_seq=next_seq, updated_at=now_utc())
                .execution_options(synchronize_session=False)
            )
            if getattr(advanced, "rowcount", 0) != 1:
                current_seq = db.scalar(
                    select(KnowledgeAsset.current_version_seq).where(KnowledgeAsset.id == asset.id)
                )
                raise stale_revision(current_seq)
            asset.current_version_seq = next_seq
            asset.updated_at = now_utc()
        else:
            timestamp = now_utc()
            asset = KnowledgeAsset(
                id=str(uuid4()),
                knowledge_set_id=set_row.id,
                kind="question",
                generation_lineage_key=None,
                current_version_seq=1,
                created_by_user_id=actor_user_id,
                created_at=timestamp,
                updated_at=timestamp,
            )
            db.add(asset)
            db.flush()
            next_seq = 1

        content_json = _canonical_json(parsed_question.model_dump(mode="json"))
        version = _store_version(
            db,
            actor_user_id,
            set_row,
            asset,
            content_json,
            references,
            next_seq,
            origin="manual",
        )
        version_ids.append(version.id)
        projected_questions.append(parsed_question)
    return version_ids, _student_safe_markdown(markdown, parsed)


def save_brainform_markdown(
    db: Session,
    context: AuthContext,
    set_id: str,
    request: SaveKnowledgeMarkdownRequest,
) -> KnowledgeMarkdownDocument:
    _begin_knowledge_write_transaction(db)
    access = _editable_access(db, context, set_id)
    set_row = access.knowledge_set
    current_markdown = _current_markdown_version(db, set_row)
    if current_markdown is not None and current_markdown.content_hash == _sha256(request.markdown):
        save_knowledge_markdown_version(
            db,
            set_id=set_id,
            expected_version_seq=request.expected_version_seq,
            markdown=request.markdown,
            actor_user_id=context.user.id,
            origin="manual",
        )
        return get_brainform_markdown(db, context, set_id)

    question_asset_version_ids, student_projection = _save_manual_question_projection(
        db,
        set_row=set_row,
        current_markdown=current_markdown,
        markdown=request.markdown,
        actor_user_id=context.user.id,
    )
    asset_version_ids = question_asset_version_ids
    if current_markdown is not None and _without_question_section(
        current_markdown.markdown
    ) == _without_question_section(request.markdown):
        previous_asset_version_ids = _markdown_asset_version_ids(current_markdown)
        previous_versions = db.scalars(
            select(KnowledgeAssetVersion).where(
                KnowledgeAssetVersion.id.in_(previous_asset_version_ids)
            )
        ).all()
        previous_by_id = {version.id: version for version in previous_versions}
        non_question_version_ids = [
            version_id
            for version_id in previous_asset_version_ids
            if (version := previous_by_id.get(version_id)) is not None
            and (asset := db.get(KnowledgeAsset, version.asset_id)) is not None
            and asset.kind != "question"
        ]
        asset_version_ids = non_question_version_ids + question_asset_version_ids
        student_projection = _replace_question_section(
            current_markdown.student_projection_markdown,
            student_projection,
        )
    save_knowledge_markdown_version(
        db,
        set_id=set_id,
        expected_version_seq=request.expected_version_seq,
        markdown=request.markdown,
        actor_user_id=context.user.id,
        origin="manual",
        source_manifest_hash=(
            current_markdown.source_manifest_hash if current_markdown is not None else None
        ),
        asset_version_ids=asset_version_ids,
        student_projection_markdown=student_projection,
    )
    return get_brainform_markdown(db, context, set_id)


def enqueue_brainform_regeneration(
    db: Session,
    context: AuthContext,
    set_id: str,
    action_id: str,
) -> RegenerateKnowledgeResponse:
    from app.modules.knowledge_sets.generation import (
        enqueue_generation_for_existing_set,
    )

    # Idempotency claims are committed separately. Begin the domain writer
    # transaction before the first access read so concurrent business-action
    # aliases are serialized with their GenerationRun and intent writes.
    _begin_knowledge_write_transaction(db)
    _editable_access(db, context, set_id)

    queued = enqueue_generation_for_existing_set(
        db,
        set_id=set_id,
        owner_user_id=context.user.id,
        action_id=action_id,
        resume_blocked_unconfirmed=True,
    )
    return RegenerateKnowledgeResponse(
        action_id=UUID(queued.action_id or queued.run.action_id),
        agent_id=_uid(queued.run.agent_id),
        canonical_set_id=_uid(queued.run.knowledge_set_id),
        run_id=_uid(queued.run.id),
        job_id=_uid(queued.job.id),
        state=cast(Any, queued.run.state),
    )


def create_knowledge_set(
    db: Session, context: AuthContext, course_id: str, request: CreateKnowledgeSetRequest
) -> KnowledgeSetDetail:
    if course_member_role(db, context.user.id, course_id) is None:
        raise not_found()
    group_id = str(request.group_id) if request.group_id else None
    if group_id:
        group_course = db.scalar(select(Group.course_id).where(Group.id == group_id))
        if (
            group_course != course_id
            or scoped_group_role_for_user(db, context.user.id, group_id) != "student"
        ):
            raise not_found()
    timestamp = now_utc()
    row = KnowledgeSet(
        id=str(uuid4()),
        owner_user_id=context.user.id,
        course_id=course_id,
        group_id=group_id,
        ownership_scope="group" if group_id else "personal",
        visibility="private",
        display_name=_clean_display_name(request.display_name),
        metadata_revision=0,
        content_revision=0,
        authorization_epoch=0,
        created_at=timestamp,
        updated_at=timestamp,
    )
    db.add(row)
    db.flush()
    return KnowledgeSetDetail(
        **_summary(db, context, row, can_edit=True).model_dump(),
        sources=[],
    )


def get_knowledge_set(db: Session, context: AuthContext, set_id: str) -> KnowledgeSetDetail:
    access = _access(db, context, set_id)
    sources = [
        _source_dto(db, context, access.knowledge_set, access.role, row)
        for row in _active_sources(db, set_id)
    ]
    return KnowledgeSetDetail(
        **_summary(db, context, access.knowledge_set, can_edit=access.can_edit).model_dump(),
        sources=sources,
    )


def _current_metadata_revision(db: Session, set_id: str) -> int | None:
    return db.scalar(select(KnowledgeSet.metadata_revision).where(KnowledgeSet.id == set_id))


def update_knowledge_set(
    db: Session,
    context: AuthContext,
    set_id: str,
    *,
    expected_metadata_revision: int,
    display_name: str | None,
    visibility: Literal["private", "public"] | None,
) -> KnowledgeSetDetail:
    access = _editable_access(db, context, set_id)
    row = access.knowledge_set
    if row.metadata_revision != expected_metadata_revision:
        raise stale_revision(_current_metadata_revision(db, set_id))
    updates: dict[str, Any] = {}
    if display_name is not None:
        updates["display_name"] = _clean_display_name(display_name)
    if visibility is not None and visibility != row.visibility:
        if row.ownership_scope == "personal" and visibility == "public":
            raise unprocessable(
                "personal_set_owner_only",
                "A personal Set stays owner-only until an explicit sharing grant exists.",
            )
        if visibility == "public":
            for source in _active_sources(db, set_id):
                document = db.get(KnowledgeDocument, source.document_id)
                if (
                    document is None
                    or document.ownership_scope != "group"
                    or document.group_id != row.group_id
                    or document.visibility != "public"
                    or not _source_matches_current(
                        db, context, source, role="owner", for_write=True
                    )
                ):
                    raise unprocessable(
                        "private_source_for_public_set",
                        "A Public group Set can include only current Public sources in its group.",
                    )
        updates["visibility"] = visibility
        updates["authorization_epoch"] = row.authorization_epoch + 1
    if not updates or all(getattr(row, key) == value for key, value in updates.items()):
        return get_knowledge_set(db, context, set_id)
    result = db.execute(
        update(KnowledgeSet)
        .where(
            KnowledgeSet.id == set_id,
            KnowledgeSet.metadata_revision == expected_metadata_revision,
            KnowledgeSet.deleted_at.is_(None),
        )
        .values(
            **updates,
            metadata_revision=expected_metadata_revision + 1,
            updated_at=now_utc(),
        )
        .execution_options(synchronize_session=False)
    )
    if getattr(result, "rowcount", 0) != 1:
        raise stale_revision(_current_metadata_revision(db, set_id))
    for key, value in updates.items():
        setattr(row, key, value)
    row.metadata_revision = expected_metadata_revision + 1
    row.updated_at = now_utc()
    return get_knowledge_set(db, context, set_id)


def delete_knowledge_set(
    db: Session,
    context: AuthContext,
    set_id: str,
    *,
    expected_metadata_revision: int,
    expected_content_revision: int,
) -> KnowledgeSetRevocation:
    access = _editable_access(db, context, set_id)
    row = access.knowledge_set
    if (
        row.metadata_revision != expected_metadata_revision
        or row.content_revision != expected_content_revision
    ):
        current_revision = (
            row.metadata_revision
            if row.metadata_revision != expected_metadata_revision
            else row.content_revision
        )
        raise stale_revision(current_revision)
    revoked_at = now_utc()
    next_metadata_revision = expected_metadata_revision + 1
    next_content_revision = expected_content_revision + 1
    next_authorization_epoch = row.authorization_epoch + 1
    result = db.execute(
        update(KnowledgeSet)
        .where(
            KnowledgeSet.id == set_id,
            KnowledgeSet.owner_user_id == context.user.id,
            KnowledgeSet.metadata_revision == expected_metadata_revision,
            KnowledgeSet.content_revision == expected_content_revision,
            KnowledgeSet.deleted_at.is_(None),
        )
        .values(
            metadata_revision=next_metadata_revision,
            content_revision=next_content_revision,
            authorization_epoch=next_authorization_epoch,
            deleted_at=revoked_at,
            updated_at=revoked_at,
        )
        .execution_options(synchronize_session=False)
    )
    if getattr(result, "rowcount", 0) != 1:
        raise stale_revision(_current_metadata_revision(db, set_id))
    return KnowledgeSetRevocation(
        id=_uid(set_id),
        metadata_revision=next_metadata_revision,
        content_revision=next_content_revision,
        authorization_epoch=next_authorization_epoch,
        revoked_at=revoked_at,
    )


def replay_knowledge_set_revocation(
    db: Session,
    context: AuthContext,
    receipt: KnowledgeSetRevocation,
) -> KnowledgeSetRevocation:
    row = db.get(KnowledgeSet, str(receipt.id))
    if (
        row is None
        or row.deleted_at is None
        or row.owner_user_id != context.user.id
        or course_member_role(db, context.user.id, row.course_id) is None
        or (
            row.ownership_scope == "group"
            and (
                row.group_id is None
                or scoped_group_role_for_user(db, context.user.id, row.group_id) != "student"
            )
        )
    ):
        raise not_found()
    return receipt


def _can_bind_document_to_set(
    db: Session, context: AuthContext, row: KnowledgeSet, document: KnowledgeDocument
) -> bool:
    if (
        document.workspace_state != "active"
        or document.course_id != row.course_id
        or not can_read_source(db, context, document)
    ):
        return False
    if document.ownership_scope == "personal":
        if document.owner_user_id != context.user.id or row.owner_user_id != context.user.id:
            return False
        if row.visibility == "public":
            return False
        return True
    if document.group_id is None:
        return False
    if scoped_group_role_for_user(db, context.user.id, document.group_id) != "student":
        return False
    if row.group_id is not None and document.group_id != row.group_id:
        return False
    if document.owner_user_id != context.user.id and document.visibility != "public":
        return False
    if row.visibility == "public" and (
        row.group_id is None or document.group_id != row.group_id or document.visibility != "public"
    ):
        return False
    return True


def _source_snapshot_matches(
    row: KnowledgeSetSource, document: KnowledgeDocument, stored_file: StoredFile
) -> bool:
    return (
        document.workspace_state == "active"
        and document.stored_file_id == row.stored_file_id
        and document.content_hash == row.source_content_hash
        and stored_file.sha256 == row.source_file_sha256
        and document.authorization_epoch == row.source_authorization_epoch
    )


def _advance_set_content(
    db: Session,
    row: KnowledgeSet,
    expected_revision: int,
    *,
    authorization_changed: bool = False,
) -> None:
    result = db.execute(
        update(KnowledgeSet)
        .where(
            KnowledgeSet.id == row.id,
            KnowledgeSet.content_revision == expected_revision,
            KnowledgeSet.deleted_at.is_(None),
        )
        .values(
            content_revision=expected_revision + 1,
            authorization_epoch=(
                row.authorization_epoch + 1 if authorization_changed else row.authorization_epoch
            ),
            updated_at=now_utc(),
        )
        .execution_options(synchronize_session=False)
    )
    if getattr(result, "rowcount", 0) != 1:
        current = db.scalar(select(KnowledgeSet.content_revision).where(KnowledgeSet.id == row.id))
        raise stale_revision(current)
    row.content_revision = expected_revision + 1
    if authorization_changed:
        row.authorization_epoch += 1
    row.updated_at = now_utc()


def _enqueue_source_binding_generation(
    db: Session,
    context: AuthContext,
    set_row: KnowledgeSet,
    *,
    allow_empty_blocked: bool,
) -> str | None:
    has_generation_relation = db.scalar(
        select(KnowledgeGenerationRun.id)
        .where(KnowledgeGenerationRun.knowledge_set_id == set_row.id)
        .limit(1)
    )
    if has_generation_relation is None:
        return None
    from app.modules.knowledge_sets.generation import enqueue_generation_for_existing_set

    action_id = str(
        uuid5(
            UUID("efdf85a2-3c5f-4f52-8f52-b4dd45e22d90"),
            f"binding:{set_row.id}:{set_row.content_revision}",
        )
    )
    try:
        queued = enqueue_generation_for_existing_set(
            db,
            set_id=set_row.id,
            owner_user_id=context.user.id,
            action_id=action_id,
            allow_empty_blocked=allow_empty_blocked,
        )
    except PlatformError as error:
        if error.status_code == 404:
            # The source edit remains valid even if an old generator relation
            # has since lost its own authorization.
            return None
        raise
    return queued.run.id


def replace_knowledge_set_sources(
    db: Session,
    context: AuthContext,
    set_id: str,
    *,
    expected_content_revision: int,
    source_document_ids: list[UUID],
    enqueued_generation_run_ids: list[str] | None = None,
) -> KnowledgeSetDetail:
    access = _editable_access(db, context, set_id)
    row = access.knowledge_set
    if row.content_revision != expected_content_revision:
        raise stale_revision(row.content_revision)
    source_ids = [str(value) for value in source_document_ids]
    if len(source_ids) != len(set(source_ids)):
        raise unprocessable("duplicate_knowledge_set_source", "A source can be selected only once.")
    documents = [db.get(KnowledgeDocument, document_id) for document_id in source_ids]
    if any(document is None for document in documents):
        raise not_found()
    typed_documents = [document for document in documents if document is not None]
    for document in typed_documents:
        if not _can_bind_document_to_set(db, context, row, document):
            raise not_found()
    if row.visibility == "public" and any(
        document.ownership_scope != "group"
        or document.group_id != row.group_id
        or document.visibility != "public"
        for document in typed_documents
    ):
        raise unprocessable(
            "private_source_for_public_set",
            "A Public group Set can include only Public sources from its group.",
        )

    current = _active_sources(db, set_id)
    same = len(current) == len(typed_documents) and all(
        binding.document_id == document.id
        and binding.stored_file_id == document.stored_file_id
        and binding.source_content_hash == document.content_hash
        and binding.source_authorization_epoch == document.authorization_epoch
        and binding.order_index == index
        for index, (binding, document) in enumerate(zip(current, typed_documents, strict=False))
    )
    if same:
        return get_knowledge_set(db, context, set_id)

    files = {
        row.id: row
        for row in db.scalars(
            select(StoredFile).where(StoredFile.id.in_([d.stored_file_id for d in typed_documents]))
        ).all()
    }
    for document in typed_documents:
        stored_file = files.get(document.stored_file_id)
        if stored_file is None or stored_file.state != "active":
            raise not_found()

    _advance_set_content(db, row, expected_content_revision)
    requested_ids = set(source_ids)
    for binding in current:
        if binding.document_id not in requested_ids:
            binding.is_active = False
    timestamp = now_utc()
    active_by_doc = {binding.document_id: binding for binding in current}
    for index, document in enumerate(typed_documents):
        stored_file = files[document.stored_file_id]
        existing = active_by_doc.get(document.id)
        if existing is not None and _source_snapshot_matches(existing, document, stored_file):
            existing.order_index = index
            continue
        if existing is not None:
            existing.is_active = False
            # The partial active-source index is immediate. Persist the old
            # binding inactive before inserting its refreshed snapshot row.
            db.flush()
        binding = KnowledgeSetSource(
            id=str(uuid4()),
            knowledge_set_id=set_id,
            document_id=document.id,
            stored_file_id=stored_file.id,
            source_content_hash=document.content_hash,
            source_file_sha256=stored_file.sha256,
            source_authorization_epoch=document.authorization_epoch,
            source_index_revision=document.index_revision,
            source_filename=document.source_filename,
            order_index=index,
            is_active=True,
            created_by_user_id=context.user.id,
            created_at=timestamp,
        )
        db.add(binding)
        db.flush()
        db.add(
            FileReference(
                id=str(uuid4()),
                stored_file_id=stored_file.id,
                owner_type="knowledge_set_source",
                owner_id=binding.id,
                purpose="source",
                created_at=timestamp,
            )
        )
    db.flush()
    run_id = _enqueue_source_binding_generation(db, context, row, allow_empty_blocked=True)
    if run_id is not None and enqueued_generation_run_ids is not None:
        enqueued_generation_run_ids.append(run_id)
    return get_knowledge_set(db, context, set_id)


def remove_knowledge_set_source(
    db: Session,
    context: AuthContext,
    set_id: str,
    binding_id: str,
    *,
    expected_content_revision: int,
    enqueued_generation_run_ids: list[str] | None = None,
) -> KnowledgeSetDetail:
    access = _editable_access(db, context, set_id)
    row = access.knowledge_set
    if row.content_revision != expected_content_revision:
        raise stale_revision(row.content_revision)
    binding = db.get(KnowledgeSetSource, binding_id)
    if binding is None or binding.knowledge_set_id != set_id:
        raise not_found()
    if binding.is_active:
        _advance_set_content(db, row, expected_content_revision)
        binding.is_active = False
        db.flush()
        run_id = _enqueue_source_binding_generation(db, context, row, allow_empty_blocked=True)
        if run_id is not None and enqueued_generation_run_ids is not None:
            enqueued_generation_run_ids.append(run_id)
    return get_knowledge_set(db, context, set_id)


def _version_sources(db: Session, version_id: str) -> list[KnowledgeAssetVersionSource]:
    return list(
        db.scalars(
            select(KnowledgeAssetVersionSource)
            .where(KnowledgeAssetVersionSource.asset_version_id == version_id)
            .order_by(KnowledgeAssetVersionSource.created_at, KnowledgeAssetVersionSource.id)
        ).all()
    )


def _asset_version_sources_readable(
    db: Session,
    context: AuthContext | str,
    set_row: KnowledgeSet,
    role: SetRole,
    version: KnowledgeAssetVersion,
) -> bool:
    if role != "owner" and version.set_authorization_epoch != set_row.authorization_epoch:
        return False
    for reference in _version_sources(db, version.id):
        binding = db.get(KnowledgeSetSource, reference.source_binding_id)
        if binding is None or binding.knowledge_set_id != set_row.id:
            return False
        if role != "owner" and not binding.is_active:
            return False
        if binding.document_id != reference.document_id:
            return False
        historical = db.scalar(
            select(KnowledgeDocumentVersion).where(
                KnowledgeDocumentVersion.document_id == reference.document_id,
                KnowledgeDocumentVersion.stored_file_id == reference.stored_file_id,
                KnowledgeDocumentVersion.content_hash == reference.source_content_hash,
                KnowledgeDocumentVersion.file_sha256 == reference.source_file_sha256,
            )
        )
        if historical is None:
            # Older isolated databases may not have run the history migration;
            # accept only a byte-for-byte match to the current source head.
            # Authorization epochs belong to the live ACL checks below, not to
            # the immutable identity of the historical content bytes.
            document = db.get(KnowledgeDocument, reference.document_id)
            stored_file = db.get(StoredFile, reference.stored_file_id)
            if (
                document is None
                or stored_file is None
                or document.stored_file_id != reference.stored_file_id
                or document.content_hash != reference.source_content_hash
                or stored_file.sha256 != reference.source_file_sha256
            ):
                return False
        document = db.get(KnowledgeDocument, reference.document_id)
        if document is None:
            return False
        if role == "owner":
            actor_id = context.user.id if isinstance(context, AuthContext) else context
            if (
                set_row.ownership_scope == "personal"
                and document.ownership_scope == "group"
                and document.group_id is not None
                and scoped_group_role_for_user(db, actor_id, document.group_id) != "student"
            ) or not can_read_source(db, context, document, require_active=False):
                return False
        elif not _source_matches_current(db, context, binding, role=role, for_write=False):
            return False
    return True


def _validated_content(
    db: Session,
    context: AuthContext | str,
    set_row: KnowledgeSet,
    role: SetRole,
    content: AssetContent,
    *,
    data_root: Path,
    current_asset_id: str | None = None,
    for_write: bool,
) -> tuple[str, list[tuple[KnowledgeSetSource, AssetCitation]]]:
    if current_asset_id is not None and content.kind == "concept":
        concept = content
        if current_asset_id in {str(value) for value in concept.prerequisite_ids}:
            raise unprocessable("self_prerequisite", "A Concept cannot depend on itself.")
    references: list[tuple[KnowledgeSetSource, AssetCitation]] = []
    seen_source_location: set[tuple[str, str]] = set()
    for citation in content.citations:
        binding = db.get(KnowledgeSetSource, str(citation.source_binding_id))
        if binding is None or binding.knowledge_set_id != set_row.id or not binding.is_active:
            raise unprocessable(
                "knowledge_source_not_bound",
                "Every citation must reference a current source bound to this Set.",
            )
        if not _source_matches_current(
            db,
            context,
            binding,
            role=role,
            for_write=for_write,
        ):
            raise unprocessable(
                "knowledge_source_access_changed",
                "A cited source is no longer current and authorized.",
            )
        document = db.get(KnowledgeDocument, binding.document_id)
        if document is None:
            raise not_found()
        location = citation.location
        if location.section_path or location.paragraph_index is not None:
            raise unprocessable(
                "knowledge_source_location_unverified",
                "Section paths and paragraph indexes are not supported as verified locations.",
            )
        if (location.start_offset is not None and location.start_offset > document.char_count) or (
            location.end_offset is not None and location.end_offset > document.char_count
        ):
            raise unprocessable(
                "knowledge_source_location_invalid",
                "A source location is outside the selected source version.",
            )
        if location.excerpt_hash is not None:
            if (
                location.start_offset is None
                or location.end_offset is None
                or location.end_offset <= location.start_offset
            ):
                raise unprocessable(
                    "knowledge_source_excerpt_unverifiable",
                    "An excerpt hash requires a non-empty half-open source offset range.",
                )
            stored_file = db.get(StoredFile, binding.stored_file_id)
            if stored_file is None:
                raise not_found()
            try:
                source_bytes = document_file_content(data_root, document)
                normalized = normalize_markdown(document.source_filename, source_bytes)
            except (FileBoundaryError, MarkdownInputError, OSError):
                raise unprocessable(
                    "knowledge_source_excerpt_unverifiable",
                    "The selected source version could not be verified.",
                ) from None
            if (
                hashlib.sha256(source_bytes).hexdigest() != stored_file.sha256
                or normalized.char_count != document.char_count
                or normalized.content_hash != document.content_hash
            ):
                raise unprocessable(
                    "knowledge_source_excerpt_unverifiable",
                    "The selected source version could not be verified.",
                )
            excerpt = normalized.normalized[location.start_offset : location.end_offset]
            if hashlib.sha256(excerpt.encode("utf-8")).hexdigest() != location.excerpt_hash:
                raise unprocessable(
                    "knowledge_source_excerpt_mismatch",
                    "The excerpt hash does not match the selected source range.",
                )
        location_key = _canonical_json(location.model_dump(mode="json"))
        identity = (binding.id, location_key)
        if identity not in seen_source_location:
            references.append((binding, citation))
            seen_source_location.add(identity)

    concept_ids: list[str] = []
    if isinstance(content, ConceptContent):
        concept_ids = [str(value) for value in content.prerequisite_ids]
    elif isinstance(content, QuestionContent):
        concept_ids = [str(value) for value in content.concept_ids]
    if len(concept_ids) != len(set(concept_ids)):
        raise unprocessable("duplicate_concept_reference", "A Concept can be referenced only once.")
    if concept_ids:
        matches = db.scalars(
            select(KnowledgeAsset).where(
                KnowledgeAsset.id.in_(concept_ids),
                KnowledgeAsset.knowledge_set_id == set_row.id,
                KnowledgeAsset.kind == "concept",
                KnowledgeAsset.current_version_seq >= 1,
            )
        ).all()
        if len(matches) != len(concept_ids):
            raise unprocessable(
                "knowledge_concept_not_found",
                "Concept references must identify current Concepts in this Set.",
            )
        for asset in matches:
            current_version = db.scalar(
                select(KnowledgeAssetVersion).where(
                    KnowledgeAssetVersion.asset_id == asset.id,
                    KnowledgeAssetVersion.version_seq == asset.current_version_seq,
                )
            )
            if current_version is None or not _asset_version_sources_readable(
                db, context, set_row, role, current_version
            ):
                raise unprocessable(
                    "knowledge_concept_not_available",
                    "A referenced Concept is not currently available in this scope.",
                )
    return _canonical_json(content.model_dump(mode="json")), references


def _store_version(
    db: Session,
    actor_user_id: str,
    set_row: KnowledgeSet,
    asset: KnowledgeAsset,
    content_json: str,
    references: list[tuple[KnowledgeSetSource, AssetCitation]],
    version_seq: int,
    *,
    origin: Literal["manual", "ai"] = "manual",
    generator_agent_version_id: str | None = None,
    generation_job_id: str | None = None,
) -> KnowledgeAssetVersion:
    timestamp = now_utc()
    source_canonical = _canonical_json(
        [
            {
                "binding_id": binding.id,
                "document_id": binding.document_id,
                "stored_file_id": binding.stored_file_id,
                "content_hash": binding.source_content_hash,
                "file_sha256": binding.source_file_sha256,
                "authorization_epoch": binding.source_authorization_epoch,
                "location": citation.location.model_dump(mode="json"),
            }
            for binding, citation in references
        ]
    )
    version = KnowledgeAssetVersion(
        id=str(uuid4()),
        asset_id=asset.id,
        version_seq=version_seq,
        content_json=content_json,
        content_hash=_sha256(content_json),
        source_dependency_hash=_sha256(source_canonical) if references else None,
        dependency_authorization_epoch=(set_row.authorization_epoch if references else None),
        set_authorization_epoch=set_row.authorization_epoch,
        origin=origin,
        created_by_user_id=actor_user_id,
        generator_agent_version_id=generator_agent_version_id,
        generation_job_id=generation_job_id,
        created_at=timestamp,
    )
    db.add(version)
    db.flush()
    for binding, citation in references:
        location_json = _canonical_json(citation.location.model_dump(mode="json"))
        relation_id = str(uuid4())
        db.add(
            KnowledgeAssetVersionSource(
                id=relation_id,
                asset_version_id=version.id,
                source_binding_id=binding.id,
                document_id=binding.document_id,
                stored_file_id=binding.stored_file_id,
                source_content_hash=binding.source_content_hash,
                source_file_sha256=binding.source_file_sha256,
                source_authorization_epoch=binding.source_authorization_epoch,
                source_location_json=location_json,
                source_location_hash=_sha256(location_json),
                created_at=timestamp,
            )
        )
        db.add(
            FileReference(
                id=str(uuid4()),
                stored_file_id=binding.stored_file_id,
                owner_type="knowledge_asset_version_source",
                owner_id=relation_id,
                purpose="source",
                created_at=timestamp,
            )
        )
    db.flush()
    return version


def save_generated_knowledge_asset(
    db: Session,
    *,
    actor_user_id: str,
    set_id: str,
    generation_lineage_key: str,
    expected_asset_version_seq: int | None,
    content: AssetContent,
    generator_agent_version_id: str,
    generation_job_id: str,
    data_root: Path,
) -> tuple[KnowledgeAsset, KnowledgeAssetVersion]:
    """Save one generated item using K1's source validation and content CAS."""

    set_row = db.scalar(select(KnowledgeSet).where(KnowledgeSet.id == set_id).with_for_update())
    if (
        set_row is None
        or set_row.deleted_at is not None
        or set_row.owner_user_id != actor_user_id
        or set_row.ownership_scope != "personal"
        or len(generation_lineage_key) != 64
    ):
        raise not_found()
    content_json, references = _validated_content(
        db,
        actor_user_id,
        set_row,
        "owner",
        content,
        data_root=data_root,
        for_write=True,
    )
    asset = db.scalar(
        select(KnowledgeAsset)
        .where(
            KnowledgeAsset.knowledge_set_id == set_row.id,
            KnowledgeAsset.generation_lineage_key == generation_lineage_key,
        )
        .with_for_update()
    )
    if expected_asset_version_seq is None:
        if asset is not None:
            raise stale_revision(asset.current_version_seq)
        _advance_set_content(db, set_row, set_row.content_revision)
        timestamp = now_utc()
        asset = KnowledgeAsset(
            id=str(uuid4()),
            knowledge_set_id=set_row.id,
            kind=content.kind,
            generation_lineage_key=generation_lineage_key,
            current_version_seq=1,
            created_by_user_id=actor_user_id,
            created_at=timestamp,
            updated_at=timestamp,
        )
        db.add(asset)
        db.flush()
        version_seq = 1
    else:
        if asset is None or asset.current_version_seq != expected_asset_version_seq:
            raise stale_revision(asset.current_version_seq if asset is not None else None)
        if asset.kind != content.kind:
            raise unprocessable(
                "knowledge_asset_kind_immutable",
                "A generated Asset keeps its original kind.",
            )
        current_version = db.scalar(
            select(KnowledgeAssetVersion).where(
                KnowledgeAssetVersion.asset_id == asset.id,
                KnowledgeAssetVersion.version_seq == expected_asset_version_seq,
            )
        )
        if current_version is None:
            raise stale_revision(asset.current_version_seq)
        _advance_set_content(db, set_row, set_row.content_revision)
        next_seq = expected_asset_version_seq + 1
        result = db.execute(
            update(KnowledgeAsset)
            .where(
                KnowledgeAsset.id == asset.id,
                KnowledgeAsset.knowledge_set_id == set_row.id,
                KnowledgeAsset.current_version_seq == expected_asset_version_seq,
            )
            .values(current_version_seq=next_seq, updated_at=now_utc())
            .execution_options(synchronize_session=False)
        )
        if getattr(result, "rowcount", 0) != 1:
            raise stale_revision(
                db.scalar(
                    select(KnowledgeAsset.current_version_seq).where(KnowledgeAsset.id == asset.id)
                )
            )
        asset.current_version_seq = next_seq
        asset.updated_at = now_utc()
        version_seq = next_seq
    version = _store_version(
        db,
        actor_user_id,
        set_row,
        asset,
        content_json,
        references,
        version_seq,
        origin="ai",
        generator_agent_version_id=generator_agent_version_id,
        generation_job_id=generation_job_id,
    )
    return asset, version


def _full_version_dto(
    version: KnowledgeAssetVersion, *, expose_version_seq: bool = True
) -> AssetVersionFullDTO:
    payload = json.loads(version.content_json)
    return AssetVersionFullDTO(
        id=_uid(version.id),
        asset_id=_uid(version.asset_id),
        version_seq=version.version_seq if expose_version_seq else None,
        content=payload,
        content_hash=version.content_hash,
        created_by_user_id=_uid(version.created_by_user_id),
        created_at=version.created_at,
    )


def _student_content(payload: dict[str, Any]) -> StudentAssetContent:
    if payload.get("kind") == "question":
        full = QuestionContent.model_validate(payload)
        projected = StudentQuestionContent(
            kind="question",
            prompt=full.prompt,
            concept_ids=full.concept_ids,
            citations=full.citations,
        )
        return projected
    return TypeAdapter(StudentAssetContent).validate_python(payload)


def _student_version_dto(version: KnowledgeAssetVersion) -> AssetVersionStudentDTO:
    payload = json.loads(version.content_json)
    projected = _student_content(payload)
    projected_json = _canonical_json(projected.model_dump(mode="json"))
    return AssetVersionStudentDTO(
        id=_uid(version.id),
        asset_id=_uid(version.asset_id),
        version_seq=None,
        content=projected,
        # Do not expose a digest of a Question's hidden Rubric. This hash
        # fingerprints only the typed student-visible projection.
        content_hash=_sha256(projected_json),
        created_by_user_id=_uid(version.created_by_user_id),
        created_at=version.created_at,
    )


def _asset_dto(
    db: Session,
    context: AuthContext,
    set_row: KnowledgeSet,
    role: SetRole,
    asset: KnowledgeAsset,
    *,
    version: KnowledgeAssetVersion | None = None,
) -> KnowledgeAssetFullDTO | KnowledgeAssetStudentDTO:
    actual_version = version
    if actual_version is None:
        actual_version = db.scalar(
            select(KnowledgeAssetVersion).where(
                KnowledgeAssetVersion.asset_id == asset.id,
                KnowledgeAssetVersion.version_seq == asset.current_version_seq,
            )
        )
    if actual_version is None:
        raise invalid_state("The Knowledge Asset has no current version.")
    if not _asset_version_sources_readable(db, context, set_row, role, actual_version):
        raise not_found()
    if role == "student":
        return KnowledgeAssetStudentDTO(
            audience="student",
            id=_uid(asset.id),
            knowledge_set_id=_uid(set_row.id),
            kind=asset.kind,  # type: ignore[arg-type]
            current_version_seq=None,
            current_version=_student_version_dto(actual_version),
            created_at=None,
            updated_at=actual_version.created_at,
        )
    return KnowledgeAssetFullDTO(
        audience="full",
        id=_uid(asset.id),
        knowledge_set_id=_uid(set_row.id),
        kind=asset.kind,  # type: ignore[arg-type]
        current_version_seq=actual_version.version_seq if role == "owner" else None,
        current_version=_full_version_dto(actual_version, expose_version_seq=role == "owner"),
        can_edit=role == "owner",
        created_at=asset.created_at if role == "owner" else None,
        updated_at=asset.updated_at if role == "owner" else actual_version.created_at,
    )


def list_knowledge_assets(
    db: Session,
    context: AuthContext,
    set_id: str,
    *,
    kind: str | None = None,
) -> list[KnowledgeAssetFullDTO | KnowledgeAssetStudentDTO]:
    access = _access(db, context, set_id)
    statement = select(KnowledgeAsset).where(
        KnowledgeAsset.knowledge_set_id == set_id,
        KnowledgeAsset.current_version_seq >= 1,
    )
    if kind:
        statement = statement.where(KnowledgeAsset.kind == kind)
    rows = db.scalars(
        statement.order_by(KnowledgeAsset.kind, KnowledgeAsset.created_at, KnowledgeAsset.id)
    ).all()
    result: list[KnowledgeAssetFullDTO | KnowledgeAssetStudentDTO] = []
    markdown_version = _current_markdown_version(db, access.knowledge_set)
    projected_ids = (
        set(_markdown_asset_version_ids(markdown_version)) if markdown_version else set()
    )
    projected_versions = (
        {
            version.asset_id: version
            for version in db.scalars(
                select(KnowledgeAssetVersion).where(KnowledgeAssetVersion.id.in_(projected_ids))
            ).all()
        }
        if projected_ids
        else {}
    )
    for asset in rows:
        if markdown_version is None:
            version = db.scalar(
                select(KnowledgeAssetVersion).where(
                    KnowledgeAssetVersion.asset_id == asset.id,
                    KnowledgeAssetVersion.version_seq == asset.current_version_seq,
                )
            )
        else:
            version = projected_versions.get(asset.id)
        if version is None:
            continue
        if not _asset_version_sources_readable(
            db, context, access.knowledge_set, access.role, version
        ):
            continue
        result.append(
            _asset_dto(
                db,
                context,
                access.knowledge_set,
                access.role,
                asset,
                version=version,
            )
        )
    return result


def create_knowledge_asset(
    db: Session,
    context: AuthContext,
    set_id: str,
    *,
    expected_content_revision: int,
    content: AssetContent,
    data_root: Path,
) -> KnowledgeAssetFullDTO:
    access = _editable_access(db, context, set_id)
    set_row = access.knowledge_set
    if set_row.content_revision != expected_content_revision:
        raise stale_revision(set_row.content_revision)
    if set_row.current_markdown_version_seq > 0:
        raise unprocessable(
            "knowledge_markdown_is_canonical",
            "Edit the canonical Knowledge Markdown to change its content.",
        )
    content_json, references = _validated_content(
        db,
        context,
        set_row,
        access.role,
        content,
        data_root=data_root,
        for_write=True,
    )
    _advance_set_content(db, set_row, expected_content_revision)
    timestamp = now_utc()
    asset = KnowledgeAsset(
        id=str(uuid4()),
        knowledge_set_id=set_id,
        kind=content.kind,
        current_version_seq=1,
        created_by_user_id=context.user.id,
        created_at=timestamp,
        updated_at=timestamp,
    )
    db.add(asset)
    db.flush()
    version = _store_version(db, context.user.id, set_row, asset, content_json, references, 1)
    return _asset_dto(db, context, set_row, access.role, asset, version=version)  # type: ignore[return-value]


def update_knowledge_asset(
    db: Session,
    context: AuthContext,
    asset_id: str,
    *,
    expected_content_revision: int,
    expected_asset_version_seq: int,
    content: AssetContent,
    data_root: Path,
) -> KnowledgeAssetFullDTO:
    asset = db.get(KnowledgeAsset, asset_id)
    if asset is None:
        raise not_found()
    access = _editable_access(db, context, asset.knowledge_set_id)
    set_row = access.knowledge_set
    if set_row.content_revision != expected_content_revision:
        raise stale_revision(set_row.content_revision)
    if set_row.current_markdown_version_seq > 0:
        raise unprocessable(
            "knowledge_markdown_is_canonical",
            "Edit the canonical Knowledge Markdown to change its content.",
        )
    if asset.current_version_seq != expected_asset_version_seq:
        raise stale_revision(asset.current_version_seq)
    if content.kind != asset.kind:
        raise unprocessable("knowledge_asset_kind_immutable", "An Asset keeps its original kind.")
    content_json, references = _validated_content(
        db,
        context,
        set_row,
        access.role,
        content,
        data_root=data_root,
        current_asset_id=asset_id,
        for_write=True,
    )
    _advance_set_content(db, set_row, expected_content_revision)
    next_seq = expected_asset_version_seq + 1
    result = db.execute(
        update(KnowledgeAsset)
        .where(
            KnowledgeAsset.id == asset_id,
            KnowledgeAsset.knowledge_set_id == set_row.id,
            KnowledgeAsset.current_version_seq == expected_asset_version_seq,
        )
        .values(current_version_seq=next_seq, updated_at=now_utc())
        .execution_options(synchronize_session=False)
    )
    if getattr(result, "rowcount", 0) != 1:
        raise stale_revision(
            db.scalar(
                select(KnowledgeAsset.current_version_seq).where(KnowledgeAsset.id == asset_id)
            )
        )
    asset.current_version_seq = next_seq
    asset.updated_at = now_utc()
    version = _store_version(
        db, context.user.id, set_row, asset, content_json, references, next_seq
    )
    return _asset_dto(db, context, set_row, access.role, asset, version=version)  # type: ignore[return-value]


def _history_versions(
    db: Session,
    context: AuthContext,
    set_row: KnowledgeSet,
    role: SetRole,
    asset: KnowledgeAsset,
) -> list[KnowledgeAssetVersion]:
    versions = db.scalars(
        select(KnowledgeAssetVersion)
        .where(KnowledgeAssetVersion.asset_id == asset.id)
        .order_by(KnowledgeAssetVersion.version_seq.desc())
    ).all()
    if role == "owner":
        return [
            version
            for version in versions
            if _asset_version_sources_readable(db, context, set_row, role, version)
        ]
    return [
        version
        for version in versions
        if version.set_authorization_epoch == set_row.authorization_epoch
        and _asset_version_sources_readable(db, context, set_row, role, version)
    ]


def get_knowledge_asset(
    db: Session, context: AuthContext, asset_id: str
) -> KnowledgeAssetFullDTO | KnowledgeAssetStudentDTO:
    asset = db.get(KnowledgeAsset, asset_id)
    if asset is None:
        raise not_found()
    access = _access(db, context, asset.knowledge_set_id)
    markdown_version = _current_markdown_version(db, access.knowledge_set)
    if markdown_version is None:
        version = None
    else:
        projected_ids = set(_markdown_asset_version_ids(markdown_version))
        version = db.scalar(
            select(KnowledgeAssetVersion).where(
                KnowledgeAssetVersion.asset_id == asset.id,
                KnowledgeAssetVersion.id.in_(projected_ids),
            )
        )
        if version is None:
            raise not_found()
    return _asset_dto(db, context, access.knowledge_set, access.role, asset, version=version)


def get_knowledge_asset_version(
    db: Session,
    context: AuthContext,
    asset_id: str,
    version_seq: int,
) -> KnowledgeAssetFullDTO:
    asset = db.get(KnowledgeAsset, asset_id)
    if asset is None:
        raise not_found()
    access = _access(db, context, asset.knowledge_set_id)
    if not access.can_edit:
        raise not_found()
    version = db.scalar(
        select(KnowledgeAssetVersion).where(
            KnowledgeAssetVersion.asset_id == asset_id,
            KnowledgeAssetVersion.version_seq == version_seq,
        )
    )
    if version is None or not _asset_version_sources_readable(
        db, context, access.knowledge_set, access.role, version
    ):
        raise not_found()
    return KnowledgeAssetFullDTO(
        audience="full",
        id=_uid(asset.id),
        knowledge_set_id=_uid(asset.knowledge_set_id),
        kind=asset.kind,  # type: ignore[arg-type]
        current_version_seq=version.version_seq,
        current_version=_full_version_dto(version),
        can_edit=True,
        created_at=asset.created_at,
        updated_at=version.created_at,
    )


def list_knowledge_asset_versions(
    db: Session, context: AuthContext, asset_id: str
) -> tuple[str, list[AssetVersionFullDTO] | list[AssetVersionStudentDTO]]:
    asset = db.get(KnowledgeAsset, asset_id)
    if asset is None:
        raise not_found()
    access = _access(db, context, asset.knowledge_set_id)
    versions = _history_versions(db, context, access.knowledge_set, access.role, asset)
    if not versions:
        raise not_found()
    if access.role == "student":
        return asset.id, [_student_version_dto(version) for version in versions]
    return asset.id, [
        _full_version_dto(version, expose_version_seq=access.role == "owner")
        for version in versions
    ]


def get_knowledge_graph(db: Session, context: AuthContext, set_id: str) -> KnowledgeGraph:
    access = _access(db, context, set_id)
    markdown_version = _current_markdown_version(db, access.knowledge_set)
    projected_ids = (
        set(_markdown_asset_version_ids(markdown_version)) if markdown_version else set()
    )
    rows = db.scalars(
        select(KnowledgeAsset).where(
            KnowledgeAsset.knowledge_set_id == set_id,
            KnowledgeAsset.kind == "concept",
            KnowledgeAsset.current_version_seq >= 1,
        )
    ).all()
    nodes: list[KnowledgeGraphNode] = []
    edges: list[KnowledgeGraphEdge] = []
    visible_ids: set[str] = set()
    current_payloads: dict[str, ConceptContent] = {}
    for asset in rows:
        if markdown_version is None:
            version = db.scalar(
                select(KnowledgeAssetVersion).where(
                    KnowledgeAssetVersion.asset_id == asset.id,
                    KnowledgeAssetVersion.version_seq == asset.current_version_seq,
                )
            )
        else:
            version = db.scalar(
                select(KnowledgeAssetVersion).where(
                    KnowledgeAssetVersion.asset_id == asset.id,
                    KnowledgeAssetVersion.id.in_(projected_ids),
                )
            )
            if version is not None and version.id not in projected_ids:
                version = None
        if version is None or not _asset_version_sources_readable(
            db, context, access.knowledge_set, access.role, version
        ):
            continue
        content = ConceptContent.model_validate(json.loads(version.content_json))
        visible_ids.add(asset.id)
        current_payloads[asset.id] = content
        nodes.append(
            KnowledgeGraphNode(
                id=_uid(asset.id), title=content.title, description=content.description
            )
        )
    for asset_id, content in current_payloads.items():
        for target in content.prerequisite_ids:
            target_id = str(target)
            if target_id in visible_ids:
                edges.append(
                    KnowledgeGraphEdge(source_id=_uid(asset_id), target_id=_uid(target_id))
                )
    return KnowledgeGraph(
        set_id=_uid(set_id),
        content_revision=(
            access.knowledge_set.content_revision if access.role == "owner" else None
        ),
        nodes=nodes,
        edges=edges,
    )


def _agent_for_binding(db: Session, context: AuthContext, agent_id: str, *, edit: bool) -> Agent:
    agent = db.get(Agent, agent_id)
    if agent is None or agent.deleted_at is not None or agent.status != "active":
        raise not_found()
    role = _agent_workspace_role(db, context, agent)
    if role is None or (edit and role != "owner"):
        raise not_found()
    return agent


def get_agent_knowledge_sets(
    db: Session, context: AuthContext, agent_id: str
) -> tuple[int, list[KnowledgeSetSummary]]:
    # A teacher looking round the group sees which Knowledge a private Agent
    # draws on, by name and read-only.
    observed = db.get(Agent, agent_id)
    observing = observed is not None and observes_private_agent(db, context, observed)
    agent = (
        cast(Agent, observed)
        if observing
        else _agent_for_binding(db, context, agent_id, edit=False)
    )
    rows = db.scalars(
        select(AgentKnowledgeSet)
        .where(AgentKnowledgeSet.agent_id == agent_id)
        .order_by(AgentKnowledgeSet.order_index, AgentKnowledgeSet.knowledge_set_id)
    ).all()
    sets: list[KnowledgeSetSummary] = []
    for binding in rows:
        row = db.get(KnowledgeSet, binding.knowledge_set_id)
        if row is None or row.course_id != agent.course_id:
            continue
        if observing:
            if row.group_id is None or row.group_id == agent.group_id:
                sets.append(_summary(db, context, row, can_edit=False))
            continue
        role = _set_role(db, context, row)
        if role is None or not _set_sources_readable(db, context, row, role):
            continue
        if (
            agent.group_id is not None
            and row.group_id is not None
            and row.group_id != agent.group_id
        ):
            continue
        sets.append(_summary(db, context, row, can_edit=role == "owner"))
    return agent.metadata_revision, sets


def get_agent_runtime_knowledge(
    db: Session, context: AuthContext, agent_id: str
) -> list[dict[str, Any]]:
    """Resolve this Agent's currently readable canonical Knowledge for one run."""

    _revision, summaries = get_agent_knowledge_sets(db, context, agent_id)
    result: list[dict[str, Any]] = []
    for summary in summaries:
        projection = runtime_knowledge_projection(
            db,
            str(summary.id),
            context.user.id,
        )
        if projection.canonical_markdown is None and not projection.assets:
            continue
        result.append(
            {
                "canonical_set_id": str(summary.id),
                "markdown": projection.canonical_markdown,
                "assets": list(projection.assets),
            }
        )
    return result


def replace_agent_knowledge_sets(
    db: Session,
    context: AuthContext,
    agent_id: str,
    *,
    expected_agent_metadata_revision: int,
    set_ids: list[UUID],
) -> tuple[int, list[KnowledgeSetSummary]]:
    agent = _agent_for_binding(db, context, agent_id, edit=True)
    if agent.metadata_revision != expected_agent_metadata_revision:
        raise stale_revision(agent.metadata_revision)
    string_ids = [str(value) for value in set_ids]
    if len(string_ids) != len(set(string_ids)):
        raise unprocessable("duplicate_knowledge_set_binding", "A Set can be linked only once.")
    candidate_rows: list[KnowledgeSet] = []
    for set_id in string_ids:
        row = db.get(KnowledgeSet, set_id)
        if row is None or row.course_id != agent.course_id:
            raise not_found()
        role = _set_role(db, context, row)
        if role is None or not _set_sources_readable(db, context, row, role):
            raise not_found()
        if row.visibility == "private" and agent.owner_user_id != context.user.id:
            # Private material may be attached only to the calling owner's
            # Agent. A public/group Agent binding must not turn a private Set
            # into an implicit invitation for its other readers.
            raise not_found()
        if (
            agent.group_id is not None
            and row.group_id is not None
            and row.group_id != agent.group_id
        ):
            raise not_found()
        if row.ownership_scope == "personal" and row.owner_user_id != context.user.id:
            raise not_found()
        if (
            row.group_id is not None
            and scoped_group_role_for_user(db, context.user.id, row.group_id) != "student"
        ):
            raise not_found()
        candidate_rows.append(row)

    existing = db.scalars(
        select(AgentKnowledgeSet)
        .where(AgentKnowledgeSet.agent_id == agent_id)
        .order_by(AgentKnowledgeSet.order_index, AgentKnowledgeSet.knowledge_set_id)
    ).all()
    if [row.knowledge_set_id for row in existing] == string_ids:
        return agent.metadata_revision, [
            _summary(db, context, row, can_edit=_set_role(db, context, row) == "owner")
            for row in candidate_rows
        ]
    result = db.execute(
        update(Agent)
        .where(
            Agent.id == agent_id,
            Agent.metadata_revision == expected_agent_metadata_revision,
            Agent.deleted_at.is_(None),
        )
        .values(
            metadata_revision=expected_agent_metadata_revision + 1,
            updated_at=now_utc(),
        )
        .execution_options(synchronize_session=False)
    )
    if getattr(result, "rowcount", 0) != 1:
        current = db.scalar(select(Agent.metadata_revision).where(Agent.id == agent_id))
        raise stale_revision(current)
    db.query(AgentKnowledgeSet).filter(AgentKnowledgeSet.agent_id == agent_id).delete(
        synchronize_session=False
    )
    timestamp = now_utc()
    for order_index, row in enumerate(candidate_rows):
        db.add(
            AgentKnowledgeSet(
                agent_id=agent_id,
                knowledge_set_id=row.id,
                order_index=order_index,
                created_by_user_id=context.user.id,
                created_at=timestamp,
            )
        )
    db.flush()
    agent.metadata_revision = expected_agent_metadata_revision + 1
    agent.updated_at = timestamp
    return agent.metadata_revision, [
        _summary(db, context, row, can_edit=_set_role(db, context, row) == "owner")
        for row in candidate_rows
    ]
