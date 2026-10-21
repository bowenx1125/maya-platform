from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from app.core.config import Settings
from app.core.db import Database
from app.core.models import Agent, AgentVersion, FileOperation, VoiceProfile
from app.main import create_app
from app.modules.agents.cascade import _cascade_lock, bump_agent, sweep_stale_agents
from app.modules.knowledge.recovery import recover_file_operations
from app.seed import BOWEN_ID
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from tests.conftest import login
from tests.test_agent_source_cascade import GROUP_ID, _agent_with_docs, _current, _h, _upload


class ProcessCrash(BaseException):
    pass


@pytest.fixture(params=["sqlite", "postgres"])
def app_bundle(
    app_factory: Callable[..., tuple[FastAPI, Database, Settings]], request: pytest.FixtureRequest
) -> Iterator[tuple[FastAPI, Database, Settings]]:
    bundle = app_factory()
    if request.param == "sqlite":
        yield bundle
        return
    postgres_url = os.environ.get("MAYA_TEST_POSTGRES_URL")
    if not postgres_url:
        bundle[1].dispose()
        pytest.skip("MAYA_TEST_POSTGRES_URL is not set")
    bundle[1].dispose()
    settings = bundle[2].model_copy(update={"database_url": postgres_url})
    database = Database(postgres_url, settings.data_root)
    with database.engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    yield create_app(settings, database), database, settings
    database.dispose()


def _prepared(client: TestClient, database: Database) -> tuple[str, str]:
    _, csrf = login(client, "bowen")
    agent_id = _agent_with_docs(client, csrf, "Recovery Draft", [])
    created = client.post(
        f"/api/v1/agents/{agent_id}/versions",
        headers=_h(csrf, "cascade-recovery-next-draft"),
    )
    assert created.status_code == 201, created.text
    draft_id = created.json()["id"]
    with database.session() as db:
        agent = db.get(Agent, agent_id)
        assert agent is not None
        published = db.get(AgentVersion, agent.current_published_version_id)
        draft = db.get(AgentVersion, draft_id)
        assert published is not None and draft is not None
        published.voice_profile_id = "recovery-voice"
        draft.voice_profile_id = "recovery-voice"
        draft.agent_md = "# Owner draft\n\nDo not publish this edit."
        for version in (published, draft):
            version.persona_confirmation_revision = version.revision
            version.student_confirmed_at = datetime.now(UTC)
            version.persona_confirming_user_id = agent.owner_user_id
    return agent_id, draft_id


@pytest.mark.parametrize(
    "failure", ["exception", "referenced_exception", "crash", "committed_crash"]
)
def test_failure_restores_owner_draft_without_automatic_retry(
    client: TestClient, app_bundle: Any, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    from app.modules.agents import router

    _, database, settings = app_bundle
    agent_id, draft_id = _prepared(client, database)
    before, _ = _current(database, agent_id)
    original = router._publish_agent_version_admitted
    calls = 0

    def fail(*args: Any, **kwargs: Any) -> None:
        nonlocal calls
        calls += 1
        if failure == "referenced_exception":
            with database.session() as db:
                db.execute(
                    text(
                        "CREATE TABLE cascade_recovery_reference ("
                        "version_id TEXT REFERENCES agent_versions(id) ON DELETE RESTRICT)"
                    )
                )
                db.execute(
                    text("INSERT INTO cascade_recovery_reference VALUES (:id)"),
                    {"id": str(args[0])},
                )
        if failure == "committed_crash":
            original(*args, **kwargs)
        if failure in {"exception", "referenced_exception"}:
            raise RuntimeError("injected publication failure")
        raise ProcessCrash()

    monkeypatch.setattr(router, "_publish_agent_version_admitted", fail)
    with database.session() as db:
        with pytest.raises(
            RuntimeError if failure in {"exception", "referenced_exception"} else ProcessCrash
        ):
            bump_agent(db, settings, agent_id, drop_voice_profile_ids=["recovery-voice"])
        db.rollback()
    if failure not in {"exception", "referenced_exception"}:
        with database.session() as db:
            recover_file_operations(db, settings.resolved_data_root)
        # A completed publish leaves no stale source, but its parked draft
        # still needs recovery after a crash before restoration.
        assert sweep_stale_agents(database, settings) == 0
    with database.session() as db:
        draft = db.get(AgentVersion, draft_id)
        assert draft is not None and draft.state == "draft"
        assert draft.agent_md == "# Owner draft\n\nDo not publish this edit."
        assert draft.voice_profile_id is None
        operations = db.scalars(
            select(FileOperation).where(
                FileOperation.operation_kind.in_(("agent_cascade_publish", "agent_cascade_park"))
            )
        ).all()
        assert len(operations) == 2
        assert {op.state for op in operations} == {
            "committed" if failure == "committed_crash" else "recovered"
        }
        assert bump_agent(db, settings, agent_id, drop_voice_profile_ids=["recovery-voice"]) is None
    after, _ = _current(database, agent_id)
    assert (after.id != before.id) == (failure == "committed_crash")
    assert "Owner draft" not in after.agent_md
    assert calls == 1


def test_active_cascade_is_not_recovered_or_published_by_another_worker(
    client: TestClient, app_bundle: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.modules.agents import router

    _, database, settings = app_bundle
    agent_id, draft_id = _prepared(client, database)
    original = router._publish_agent_version_admitted

    def publish(*args: Any, **kwargs: Any) -> Any:
        with database.session() as peer:
            assert (
                bump_agent(peer, settings, agent_id, drop_voice_profile_ids=["recovery-voice"])
                is None
            )
        with database.session() as peer:
            parked = peer.get(AgentVersion, draft_id)
            assert parked is not None and parked.state == "superseded"
        return original(*args, **kwargs)

    monkeypatch.setattr(router, "_publish_agent_version_admitted", publish)
    with database.session() as db:
        assert bump_agent(db, settings, agent_id, drop_voice_profile_ids=["recovery-voice"])
        draft = db.get(AgentVersion, draft_id)
        assert draft is not None and draft.state == "draft"


def test_cascade_lock_releases_after_exception(client: TestClient, app_bundle: Any) -> None:
    _, database, settings = app_bundle
    agent_id, _ = _prepared(client, database)
    with database.session() as db:
        with pytest.raises(RuntimeError), _cascade_lock(db, settings, agent_id) as acquired:
            assert acquired
            raise RuntimeError("worker failure")
    with database.session() as db, _cascade_lock(db, settings, agent_id) as acquired:
        assert acquired


def test_affected_lists_hide_other_owners_private_names_but_cascade_still_updates_them(
    client: TestClient, app_bundle: Any
) -> None:
    _, database, _ = app_bundle
    _, csrf = login(client, "bowen")
    document_id = _upload(
        client, csrf, "shared.md", b"# Shared\n\nPublic source", "privacy-shared-upload"
    )
    public = _agent_with_docs(client, csrf, "Visible Public", [document_id])
    own_private = _agent_with_docs(client, csrf, "Own Private", [document_id], visibility="private")
    _, peer_csrf = login(client, "kaikai")
    peer_private = _agent_with_docs(
        client, peer_csrf, "Private Name Canary", [document_id], visibility="private"
    )
    versions = [_current(database, agent_id)[0] for agent_id in (public, own_private, peer_private)]
    voice_id = str(uuid4())
    with database.session() as db:
        timestamp = datetime.now(UTC)
        db.add(
            VoiceProfile(
                id=voice_id,
                scope="group",
                group_id=GROUP_ID,
                display_name="Shared voice",
                status="ready",
                provider_key="mock",
                target_model_key="mock",
                recovery_name=str(uuid4()),
                consent_actor_user_id=BOWEN_ID,
                created_at=timestamp,
                updated_at=timestamp,
            )
        )
        for version in versions:
            current = db.get(AgentVersion, version.id)
            assert current is not None
            current.voice_profile_id = voice_id
    _, csrf = login(client, "bowen")
    assert client.get(f"/api/v1/agents/{peer_private}").status_code == 404
    for path in (f"knowledge-documents/{document_id}", f"voice-profiles/{voice_id}"):
        listed = client.get(f"/api/v1/{path}/affected-agents")
        assert listed.status_code == 200, listed.text
        assert {row["agent_id"] for row in listed.json()} == {public, own_private}
        assert "Private Name Canary" not in listed.text
    hidden = client.post(
        f"/api/v1/knowledge-documents/{document_id}/hide", headers=_h(csrf, "privacy-shared-hide")
    )
    assert hidden.status_code == 200, hidden.text
    for old in versions:
        updated, documents = _current(database, old.agent_id)
        assert updated.id != old.id and documents == []
