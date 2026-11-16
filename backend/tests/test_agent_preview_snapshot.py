"""Published Preview uses the controlled production vector and LLM boundaries."""

from __future__ import annotations

import json
import struct
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from app.core.models import (
    Agent,
    AgentVersion,
    Course,
    CourseMember,
    GroupMember,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeSnapshot,
    ProviderOperation,
)
from app.modules.agents import preview_provider
from app.modules.debates.playback.generation_adapter import SqlSnapshotRetriever
from app.modules.knowledge.mock_lexical import MockLexicalAnchorV2
from app.modules.knowledge.providers import query_embedding
from app.modules.knowledge.providers.adapters import (
    DashScopeEmbeddingAdapter,
    DashScopeEmbeddingConfig,
    EmbeddingTransportResponse,
)
from app.modules.knowledge.vector import IdentityVectorStore, MockVectorStore
from app.modules.runtime_tools.models import RuntimeModelCallStage
from app.modules.workspace import chat_provider
from app.modules.workspace.models import (
    AgentAccountMemory,
    ChatMemoryEntryAction,
    Conversation,
    ConversationTurn,
)
from app.providers.control_repository import ProviderRepository
from app.providers.llm_adapter import DashScopeLLMAdapter, DashScopeLLMConfig
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import func, select

from tests.conftest import login
from tests.test_agent_preview import body, published_version
from tests.test_wave2_setup import COURSE_ID, GROUP_DEMO_ID, headers
from tests.test_wave4_query_standing_consent import _policy, _QueryTransport, _realise_snapshot

BOWEN = "60541c78-30f1-55c5-b2aa-207b6a766883"
KAIKAI = "bc170f51-45fb-5296-a36d-a2edc8f8d315"
EVIDENCE = "Cobalt mechanisms stabilize crystalline lattices."


@pytest.fixture
def real_preview(app_factory: Any, monkeypatch: Any) -> Any:
    app, database, settings = app_factory()
    # Startup seeds memberships before the published fixture is inserted.
    with TestClient(app) as client:
        _, csrf = login(client, "bowen")
        version_id = published_version(database)
        with database.session() as db:
            version = db.get(AgentVersion, version_id)
            assert version is not None
            agent_id = version.agent_id
        _realise_snapshot(database, agent_id)
        with database.session() as db:
            chunk = db.scalar(
                select(KnowledgeChunk).where(
                    KnowledgeChunk.snapshot_id == version.knowledge_snapshot_id
                )
            )
            assert chunk is not None
            chunk.chunk_text = EVIDENCE
            chunk.end_offset = len(EVIDENCE)
            # The exact question has zero vector similarity, despite maximal term overlap.
            db.add(
                KnowledgeChunk(
                    id=str(uuid4()),
                    snapshot_id=chunk.snapshot_id,
                    snapshot_document_id=chunk.snapshot_document_id,
                    document_id=chunk.document_id,
                    chunk_index=1,
                    chunk_text="What is evidence?",
                    start_offset=0,
                    end_offset=17,
                    embedding_blob=struct.pack("<1024f", 0.0, 1.0, *([0.0] * 1022)),
                    embedding_dimension=1024,
                    embedding_key=chunk.embedding_key,
                )
            )
        config = DashScopeEmbeddingConfig(api_key="fixture", workspace_id="fixture")
        policy = _policy(config.resolved_endpoint)
        ProviderRepository(database).save_policy_snapshot(policy)
        settings.embedding_provider = "dashscope"
        settings.embedding_provider_policy_hash = policy.policy_hash
        transport = _QueryTransport()
        embedding = DashScopeEmbeddingAdapter(config, transport)
        monkeypatch.setattr(chat_provider, "embedding_provider", lambda _: embedding)
        llm = DashScopeLLMAdapter(
            DashScopeLLMConfig(
                api_key="fixture",
                workspace_id="fixture",
                model_key=settings.chat_settings().llm_model,
            )
        )
        llm_policy = replace(_policy(llm.config.resolved_endpoint), policy_id="preview-llm-policy")
        ProviderRepository(database).save_policy_snapshot(llm_policy)
        settings.llm_provider = "dashscope"
        settings.llm_provider_policy_hash = llm_policy.policy_hash
        monkeypatch.setattr(preview_provider, "llm_provider", lambda _: llm)
        calls: list[Any] = []

        def reply(*a: Any, **kw: Any) -> Response:
            calls.append(json.loads(kw["content"]))
            return Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {"role": "assistant", "content": "One sentence. Discarded."},
                            "finish_reason": "stop",
                        }
                    ]
                },
            )

        monkeypatch.setattr(preview_provider.HttpxLLMTransport, "post_bytes", reply)
        yield client, database, settings, version_id, csrf, transport, calls


def test_real_identity_vector_ranking_and_single_charged_calls(
    real_preview: Any, monkeypatch: Any
) -> None:
    client, database, _, version_id, csrf, transport, calls = real_preview

    def forbidden(*a: Any, **kw: Any) -> Any:
        pytest.fail("Real Preview must never use mock vectors or lexical ranking")

    monkeypatch.setattr(MockVectorStore, "__init__", forbidden)
    monkeypatch.setattr(MockLexicalAnchorV2, "from_topic", forbidden)
    monkeypatch.setattr(query_embedding, "_mock_embedding", forbidden)
    embedded, searched, policies = [], [], []
    embed = query_embedding.QueryEmbeddingService.embed_query
    search = IdentityVectorStore.search_values
    retrieve = SqlSnapshotRetriever.retrieve

    def embed_spy(self: Any, *a: Any, **kw: Any) -> Any:
        embedded.append(a)
        return embed(self, *a, **kw)

    def search_spy(self: Any, *a: Any, **kw: Any) -> Any:
        searched.append(self.identity.provider)
        return search(self, *a, **kw)

    def retrieve_spy(self: Any, *a: Any, **kw: Any) -> Any:
        policies.append(kw.get("policy_id"))
        return retrieve(self, *a, **kw)

    monkeypatch.setattr(query_embedding.QueryEmbeddingService, "embed_query", embed_spy)
    monkeypatch.setattr(IdentityVectorStore, "search_values", search_spy)
    monkeypatch.setattr(SqlSnapshotRetriever, "retrieve", retrieve_spy)
    models = (
        Conversation,
        ConversationTurn,
        AgentAccountMemory,
        ChatMemoryEntryAction,
        RuntimeModelCallStage,
        AgentVersion,
        KnowledgeSnapshot,
    )
    with database.session() as db:
        before = {model: db.scalar(select(func.count()).select_from(model)) for model in models}
    result = client.post(
        "/api/v1/agents/preview", headers=headers(csrf), json=body(version_id=version_id)
    )
    assert result.status_code == 200, result.text
    assert result.json() == {
        "answer": "One sentence.",
        "audio_base64": None,
        "audio_content_type": None,
    }
    assert len(embedded) == 1 and searched == ["dashscope"] and policies == [None]
    assert len(transport.calls) == len(calls) == 1
    assert transport.calls[0]["input"]["texts"] == ["What is evidence?"]
    messages = calls[0]["messages"]
    assert [item["role"] for item in messages] == ["system", "user"]
    evidence = json.loads(messages[0]["content"].split("\n", 1)[1])["evidence"]
    assert evidence == [{"text": EVIDENCE}]
    assert messages[1] == {"role": "user", "content": "What is evidence?"}
    assert "tools" not in calls[0] and "max_tokens" not in calls[0]
    with database.session() as db:
        assert before == {
            model: db.scalar(select(func.count()).select_from(model)) for model in models
        }
        operations = list(db.scalars(select(ProviderOperation)))
        assert sorted(
            (op.provider_operation, op.state, op.charged_request_count) for op in operations
        ) == [("embedding_query", "succeeded", 1), ("llm_agent_chat", "succeeded", 1)]


@pytest.mark.parametrize("failure", ["embedding", "vector", "llm"])
def test_provider_failure_never_retries_or_falls_back(
    real_preview: Any, monkeypatch: Any, failure: str
) -> None:
    client, database, _, version_id, csrf, transport, calls = real_preview
    attempts = []
    if failure == "embedding":

        def rejected(*a: Any, **kw: Any) -> EmbeddingTransportResponse:
            attempts.append(1)
            return EmbeddingTransportResponse(503, {})

        monkeypatch.setattr(transport, "post", rejected)
    elif failure == "vector":

        def corrupt(*a: Any, **kw: Any) -> Any:
            attempts.append(1)
            raise ValueError("Invalid vector fixture")

        monkeypatch.setattr(IdentityVectorStore, "search_values", corrupt)
    else:

        def rejected_llm(*a: Any, **kw: Any) -> Response:
            attempts.append(1)
            return Response(503)

        monkeypatch.setattr(preview_provider.HttpxLLMTransport, "post_bytes", rejected_llm)
    result = client.post(
        "/api/v1/agents/preview", headers=headers(csrf), json=body(version_id=version_id)
    )
    assert result.status_code == 503, result.text
    assert len(attempts) == 1
    assert not calls
    assert len(transport.calls) == (0 if failure == "embedding" else 1)
    with database.session() as db:
        operations = list(db.scalars(select(ProviderOperation)))
        assert len(operations) == (2 if failure == "llm" else 1)
        assert all(op.attempt_no == 1 for op in operations)
        assert db.scalar(select(func.count()).select_from(Conversation)) == 0


@pytest.mark.parametrize("missing", ["published_version", "snapshot"])
def test_saved_agent_without_snapshot_calls_no_providers(real_preview: Any, missing: str) -> None:
    client, database, _, version_id, csrf, transport, calls = real_preview
    with database.session() as db:
        version = db.get(AgentVersion, version_id)
        agent = db.get(Agent, version.agent_id)
        if missing == "published_version":
            agent.current_published_version_id = None
        else:
            version.knowledge_snapshot_id = None
    result = client.post(
        "/api/v1/agents/preview", headers=headers(csrf), json=body(version_id=version_id)
    )
    assert result.status_code == 409, result.text
    assert result.json()["code"] == "agent_not_published"
    assert result.json()["details"] == {"agent_name": "Preview"}
    assert not transport.calls and not calls
    with database.session() as db:
        assert db.scalar(select(func.count()).select_from(ProviderOperation)) == 0


@pytest.mark.parametrize(
    "case,username,status",
    [
        ("owner_private", "bowen", 200),
        ("other_private", "kaikai", 404),
        ("teacher_public", "maya", 200),
        ("teacher_other_course", "maya", 404),
        ("groupmate", "kaikai", 200),
        ("outside_group", "kaikai", 404),
        ("unreadable", "maya", 404),
        ("cross_course", "bowen", 404),
    ],
)
def test_snapshot_permissions(real_preview: Any, case: str, username: str, status: int) -> None:
    client, database, _, version_id, _, transport, calls = real_preview
    # Login first: the demo catalog must not undo the membership fixture below.
    _, csrf = login(client, username)
    with database.session() as db:
        version = db.get(AgentVersion, version_id)
        agent = db.get(Agent, version.agent_id)
        document = db.scalar(
            select(KnowledgeDocument)
            .join(KnowledgeChunk, KnowledgeChunk.document_id == KnowledgeDocument.id)
            .where(KnowledgeChunk.snapshot_id == version.knowledge_snapshot_id)
        )
        assert document is not None
        if case in {"owner_private", "other_private"}:
            agent.visibility = "private"
            version.published_visibility = "private"
        elif case == "teacher_other_course":
            member = db.get(CourseMember, (COURSE_ID, "08b9de2d-bb75-5c71-a64b-231b48f9eb25"))
            assert member is not None
            db.delete(member)
        elif case == "groupmate":
            db.merge(
                GroupMember(
                    group_id=GROUP_DEMO_ID,
                    user_id=KAIKAI,
                    role="member",
                    created_at=datetime.now(UTC),
                )
            )
        elif case == "outside_group":
            member = db.get(GroupMember, (GROUP_DEMO_ID, KAIKAI))
            if member is not None:
                db.delete(member)
        elif case == "unreadable":
            document.visibility = "private"
            document.owner_user_id = BOWEN
        elif case == "cross_course":
            course = db.scalar(select(Course).where(Course.id != COURSE_ID))
            assert course is not None
            document.course_id = course.id
            document.group_id = None
            document.ownership_scope = "personal"
            document.owner_user_id = BOWEN
    result = client.post(
        "/api/v1/agents/preview", headers=headers(csrf), json=body(version_id=version_id)
    )
    assert result.status_code == status, result.text
    assert len(transport.calls) == len(calls) == (1 if status == 200 else 0)


def test_chat_and_stateless_snapshot_retrieval_are_identical(real_preview: Any) -> None:
    client, database, settings, version_id, csrf, _, _ = real_preview
    created = client.post(
        "/api/v1/conversations", headers=headers(csrf), json={"version_id": version_id}
    )
    assert created.status_code == 200, created.text
    scope_id = created.json()["id"]
    with database.session() as db:
        version = db.get(AgentVersion, version_id)
        assert version is not None
        common = dict(
            course_id=COURSE_ID,
            scope_id=scope_id,
            request_id=str(uuid4()),
            message="What is evidence?",
        )
        chat = chat_provider.retrieve_sources(db, settings, version, **common)
        stateless = chat_provider.retrieve_snapshot_sources(
            db,
            settings,
            version,
            viewer_user_id=BOWEN,
            **{**common, "scope_id": str(uuid4()), "request_id": str(uuid4())},
        )
        assert chat == stateless
        assert [item.excerpt for item in chat] == [EVIDENCE]


@pytest.mark.parametrize("state", ["draft", "superseded"])
def test_editor_version_always_resolves_current_publication(real_preview: Any, state: str) -> None:
    client, database, _, version_id, csrf, transport, calls = real_preview
    other_id = str(uuid4())
    with database.session() as db:
        version = db.get(AgentVersion, version_id)
        assert version is not None
        db.add(
            AgentVersion(
                id=other_id,
                agent_id=version.agent_id,
                version_seq=1,
                state=state,
                revision=0,
                agent_md="This version has no snapshot.",
                avatar_config_json=version.avatar_config_json,
                published_visibility="public" if state == "superseded" else None,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
    result = client.post(
        "/api/v1/agents/preview", headers=headers(csrf), json=body(version_id=other_id)
    )
    assert result.status_code == 200, result.text
    assert EVIDENCE in calls[0]["messages"][0]["content"]
    assert "amber philosopher" in calls[0]["messages"][0]["content"]
    assert len(transport.calls) == len(calls) == 1


def test_relaxed_no_match_reuses_one_query_embedding(real_preview: Any) -> None:
    client, database, _, version_id, csrf, transport, calls = real_preview
    with database.session() as db:
        version = db.get(AgentVersion, version_id)
        assert version is not None
        for chunk in db.scalars(
            select(KnowledgeChunk).where(
                KnowledgeChunk.snapshot_id == version.knowledge_snapshot_id
            )
        ):
            chunk.embedding_blob = struct.pack("<1024f", 0.0, 1.0, *([0.0] * 1022))
    result = client.post(
        "/api/v1/agents/preview", headers=headers(csrf), json=body(version_id=version_id)
    )
    assert result.status_code == 200, result.text
    assert len(transport.calls) == len(calls) == 1
    evidence = json.loads(calls[0]["messages"][0]["content"].split("\n", 1)[1])["evidence"]
    assert evidence == []
