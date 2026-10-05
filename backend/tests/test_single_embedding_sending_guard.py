"""Actual Embedding transport-boundary ACL checks for Single Chat."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from app.core.models import (
    Agent,
    AgentVersion,
    CourseMember,
    KnowledgeDocument,
    ProviderOperation,
    SnapshotDocument,
    StoredFile,
    User,
)
from app.modules.workspace.chat import _chat_sending_guard, claim_chat_send
from app.modules.workspace.chat_provider import retrieve_sources
from app.modules.workspace.models import ChatProviderStandingGrant, Conversation
from app.providers.control_repository import ProviderRepository
from app.seed import COURSE_ID
from fastapi.testclient import TestClient
from sqlalchemy import select

from tests.conftest import login
from tests.test_wave3_mock_rag_delta import GROUP_DEMO_ID, _insert_sql_published_agent
from tests.test_wave4_query_standing_consent import (
    _policy,
    _QueryTransport,
    _realise_snapshot,
)


@pytest.mark.parametrize(
    "mutation",
    [
        "none",
        "actor_inactive",
        "actor_course_removed",
        "source_hidden",
        "source_file_deleted",
        "agent_archived",
        "grant_revoked",
        "claim_superseded",
        "chat_withdrawn",
    ],
)
def test_single_embedding_send_rechecks_live_source_with_actor_context(
    mutation: str,
    client: TestClient,
    app_bundle: Any,
    monkeypatch: Any,
) -> None:
    app, database, settings = app_bundle
    from app.modules.knowledge.providers.adapters import (
        DashScopeEmbeddingAdapter,
        DashScopeEmbeddingConfig,
    )

    agent_id = _insert_sql_published_agent(
        database,
        group_id=GROUP_DEMO_ID,
        name="Single Query Consent",
        evidence="A source that remains available to its published Agent.",
    )
    _realise_snapshot(database, agent_id)
    with database.session() as db:
        agent = db.get(Agent, agent_id)
        assert agent is not None and agent.current_published_version_id is not None
        version_id = agent.current_published_version_id

    config = DashScopeEmbeddingConfig(api_key="fixture-query-key", workspace_id="fixture")
    policy = _policy(config.resolved_endpoint)
    ProviderRepository(database).save_policy_snapshot(policy)
    app.state.settings = app.state.settings.model_copy(
        update={
            "embedding_provider": "dashscope",
            "embedding_provider_policy_hash": policy.policy_hash,
            "dashscope_api_key": "fixture-query-key",
            "dashscope_workspace_id": "fixture",
            "dashscope_region": "cn-beijing",
            "demo_auto_confirm_provider": False,
        }
    )
    transport = _QueryTransport()
    adapter = DashScopeEmbeddingAdapter(config, transport)
    monkeypatch.setattr("app.modules.workspace.chat_provider.embedding_provider", lambda _: adapter)

    _, teacher_csrf = login(client, "maya")
    teacher_headers = {"Origin": "http://testserver", "X-CSRF-Token": teacher_csrf}
    preview = client.get(
        "/api/v1/provider/data-call/chat-standing/disclosure",
        headers=teacher_headers,
        params={"course_id": COURSE_ID, "provider_operation": "embedding_query"},
    )
    assert preview.status_code == 200, preview.text
    reviewed = preview.json()
    assert reviewed["disclosure"]["outbound_field_classes"] == ["current_evidence_excerpt"]
    assert "A source that remains available" not in preview.text
    confirmed = client.post(
        "/api/v1/provider/data-call/disclosure/confirm",
        headers=teacher_headers,
        json={
            "policy_hash": reviewed["policy_hash"],
            "manifest_hash": reviewed["manifest_hash"],
            "expected_revision": reviewed["confirmation_revision"],
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    with database.session() as db:
        grant = db.scalar(
            select(ChatProviderStandingGrant).where(
                ChatProviderStandingGrant.provider_operation == "embedding_query"
            )
        )
        assert grant is not None and grant.policy_hash == policy.policy_hash
        assert grant.field_classes_json == '["current_evidence_excerpt"]'
        grant_id = grant.id

    student, csrf = login(client, "bowen")
    actor_user_id = str(student["user"]["id"])
    created = client.post(
        "/api/v1/conversations",
        headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
        json={"version_id": version_id},
    )
    assert created.status_code == 200, created.text
    conversation_id = str(created.json()["id"])
    request_id = str(uuid4())
    message = "My current retrieval question"
    boundary_seen: list[str] = []
    original_transition = ProviderRepository.transition

    def transition(self: Any, operation_id: str, **kwargs: Any) -> Any:
        if kwargs.get("expected") == "reserved" and kwargs.get("state") == "sending":
            boundary_seen.append(operation_id)
            with database.session() as mutation_db:
                source = mutation_db.scalar(
                    select(KnowledgeDocument)
                    .join(SnapshotDocument, SnapshotDocument.document_id == KnowledgeDocument.id)
                    .join(
                        AgentVersion,
                        AgentVersion.knowledge_snapshot_id == SnapshotDocument.snapshot_id,
                    )
                    .where(AgentVersion.id == version_id)
                )
                assert source is not None
                if mutation == "actor_inactive":
                    actor = mutation_db.get(User, actor_user_id)
                    assert actor is not None
                    actor.status = "inactive"
                elif mutation == "actor_course_removed":
                    membership = mutation_db.get(CourseMember, (COURSE_ID, actor_user_id))
                    assert membership is not None
                    mutation_db.delete(membership)
                elif mutation == "source_hidden":
                    source.workspace_state = "hidden"
                elif mutation == "source_file_deleted":
                    source_file = mutation_db.get(StoredFile, source.stored_file_id)
                    assert source_file is not None
                    source_file.state = "deleted"
                elif mutation == "agent_archived":
                    agent = mutation_db.get(Agent, agent_id)
                    assert agent is not None
                    agent.status = "archived"
                elif mutation == "grant_revoked":
                    standing = mutation_db.get(ChatProviderStandingGrant, grant_id)
                    assert standing is not None
                    standing.revoked_at = datetime.now(UTC)
                elif mutation == "claim_superseded":
                    row = mutation_db.get(Conversation, conversation_id)
                    assert row is not None
                    row.active_request_id = None
                elif mutation == "chat_withdrawn":
                    row = mutation_db.get(Conversation, conversation_id)
                    assert row is not None
                    row.withdrawn_at = datetime.now(UTC)
        return original_transition(self, operation_id, **kwargs)

    monkeypatch.setattr(ProviderRepository, "transition", transition)
    error: str | None = None
    with database.session() as db:
        conversation = db.get(Conversation, conversation_id)
        version = db.get(AgentVersion, version_id)
        assert conversation is not None and version is not None
        turn, is_new = claim_chat_send(
            db,
            conversation,
            request_id=request_id,
            expected_revision=0,
            message=message,
            settings=app.state.settings,
        )
        assert is_new and turn.id == request_id
        try:
            sources = retrieve_sources(
                db,
                app.state.settings,
                version,
                course_id=conversation.course_id,
                scope_id=conversation.id,
                request_id=request_id,
                message=message,
                actor_user_id=actor_user_id,
                turn_id=turn.id,
                claim_revision=1,
                sending_guard=_chat_sending_guard(
                    conversation.id, turn.id, 1, actor_user_id=actor_user_id
                ),
            )
            assert sources
        except Exception as exc:
            error = type(exc).__name__

    assert len(boundary_seen) == 1
    with database.session() as db:
        operation = db.get(ProviderOperation, boundary_seen[0])
        assert operation is not None
        if mutation == "none":
            assert len(transport.calls) == 1
            assert operation.state == "succeeded"
            assert operation.charged_request_count == 1
            assert error is None
        else:
            assert len(transport.calls) == 0
            assert operation.state == "not_sent"
            assert operation.charged_request_count == 0
