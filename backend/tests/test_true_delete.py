"""Real deletion leaves Debates, Records and chat history intact."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.core.models import (
    Agent,
    AgentVersion,
    AgentVersionDocument,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeSnapshot,
    SnapshotDocument,
    StoredFile,
    VoiceProfile,
)
from app.modules.debates.models import DebateKnowledgeCopy, DebateParticipant, DebateVoiceClone
from app.modules.debates.playback.sql_repository import SqlPlaybackRepository, SqlRow
from app.modules.debates.voice_clones import sweep_debate_voice_clones
from app.modules.knowledge.files import write_atomic
from app.modules.knowledge_sets.models import (
    AgentKnowledgeSet,
    KnowledgeSet,
    KnowledgeSetMarkdownVersion,
)
from app.modules.real_delete import (
    hard_delete_agent,
    hard_delete_document,
    hard_delete_knowledge_set,
    hard_delete_voice,
    prune_agent_versions,
)
from app.modules.workspace.chat import session_view
from app.modules.workspace.models import Conversation
from app.seed import BOWEN_ID
from sqlalchemy import select

from tests import test_wave2_setup as debate_fixtures
from tests.conftest import login
from tests.test_debate_voice_clones import (
    FakeCloneProvider,
    _create_voiced_debate,
    _voice_with_sample,
)
from tests.test_wave2_setup import (
    COURSE_ID,
    GROUP_DEMO_ID,
    _insert_published_agent,
    headers,
)

debate_app = debate_fixtures.debate_app


def test_debate_keeps_its_copy_after_voice_and_agent_are_deleted(debate_app: Any) -> None:
    app, database, client = debate_app
    settings = app.state.settings
    settings.fallback_voice_profile_id = None
    voice_id = _voice_with_sample(database, settings)
    debate_id = _create_voiced_debate(database, client, voice_id)
    provider = FakeCloneProvider()
    with database.session() as db:
        participant = db.scalars(
            select(DebateParticipant).where(
                DebateParticipant.debate_id == debate_id, DebateParticipant.order_index == 0
            )
        ).one()
        assert participant.agent_md_snapshot
        owned = db.get(KnowledgeSnapshot, participant.knowledge_snapshot_id)
        assert owned is not None and owned.owner_debate_id == debate_id
        original_agent = participant.agent_id
        sweep_debate_voice_clones(
            db, data_root=settings.resolved_data_root, settings=settings, provider=provider
        )
        profile = db.get(VoiceProfile, voice_id)
        assert profile is not None
        hard_delete_voice(db, profile, settings.resolved_data_root)
        db.commit()
        clone = db.scalars(
            select(DebateVoiceClone).where(DebateVoiceClone.debate_id == debate_id)
        ).one()
        assert clone.status == "ready"
        row = SqlRow(
            {
                "debate_id": debate_id,
                "effective_voice_kind": "platform_profile",
                "effective_voice_profile_id": None,
                "voice_snapshot_json": participant.voice_snapshot_json,
            }
        )
        voice = SqlPlaybackRepository.resolve_effective_voice(
            db, row, settings.model_copy(update={"tts_provider": "dashscope"})
        )
        assert voice.voice_token == provider.enrolled[0]
        agent = db.get(Agent, original_agent)
        assert agent is not None
        hard_delete_agent(db, agent, settings.resolved_data_root)
        db.commit()
        db.refresh(participant)
        assert participant.agent_id is None
        assert participant.agent_md_snapshot
        still = db.get(KnowledgeSnapshot, participant.knowledge_snapshot_id)
        assert still is not None and still.owner_debate_id == debate_id
        assert db.get(Agent, original_agent) is None


def test_deleted_agent_chat_stays_readable_and_cannot_continue(debate_app: Any) -> None:
    app, database, client = debate_app
    settings = app.state.settings
    agent_id, version_id, _snapshot = _insert_published_agent(
        database, group_id=GROUP_DEMO_ID, name="Readable"
    )
    _payload, csrf = login(client, "bowen")
    token = client.cookies.get("maya_session")
    assert token
    created = client.post(
        "/api/v1/conversations",
        headers={"X-CSRF-Token": csrf, "Origin": "http://testserver"},
        json={"version_id": version_id},
    )
    assert created.status_code == 200, created.text
    conversation_id = created.json()["id"]
    with database.session() as db:
        agent = db.get(Agent, agent_id)
        assert agent is not None
        hard_delete_agent(db, agent, settings.resolved_data_root)
        db.commit()
        from app.modules.auth.service import get_auth_context

        context = get_auth_context(db, settings, token)
        assert context is not None
        row = db.get(Conversation, conversation_id)
        assert row is not None and row.source_removed_at is not None
        view = session_view(db, row, context, settings)
    assert view.can_send is False
    assert view.agent.deleted is True
    assert view.agent.name == "Readable"
    refused = client.post(
        f"/api/v1/conversations/{conversation_id}/messages:stream",
        headers={
            "X-CSRF-Token": csrf,
            "Origin": "http://testserver",
            "Accept": "text/event-stream",
        },
        json={"request_id": str(uuid4()), "expected_revision": view.revision, "message": "hi"},
    )
    assert refused.status_code == 409
    assert refused.json()["code"] == "agent_deleted"


def test_prune_keeps_current_and_previous_agent_md_only(debate_app: Any) -> None:
    _app, database, _client = debate_app
    agent_id, current_id, _snapshot = _insert_published_agent(
        database, group_id=GROUP_DEMO_ID, name="Pruned"
    )
    now = datetime.now(UTC)
    older_ids = []
    with database.session() as db:
        current = db.get(AgentVersion, current_id)
        assert current is not None
        current.version_seq = 3
        agent = db.get(Agent, agent_id)
        assert agent is not None
        for seq, state in ((0, "superseded"), (1, "superseded"), (2, "superseded")):
            version_id = str(uuid4())
            older_ids.append(version_id)
            db.add(
                AgentVersion(
                    id=version_id,
                    agent_id=agent_id,
                    version_seq=seq,
                    state=state,
                    revision=1,
                    agent_md=f"version {seq}",
                    avatar_config_json=current.avatar_config_json,
                    created_at=now,
                    updated_at=now,
                )
            )
        db.commit()
    with database.session() as db:
        removed = prune_agent_versions(db, agent_id, database.data_root)
        db.commit()
        remaining = {
            row.version_seq: row.agent_md
            for row in db.scalars(
                select(AgentVersion).where(AgentVersion.agent_id == agent_id)
            ).all()
        }
        assert removed >= 1
        assert 3 in remaining
        assert 2 in remaining
        assert 0 not in remaining
        links = db.scalars(
            select(AgentVersionDocument).where(
                AgentVersionDocument.agent_version_id.in_(
                    select(AgentVersion.id).where(AgentVersion.agent_id == agent_id)
                )
            )
        ).all()
        assert links == []


def test_rag_knowledge_voice_and_agent_deletion_keeps_debate_material(
    debate_app: Any,
) -> None:
    """A Debate replays from its own RAG, Knowledge text and voice clone."""

    app, database, client = debate_app
    settings = app.state.settings
    settings.fallback_voice_profile_id = None
    voice_id = _voice_with_sample(database, settings)
    agent_id, version_id, snapshot_id = _insert_published_agent(
        database, group_id=GROUP_DEMO_ID, name="Source"
    )
    other_id, _, _ = _insert_published_agent(database, group_id=GROUP_DEMO_ID, name="Other")
    rag_text = "RAG_CANARY_FOR_DEBATE"
    knowledge_text = "KNOWLEDGE_CANARY_FOR_DEBATE"
    now = datetime.now(UTC)
    document_id, set_id = str(uuid4()), str(uuid4())
    relative = f"groups/{GROUP_DEMO_ID}/knowledge/{document_id}/source.md"
    digest, size = write_atomic(settings.resolved_data_root, relative, rag_text.encode())
    with database.session() as db:
        file_id = str(uuid4())
        db.add(
            StoredFile(
                id=file_id,
                kind="markdown",
                relative_path=relative,
                sha256=digest,
                size_bytes=size,
                state="active",
                created_at=now,
                updated_at=now,
            )
        )
        db.flush()
        db.add(
            KnowledgeDocument(
                id=document_id,
                group_id=GROUP_DEMO_ID,
                owner_user_id=BOWEN_ID,
                course_id=COURSE_ID,
                source_filename="source.md",
                stored_file_id=file_id,
                char_count=len(rag_text),
                content_hash=hashlib.sha256(rag_text.encode()).hexdigest(),
                created_at=now,
                updated_at=now,
            )
        )
        doc_row_id = str(uuid4())
        db.add(
            SnapshotDocument(
                id=doc_row_id,
                snapshot_id=snapshot_id,
                document_id=document_id,
                stored_file_id=file_id,
                source_filename="source.md",
                char_count=len(rag_text),
                order_index=0,
            )
        )
        db.flush()
        db.add(
            KnowledgeChunk(
                id=str(uuid4()),
                snapshot_id=snapshot_id,
                snapshot_document_id=doc_row_id,
                document_id=document_id,
                chunk_index=0,
                chunk_text=rag_text,
                start_offset=0,
                end_offset=len(rag_text),
                embedding_blob=b"\x00",
                embedding_dimension=1,
                embedding_key="mock",
            )
        )
        db.add(
            KnowledgeSet(
                id=set_id,
                owner_user_id=BOWEN_ID,
                course_id=COURSE_ID,
                group_id=GROUP_DEMO_ID,
                ownership_scope="group",
                visibility="public",
                display_name="Frozen set",
                current_markdown_version_seq=1,
                created_at=now,
                updated_at=now,
            )
        )
        db.add(
            KnowledgeSetMarkdownVersion(
                id=str(uuid4()),
                knowledge_set_id=set_id,
                version_seq=1,
                markdown=knowledge_text,
                content_hash=hashlib.sha256(knowledge_text.encode()).hexdigest(),
                origin="manual",
                created_by_user_id=BOWEN_ID,
                created_at=now,
            )
        )
        db.flush()
        db.add(
            AgentKnowledgeSet(
                agent_id=agent_id,
                knowledge_set_id=set_id,
                order_index=0,
                created_by_user_id=BOWEN_ID,
                created_at=now,
            )
        )
        version = db.get(AgentVersion, version_id)
        assert version is not None
        version.voice_profile_id = voice_id
        db.commit()
    _, csrf = login(client)
    created = client.post(
        f"/api/v1/courses/{COURSE_ID}/debates",
        headers=headers(csrf, **{"Idempotency-Key": f"true-delete-{uuid4()}"}),
        json={
            "topic": "How should people learn together?",
            "participants": [
                {"agent_id": agent_id, "stance_mode": "open"},
                {"agent_id": other_id, "stance_mode": "open"},
            ],
            "round_count": 4,
            "rule_set_id": "ordered_multi_expert_mutual_learning_v1",
        },
    )
    assert created.status_code == 201, created.text
    debate_id = str(created.json()["id"])
    provider = FakeCloneProvider()
    with database.session() as db:
        participant = db.scalars(
            select(DebateParticipant).where(
                DebateParticipant.debate_id == debate_id,
                DebateParticipant.order_index == 0,
            )
        ).one()
        owned_id = participant.knowledge_snapshot_id
        assert owned_id != snapshot_id
        copy = db.scalars(
            select(DebateKnowledgeCopy).where(DebateKnowledgeCopy.participant_id == participant.id)
        ).one()
        assert copy.markdown == knowledge_text
        sweep_debate_voice_clones(
            db, data_root=settings.resolved_data_root, settings=settings, provider=provider
        )
        document = db.get(KnowledgeDocument, document_id)
        knowledge = db.get(KnowledgeSet, set_id)
        profile = db.get(VoiceProfile, voice_id)
        agent = db.get(Agent, agent_id)
        assert document is not None and knowledge is not None
        assert profile is not None and agent is not None
        hard_delete_document(db, document, settings.resolved_data_root)
        hard_delete_knowledge_set(db, knowledge, settings.resolved_data_root)
        hard_delete_voice(db, profile, settings.resolved_data_root)
        hard_delete_agent(db, agent, settings.resolved_data_root)
        db.commit()
        still = db.get(KnowledgeSnapshot, owned_id)
        assert still is not None and still.owner_debate_id == debate_id
        kept = db.scalars(
            select(KnowledgeChunk.chunk_text).where(KnowledgeChunk.snapshot_id == owned_id)
        ).all()
        assert rag_text in kept
        assert db.get(KnowledgeDocument, document_id) is None
        assert db.get(KnowledgeSet, set_id) is None
        assert db.get(Agent, agent_id) is None
        frozen = db.scalars(
            select(DebateKnowledgeCopy).where(DebateKnowledgeCopy.debate_id == debate_id)
        ).one()
        assert frozen.markdown == knowledge_text
        db.refresh(participant)
        row = SqlRow(
            {
                "debate_id": debate_id,
                "effective_voice_kind": "platform_profile",
                "effective_voice_profile_id": None,
                "voice_snapshot_json": participant.voice_snapshot_json,
            }
        )
        voice = SqlPlaybackRepository.resolve_effective_voice(
            db, row, settings.model_copy(update={"tts_provider": "dashscope"})
        )
        assert voice.voice_token == provider.enrolled[0]
