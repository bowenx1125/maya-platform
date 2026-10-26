"""Auto-publish the Agents that lose a RAG file or a Voice.

Owner decision (2026-10-20): deleting (or editing) a RAG file or a Voice
publishes a new version of every live Agent whose current published version
uses it. The deleted file is dropped and a deleted Voice is cleared, so the
Agent keeps working (no RAG -> plain Agent, no Voice -> silent in Immerse).
The publish runs as the Agent's owner and reuses that owner's existing
provider consent; nobody is prompted. Teams follow through the normal
``follow_published_agent`` hook inside publish. Debates keep their own
version and snapshot and are never touched.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.db import Database
from app.core.errors import PlatformError
from app.core.models import (
    Agent,
    AgentVersion,
    AgentVersionDocument,
    FileOperation,
    KnowledgeDocument,
    User,
)
from app.core.sqlutil import begin_immediate

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class AffectedAgent:
    agent_id: str
    name: str
    owner_user_id: str | None
    version_seq: int


def _live_current_versions(db: Session) -> Any:
    return (
        select(Agent, AgentVersion)
        .join(AgentVersion, AgentVersion.id == Agent.current_published_version_id)
        .where(
            Agent.deleted_at.is_(None),
            Agent.status == "active",
            AgentVersion.state == "published",
        )
    )


def affected_agents(
    db: Session,
    *,
    document_ids: Iterable[str] = (),
    voice_profile_ids: Iterable[str] = (),
    viewer_user_id: str | None = None,
) -> list[AffectedAgent]:
    """Live Agents whose current published version uses any given file or Voice."""

    docs = [str(item) for item in document_ids]
    voices = [str(item) for item in voice_profile_ids]
    found: dict[str, AffectedAgent] = {}
    if docs:
        rows = db.execute(
            _live_current_versions(db)
            .join(
                AgentVersionDocument,
                AgentVersionDocument.agent_version_id == AgentVersion.id,
            )
            .where(AgentVersionDocument.document_id.in_(docs))
        ).all()
        for agent, version in rows:
            found[agent.id] = AffectedAgent(
                agent.id, agent.name, agent.owner_user_id, version.version_seq
            )
    if voices:
        rows = db.execute(
            _live_current_versions(db).where(AgentVersion.voice_profile_id.in_(voices))
        ).all()
        for agent, version in rows:
            found[agent.id] = AffectedAgent(
                agent.id, agent.name, agent.owner_user_id, version.version_seq
            )
    if viewer_user_id is not None:
        from app.modules.knowledge.services import can_use_agent

        # Source ownership does not grant visibility into another owner's
        # private Agent. Background cascades still need the full affected set.
        found = {
            agent_id: item
            for agent_id, item in found.items()
            if (agent := db.get(Agent, agent_id)) is not None
            and can_use_agent(db, viewer_user_id, agent)
        }
    return sorted(found.values(), key=lambda item: (item.name.casefold(), item.agent_id))


def agents_using_documents(
    db: Session, document_ids: Iterable[str], *, viewer_user_id: str
) -> dict[str, list[AffectedAgent]]:
    """Per document, the live Agents whose current version uses it.

    One query for every document; only Agents the viewer may use are kept,
    the same filter the per-document affected-agents endpoint applies.
    """

    docs = sorted({str(item) for item in document_ids})
    found: dict[str, list[AffectedAgent]] = {doc: [] for doc in docs}
    if not docs:
        return found
    rows = db.execute(
        _live_current_versions(db)
        .add_columns(AgentVersionDocument.document_id)
        .join(
            AgentVersionDocument,
            AgentVersionDocument.agent_version_id == AgentVersion.id,
        )
        .where(AgentVersionDocument.document_id.in_(docs))
    ).all()
    from app.modules.knowledge.services import can_use_agent

    usable: dict[str, bool] = {}
    for agent, version, document_id in rows:
        if agent.id not in usable:
            usable[agent.id] = can_use_agent(db, viewer_user_id, agent)
        if usable[agent.id]:
            found[document_id].append(
                AffectedAgent(agent.id, agent.name, agent.owner_user_id, version.version_seq)
            )
    for items in found.values():
        items.sort(key=lambda item: (item.name.casefold(), item.agent_id))
    return found


def _owner_context(db: Session, agent: Agent) -> Any:
    from app.modules.auth.service import AuthContext

    owner = db.get(User, agent.owner_user_id) if agent.owner_user_id else None
    if owner is None or owner.status != "active":
        return None
    return AuthContext("", None, owner, "")  # type: ignore[arg-type]


@contextmanager
def _cascade_lock(db: Session, settings: Settings, agent_id: str) -> Iterator[bool]:
    # Publish commits in several transactions. A transaction lock cannot keep
    # a second replica or the recovery sweep out for the whole operation.
    if db.get_bind().dialect.name == "postgresql":
        with Session(bind=db.get_bind()) as lock_db:
            key = {"key": f"agent-cascade:{agent_id}"}
            acquired = bool(
                lock_db.scalar(text("SELECT pg_try_advisory_lock(hashtext(:key))"), key)
            )
            try:
                yield acquired
            finally:
                if acquired:
                    lock_db.execute(text("SELECT pg_advisory_unlock(hashtext(:key))"), key)
        return
    from app.modules.voices.lease_lock import lock_exclusive, unlock

    folder = settings.resolved_data_root / "agent-cascade-locks"
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / f"{UUID(agent_id)}.lock").open("a+b") as handle:
        try:
            lock_exclusive(handle)
        except OSError:
            yield False
            return
        try:
            yield True
        finally:
            unlock(handle)


def _finish_cascade(db: Session, operation_id: str) -> None:
    db.rollback()
    begin_immediate(db)
    operation = db.get(FileOperation, operation_id)
    if operation is None or operation.state != "prepared":
        db.rollback()
        return
    candidate = db.get(AgentVersion, operation.request_id)
    published = (
        candidate is not None
        and candidate.state in {"published", "superseded"}
        and candidate.published_at is not None
    )
    if not published:
        _retire_failed_draft(db, operation.request_id)
    for parked in db.scalars(
        select(FileOperation).where(
            FileOperation.operation_kind == "agent_cascade_park",
            FileOperation.request_id == operation.request_id,
            FileOperation.state == "prepared",
        )
    ).all():
        _restore_parked_draft(db, operation.entity_id, parked.entity_id)
        parked.state = "committed" if published else "recovered"
    operation.state = "committed" if published else "recovered"
    operation.safe_error_code = None if published else "agent_auto_publish_failed"
    operation.updated_at = datetime.now(UTC)
    db.commit()
    if not published:
        LOGGER.warning(
            "Agent auto-bump stopped agent_id=%s operation_id=%s code=agent_auto_publish_failed",
            operation.entity_id,
            operation_id,
        )


def _recover_cascades(db: Session, settings: Settings, agent_id: str | None = None) -> None:
    query = select(FileOperation.id, FileOperation.entity_id).where(
        FileOperation.operation_kind == "agent_cascade_publish",
        FileOperation.state == "prepared",
    )
    if agent_id is not None:
        query = query.where(FileOperation.entity_id == agent_id)
    rows = db.execute(query).all()
    db.rollback()
    for operation_id, owner_id in rows:
        with _cascade_lock(db, settings, owner_id) as acquired:
            if acquired:
                _finish_cascade(db, operation_id)


def bump_agent(
    db: Session,
    settings: Settings,
    agent_id: str,
    *,
    drop_document_ids: Iterable[str] = (),
    drop_voice_profile_ids: Iterable[str] = (),
    refresh_document_ids: Iterable[str] = (),
) -> str | None:
    _recover_cascades(db, settings, agent_id)
    with _cascade_lock(db, settings, agent_id) as acquired:
        if not acquired:
            return None
        return _bump_agent_locked(
            db,
            settings,
            agent_id,
            drop_document_ids=drop_document_ids,
            drop_voice_profile_ids=drop_voice_profile_ids,
            refresh_document_ids=refresh_document_ids,
        )


def _bump_agent_locked(
    db: Session,
    settings: Settings,
    agent_id: str,
    *,
    drop_document_ids: Iterable[str] = (),
    drop_voice_profile_ids: Iterable[str] = (),
    refresh_document_ids: Iterable[str] = (),
) -> str | None:
    """Publish the next version of one Agent without the given files/Voices.

    Returns the new published version id, or ``None`` when nothing applied.
    An owner's unpublished draft is kept: it moves one sequence number up and
    loses the same files/Voice, so their edit is not published by accident.
    """

    from app.modules.agents.persona import raw_agent_md_hash
    from app.modules.agents.router import _publish_agent_version_admitted, _time
    from app.modules.agents.schemas import PublishAgentVersionRequest

    drop_docs = {str(item) for item in drop_document_ids}
    drop_voices = {str(item) for item in drop_voice_profile_ids}
    refresh_docs = {str(item) for item in refresh_document_ids}
    agent = db.get(Agent, agent_id)
    if agent is None or agent.deleted_at is not None or agent.status != "active":
        return None
    current = (
        db.get(AgentVersion, agent.current_published_version_id)
        if agent.current_published_version_id
        else None
    )
    if current is None or current.state != "published":
        return None
    relations = list(
        db.scalars(
            select(AgentVersionDocument)
            .where(AgentVersionDocument.agent_version_id == current.id)
            .order_by(AgentVersionDocument.order_index)
        ).all()
    )
    uses_doc = any(rel.document_id in drop_docs | refresh_docs for rel in relations)
    uses_voice = current.voice_profile_id is not None and current.voice_profile_id in drop_voices
    if not uses_doc and not uses_voice:
        return None
    context = _owner_context(db, agent)
    if context is None:
        LOGGER.warning("Agent auto-bump skipped: owner inactive agent_id=%s", agent_id)
        return None

    sources = list(
        db.execute(
            select(
                KnowledgeDocument.id,
                KnowledgeDocument.stored_file_id,
                KnowledgeDocument.index_revision,
            )
            .where(KnowledgeDocument.id.in_(drop_docs | refresh_docs))
            .order_by(KnowledgeDocument.id)
        ).tuples()
    )
    fingerprint = hashlib.sha256(
        json.dumps(
            [
                current.id,
                sorted(drop_docs),
                sorted(drop_voices),
                sorted(refresh_docs),
                [list(row) for row in sources],
            ],
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    # An interrupted real publication may already have reached the supplier.
    # Keep its durable outcome; the periodic sweep must never authorize a
    # fresh paid retry of the same source change.
    if (
        db.scalar(
            select(FileOperation.id).where(
                FileOperation.operation_kind == "agent_cascade_publish",
                FileOperation.entity_id == agent_id,
                FileOperation.expected_sha256 == fingerprint,
            )
        )
        is not None
    ):
        return None

    max_seq = (
        db.scalar(
            select(func.max(AgentVersion.version_seq)).where(AgentVersion.agent_id == agent.id)
        )
        or current.version_seq
    )
    draft = db.scalar(
        select(AgentVersion).where(AgentVersion.agent_id == agent.id, AgentVersion.state == "draft")
    )
    timestamp = _time()
    # Only one draft may exist per Agent. Park the owner's unpublished edit
    # (same row and id) outside the draft slot, publish the auto version,
    # then put the edit back as the next draft minus the same files/Voice,
    # so it is never published by accident and an open editor keeps its id.
    parked_id: str | None = None
    if draft is not None:
        parked_id = draft.id
        changed = False
        for rel in db.scalars(
            select(AgentVersionDocument).where(
                AgentVersionDocument.agent_version_id == draft.id,
                AgentVersionDocument.document_id.in_(drop_docs or {""}),
            )
        ).all():
            db.delete(rel)
            changed = True
        if draft.voice_profile_id is not None and draft.voice_profile_id in drop_voices:
            draft.voice_profile_id = None
            changed = True
        if changed:
            draft.revision = draft.revision + 1
            if draft.persona_confirmation_revision is not None:
                draft.persona_confirmation_revision = draft.revision
            draft.updated_at = timestamp
        # The state CHECK allows only draft/published/superseded; a superseded
        # row with no published_at is the transient parking spot.
        draft.state = "superseded"
        draft.version_seq = max_seq + 2
        db.flush()
    version = AgentVersion(
        id=str(uuid4()),
        agent_id=agent.id,
        version_seq=max_seq + 1,
        state="draft",
        revision=0,
        agent_md=current.agent_md,
        raw_agent_md_hash=raw_agent_md_hash(current.agent_md),
        persona_spec_json=current.persona_spec_json,
        persona_spec_hash=current.persona_spec_hash,
        persona_compiler_version=current.persona_compiler_version,
        persona_diagnostics_json=current.persona_diagnostics_json,
        persona_confirmation_revision=(
            0 if current.persona_confirmation_revision is not None else None
        ),
        student_confirmed_at=current.student_confirmed_at,
        persona_confirming_user_id=current.persona_confirming_user_id,
        persona_required=current.persona_required,
        avatar_config_json=current.avatar_config_json,
        voice_profile_id=None if uses_voice else current.voice_profile_id,
        knowledge_snapshot_id=None,
        authorization_epoch=agent.authorization_epoch,
        draft_visibility=current.published_visibility or current.draft_visibility,
        published_visibility=None,
        created_at=timestamp,
        updated_at=timestamp,
    )
    db.add(version)
    db.flush()
    order = 0
    for rel in relations:
        if rel.document_id in drop_docs:
            continue
        db.add(
            AgentVersionDocument(
                agent_version_id=version.id,
                document_id=rel.document_id,
                enabled=rel.enabled,
                order_index=order,
            )
        )
        order += 1
    version_id = version.id
    operation = FileOperation(
        id=str(uuid4()),
        operation_kind="agent_cascade_publish",
        entity_id=agent_id,
        request_id=version_id,
        expected_sha256=fingerprint,
        state="prepared",
        created_at=timestamp,
        updated_at=timestamp,
    )
    db.add(operation)
    if parked_id is not None:
        db.add(
            FileOperation(
                id=str(uuid4()),
                operation_kind="agent_cascade_park",
                entity_id=parked_id,
                request_id=version_id,
                state="prepared",
                created_at=timestamp,
                updated_at=timestamp,
            )
        )
    db.commit()
    operation_id = operation.id
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    try:
        _publish_agent_version_admitted(
            UUID(version_id),
            PublishAgentVersionRequest(expected_revision=0),
            f"auto-bump-{version_id}",
            context,
            db,
            settings,
            request,  # type: ignore[arg-type]
        )
    except PlatformError as error:
        db.rollback()
        LOGGER.warning("Agent auto-bump publish failed agent_id=%s code=%s", agent_id, error.code)
        _finish_cascade(db, operation_id)
        return None
    except Exception:
        _finish_cascade(db, operation_id)
        raise
    _finish_cascade(db, operation_id)
    return version_id


def _restore_parked_draft(db: Session, agent_id: str, parked_id: str | None) -> None:
    if parked_id is None:
        return
    draft = db.get(AgentVersion, parked_id)
    if draft is None or draft.state != "superseded" or draft.published_at is not None:
        return
    max_seq = (
        db.scalar(
            select(func.max(AgentVersion.version_seq)).where(
                AgentVersion.agent_id == agent_id, AgentVersion.id != parked_id
            )
        )
        or 0
    )
    draft.state = "draft"
    draft.version_seq = max_seq + 1
    db.flush()


def _retire_failed_draft(db: Session, version_id: str) -> None:
    leftover = db.get(AgentVersion, version_id)
    if leftover is not None and leftover.state == "draft":
        # A failed publication may already own a snapshot or provider ledger.
        # Retain those references while releasing the unique editable slot.
        leftover.state = "superseded"
        leftover.updated_at = datetime.now(UTC)
        db.flush()


def cascade_removed_sources(
    database: Database,
    settings: Settings,
    *,
    agent_ids: Iterable[str],
    document_ids: Iterable[str] = (),
    voice_profile_ids: Iterable[str] = (),
    refreshed_document_ids: Iterable[str] = (),
) -> list[str]:
    """Background entry point: bump each Agent in its own session.

    ``document_ids`` were deleted (dropped from the Agent);
    ``refreshed_document_ids`` were edited (kept, snapshot rebuilt).
    """

    refreshed = list(refreshed_document_ids)
    docs = list(document_ids)
    voices = list(voice_profile_ids)
    published: list[str] = []
    for agent_id in agent_ids:
        session = database.session_factory()
        session.info["maya_settings"] = settings
        try:
            new_id = bump_agent(
                session,
                settings,
                agent_id,
                drop_document_ids=docs,
                drop_voice_profile_ids=voices,
                refresh_document_ids=refreshed,
            )
            if new_id is not None:
                published.append(new_id)
        except Exception:  # noqa: BLE001 - one Agent must not stop the others
            session.rollback()
            LOGGER.exception("Agent auto-bump crashed agent_id=%s", agent_id)
        finally:
            session.close()
    LOGGER.info(
        "Agent auto-bump done at=%s published=%d", datetime.now(UTC).isoformat(), len(published)
    )
    return published


_SWEEP_LOCK_KEY = 0x4D415941_0228  # "MAYA" + PR number; one sweeper across backends


def stale_agents(db: Session) -> list[tuple[str, list[str], list[str], list[str]]]:
    """Live Agents whose current version still uses a deleted or edited source.

    Derived from durable state only, so it doubles as the restart-recovery
    journal: a job lost to a crash leaves exactly these rows behind.
    Returns ``(agent_id, dropped_doc_ids, dropped_voice_ids, refreshed_doc_ids)``.
    """

    from sqlalchemy.orm import aliased

    from app.core.models import (
        KnowledgeDocument,
        KnowledgeSnapshot,
        SnapshotDocument,
        StoredFile,
        VoiceProfile,
    )

    frozen = aliased(StoredFile)
    live = aliased(StoredFile)
    found: dict[str, tuple[set[str], set[str], set[str]]] = {}

    def slot(agent_id: str) -> tuple[set[str], set[str], set[str]]:
        return found.setdefault(agent_id, (set(), set(), set()))

    for agent, _version, document in db.execute(
        _live_current_versions(db)
        .join(AgentVersionDocument, AgentVersionDocument.agent_version_id == AgentVersion.id)
        .join(KnowledgeDocument, KnowledgeDocument.id == AgentVersionDocument.document_id)
        .add_columns(KnowledgeDocument)
        .where(KnowledgeDocument.workspace_state != "active")
    ).all():
        slot(agent.id)[0].add(document.id)
    for agent, version in db.execute(
        _live_current_versions(db).where(AgentVersion.voice_profile_id.is_not(None))
    ).all():
        voice = db.get(VoiceProfile, version.voice_profile_id)
        if voice is not None and voice.status == "deleted":
            slot(agent.id)[1].add(voice.id)
    for agent, _version, document_id in db.execute(
        _live_current_versions(db)
        .join(KnowledgeSnapshot, KnowledgeSnapshot.id == AgentVersion.knowledge_snapshot_id)
        .join(SnapshotDocument, SnapshotDocument.snapshot_id == KnowledgeSnapshot.id)
        .join(KnowledgeDocument, KnowledgeDocument.id == SnapshotDocument.document_id)
        .join(frozen, frozen.id == SnapshotDocument.stored_file_id)
        .join(live, live.id == KnowledgeDocument.stored_file_id)
        .add_columns(KnowledgeDocument.id)
        .where(
            KnowledgeDocument.workspace_state == "active",
            frozen.sha256 != live.sha256,
        )
    ).all():
        slot(agent.id)[2].add(document_id)
    return [
        (agent_id, sorted(docs), sorted(voices), sorted(refresh - docs))
        for agent_id, (docs, voices, refresh) in sorted(found.items())
    ]


def sweep_stale_agents(database: Database, settings: Settings) -> int:
    """Re-run lost auto-publishes. Idempotent; one sweeper at a time on Postgres."""

    from sqlalchemy import text

    lock_session = database.session_factory()
    try:
        postgres = lock_session.get_bind().dialect.name == "postgresql"
        if (
            postgres
            and not lock_session.execute(
                text("SELECT pg_try_advisory_lock(:k)"), {"k": _SWEEP_LOCK_KEY}
            ).scalar()
        ):
            return 0
        try:
            scan = database.session_factory()
            try:
                _recover_cascades(scan, settings)
                work = stale_agents(scan)
            finally:
                scan.close()
            published = 0
            for agent_id, docs, voices, refresh in work:
                session = database.session_factory()
                session.info["maya_settings"] = settings
                try:
                    if bump_agent(
                        session,
                        settings,
                        agent_id,
                        drop_document_ids=docs,
                        drop_voice_profile_ids=voices,
                        refresh_document_ids=refresh,
                    ):
                        published += 1
                except Exception:  # noqa: BLE001
                    session.rollback()
                    LOGGER.exception("Agent auto-bump sweep failed agent_id=%s", agent_id)
                finally:
                    session.close()
            retarget_session = database.session_factory()
            try:
                for agent_id in _agents_with_stale_chats(retarget_session):
                    retarget_agent_chats(retarget_session, agent_id)
            finally:
                retarget_session.close()
            _sweep_team_chats_and_junk(database, settings)
            if work:
                LOGGER.info("Agent auto-bump sweep stale=%d published=%d", len(work), published)
            return published
        finally:
            if postgres:
                lock_session.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _SWEEP_LOCK_KEY})
    finally:
        lock_session.close()


def _sweep_team_chats_and_junk(database: Database, settings: Settings) -> None:
    """Retarget idle Team chats and drop junk, under the sweep lock already held."""

    from collections.abc import Callable

    def run(label: str, work: Callable[[Session], None]) -> None:
        session = database.session_factory()
        try:
            work(session)
        except Exception:  # noqa: BLE001
            session.rollback()
            LOGGER.exception("%s failed", label)
        finally:
            session.close()

    def retarget_teams(session: Session) -> None:
        from app.modules.teams.retarget import retarget_team_chats, teams_with_stale_chats

        for team_id in teams_with_stale_chats(session):
            retarget_team_chats(session, team_id)

    def drop_abandoned(session: Session) -> None:
        from app.modules.agents.cleanup import sweep_abandoned_agents

        sweep_abandoned_agents(session)

    def drop_failed_uploads(session: Session) -> None:
        from app.modules.knowledge.recovery import purge_failed_knowledge_uploads

        purge_failed_knowledge_uploads(session, settings.resolved_data_root)
        session.commit()

    def drop_failed_voices(session: Session) -> None:
        from app.modules.voices.cleanup import sweep_failed_voices

        sweep_failed_voices(session, settings.resolved_data_root)

    def prune_versions(session: Session) -> None:
        from app.modules.real_delete import prune_agent_versions

        # Versions a chat or attempt still used at publish time are pruned
        # once it has moved on. Only Agents with something to prune are read.
        crowded = session.scalars(
            select(AgentVersion.agent_id)
            .where(AgentVersion.state != "draft")
            .group_by(AgentVersion.agent_id)
            .having(func.count() > 2)
        ).all()
        for agent_id in crowded:
            # One Agent's failure (a constraint only production has) must not
            # leave every later Agent unpruned for the whole round.
            try:
                prune_agent_versions(session, agent_id, settings.resolved_data_root)
                session.commit()
            except Exception:  # noqa: BLE001
                session.rollback()
                LOGGER.exception("Agent version prune failed agent_id=%s", agent_id)

    run("Team chat retarget sweep", retarget_teams)
    run("Abandoned agent sweep", drop_abandoned)
    run("Failed upload sweep", drop_failed_uploads)
    run("Failed voice sweep", drop_failed_voices)
    run("Agent version prune sweep", prune_versions)


def retarget_agent_chats(db: Session, agent_id: str) -> int:
    """Move open single-Agent chats to the Agent's current published version.

    Owner decision (2026-10-20): a chat in progress keeps going after any
    version change, now talking to the new version with its full history
    (turns belong to the conversation, so the new version sees all of them).
    A chat mid-reply (``active_request_id``) is left for the next publish or
    sweep. Deleted Agents are not touched: their chats already refuse to send.
    """

    from sqlalchemy import update

    from app.modules.workspace.models import Conversation

    agent = db.get(Agent, agent_id)
    if agent is None or agent.deleted_at is not None or agent.status != "active":
        return 0
    current = (
        db.get(AgentVersion, agent.current_published_version_id)
        if agent.current_published_version_id
        else None
    )
    if current is None or current.state != "published":
        return 0
    result = db.execute(
        update(Conversation)
        .where(
            Conversation.entry_kind == "agent",
            Conversation.withdrawn_at.is_(None),
            Conversation.active_request_id.is_(None),
            Conversation.agent_version_id != current.id,
            Conversation.agent_version_id.in_(
                select(AgentVersion.id).where(AgentVersion.agent_id == agent.id)
            ),
        )
        .values(
            agent_version_id=current.id,
            snapshot_id=current.knowledge_snapshot_id,
            agent_name_snapshot=agent.name,
            agent_authorization_epoch=agent.authorization_epoch,
        )
        .execution_options(synchronize_session=False)
    )
    db.commit()
    return int(getattr(result, "rowcount", 0) or 0)


def _agents_with_stale_chats(db: Session) -> list[str]:
    from app.modules.workspace.models import Conversation

    return list(
        db.scalars(
            select(Agent.id)
            .join(AgentVersion, AgentVersion.agent_id == Agent.id)
            .join(Conversation, Conversation.agent_version_id == AgentVersion.id)
            .where(
                Agent.deleted_at.is_(None),
                Agent.status == "active",
                Conversation.entry_kind == "agent",
                Conversation.withdrawn_at.is_(None),
                AgentVersion.id != Agent.current_published_version_id,
            )
            .distinct()
        ).all()
    )
