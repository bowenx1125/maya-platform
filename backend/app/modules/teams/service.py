"""ACL-checked persistence and frozen selection for Team definitions."""

from __future__ import annotations

import json
import logging
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, cast
from uuid import UUID, uuid4

from app.core.errors import PlatformError, conflict, not_found, stale_revision, unprocessable
from app.core.links import live_link
from app.core.models import (
    Agent,
    AgentVersion,
    CourseMember,
    FileReference,
    Group,
    KnowledgeDocument,
    KnowledgeSnapshot,
    SnapshotDocument,
    StoredFile,
    User,
)
from app.core.read_memo import memoized, transaction_memoized
from app.modules.auth.service import AuthContext
from app.modules.knowledge.services import (
    _agent_workspace_role,
    can_read_source,
    can_read_version,
    course_member_role,
    observes_group,
    scoped_group_role_for_user,
)
from app.modules.knowledge_sets import service as knowledge_set_service
from app.modules.knowledge_sets.models import (
    KnowledgeDocumentVersion,
    KnowledgeSet,
    KnowledgeSetSource,
)
from app.modules.knowledge_sets.service import _source_matches_current
from app.modules.teams.models import (
    CourseTeamPublication,
    Team,
    TeamMemberInvokeGrant,
    TeamVersion,
    TeamVersionMember,
    TeamVersionSet,
)
from app.modules.teams.publication_access import (
    live_teacher_publication,
    log_team_chat_refused,
    teacher_uses_student_public_team,
    team_owner_is_teacher,
    uses_teacher_public_team,
)
from app.modules.teams.schemas import (
    CreateTeamRequest,
    DirectoryMemberDTO,
    MayaTeamDirectoryEntry,
    SaveTeamVersionRequest,
    SharedKnowledgeSetDTO,
    TeamDetail,
    TeamFaceMember,
    TeamMemberDTO,
    TeamMemberInput,
    TeamSummary,
)
from sqlalchemy import select, update
from sqlalchemy.orm import Session

LOGGER = logging.getLogger("maya.teams")


def now_utc() -> datetime:
    return datetime.now(UTC)


def _uid(value: str) -> UUID:
    return UUID(value)


def _required_set_id(value: str | None) -> str:
    if value is None:
        raise not_found()
    return value


def _actor_id(actor: AuthContext | str) -> str:
    return actor.user.id if isinstance(actor, AuthContext) else actor


def _clean_name(value: str) -> str:
    name = unicodedata.normalize("NFKC", value).strip()
    if not name or any(ord(char) < 0x20 for char in name):
        raise unprocessable("invalid_team_name", "A Team name is required.")
    return name


def _course_scope(db: Session, user_id: str, course_id: str) -> str:
    role = course_member_role(db, user_id, course_id)
    if role is None:
        raise not_found()
    return role


def _can_access_group_scope(db: Session, user_id: str, group_id: str, course_id: str) -> None:
    group = db.get(Group, group_id)
    if group is None or group.course_id != course_id:
        raise not_found()
    if scoped_group_role_for_user(db, user_id, group_id) != "student":
        # A teacher is inside a group only after joining it. This function is
        # deliberately shared by create, save, and read paths.
        raise not_found()


def can_read_team(db: Session, user_id: str, team: Team) -> bool:
    """Private stays with the owner. Public follows who published the Team."""

    if team.deleted_at is not None or course_member_role(db, user_id, team.course_id) is None:
        return False
    if team.owner_user_id == user_id:
        if team.group_id is None:
            return True
        return scoped_group_role_for_user(db, user_id, team.group_id) == "student"
    if team.visibility != "public" or team.owner_user_id is None:
        return False
    owner_role = course_member_role(db, team.owner_user_id, team.course_id)
    viewer_role = course_member_role(db, user_id, team.course_id)
    if owner_role == "teacher":
        return viewer_role in {"student", "teacher"}
    if viewer_role == "teacher":
        return True
    if team.group_id is None or viewer_role != "student":
        return False
    return scoped_group_role_for_user(db, user_id, team.group_id) is not None


def can_view_team(db: Session, user_id: str, team: Team) -> bool:
    """``can_read_team`` for the read routes, plus a teacher looking round
    the Team's group. Chat entry keeps ``can_read_team``: an observer reads a
    student's private Team but does not talk to it."""

    return can_read_team(db, user_id, team) or (
        team.deleted_at is None and observes_group(db, user_id, team.group_id)
    )


def _get_team_for_owner(db: Session, actor: AuthContext | str, team_id: str) -> Team:
    user_id = _actor_id(actor)
    row = db.scalar(
        select(Team).where(
            Team.id == team_id,
            Team.owner_user_id == user_id,
            Team.deleted_at.is_(None),
        )
    )
    if row is None or course_member_role(db, user_id, row.course_id) is None:
        raise not_found()
    if row.group_id is not None:
        _can_access_group_scope(db, user_id, row.group_id, row.course_id)
    return row


def _validate_members(
    db: Session,
    actor: AuthContext,
    course_id: str,
    group_id: str | None,
    request: CreateTeamRequest | SaveTeamVersionRequest,
) -> list[tuple[Agent, AgentVersion, int, bool, list[dict[str, object]], list[dict[str, object]]]]:
    user_id = actor.user.id
    normalized = sorted(request.members, key=lambda member: member.position)
    output: list[
        tuple[Agent, AgentVersion, int, bool, list[dict[str, object]], list[dict[str, object]]]
    ] = []
    seen_agent_ids: set[str] = set()
    for member in normalized:
        row = db.execute(
            select(AgentVersion, Agent)
            .join(Agent, Agent.id == AgentVersion.agent_id)
            .where(
                AgentVersion.id == str(member.agent_version_id),
                Agent.course_id == course_id,
                Agent.deleted_at.is_(None),
                Agent.status == "active",
            )
        ).first()
        if row is None:
            retired = db.execute(
                select(AgentVersion, Agent)
                .join(Agent, Agent.id == AgentVersion.agent_id)
                .where(
                    AgentVersion.id == str(member.agent_version_id),
                    Agent.course_id == course_id,
                )
            ).first()
            if retired is not None and (
                retired[1].deleted_at is not None or retired[1].status != "active"
            ):
                raise unprocessable(
                    "agent_archived",
                    "Archived Agents are not available for new classroom work.",
                )
            raise not_found("An Agent version is not available in this course.")
        version, agent = row
        if version.state not in {"published", "superseded"}:
            raise unprocessable(
                "team_member_version_not_immutable",
                "Team members must use a published immutable Agent version.",
            )
        if agent.id in seen_agent_ids:
            raise unprocessable(
                "duplicate_team_agent",
                "An Agent can only appear once in a Team.",
                {"agent_id": agent.id, "agent_name": agent.name},
            )
        seen_agent_ids.add(agent.id)
        role = _agent_workspace_role(db, actor, agent)
        if role is None or not can_read_version(db, version, agent, role, context=actor):
            raise not_found(
                "An Agent version is not available to the current user. "
                "Choose an Agent you can open, or ask its publisher to make it Public."
            )
        if group_id is not None and agent.group_id != group_id:
            raise not_found("A group Team can only contain Agents from that group.")
        # Other members can read a public Team's roster, so a private Agent
        # there would reveal that it exists. Private Teams may mix both.
        if request.visibility == "public" and (
            agent.visibility != "public" or version.published_visibility == "private"
        ):
            raise unprocessable(
                "team_member_private",
                "A public Team can only contain public Agents.",
                {"agent_id": agent.id, "agent_name": agent.name},
            )
        raw_source_fences = _capture_raw_source_fences(db, version, course_id)
        if not _raw_source_fences_current(
            db,
            user_id,
            raw_source_fences,
            agent_version_id=version.id,
            course_id=course_id,
        ):
            raise unprocessable(
                "team_member_source_unavailable",
                "An Agent source is not currently available to the Team owner.",
            )
        _metadata_revision, own_sets = knowledge_set_service.get_agent_knowledge_sets(
            db, actor, agent.id
        )
        own_set_snapshots: list[dict[str, object]] = []
        for own_set in own_sets:
            set_row = db.get(KnowledgeSet, str(own_set.id))
            if set_row is not None and _knowledge_set_currently_readable(db, user_id, set_row):
                own_set_snapshots.append(
                    {"id": set_row.id, "authorization_epoch": set_row.authorization_epoch}
                )
        output.append(
            (
                agent,
                version,
                member.position,
                member.is_leader,
                own_set_snapshots,
                raw_source_fences,
            )
        )
    return output


def _validate_sets(
    db: Session,
    actor: AuthContext,
    course_id: str,
    group_id: str | None,
    set_ids: list[UUID],
) -> list[KnowledgeSet]:
    rows: list[KnowledgeSet] = []
    for requested_id in set_ids:
        set_id = str(requested_id)
        detail = knowledge_set_service.get_knowledge_set(db, actor, set_id)
        if str(detail.course_id) != course_id:
            raise not_found("A Knowledge Set is not available in this course.")
        # A course Teacher's read-only summary of another group's Set does not
        # grant authority to attach that source set to a Team.
        if any(source.is_active and not source.available for source in detail.sources):
            raise not_found("A Knowledge Set source is not currently available.")
        row = db.get(KnowledgeSet, set_id)
        if row is None or row.deleted_at is not None:
            raise not_found()
        if group_id is not None and row.group_id not in {None, group_id}:
            raise not_found("A group Team cannot bind another group's Knowledge Set.")
        rows.append(row)
    return rows


def _knowledge_set_role_for_user(
    db: Session, user_id: str, row: KnowledgeSet
) -> Literal["owner", "student", "teacher"] | None:
    if row.deleted_at is not None or course_member_role(db, user_id, row.course_id) is None:
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
    return (
        cast(Literal["owner", "student", "teacher"], group_role)
        if row.visibility == "public"
        else None
    )


def _knowledge_set_currently_readable(db: Session, user_id: str, row: KnowledgeSet) -> bool:
    role = _knowledge_set_role_for_user(db, user_id, row)
    if role is None:
        return False
    sources = db.scalars(
        select(KnowledgeSetSource).where(
            KnowledgeSetSource.knowledge_set_id == row.id,
            KnowledgeSetSource.is_active.is_(True),
        )
    ).all()
    return all(
        _source_matches_current(db, user_id, source, role=role, for_write=True)
        for source in sources
    )


def _has_file_reference(
    db: Session, stored_file_id: str, owner_type: str, owner_id: str, purpose: str
) -> bool:
    # Every source fence of a Team check asks again; production repeated the
    # same lookup ~24 times per chat open. A write in the transaction drops it.
    return transaction_memoized(
        db,
        ("file_reference", stored_file_id, owner_type, owner_id, purpose),
        lambda: _read_file_reference(db, stored_file_id, owner_type, owner_id, purpose),
    )


def _read_file_reference(
    db: Session, stored_file_id: str, owner_type: str, owner_id: str, purpose: str
) -> bool:
    return (
        db.scalar(
            select(FileReference.id).where(
                FileReference.stored_file_id == stored_file_id,
                FileReference.owner_type == owner_type,
                FileReference.owner_id == owner_id,
                FileReference.purpose == purpose,
            )
        )
        is not None
    )


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _valid_authorization_epoch(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _capture_raw_source_fences(
    db: Session, version: AgentVersion, course_id: str
) -> list[dict[str, object]]:
    if version.knowledge_snapshot_id is None:
        return []
    snapshot = db.get(KnowledgeSnapshot, version.knowledge_snapshot_id)
    if snapshot is None or snapshot.agent_version_id != version.id:
        raise not_found("An Agent snapshot is not available to the Team owner.")
    snapshot_file = db.get(StoredFile, snapshot.stored_file_id)
    if (
        snapshot_file is None
        or snapshot_file.kind != "snapshot_rag"
        or snapshot_file.state != "active"
        or snapshot_file.sha256 != snapshot.content_hash
        or not _is_sha256(snapshot.content_hash)
        or not _has_file_reference(db, snapshot_file.id, "knowledge_snapshot", snapshot.id, "rag")
    ):
        raise not_found("An Agent snapshot is not available to the Team owner.")
    rows = db.execute(
        select(SnapshotDocument, KnowledgeDocument, StoredFile)
        .join(KnowledgeDocument, KnowledgeDocument.id == SnapshotDocument.document_id)
        .join(StoredFile, StoredFile.id == SnapshotDocument.stored_file_id)
        .where(SnapshotDocument.snapshot_id == snapshot.id)
        .order_by(SnapshotDocument.order_index, SnapshotDocument.id)
    ).all()
    fences: list[dict[str, object]] = []
    for snapshot_document, document, stored_file in rows:
        if (
            document.course_id != course_id
            or document.workspace_state != "active"
            or document.authorization_epoch != snapshot_document.source_authorization_epoch
            or stored_file.kind != "snapshot_source"
            or stored_file.state != "active"
            or not _is_sha256(stored_file.sha256)
            or not _has_file_reference(
                db,
                stored_file.id,
                "snapshot_document",
                snapshot_document.id,
                "source",
            )
        ):
            raise unprocessable(
                "team_member_source_unavailable",
                "An Agent source is not currently available to the Team owner.",
            )

        source_versions = db.execute(
            select(KnowledgeDocumentVersion, StoredFile)
            .join(StoredFile, StoredFile.id == KnowledgeDocumentVersion.stored_file_id)
            .where(
                KnowledgeDocumentVersion.document_id == document.id,
                KnowledgeDocumentVersion.file_sha256 == stored_file.sha256,
                KnowledgeDocumentVersion.authorization_epoch
                == snapshot_document.source_authorization_epoch,
            )
            .order_by(KnowledgeDocumentVersion.version_seq.desc())
        ).all()
        source_version_id: str | None = None
        source_content_hash: str | None = None
        if source_versions:
            content_hashes = {version_row.content_hash for version_row, _file in source_versions}
            if len(content_hashes) != 1 or any(
                version_row.version_seq > document.content_version_seq
                or not _is_sha256(version_row.content_hash)
                or version_file.sha256 != version_row.file_sha256
                for version_row, version_file in source_versions
            ):
                raise unprocessable(
                    "team_member_source_unavailable",
                    "An Agent source is not currently available to the Team owner.",
                )
            version_row, _version_file = source_versions[0]
            source_version_id = version_row.id
            source_content_hash = version_row.content_hash

        fences.append(
            {
                "agent_version_id": version.id,
                "snapshot_id": snapshot.id,
                "snapshot_file_id": snapshot_file.id,
                "snapshot_content_hash": snapshot.content_hash,
                "snapshot_document_id": snapshot_document.id,
                "document_id": document.id,
                "course_id": course_id,
                "stored_file_id": stored_file.id,
                "source_version_id": source_version_id,
                "content_hash": source_content_hash,
                "file_sha256": stored_file.sha256,
                "authorization_epoch": snapshot_document.source_authorization_epoch,
            }
        )
    return fences


def _raw_source_fences_current(
    db: Session,
    user_id: str,
    fences: list[dict[str, object]],
    *,
    agent_version_id: str,
    course_id: str,
) -> bool:
    if any(not isinstance(fence, dict) for fence in fences):
        return False
    version = db.get(AgentVersion, agent_version_id)
    if version is None:
        return False
    # Rebuild the complete source set from the member's immutable AgentVersion
    # on both create and send. This makes an empty or partial persisted fence fail closed.
    canonical_fences = _capture_raw_source_fences(db, version, course_id)
    canonical_identities = [
        (
            str(fence["agent_version_id"]),
            str(fence["snapshot_id"]),
            str(fence["snapshot_document_id"]),
            str(fence["document_id"]),
            str(fence["course_id"]),
            str(fence["stored_file_id"]),
            str(fence["file_sha256"]),
            cast(int, fence["authorization_epoch"]),
        )
        for fence in canonical_fences
    ]
    if len(set(canonical_identities)) != len(canonical_identities):
        return False

    legacy_fields = {
        "document_id",
        "stored_file_id",
        "content_hash",
        "file_sha256",
        "authorization_epoch",
    }
    current_fields = {
        "agent_version_id",
        "snapshot_id",
        "snapshot_file_id",
        "snapshot_content_hash",
        "snapshot_document_id",
        "document_id",
        "course_id",
        "stored_file_id",
        "source_version_id",
        "content_hash",
        "file_sha256",
        "authorization_epoch",
    }
    is_legacy = bool(fences and "snapshot_id" not in fences[0])
    if fences and any(("snapshot_id" not in fence) != is_legacy for fence in fences):
        return False
    expected_fields = legacy_fields if is_legacy else current_fields
    if any(set(fence) != expected_fields for fence in fences):
        return False

    supplied_identities: list[tuple[str, ...]] = []
    canonical_identity_values: list[tuple[str, ...]]
    if is_legacy:
        for fence in fences:
            document_id = fence.get("document_id")
            stored_file_id = fence.get("stored_file_id")
            file_sha256 = fence.get("file_sha256")
            authorization_epoch = fence.get("authorization_epoch")
            if (
                not isinstance(document_id, str)
                or not isinstance(stored_file_id, str)
                or not _is_sha256(file_sha256)
                or not _valid_authorization_epoch(authorization_epoch)
                or not _is_sha256(fence.get("content_hash"))
            ):
                return False
            supplied_identities.append(
                (
                    document_id,
                    stored_file_id,
                    cast(str, file_sha256),
                    str(authorization_epoch),
                )
            )
        canonical_identity_values = [
            (
                str(fence["document_id"]),
                str(fence["stored_file_id"]),
                str(fence["file_sha256"]),
                str(fence["authorization_epoch"]),
            )
            for fence in canonical_fences
        ]
    else:
        for fence in fences:
            string_fields = (
                "agent_version_id",
                "snapshot_id",
                "snapshot_file_id",
                "snapshot_content_hash",
                "snapshot_document_id",
                "document_id",
                "course_id",
                "stored_file_id",
                "file_sha256",
            )
            if (
                any(not isinstance(fence.get(key), str) for key in string_fields)
                or not _is_sha256(fence.get("snapshot_content_hash"))
                or not _is_sha256(fence.get("file_sha256"))
                or not _valid_authorization_epoch(fence.get("authorization_epoch"))
            ):
                return False
            supplied_identities.append(
                (
                    cast(str, fence["agent_version_id"]),
                    cast(str, fence["snapshot_id"]),
                    cast(str, fence["snapshot_document_id"]),
                    cast(str, fence["document_id"]),
                    cast(str, fence["course_id"]),
                    cast(str, fence["stored_file_id"]),
                    cast(str, fence["file_sha256"]),
                    str(fence["authorization_epoch"]),
                )
            )
        canonical_identity_values = [
            tuple(
                str(fence[key])
                for key in (
                    "agent_version_id",
                    "snapshot_id",
                    "snapshot_document_id",
                    "document_id",
                    "course_id",
                    "stored_file_id",
                    "file_sha256",
                    "authorization_epoch",
                )
            )
            for fence in canonical_fences
        ]
    if (
        len(set(supplied_identities)) != len(supplied_identities)
        or len(supplied_identities) != len(canonical_identity_values)
        or set(supplied_identities) != set(canonical_identity_values)
    ):
        return False
    if is_legacy:
        # Old Team rows mixed the current content hash with frozen file identity.
        # Keep the stored JSON untouched and validate through the exact SnapshotDocument set.
        fences = canonical_fences

    for fence in fences:
        fenced_agent_version_id = fence.get("agent_version_id")
        snapshot_id = fence.get("snapshot_id")
        snapshot_document_id = fence.get("snapshot_document_id")
        document_id = fence.get("document_id")
        stored_file_id = fence.get("stored_file_id")
        expected_file_sha = fence.get("file_sha256")
        authorization_epoch = fence.get("authorization_epoch")
        if (
            not all(
                isinstance(value, str) and value
                for value in (
                    fenced_agent_version_id,
                    snapshot_id,
                    snapshot_document_id,
                    document_id,
                    stored_file_id,
                )
            )
            or not _is_sha256(expected_file_sha)
            or not _valid_authorization_epoch(authorization_epoch)
        ):
            return False
        if fenced_agent_version_id != agent_version_id:
            return False
        if fence.get("course_id") != course_id:
            return False
        agent_version = db.get(AgentVersion, fenced_agent_version_id)
        snapshot = db.get(KnowledgeSnapshot, snapshot_id)
        snapshot_file_id = fence.get("snapshot_file_id")
        snapshot_file = (
            db.get(StoredFile, snapshot_file_id) if isinstance(snapshot_file_id, str) else None
        )
        snapshot_document = db.get(SnapshotDocument, snapshot_document_id)
        document = db.get(KnowledgeDocument, str(document_id)) if document_id else None
        stored_file = db.get(StoredFile, str(stored_file_id)) if stored_file_id else None
        if (
            agent_version is None
            or agent_version.knowledge_snapshot_id != snapshot_id
            or snapshot is None
            or snapshot.agent_version_id != agent_version.id
            or snapshot.stored_file_id != snapshot_file_id
            or snapshot.content_hash != fence.get("snapshot_content_hash")
            or not _is_sha256(snapshot.content_hash)
            or snapshot_file is None
            or snapshot_file.kind != "snapshot_rag"
            or snapshot_file.state != "active"
            or snapshot_file.sha256 != snapshot.content_hash
            or not _has_file_reference(
                db, snapshot_file.id, "knowledge_snapshot", snapshot.id, "rag"
            )
            or snapshot_document is None
            or snapshot_document.snapshot_id != snapshot.id
            or snapshot_document.document_id != document_id
            or snapshot_document.stored_file_id != stored_file_id
            or snapshot_document.source_authorization_epoch != authorization_epoch
        ):
            return False
        if (
            document is None
            or stored_file is None
            or document.course_id != course_id
            or document.workspace_state != "active"
            or document.authorization_epoch != authorization_epoch
            or stored_file.kind != "snapshot_source"
            or stored_file.sha256 != expected_file_sha
            or stored_file.state != "active"
            or not _has_file_reference(
                db,
                stored_file.id,
                "snapshot_document",
                snapshot_document.id,
                "source",
            )
            or not can_read_source(db, user_id, document, require_active=True)
        ):
            return False
        source_version_id = fence.get("source_version_id")
        content_hash = fence.get("content_hash")
        if source_version_id is None:
            # Pre-0047 snapshots have no per-source version row. Their exact
            # SnapshotDocument reference and active frozen-file SHA remain authoritative.
            if content_hash is not None:
                return False
        else:
            if not isinstance(source_version_id, str) or not source_version_id:
                return False
            source_version = db.get(KnowledgeDocumentVersion, str(source_version_id))
            source_version_file = (
                db.get(StoredFile, source_version.stored_file_id)
                if source_version is not None
                else None
            )
            if (
                source_version is None
                or source_version_file is None
                or source_version.document_id != document.id
                or source_version.authorization_epoch != authorization_epoch
                or source_version.content_hash != content_hash
                or source_version.file_sha256 != expected_file_sha
                or source_version_file.sha256 != source_version.file_sha256
                or source_version.version_seq > document.content_version_seq
                or not _is_sha256(content_hash)
            ):
                return False
    return True


def _version_for_seq(db: Session, team: Team, seq: int | None = None) -> TeamVersion:
    version_seq = team.current_version_seq if seq is None else seq
    row = db.scalar(
        select(TeamVersion).where(
            TeamVersion.team_id == team.id,
            TeamVersion.version_seq == version_seq,
        )
    )
    if row is None:
        raise not_found()
    return row


def _member_rows(db: Session, team_version_id: str) -> list[TeamVersionMember]:
    return list(
        db.scalars(
            select(TeamVersionMember)
            .where(TeamVersionMember.team_version_id == team_version_id)
            .order_by(TeamVersionMember.position)
        ).all()
    )


def _set_rows(db: Session, team_version_id: str) -> list[TeamVersionSet]:
    return list(
        db.scalars(
            select(TeamVersionSet)
            .where(TeamVersionSet.team_version_id == team_version_id)
            .order_by(TeamVersionSet.position)
        ).all()
    )


def _team_member_dto(row: TeamVersionMember) -> TeamMemberDTO:
    try:
        avatar = json.loads(row.avatar_config_json)
    except (TypeError, ValueError):
        avatar = {}
    if not isinstance(avatar, dict):
        avatar = {}
    return TeamMemberDTO(
        id=_uid(row.id),
        agent_id=_uid(live_link(row.agent_id, "Agent")),
        agent_version_id=_uid(live_link(row.agent_version_id, "Agent version")),
        display_name=row.display_name,
        avatar_config=cast(dict[str, object], avatar),
        position=row.position,
        is_leader=row.is_leader,
    )


def _publication_state(db: Session, team: Team, version: TeamVersion) -> str:
    if version.visibility != "public" or team.ownership_scope != "personal":
        return "unpublished"
    published = db.scalar(
        select(CourseTeamPublication.id).where(
            CourseTeamPublication.team_id == team.id,
            CourseTeamPublication.team_version_id == version.id,
            CourseTeamPublication.authorization_epoch == team.authorization_epoch,
            CourseTeamPublication.state == "published",
        )
    )
    return "published" if published else "unpublished"


def _can_delete_team(db: Session, user_id: str, team: Team) -> bool:
    """Mirror of _get_team_for_owner, which guards DELETE /teams/{team_id}."""

    if team.owner_user_id != user_id or team.deleted_at is not None:
        return False
    if course_member_role(db, user_id, team.course_id) is None:
        return False
    if team.group_id is None:
        return True
    group = db.get(Group, team.group_id)
    if group is None or group.course_id != team.course_id:
        return False
    return scoped_group_role_for_user(db, user_id, team.group_id) == "student"


def _team_summary(
    db: Session,
    team: Team,
    *,
    user_id: str,
    owner_names: dict[str, str] | None = None,
    version: TeamVersion | None = None,
    members: list[TeamVersionMember] | None = None,
) -> TeamSummary:
    if version is None:
        version = _version_for_seq(db, team)
    if members is None:
        members = _members_by_version(db, [version.id]).get(version.id, [])
    if owner_names is not None:
        owner_name = owner_names.get(team.owner_user_id)
    else:
        owner = db.get(User, team.owner_user_id) if team.owner_user_id else None
        owner_name = owner.display_name if owner is not None else None
    return TeamSummary(
        id=_uid(team.id),
        course_id=_uid(team.course_id),
        owner_user_id=_uid(team.owner_user_id),
        ownership_scope=team.ownership_scope,  # type: ignore[arg-type]
        group_id=_uid(team.group_id) if team.group_id else None,
        display_name=team.display_name,
        visibility=team.visibility,  # type: ignore[arg-type]
        metadata_revision=team.metadata_revision,
        authorization_epoch=team.authorization_epoch,
        current_version_id=_uid(version.id),
        current_version_seq=version.version_seq,
        member_count=len(members),
        can_edit=team.owner_user_id == user_id,
        can_delete=_can_delete_team(db, user_id, team),
        is_teacher_owned=team_owner_is_teacher(db, team),
        updated_at=team.updated_at,
        last_edited_by_name=owner_name,
        members=_face_members(members),
    )


def _members_by_version(db: Session, version_ids: list[str]) -> dict[str, list[TeamVersionMember]]:
    """All members of the given Team versions in one query, by position."""

    grouped: dict[str, list[TeamVersionMember]] = {key: [] for key in version_ids}
    if not version_ids:
        return grouped
    rows = db.scalars(
        select(TeamVersionMember)
        .where(TeamVersionMember.team_version_id.in_(version_ids))
        .order_by(TeamVersionMember.team_version_id, TeamVersionMember.position)
    ).all()
    for row in rows:
        grouped.setdefault(row.team_version_id, []).append(row)
    return grouped


def _face_members(members: list[TeamVersionMember]) -> list[TeamFaceMember]:
    ordered = sorted(members, key=lambda row: (not row.is_leader, row.position))
    faces: list[TeamFaceMember] = []
    for row in ordered[:4]:
        try:
            avatar = json.loads(row.avatar_config_json or "{}")
        except ValueError:
            avatar = {}
        theme = avatar.get("material_theme") if isinstance(avatar, dict) else None
        faces.append(
            TeamFaceMember(
                agent_id=_uid(row.agent_id) if row.agent_id else None,
                material_theme=theme if isinstance(theme, str) else None,
                is_leader=bool(row.is_leader),
            )
        )
    return faces


def _shared_knowledge_set_dtos(db: Session, version_id: str) -> list[SharedKnowledgeSetDTO]:
    named: list[SharedKnowledgeSetDTO] = []
    for binding in _set_rows(db, version_id):
        row = db.get(KnowledgeSet, binding.knowledge_set_id)
        if row is None:
            raise not_found()
        named.append(SharedKnowledgeSetDTO(id=_uid(row.id), display_name=row.display_name))
    return named


def get_team_detail(db: Session, actor: AuthContext | str, team_id: str) -> TeamDetail:
    user_id = _actor_id(actor)
    team = db.scalar(select(Team).where(Team.id == team_id, Team.deleted_at.is_(None)))
    if team is None or not can_view_team(db, user_id, team):
        raise not_found()
    version = _version_for_seq(db, team)
    summary = _team_summary(db, team, user_id=user_id)
    return TeamDetail(
        **summary.model_dump(exclude={"members"}),
        created_at=team.created_at,
        members=[_team_member_dto(row) for row in _member_rows(db, version.id)],
        shared_knowledge_set_ids=[
            _uid(_required_set_id(row.knowledge_set_id)) for row in _set_rows(db, version.id)
        ],
        shared_knowledge_sets=_shared_knowledge_set_dtos(db, version.id),
        publication_state=_publication_state(db, team, version),  # type: ignore[arg-type]
    )


def _create_version_rows(
    db: Session,
    *,
    team: Team,
    actor: AuthContext,
    version_seq: int,
    name: str,
    visibility: str,
    members: list[
        tuple[Agent, AgentVersion, int, bool, list[dict[str, object]], list[dict[str, object]]]
    ],
    sets: list[KnowledgeSet],
) -> TeamVersion:
    timestamp = now_utc()
    version = TeamVersion(
        id=str(uuid4()),
        team_id=team.id,
        version_seq=version_seq,
        display_name=name,
        visibility=visibility,
        authorization_epoch=team.authorization_epoch,
        created_by_user_id=actor.user.id,
        created_at=timestamp,
    )
    db.add(version)
    db.flush()
    for agent, agent_version, position, is_leader, own_set_snapshots, source_fences in members:
        db.add(
            TeamVersionMember(
                id=str(uuid4()),
                team_version_id=version.id,
                agent_id=agent.id,
                agent_version_id=agent_version.id,
                position=position,
                is_leader=is_leader,
                display_name=agent.name,
                avatar_config_json=agent_version.avatar_config_json,
                own_knowledge_set_snapshots_json=json.dumps(
                    own_set_snapshots, ensure_ascii=True, separators=(",", ":")
                ),
                raw_source_fences_json=json.dumps(
                    source_fences, ensure_ascii=True, separators=(",", ":")
                ),
                created_at=timestamp,
            )
        )
    for position, knowledge_set in enumerate(sets):
        db.add(
            TeamVersionSet(
                id=str(uuid4()),
                team_version_id=version.id,
                knowledge_set_id=knowledge_set.id,
                authorization_epoch=knowledge_set.authorization_epoch,
                position=position,
                created_at=timestamp,
            )
        )
    db.flush()
    return version


def _revoke_publications(db: Session, team_id: str, timestamp: datetime) -> None:
    active = db.scalars(
        select(CourseTeamPublication).where(
            CourseTeamPublication.team_id == team_id,
            CourseTeamPublication.state.in_(("published", "retained")),
        )
    ).all()
    for publication in active:
        publication.state = "revoked"
        publication.revoked_at = timestamp


def _retain_current_publications(db: Session, team_id: str) -> None:
    active = db.scalars(
        select(CourseTeamPublication).where(
            CourseTeamPublication.team_id == team_id,
            CourseTeamPublication.state == "published",
        )
    ).all()
    for publication in active:
        publication.state = "retained"


def _member_authorization_projection(
    members: list[
        tuple[Agent, AgentVersion, int, bool, list[dict[str, object]], list[dict[str, object]]]
    ],
) -> list[tuple[str, int, bool, tuple[tuple[str, int], ...]]]:
    def set_signature(snapshots: list[dict[str, object]]) -> tuple[tuple[str, int], ...]:
        result: list[tuple[str, int]] = []
        for snapshot in snapshots:
            set_id = snapshot.get("id")
            set_epoch = snapshot.get("authorization_epoch")
            if not isinstance(set_id, str) or not isinstance(set_epoch, int):
                raise not_found()
            result.append((set_id, set_epoch))
        return tuple(sorted(result))

    return [
        (
            version.id,
            position,
            is_leader,
            set_signature(own_sets),
        )
        for _agent, version, position, is_leader, own_sets, _source_fences in members
    ]


def _team_authorization_changed(
    db: Session,
    team: Team,
    new_visibility: str,
    new_members: list[
        tuple[Agent, AgentVersion, int, bool, list[dict[str, object]], list[dict[str, object]]]
    ],
    new_sets: list[KnowledgeSet],
) -> bool:
    current = _version_for_seq(db, team)
    if current.visibility != new_visibility:
        return True
    old_members = [
        (
            member.agent_version_id,
            member.position,
            member.is_leader,
            _member_authorization_projection_from_row(member),
        )
        for member in _member_rows(db, current.id)
    ]
    if old_members != _member_authorization_projection(new_members):
        return True
    old_sets = [
        (row.knowledge_set_id, row.authorization_epoch) for row in _set_rows(db, current.id)
    ]
    new_set_signature = [(row.id, row.authorization_epoch) for row in new_sets]
    return old_sets != new_set_signature


def _member_authorization_projection_from_row(
    member: TeamVersionMember,
) -> tuple[tuple[str, int], ...]:
    try:
        snapshots = json.loads(member.own_knowledge_set_snapshots_json)
    except (TypeError, ValueError):
        raise not_found() from None
    if not isinstance(snapshots, list) or any(not isinstance(item, dict) for item in snapshots):
        raise not_found()
    values: list[tuple[str, int]] = []
    for snapshot in snapshots:
        set_id = snapshot.get("id")
        epoch = snapshot.get("authorization_epoch")
        if not isinstance(set_id, str) or not isinstance(epoch, int):
            raise not_found()
        values.append((set_id, epoch))
    return tuple(sorted(values))


def _publish_eligible_team(
    db: Session,
    team: Team,
    version: TeamVersion,
    actor: AuthContext,
    timestamp: datetime,
) -> None:
    if (
        team.ownership_scope != "personal"
        or team.group_id is not None
        or team.visibility != "public"
        or course_member_role(db, actor.user.id, team.course_id) != "teacher"
    ):
        return
    publication = CourseTeamPublication(
        id=str(uuid4()),
        course_id=team.course_id,
        team_id=team.id,
        team_version_id=version.id,
        publisher_user_id=actor.user.id,
        authorization_epoch=team.authorization_epoch,
        state="published",
        published_at=timestamp,
        revoked_at=None,
    )
    db.add(publication)
    db.flush()
    for member in _member_rows(db, version.id):
        db.add(
            TeamMemberInvokeGrant(
                id=str(uuid4()),
                publication_id=publication.id,
                team_version_id=version.id,
                team_member_id=member.id,
                agent_id=live_link(member.agent_id, "Agent"),
                agent_version_id=live_link(member.agent_version_id, "Agent version"),
                authorization_epoch=team.authorization_epoch,
                created_at=timestamp,
            )
        )


def create_team(
    db: Session,
    actor: AuthContext,
    course_id: str,
    request: CreateTeamRequest,
) -> TeamDetail:
    user_id = actor.user.id
    _course_scope(db, user_id, course_id)
    group_id = str(request.group_id) if request.group_id is not None else None
    if group_id is not None:
        _can_access_group_scope(db, user_id, group_id, course_id)
    members = _validate_members(db, actor, course_id, group_id, request)
    sets = _validate_sets(db, actor, course_id, group_id, request.shared_knowledge_set_ids)
    name = _clean_name(request.display_name)
    timestamp = now_utc()
    team = Team(
        id=str(uuid4()),
        owner_user_id=user_id,
        course_id=course_id,
        group_id=group_id,
        ownership_scope="group" if group_id else "personal",
        display_name=name,
        visibility=request.visibility,
        metadata_revision=0,
        authorization_epoch=0,
        current_version_seq=1,
        deleted_at=None,
        created_at=timestamp,
        updated_at=timestamp,
    )
    db.add(team)
    db.flush()
    version = _create_version_rows(
        db,
        team=team,
        actor=actor,
        version_seq=1,
        name=name,
        visibility=request.visibility,
        members=members,
        sets=sets,
    )
    _publish_eligible_team(db, team, version, actor, timestamp)
    db.flush()
    return get_team_detail(db, actor, team.id)


def save_team_version(
    db: Session,
    actor: AuthContext,
    team_id: str,
    request: SaveTeamVersionRequest,
) -> TeamDetail:
    team = _get_team_for_owner(db, actor, team_id)
    if request.visibility != team.visibility:
        raise conflict(
            "team_visibility_locked",
            "Private or Public is chosen when the Team is created.",
        )
    if team.metadata_revision != request.expected_metadata_revision:
        raise stale_revision(team.metadata_revision)
    members = _validate_members(db, actor, team.course_id, team.group_id, request)
    sets = _validate_sets(
        db,
        actor,
        team.course_id,
        team.group_id,
        request.shared_knowledge_set_ids,
    )
    name = _clean_name(request.display_name)
    timestamp = now_utc()
    authorization_changed = _team_authorization_changed(db, team, request.visibility, members, sets)
    next_epoch = team.authorization_epoch + int(authorization_changed)
    next_seq = team.current_version_seq + 1
    result = db.execute(
        update(Team)
        .where(
            Team.id == team.id,
            Team.owner_user_id == actor.user.id,
            Team.metadata_revision == request.expected_metadata_revision,
            Team.deleted_at.is_(None),
        )
        .values(
            display_name=name,
            visibility=request.visibility,
            metadata_revision=request.expected_metadata_revision + 1,
            authorization_epoch=next_epoch,
            current_version_seq=next_seq,
            updated_at=timestamp,
        )
        .execution_options(synchronize_session=False)
    )
    if getattr(result, "rowcount", 0) != 1:
        raise stale_revision(db.scalar(select(Team.metadata_revision).where(Team.id == team.id)))
    team.display_name = name
    team.visibility = request.visibility
    team.metadata_revision = request.expected_metadata_revision + 1
    team.authorization_epoch = next_epoch
    team.current_version_seq = next_seq
    team.updated_at = timestamp
    version = _create_version_rows(
        db,
        team=team,
        actor=actor,
        version_seq=next_seq,
        name=name,
        visibility=request.visibility,
        members=members,
        sets=sets,
    )
    if authorization_changed:
        _revoke_publications(db, team.id, timestamp)
    else:
        _retain_current_publications(db, team.id)
    _publish_eligible_team(db, team, version, actor, timestamp)
    db.flush()
    return get_team_detail(db, actor, team.id)


def delete_team(db: Session, actor: AuthContext, team_id: str) -> None:
    """Remove a Team. Chats stay readable under the snapshotted name and stop."""

    team = _get_team_for_owner(db, actor, team_id)
    from app.modules.real_delete import hard_delete_team

    hard_delete_team(db, team)


def _team_on_group_page(db: Session, team: Team, user_id: str, group_id: str) -> bool:
    """Teams shown on a group's Studyform page.

    That group's Teams, the caller's own Teams (including personal), and every
    teacher-owned Public Team in the course. Never drops the caller's own
    items behind a group filter.
    """

    if team.group_id == group_id:
        return True
    if team.owner_user_id == user_id:
        return True
    return team.visibility == "public" and team_owner_is_teacher(db, team)


def list_course_teams(
    db: Session, actor: AuthContext, course_id: str, group_id: str | None = None
) -> list[TeamSummary]:
    """The course's Teams this caller may use, or one group's Teams.

    Only the group listing adds the private Teams of a group a teacher has
    entered: the course listing feeds Chatform and Memory, which would offer
    a Team the teacher may read but not talk to. A group listing also keeps
    teacher-owned Public Teams and the caller's own Teams (including personal).
    """

    user_id = actor.user.id
    _course_scope(db, user_id, course_id)
    query = select(Team).where(Team.course_id == course_id, Team.deleted_at.is_(None))
    rows = db.scalars(query.order_by(Team.updated_at.desc(), Team.id)).all()
    readable = can_view_team if group_id is not None else can_read_team
    shown = [
        team
        for team in rows
        if readable(db, user_id, team)
        and (group_id is None or _team_on_group_page(db, team, user_id, group_id))
    ]
    owner_ids = {team.owner_user_id for team in shown if team.owner_user_id}
    owner_names: dict[str, str] = {}
    if owner_ids:
        names = db.execute(select(User.id, User.display_name).where(User.id.in_(owner_ids)))
        owner_names = {user_id: name for user_id, name in names.all()}
    versions = {team.id: _version_for_seq(db, team) for team in shown}
    members = _members_by_version(db, [version.id for version in versions.values()])
    return [
        _team_summary(
            db,
            team,
            user_id=user_id,
            owner_names=owner_names,
            version=versions[team.id],
            members=members.get(versions[team.id].id, []),
        )
        for team in shown
    ]


def list_maya_teams(
    db: Session, actor: AuthContext, course_id: str
) -> list[MayaTeamDirectoryEntry]:
    _course_scope(db, actor.user.id, course_id)
    rows = db.execute(
        select(CourseTeamPublication, Team, TeamVersion)
        .join(Team, Team.id == CourseTeamPublication.team_id)
        .join(TeamVersion, TeamVersion.id == CourseTeamPublication.team_version_id)
        .join(
            CourseMember,
            (CourseMember.course_id == CourseTeamPublication.course_id)
            & (CourseMember.user_id == CourseTeamPublication.publisher_user_id),
        )
        .where(
            CourseTeamPublication.course_id == course_id,
            CourseTeamPublication.state == "published",
            CourseMember.role == "teacher",
            Team.owner_user_id == CourseTeamPublication.publisher_user_id,
            Team.ownership_scope == "personal",
            Team.visibility == "public",
            Team.deleted_at.is_(None),
            Team.current_version_seq == TeamVersion.version_seq,
            Team.authorization_epoch == CourseTeamPublication.authorization_epoch,
        )
        .order_by(Team.display_name, Team.id)
    ).all()
    entries: list[MayaTeamDirectoryEntry] = []
    for publication, team, version in rows:
        members = _member_rows(db, version.id)
        directory_members: list[DirectoryMemberDTO] = []
        leader_name = ""
        for member in members:
            dto = _team_member_dto(member)
            if dto.is_leader:
                leader_name = dto.display_name
            directory_members.append(
                DirectoryMemberDTO(
                    display_name=dto.display_name,
                    avatar_config=dto.avatar_config,
                    position=dto.position,
                    is_leader=dto.is_leader,
                )
            )
        entries.append(
            MayaTeamDirectoryEntry(
                id=_uid(team.id),
                team_version_id=_uid(version.id),
                course_id=_uid(team.course_id),
                display_name=team.display_name,
                leader_display_name=leader_name,
                members=directory_members,
                published_at=publication.published_at,
            )
        )
    return entries


@dataclass(frozen=True)
class FrozenTeamMember:
    binding_id: str
    agent_id: str
    agent_version_id: str
    position: int
    is_leader: bool
    display_name: str
    avatar_config: dict[str, object]
    invoke_grant_id: str | None
    own_knowledge_set_ids: tuple[str, ...]


@dataclass(frozen=True)
class FrozenTeamSelection:
    team_id: str
    team_version_id: str
    course_id: str
    owner_user_id: str
    display_name: str
    publication_id: str | None
    publication_epoch: int | None
    team_authorization_epoch: int
    require_publication: bool
    members: tuple[FrozenTeamMember, ...]
    leader_binding_id: str
    shared_knowledge_set_ids: tuple[str, ...]
    invokable_binding_ids: tuple[str, ...]


def resolve_chat_entry(
    db: Session,
    actor: AuthContext | str,
    team_id: str,
    team_version_id: str | None = None,
    *,
    require_publication: bool = False,
    target_binding_ids: set[str] | None = None,
) -> FrozenTeamSelection:
    """Resolve a Team selection after checking current course and Team ACLs.

    This is a resource-selection service only. Chat decides its entry kind and
    Tool classes; a Team grant can never be used outside this Team version.
    """

    user_id = _actor_id(actor)
    team = db.scalar(select(Team).where(Team.id == team_id, Team.deleted_at.is_(None)))
    if team is None or course_member_role(db, user_id, team.course_id) is None:
        raise not_found()
    version = (
        db.get(TeamVersion, team_version_id)
        if team_version_id is not None
        else _version_for_seq(db, team)
    )
    if (
        version is None
        or version.team_id != team.id
        or version.version_seq != team.current_version_seq
        or version.authorization_epoch != team.authorization_epoch
    ):
        raise not_found()
    publication = db.scalar(
        select(CourseTeamPublication).where(
            CourseTeamPublication.team_id == team.id,
            CourseTeamPublication.team_version_id == version.id,
            CourseTeamPublication.course_id == team.course_id,
            CourseTeamPublication.publisher_user_id == team.owner_user_id,
            CourseTeamPublication.authorization_epoch == team.authorization_epoch,
            CourseTeamPublication.state == "published",
        )
    )
    teacher_public = (
        publication is not None
        and team.ownership_scope == "personal"
        and team.visibility == "public"
        and team.owner_user_id is not None
        and course_member_role(db, team.owner_user_id, team.course_id) == "teacher"
    )
    if require_publication and not teacher_public:
        raise not_found()
    if not teacher_public:
        publication = None
        if not can_read_team(db, user_id, team):
            raise not_found()
    members = _member_rows(db, version.id)
    all_member_ids = {member.id for member in members}
    requested_targets = all_member_ids if target_binding_ids is None else set(target_binding_ids)
    if not requested_targets or not requested_targets.issubset(all_member_ids):
        raise not_found()
    resolved_members: list[FrozenTeamMember] = []
    leader_id: str | None = None
    for member in members:
        grant_id = _grant_id_for_member(db, publication, team, version, member)
        if member.id in requested_targets:
            _validate_member_current(
                db,
                team=team,
                version=version,
                member=member,
                actor=actor,
                resource_owner_id=publication.publisher_user_id if publication else user_id,
                publication=publication,
            )
        dto = _team_member_dto(member)
        resolved_members.append(
            FrozenTeamMember(
                binding_id=member.id,
                agent_id=live_link(member.agent_id, "Agent"),
                agent_version_id=live_link(member.agent_version_id, "Agent version"),
                position=member.position,
                is_leader=member.is_leader,
                display_name=dto.display_name,
                avatar_config=dto.avatar_config,
                invoke_grant_id=grant_id,
                own_knowledge_set_ids=tuple(
                    str(snapshot["id"]) for snapshot in _own_knowledge_set_snapshots(member)
                ),
            )
        )
        if member.is_leader:
            leader_id = member.id
    if leader_id is None or len(resolved_members) < 2:
        raise not_found()
    shared_sets = [_required_set_id(row.knowledge_set_id) for row in _set_rows(db, version.id)]
    resource_owner_id = publication.publisher_user_id if publication else user_id
    if requested_targets:
        _validate_shared_sets_current(db, team, version, resource_owner_id)
    return FrozenTeamSelection(
        team_id=team.id,
        team_version_id=version.id,
        course_id=team.course_id,
        owner_user_id=team.owner_user_id,
        display_name=version.display_name,
        publication_id=publication.id if publication else None,
        publication_epoch=publication.authorization_epoch if publication else None,
        team_authorization_epoch=team.authorization_epoch,
        require_publication=require_publication,
        members=tuple(resolved_members),
        leader_binding_id=leader_id,
        shared_knowledge_set_ids=tuple(shared_sets),
        invokable_binding_ids=tuple(
            member.id for member in members if member.id in requested_targets
        ),
    )


def _own_knowledge_set_snapshots(member: TeamVersionMember) -> list[dict[str, object]]:
    try:
        values = json.loads(member.own_knowledge_set_snapshots_json)
    except (TypeError, ValueError):
        raise not_found() from None
    if not isinstance(values, list) or any(not isinstance(value, dict) for value in values):
        raise not_found()
    return cast(list[dict[str, object]], values)


def _grant_id_for_member(
    db: Session,
    publication: CourseTeamPublication | None,
    team: Team,
    version: TeamVersion,
    member: TeamVersionMember,
) -> str | None:
    if publication is None:
        return None
    grant = db.scalar(
        select(TeamMemberInvokeGrant).where(
            TeamMemberInvokeGrant.publication_id == publication.id,
            TeamMemberInvokeGrant.team_version_id == version.id,
            TeamMemberInvokeGrant.team_member_id == member.id,
            TeamMemberInvokeGrant.agent_id == member.agent_id,
            TeamMemberInvokeGrant.agent_version_id == member.agent_version_id,
            TeamMemberInvokeGrant.authorization_epoch == team.authorization_epoch,
        )
    )
    return grant.id if grant is not None else None


def _member_unavailable(team: Team, member: TeamVersionMember, reason: str) -> PlatformError:
    """Log which member check refused a Team, then refuse it as not found.

    Bug (2026-10-13): a student's Team could neither chat nor save while all
    its members looked present, and nothing said which check failed.
    """

    LOGGER.warning(
        "Team member unavailable team_id=%s agent_id=%s agent_version_id=%s reason=%s",
        team.id,
        member.agent_id,
        member.agent_version_id,
        reason,
    )
    return not_found()


def _validate_member_current(
    db: Session,
    *,
    team: Team,
    version: TeamVersion,
    member: TeamVersionMember,
    actor: AuthContext | str,
    resource_owner_id: str,
    publication: CourseTeamPublication | None,
) -> None:
    agent = db.get(Agent, member.agent_id)
    agent_version = db.get(AgentVersion, member.agent_version_id)
    if (
        agent is None
        or agent_version is None
        or agent.deleted_at is not None
        or agent.status != "active"
        or agent.course_id != team.course_id
        or agent_version.agent_id != agent.id
        or agent_version.state not in {"published", "superseded"}
        or agent.authorization_epoch != agent_version.authorization_epoch
    ):
        raise _member_unavailable(team, member, "agent_or_version_unavailable")
    try:
        source_fences = json.loads(member.raw_source_fences_json)
    except (TypeError, ValueError):
        raise _member_unavailable(team, member, "source_fences_unparseable") from None
    if not isinstance(source_fences, list) or not _raw_source_fences_current(
        db,
        resource_owner_id,
        cast(list[dict[str, object]], source_fences),
        agent_version_id=live_link(member.agent_version_id, "Agent version"),
        course_id=team.course_id,
    ):
        raise _member_unavailable(team, member, "rag_source_changed_or_hidden")
    if publication is not None:
        grant_id = _grant_id_for_member(db, publication, team, version, member)
        if grant_id is None:
            raise _member_unavailable(team, member, "publication_grant_missing")
        owner_role = _agent_workspace_role(db, team.owner_user_id, agent)
        if owner_role is None or not can_read_version(
            db, agent_version, agent, owner_role, context=team.owner_user_id
        ):
            raise _member_unavailable(team, member, "owner_cannot_read_version")
    else:
        role = _agent_workspace_role(db, actor, agent)
        if role is None or not can_read_version(db, agent_version, agent, role, context=actor):
            raise _member_unavailable(team, member, "actor_cannot_read_version")
    for snapshot in _own_knowledge_set_snapshots(member):
        set_id = snapshot.get("id")
        row = db.get(KnowledgeSet, str(set_id)) if set_id else None
        if (
            row is None
            or row.course_id != team.course_id
            or row.authorization_epoch != snapshot.get("authorization_epoch")
            or not _knowledge_set_currently_readable(db, resource_owner_id, row)
        ):
            raise _member_unavailable(team, member, "knowledge_set_changed")


def _validate_shared_sets_current(
    db: Session, team: Team, version: TeamVersion, resource_owner_id: str
) -> None:
    for binding in _set_rows(db, version.id):
        row = db.get(KnowledgeSet, binding.knowledge_set_id)
        if (
            row is None
            or row.course_id != team.course_id
            or row.authorization_epoch != binding.authorization_epoch
            or not _knowledge_set_currently_readable(db, resource_owner_id, row)
        ):
            raise not_found()


def resolve_frozen_chat_selection(
    db: Session,
    actor: AuthContext | str,
    frozen_selection: FrozenTeamSelection,
    target_binding_ids: set[str] | None = None,
) -> None:
    """Recheck an existing frozen Team selection without selecting its new head."""

    targets = None if target_binding_ids is None else frozenset(target_binding_ids)
    memoized(
        db,
        ("frozen_chat_selection_valid", _actor_id(actor), repr(frozen_selection), targets),
        lambda: _resolve_frozen_chat_selection(db, actor, frozen_selection, target_binding_ids),
        across_sessions=True,
    )


def _resolve_frozen_chat_selection(
    db: Session,
    actor: AuthContext | str,
    frozen_selection: FrozenTeamSelection,
    target_binding_ids: set[str] | None,
) -> None:
    user_id = _actor_id(actor)
    targets = (
        set(frozen_selection.invokable_binding_ids)
        if target_binding_ids is None
        else set(target_binding_ids)
    )
    if (
        not targets
        or not targets.issubset(set(frozen_selection.invokable_binding_ids))
        or frozen_selection.team_authorization_epoch < 0
    ):
        raise not_found()
    team = db.scalar(
        select(Team).where(
            Team.id == frozen_selection.team_id,
            Team.deleted_at.is_(None),
            Team.course_id == frozen_selection.course_id,
            Team.owner_user_id == frozen_selection.owner_user_id,
            Team.authorization_epoch == frozen_selection.team_authorization_epoch,
        )
    )
    if team is None or course_member_role(db, user_id, team.course_id) is None:
        raise not_found()
    version = db.get(TeamVersion, frozen_selection.team_version_id)
    if (
        version is None
        or version.team_id != team.id
        or version.authorization_epoch != frozen_selection.team_authorization_epoch
        or version.display_name != frozen_selection.display_name
    ):
        raise not_found()
    publication: CourseTeamPublication | None = None
    if frozen_selection.require_publication:
        if team.ownership_scope != "personal":
            raise not_found()
        publication = db.scalar(
            select(CourseTeamPublication).where(
                CourseTeamPublication.id == frozen_selection.publication_id,
                CourseTeamPublication.team_id == team.id,
                CourseTeamPublication.team_version_id == version.id,
                CourseTeamPublication.course_id == team.course_id,
                CourseTeamPublication.publisher_user_id == team.owner_user_id,
                CourseTeamPublication.authorization_epoch == frozen_selection.publication_epoch,
                CourseTeamPublication.state.in_(("published", "retained")),
            )
        )
        if (
            publication is None
            or publication.authorization_epoch != frozen_selection.team_authorization_epoch
            or course_member_role(db, team.owner_user_id, team.course_id) != "teacher"
        ):
            raise not_found()
    elif teacher_uses_student_public_team(db, user_id, team):
        # Bug (2026-10-19): a teacher opened a student's public Team (listed by
        # can_read_team) but every send 404ed here: the group check needs a
        # student inside the group. The teacher uses it as themselves, with no
        # publication: resource_owner_id below stays the teacher, so a member
        # or shared Set the teacher may not read is refused, never borrowed.
        pass
    elif uses_teacher_public_team(db, user_id, team):
        # Teacher-owned Public Teams (personal or group) are usable by every
        # course member; do not refuse with not_in_team_group.
        pass
    else:
        if team.group_id is not None:
            try:
                _can_access_group_scope(db, user_id, team.group_id, team.course_id)
            except PlatformError:
                log_team_chat_refused(team, user_id, "not_in_team_group", check="team_recheck")
                raise not_found(
                    "This Team belongs to another group. Open a Team from your "
                    "own group, a teacher Public Team, or one you own."
                ) from None
        if team.owner_user_id != user_id and (
            team.ownership_scope != "group"
            or team.visibility != "public"
            or team.group_id is None
            or scoped_group_role_for_user(db, user_id, team.group_id) != "student"
        ):
            # Bug (2026-10-18): a student who opened a teacher's public Team
            # from the Teams list got an ordinary Team Chat (no recipe, so no
            # stored publication). resolve_chat_entry let it in through the
            # live publication, but this recheck did not, so every member
            # looked unavailable and the Chat could never send. Recheck it the
            # same way: through the teacher's current publication of this
            # exact Team version, checked as the publisher.
            publication = live_teacher_publication(db, team, version)
            if publication is None:
                log_team_chat_refused(
                    team, user_id, "not_owner_and_not_public_to_caller", check="team_recheck"
                )
                raise not_found(
                    "This Team is not available to you. Use a Team you own, a "
                    "Public Team in your group, or a teacher Public Team."
                )

    current_members = _member_rows(db, version.id)
    frozen_members = {member.binding_id: member for member in frozen_selection.members}
    current_ids = {member.id for member in current_members}
    if current_ids != set(frozen_members) or len(current_members) < 2:
        raise not_found()
    if (
        not any(member.is_leader for member in current_members)
        or sum(member.is_leader for member in current_members) != 1
    ):
        raise not_found()
    current_sets = tuple(row.knowledge_set_id for row in _set_rows(db, version.id))
    if current_sets != frozen_selection.shared_knowledge_set_ids:
        raise not_found()
    resource_owner_id = publication.publisher_user_id if publication else user_id
    _validate_shared_sets_current(db, team, version, resource_owner_id)
    for member in current_members:
        frozen_member = frozen_members[member.id]
        if (
            member.agent_id != frozen_member.agent_id
            or member.agent_version_id != frozen_member.agent_version_id
            or member.position != frozen_member.position
            or member.is_leader != frozen_member.is_leader
            or member.display_name != frozen_member.display_name
        ):
            raise not_found()
        if member.id in targets:
            _validate_member_current(
                db,
                team=team,
                version=version,
                member=member,
                actor=actor,
                resource_owner_id=resource_owner_id,
                publication=publication,
            )


def assert_current_chat_targets(
    db: Session,
    actor: AuthContext | str,
    frozen_selection: FrozenTeamSelection,
    target_binding_ids: set[str] | None = None,
) -> None:
    """Fence a frozen Team before chat claim/send/result publication."""
    resolve_frozen_chat_selection(db, actor, frozen_selection, target_binding_ids)


def follow_published_agent(db: Session, agent_id: str) -> None:
    """Move every live Team holding this Agent to its members' current versions.

    Owner decision (2026-10-12): publishing a member Agent again updates its
    Teams with no Done from the teacher. Each Team is saved as its owner,
    through the same checks as an edit; one that can no longer be saved, for
    example a Public Team whose member became Private, keeps its version.
    """

    candidates = (
        db.execute(
            select(Team.id)
            .join(
                TeamVersion,
                (TeamVersion.team_id == Team.id)
                & (TeamVersion.version_seq == Team.current_version_seq),
            )
            .join(TeamVersionMember, TeamVersionMember.team_version_id == TeamVersion.id)
            .where(
                Team.deleted_at.is_(None),
                Team.owner_user_id.is_not(None),
                TeamVersionMember.agent_id == agent_id,
            )
            .distinct()
        )
        .scalars()
        .all()
    )
    for team_id in candidates:
        team = db.get(Team, team_id)
        owner = db.get(User, team.owner_user_id) if team and team.owner_user_id else None
        if team is None or owner is None or owner.status != "active":
            continue
        version = _version_for_seq(db, team)
        members = _member_rows(db, version.id)
        current: list[TeamMemberInput] = []
        changed = False
        for member in members:
            agent = db.get(Agent, member.agent_id)
            latest = agent.current_published_version_id if agent is not None else None
            target = latest or member.agent_version_id
            changed = changed or target != member.agent_version_id
            current.append(
                TeamMemberInput(
                    agent_version_id=UUID(target),
                    is_leader=member.is_leader,
                    position=member.position,
                )
            )
        if not changed:
            continue
        request = SaveTeamVersionRequest(
            display_name=team.display_name,
            visibility=team.visibility,  # type: ignore[arg-type]
            members=current,
            shared_knowledge_set_ids=[
                UUID(row.knowledge_set_id) for row in _set_rows(db, version.id)
            ],
            expected_metadata_revision=team.metadata_revision,
        )
        try:
            save_team_version(db, AuthContext("", None, owner, ""), team.id, request)  # type: ignore[arg-type]
            db.commit()
        except PlatformError as error:
            db.rollback()
            LOGGER.warning(
                "Team kept its version after a member was published team_id=%s code=%s",
                team_id,
                error.code,
            )
            continue
        try:
            from app.modules.teams.retarget import retarget_team_chats

            retarget_team_chats(db, team.id)
        except Exception:  # noqa: BLE001
            db.rollback()
            LOGGER.exception("Team chat retarget failed team_id=%s", team_id)
