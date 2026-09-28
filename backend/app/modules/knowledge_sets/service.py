"""ACL, CAS and immutable-version operations for manual Knowledge Sets."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast
from uuid import UUID, uuid4

from pydantic import TypeAdapter
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.errors import invalid_state, not_found, stale_revision, unprocessable
from app.core.models import (
    Agent,
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
    scoped_group_role_for_user,
)
from app.modules.knowledge_sets.models import (
    AgentKnowledgeSet,
    KnowledgeAsset,
    KnowledgeAssetVersion,
    KnowledgeAssetVersionSource,
    KnowledgeGenerationRun,
    KnowledgeSet,
    KnowledgeSetSource,
)
from app.modules.knowledge_sets.schemas import (
    AssetCitation,
    AssetContent,
    AssetVersionFullDTO,
    AssetVersionStudentDTO,
    ConceptContent,
    CreateKnowledgeSetRequest,
    KnowledgeAssetFullDTO,
    KnowledgeAssetStudentDTO,
    KnowledgeGraph,
    KnowledgeGraphEdge,
    KnowledgeGraphNode,
    KnowledgeSetDetail,
    KnowledgeSetRevocation,
    KnowledgeSetSourceDTO,
    KnowledgeSetSummary,
    QuestionContent,
    StudentAssetContent,
    StudentQuestionContent,
)

SetRole = Literal["owner", "student", "teacher"]


@dataclass(frozen=True)
class SetAccess:
    knowledge_set: KnowledgeSet
    role: SetRole

    @property
    def can_edit(self) -> bool:
        return self.role == "owner"


def now_utc() -> datetime:
    return datetime.now(UTC)


def _uid(value: str) -> UUID:
    return UUID(value)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _clean_display_name(value: str) -> str:
    result = unicodedata.normalize("NFKC", value).strip()
    if not result or any(ord(character) < 0x20 for character in result):
        raise unprocessable("invalid_knowledge_set_name", "A Set name is required.")
    return result


def _set_role(db: Session, context: AuthContext, row: KnowledgeSet) -> SetRole | None:
    user_id = context.user.id
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
    db: Session, context: AuthContext, row: KnowledgeSet, role: SetRole
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


def replace_knowledge_set_sources(
    db: Session,
    context: AuthContext,
    set_id: str,
    *,
    expected_content_revision: int,
    source_document_ids: list[UUID],
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
    return get_knowledge_set(db, context, set_id)


def remove_knowledge_set_source(
    db: Session,
    context: AuthContext,
    set_id: str,
    binding_id: str,
    *,
    expected_content_revision: int,
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
        if (
            binding.document_id != reference.document_id
            or binding.stored_file_id != reference.stored_file_id
            or binding.source_content_hash != reference.source_content_hash
            or binding.source_file_sha256 != reference.source_file_sha256
            or binding.source_authorization_epoch != reference.source_authorization_epoch
        ):
            return False
        if not _source_matches_current(
            db,
            context,
            binding,
            role=role,
            for_write=False,
        ):
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
        if current_version is None or current_version.origin != "ai":
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
        current_version_seq=asset.current_version_seq if role == "owner" else None,
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
    for asset in rows:
        version = db.scalar(
            select(KnowledgeAssetVersion).where(
                KnowledgeAssetVersion.asset_id == asset.id,
                KnowledgeAssetVersion.version_seq == asset.current_version_seq,
            )
        )
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
    return _asset_dto(db, context, access.knowledge_set, access.role, asset)


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
        version = db.scalar(
            select(KnowledgeAssetVersion).where(
                KnowledgeAssetVersion.asset_id == asset.id,
                KnowledgeAssetVersion.version_seq == asset.current_version_seq,
            )
        )
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
    if role is None or (edit and role not in {"owner", "student"}):
        raise not_found()
    return agent


def get_agent_knowledge_sets(
    db: Session, context: AuthContext, agent_id: str
) -> tuple[int, list[KnowledgeSetSummary]]:
    agent = _agent_for_binding(db, context, agent_id, edit=False)
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
