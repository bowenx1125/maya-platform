from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from app.cli.backfill_agent_cards import backfill
from app.core.db import ALEMBIC_HEAD
from app.core.models import Agent, AgentDebateCard, AgentVersion, ProviderOperation
from app.modules.agents import debate_cards as service
from app.modules.agents.markdown import markdown_hash
from app.modules.debates.cards import CardOutcome
from app.providers.control_repository import ProviderRepository
from sqlalchemy import inspect, select

from tests.conftest import login
from tests.test_debate_cards import CARD, _ok, _provider
from tests.test_wave1_agents_knowledge import _headers, _make_agent
from tests.test_wave2_setup import GROUP_DEMO_ID, _insert_published_agent


def _agent(client: Any) -> tuple[str, str, str]:
    _, csrf = login(client, "bowen")
    agent, version_id = _make_agent(client, csrf)
    return agent["id"], version_id, csrf


def _save(client: Any, version: str, csrf: str, text: str, revision: int = 0) -> Any:
    return client.patch(
        f"/api/v1/agent-versions/{version}",
        headers=_headers(csrf),
        json={"expected_revision": revision, "agent_md": text},
    )


def _check(client: Any, version: str, csrf: str, text: str | None = None) -> Any:
    return client.post(
        f"/api/v1/agent-versions/{version}/debate-card",
        headers=_headers(csrf),
        json={} if text is None else {"agent_md": text},
    )


def test_save_and_check_follow_exact_content_hash(client, database, monkeypatch) -> None:
    agent_id, version, csrf = _agent(client)
    calls = []

    def compile_source(*args):
        calls.append(args[3])
        return CardOutcome("ready", card=CARD, salvaged=True)

    monkeypatch.setattr(service, "compile_source", compile_source)
    saved = _save(client, version, csrf, "Free text identity")
    assert saved.status_code == 200, saved.text
    assert calls == ["Free text identity"]
    first = _check(client, version, csrf)
    assert first.status_code == 200, first.text
    assert first.json()["card"] == CARD
    assert calls == ["Free text identity"]
    # A same-content save and Check card reuse even across avatar/revision saves.
    assert _save(client, version, csrf, "Free text identity", 1).status_code == 200
    assert _check(client, version, csrf).json()["card_status"] == "ready"
    assert len(calls) == 1
    # Check card can compile unsaved editor text without changing the version.
    assert _check(client, version, csrf, "A different identity").json()["card"] == CARD
    assert len(calls) == 2
    with database.session() as db:
        row = db.get(AgentDebateCard, agent_id)
        assert row.agent_md_hash == markdown_hash("A different identity")
        assert row.salvaged is True
        assert row.agent_version_id == version
        assert row.compiled_at is not None
        assert db.get(AgentVersion, version).agent_md == "Free text identity"
    # Done with the checked text keeps the exact stored result.
    assert _save(client, version, csrf, "A different identity", 2).status_code == 200
    assert len(calls) == 2
    assert _save(client, version, csrf, "Another edit", 3).status_code == 200
    assert len(calls) == 3


@pytest.mark.parametrize("failure", [RuntimeError("provider"), ValueError("ledger")])
def test_save_commits_before_compile_and_survives_errors(
    client, database, monkeypatch, failure
) -> None:
    agent_id, version, csrf = _agent(client)
    calls = []

    def broken(*args):
        with database.session() as independent:
            assert independent.get(AgentVersion, version).agent_md == "Saved despite failure"
        calls.append(1)
        raise failure

    monkeypatch.setattr(service, "compile_source", broken)
    assert _save(client, version, csrf, "Saved despite failure").status_code == 200
    result = _check(client, version, csrf)
    assert result.status_code == 200
    assert result.json() == {
        "card_status": "fallback",
        "card": None,
        "card_teacher_reason": "other",
        "card_teacher_notice": None,
    }
    assert calls == [1]
    with database.session() as db:
        row = db.get(AgentDebateCard, agent_id)
        assert row.card_safe_error_code == "debate_card_failed"
        assert row.salvaged is False


def test_failed_save_does_not_enqueue(client, monkeypatch) -> None:
    _, version, csrf = _agent(client)
    calls = []
    monkeypatch.setattr(service, "compile_source", lambda *args: calls.append(1))
    assert _save(client, version, csrf, "not saved", 9).status_code == 409
    assert not calls


@pytest.mark.parametrize("salvaged", [False, True])
def test_real_core_personal_agent_consent_scope_and_salvage(
    client, database, monkeypatch, salvaged
) -> None:
    agent_id, version_id, _csrf = _agent(client)
    raw_card = {**CARD, "extra": "discard"} if salvaged else CARD
    adapter, transport, policy_hash = _provider(database, _ok(raw_card))
    monkeypatch.setattr(service, "llm_provider", lambda *args, **kwargs: adapter)
    settings = service.Settings(
        maya_env="test", llm_provider="mock", llm_provider_policy_hash=policy_hash
    )
    with database.session() as db:
        agent = db.get(Agent, agent_id)
        agent.ownership_scope = "personal"
        agent.group_id = None
        version = db.get(AgentVersion, version_id)
        version.agent_md = "A plain author-defined persona"
        db.commit()
        outcome = service.ensure_agent_card(db, agent_id, settings)
        assert outcome.card_status == "ready"
        assert outcome.salvaged is salvaged
        assert json.loads(outcome.card_json) == CARD
        digest = markdown_hash(version.agent_md)
    assert len(transport.calls) == 1
    operations = ProviderRepository(database).operations(scope_id=f"agent_card:{agent_id}")
    assert len(operations) == 1
    operation = operations[0]
    assert operation.logical_item_id == f"{version_id}:{digest}"
    assert operation.attempt_no == 1
    assert operation.charged_request_count == 1
    repository = ProviderRepository(database)
    assert repository.get_export_confirmation(operation.export_manifest_hash) is not None
    with database.session() as db:
        assert service.ensure_agent_card(db, agent_id, settings).card_status == "ready"
    assert len(transport.calls) == 1


def test_concurrent_claims_do_not_send_twice(client, database, monkeypatch) -> None:
    agent_id, _, _ = _agent(client)
    entered, release = Event(), Event()
    calls = []

    def compile_source(*args):
        calls.append(1)
        entered.set()
        assert release.wait(10)
        return CardOutcome("ready", card=CARD)

    monkeypatch.setattr(service, "compile_source", compile_source)

    def run():
        with database.session() as db:
            return service.ensure_agent_card(
                db, agent_id, service.Settings(maya_env="test")
            ).card_status

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(run)
        assert entered.wait(10)
        try:
            assert pool.submit(run).result(10) == "compiling"
        finally:
            release.set()
        assert first.result(10) == "ready"
    assert calls == [1]


@pytest.mark.parametrize("recovery", ["restart", "expired"])
def test_check_recovers_abandoned_or_expired_claim(client, database, monkeypatch, recovery) -> None:
    from contextlib import nullcontext
    from datetime import UTC, datetime, timedelta
    from uuid import uuid4

    from app.core.locks import held_lock

    agent_id, version, csrf = _agent(client)
    assert _save(client, version, csrf, "Interrupted card").status_code == 200
    token = str(uuid4())
    with database.session() as db:
        row = db.get(AgentDebateCard, agent_id)
        row.card_status = "compiling"
        row.card_json = row.card_safe_error_code = None
        row.claim_token = token
        row.updated_at = datetime.now(UTC) - timedelta(seconds=600 if recovery == "expired" else 0)
    calls = []
    monkeypatch.setattr(
        service,
        "compile_source",
        lambda *args: calls.append(args[6]) or CardOutcome("ready", card=CARD),
    )
    lock = (
        held_lock(database.engine, f"agent-card-worker:{token}")
        if recovery == "expired"
        else nullcontext()
    )
    with lock:
        assert _check(client, version, csrf).json()["card"] == CARD
    assert calls == [1]
    with database.session() as db:
        row = db.get(AgentDebateCard, agent_id)
        assert row.card_status == "ready" and row.claim_token is None


def _age_card(database, agent_id):
    from datetime import UTC, datetime, timedelta

    with database.session() as db:
        before = datetime.now(UTC) - timedelta(seconds=61)
        db.get(AgentDebateCard, agent_id).updated_at = before
        for operation in db.scalars(
            select(ProviderOperation).where(ProviderOperation.scope_id == f"agent_card:{agent_id}")
        ):
            operation.updated_at = before


def test_check_retries_fallback_with_cooldown_and_cap(client, database, monkeypatch) -> None:
    agent_id, version, csrf = _agent(client)
    calls = []
    monkeypatch.setattr(
        service,
        "compile_source",
        lambda *args: (
            calls.append(args[6]) or CardOutcome("fallback", safe_error_code="debate_card_invalid")
        ),
    )
    assert _save(client, version, csrf, "Retry this stored source").status_code == 200
    assert _check(client, version, csrf).json()["card_status"] == "fallback"
    assert calls == [0]
    for retry in range(1, 4):
        _age_card(database, agent_id)
        assert _check(client, version, csrf).json()["card_status"] == "fallback"
        assert calls == list(range(retry + 1))
        assert _check(client, version, csrf).json()["card_status"] == "fallback"
        assert len(calls) == retry + 1
    _age_card(database, agent_id)
    assert _check(client, version, csrf).json()["card_status"] == "fallback"
    assert calls == [0, 1, 2, 3]
    with database.session() as db:
        row = db.get(AgentDebateCard, agent_id)
        assert row.retry_count == 3
        assert row.card_safe_error_code == "debate_card_invalid"


def test_expired_worker_cannot_overwrite_recovered_card(client, database, monkeypatch) -> None:
    from datetime import UTC, datetime, timedelta

    agent_id, version, csrf = _agent(client)
    entered, release = Event(), Event()
    calls = []

    def compile_source(*args):
        calls.append(args[6])
        if len(calls) == 1:
            entered.set()
            assert release.wait(10)
            return CardOutcome("fallback", safe_error_code="debate_card_failed")
        return CardOutcome("ready", card=CARD)

    monkeypatch.setattr(service, "compile_source", compile_source)
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(
            service.check_agent_card,
            database.engine,
            agent_id,
            version,
            "A frozen source",
            service.Settings(maya_env="test"),
        )
        assert entered.wait(10)
        try:
            with database.session() as db:
                db.get(AgentDebateCard, agent_id).updated_at = datetime.now(UTC) - timedelta(
                    seconds=600
                )
            assert _check(client, version, csrf, "A frozen source").json()["card"] == CARD
        finally:
            release.set()
        assert first.result(10).card_status == "ready"
    assert calls == [0, 1]
    with database.session() as db:
        assert db.get(AgentDebateCard, agent_id).card_status == "ready"


def _backfill_targets(client, database, count: int) -> None:
    login(client, "bowen")
    for index in range(count):
        _insert_published_agent(database, group_id=GROUP_DEMO_ID, name=f"Backfill {index}")
    with database.session() as db:
        agents = list(
            db.scalars(
                select(Agent)
                .where(Agent.current_published_version_id.is_not(None))
                .order_by(Agent.id)
            )
        )
        assert len(agents) >= count
        for agent in agents[count:]:
            agent.current_published_version_id = None


def test_backfill_dry_run_resume_and_limit(client, database, monkeypatch) -> None:
    _backfill_targets(client, database, 2)
    calls, pauses = [], []
    monkeypatch.setattr(
        service,
        "compile_source",
        lambda *args: calls.append(args[1].id) or CardOutcome("ready", card=CARD),
    )
    settings = service.Settings(maya_env="test")
    dry = backfill(database, settings, dry_run=True, limit=1, emit=lambda _: None)
    assert dry["would_compile"] == 1 and calls == []
    first = backfill(database, settings, limit=1, sleep=pauses.append, emit=lambda _: None)
    assert first["ready"] == 1
    second = backfill(database, settings, sleep=pauses.append, emit=lambda _: None)
    assert second["ready"] == 1 and second["skipped"] == 1
    final = backfill(database, settings, sleep=pauses.append, emit=lambda _: None)
    assert final["skipped"] == 2 and len(calls) == 2
    assert pauses == [2.5, 2.5]


def test_backfill_stops_after_five_provider_failures(client, database, monkeypatch) -> None:
    _backfill_targets(client, database, 6)
    calls = []
    monkeypatch.setattr(
        service,
        "compile_source",
        lambda *args: (
            calls.append(1)
            or CardOutcome("fallback", safe_error_code="debate_card_transport_failed")
        ),
    )
    result = backfill(
        database, service.Settings(maya_env="test"), sleep=lambda _: None, emit=lambda _: None
    )
    assert result["spike_stopped"] == 1
    assert result["fallback"] == 5 and len(calls) == 5


def test_card_migration_round_trip_preserves_authored_data(client, database) -> None:
    from sqlalchemy import text

    _, version, csrf = _agent(client)
    assert _save(client, version, csrf, "Preserved authored text").status_code == 200
    database.upgrade_schema()

    def authored_rows():
        with database.engine.connect() as connection:
            return (
                connection.execute(
                    text("SELECT id, agent_md, revision, state FROM agent_versions ORDER BY id")
                ).all(),
                connection.execute(
                    text(
                        "SELECT id, visibility, current_published_version_id "
                        "FROM agents ORDER BY id"
                    )
                ).all(),
            )

    before = authored_rows()
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).parents[1] / "migrations"))
    config.attributes["database_url"] = database.database_url
    assert ScriptDirectory.from_config(config).get_heads() == [ALEMBIC_HEAD]
    assert "agent_debate_cards" in inspect(database.engine).get_table_names()
    command.downgrade(config, "0093_default_group_no_group")
    assert "agent_debate_cards" not in inspect(database.engine).get_table_names()
    assert authored_rows() == before
    command.upgrade(config, "head")
    assert authored_rows() == before
    assert "agent_debate_cards" in inspect(database.engine).get_table_names()
    assert database.check_ready()
    database.dispose()


def test_upload_and_publish_enqueue_without_check_card(client, database, monkeypatch) -> None:
    from uuid import uuid4

    agent_id, version, csrf = _agent(client)
    calls = []
    monkeypatch.setattr(
        service,
        "compile_source",
        lambda *args: calls.append(args[3]) or CardOutcome("ready", card=CARD),
    )
    uploaded = client.post(
        f"/api/v1/agent-versions/{version}/agent-md/upload",
        headers=_headers(csrf),
        data={"expected_revision": "0"},
        files={"file": ("AGENT.md", b"# Author\n\nFree text persona.\n", "text/markdown")},
    )
    assert uploaded.status_code == 200, uploaded.text
    assert len(calls) == 1
    # Remove only derived data to prove publish independently schedules it.
    with database.session() as db:
        db.delete(db.get(AgentDebateCard, agent_id))
    published = client.post(
        f"/api/v1/agent-versions/{version}/publish",
        headers=_headers(csrf, **{"Idempotency-Key": str(uuid4())}),
        json={"expected_revision": uploaded.json()["revision"]},
    )
    assert published.status_code == 200, published.text
    assert len(calls) == 2
    with database.session() as db:
        assert db.get(AgentDebateCard, agent_id).card_status == "ready"


@pytest.mark.parametrize("failure", ["ledger", "timeout"])
def test_real_provider_failures_leave_save_and_card_terminal(
    client, database, monkeypatch, failure
) -> None:
    from app.providers.llm_transport import LLMAcceptanceUnknown

    agent_id, version, csrf = _agent(client)
    adapter, transport, policy_hash = _provider(
        database, LLMAcceptanceUnknown("timeout") if failure == "timeout" else _ok(CARD)
    )
    monkeypatch.setattr(service, "llm_provider", lambda *args, **kwargs: adapter)
    original = service.compile_source

    def compile_source(db, agent, version, markdown, language, settings, *claim):
        return original(
            db,
            agent,
            version,
            markdown,
            language,
            settings.model_copy(update={"llm_provider_policy_hash": policy_hash}),
            *claim,
        )

    monkeypatch.setattr(service, "compile_source", compile_source)
    if failure == "ledger":

        def broken(*args):
            raise RuntimeError("ledger unavailable")

        monkeypatch.setattr(ProviderRepository, "reserve", broken)
    saved = _save(client, version, csrf, "A test persona")
    assert saved.status_code == 200, saved.text
    assert _check(client, version, csrf).json()["card_status"] == "fallback"
    with database.session() as db:
        row = db.get(AgentDebateCard, agent_id)
        assert row.card_safe_error_code == (
            "debate_card_acceptance_unknown"
            if failure == "timeout"
            else "debate_card_ledger_failed"
        )
        assert row.salvaged is False
    assert len(transport.calls) == (1 if failure == "timeout" else 0)


def test_salvaged_tracks_unit_truncation() -> None:
    from app.modules.debates.cards import _response_card_details

    _card, _digest, salvaged = _response_card_details(
        _ok({**CARD, "identity": "word " * 1000}), "en"
    )
    assert salvaged is True


def test_check_http_timeout_keeps_independent_claim(client, database, monkeypatch) -> None:
    from app.modules.agents import router

    agent_id, version, csrf = _agent(client)
    entered, release = Event(), Event()
    calls = []

    def compile_source(*args):
        calls.append(1)
        entered.set()
        assert release.wait(10)
        return CardOutcome("ready", card=CARD)

    monkeypatch.setattr(service, "compile_source", compile_source)
    monkeypatch.setattr(router, "CARD_TIMEOUT_SECONDS", 0.05)
    try:
        result = _check(client, version, csrf, "Bounded button request")
        assert result.status_code == 200, result.text
        assert result.json()["card_status"] == "compiling"
        assert entered.wait(5)
        assert (
            _check(client, version, csrf, "Bounded button request").json()["card_status"]
            == "compiling"
        )
        assert calls == [1]
    finally:
        release.set()
    # Joining through the same lock proves the worker's own session survives
    # the request dependency being closed after the timeout.
    with database.session() as db:
        row = service.ensure_agent_card(
            db,
            agent_id,
            service.Settings(maya_env="test"),
            version_id=version,
            markdown="Bounded button request",
            wait=True,
        )
        assert row.card_status == "ready"
    assert calls == [1]


@pytest.mark.parametrize("wait", [False, True])
def test_worker_finishing_during_liveness_probe_reuses_ready_card(
    client, database, monkeypatch, wait
) -> None:
    from contextlib import contextmanager

    agent_id, version, _ = _agent(client)
    entered, release = Event(), Event()
    calls = []

    def compile_source(*args):
        calls.append(1)
        entered.set()
        assert release.wait(10)
        return CardOutcome("ready", card=CARD)

    monkeypatch.setattr(service, "compile_source", compile_source)
    settings = service.Settings(maya_env="test")
    original_lock = service.held_lock
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(
            service.check_agent_card, database.engine, agent_id, version, "Same source", settings
        )
        assert entered.wait(10)

        @contextmanager
        def finish_before_probe(bind, name, *, wait=False):
            if name.startswith("agent-card-worker:") and not wait:
                # Completion lands after the waiter read Compiling, before it
                # checks liveness; the session must discard that stale row.
                release.set()
                assert first.result(10).card_status == "ready"
            with original_lock(bind, name, wait=wait) as acquired:
                yield acquired

        monkeypatch.setattr(service, "held_lock", finish_before_probe)
        try:
            with database.session() as db:
                row = service.ensure_agent_card(
                    db,
                    agent_id,
                    settings,
                    version_id=version,
                    markdown="Same source",
                    wait=wait,
                    retry_failed=not wait,
                )
                assert row.card_status == "ready"
                assert json.loads(row.card_json) == CARD
        finally:
            release.set()
    assert calls == [1]


def test_backfill_rolling_provider_failure_spike(client, database, monkeypatch) -> None:
    _backfill_targets(client, database, 21)
    calls = []

    def compile_source(*args):
        calls.append(1)
        if len(calls) % 3 == 1:
            return CardOutcome("fallback", safe_error_code="debate_card_http_rejected")
        return CardOutcome("ready", card=CARD)

    monkeypatch.setattr(service, "compile_source", compile_source)
    result = backfill(
        database, service.Settings(maya_env="test"), sleep=lambda _: None, emit=lambda _: None
    )
    assert result["spike_stopped"] == 1
    assert result["attempted"] == 20
    assert result["fallback"] == 7


def test_card_read_acl_and_csrf(client, database) -> None:
    from uuid import uuid4

    _, version, csrf = _agent(client)
    assert _check(client, str(uuid4()), csrf).status_code == 404
    assert client.post(f"/api/v1/agent-versions/{version}/debate-card", json={}).status_code == 403
    client.cookies.clear()
    assert _check(client, version, csrf).status_code == 401


def test_same_hash_follows_new_version_without_recompile_or_pruning_loss(
    client, database, monkeypatch
) -> None:
    from datetime import UTC, datetime
    from uuid import uuid4

    agent_id, version_id, csrf = _agent(client)
    calls = []
    monkeypatch.setattr(
        service, "compile_source", lambda *args: calls.append(1) or CardOutcome("ready", card=CARD)
    )
    assert _save(client, version_id, csrf, "Identical across versions").status_code == 200
    next_id = str(uuid4())
    with database.session() as db:
        old = db.get(AgentVersion, version_id)
        old.state = "superseded"
        db.flush()
        now = datetime.now(UTC)
        db.add(
            AgentVersion(
                id=next_id,
                agent_id=agent_id,
                version_seq=1,
                state="draft",
                revision=0,
                agent_md=old.agent_md,
                created_at=now,
                updated_at=now,
            )
        )
    with database.session() as db:
        row = service.ensure_agent_card(db, agent_id, service.Settings(maya_env="test"))
        assert row.agent_version_id == next_id
        assert row.card_status == "ready"
        db.delete(db.get(AgentVersion, version_id))
    with database.session() as db:
        assert db.get(AgentDebateCard, agent_id).card_status == "ready"
    assert calls == [1]


def test_queued_save_reads_latest_text_after_previous_compile(
    client, database, monkeypatch
) -> None:
    agent_id, version_id, _ = _agent(client)
    entered, release = Event(), Event()
    calls = []

    def compile_source(*args):
        calls.append(args[3])
        if len(calls) == 1:
            entered.set()
            assert release.wait(10)
        return CardOutcome("ready", card=CARD)

    monkeypatch.setattr(service, "compile_source", compile_source)
    settings = service.Settings(maya_env="test")
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(service.compile_after_save, database.engine, agent_id, settings)
        assert entered.wait(10)
        with database.session() as db:
            db.get(AgentVersion, version_id).agent_md = "Latest committed save"
        second = pool.submit(service.compile_after_save, database.engine, agent_id, settings)
        release.set()
        first.result(10)
        second.result(10)
    assert len(calls) == 2 and calls[-1] == "Latest committed save"
    with database.session() as db:
        assert db.get(AgentDebateCard, agent_id).agent_md_hash == markdown_hash(
            "Latest committed save"
        )


def test_check_retry_has_distinct_ledger_manifest_and_preserves_old_charge(
    client, database, monkeypatch
) -> None:
    agent_id, version, csrf = _agent(client)
    adapter, transport, policy_hash = _provider(database, _ok({**CARD, "identity": ""}))
    monkeypatch.setattr(service, "llm_provider", lambda *args, **kwargs: adapter)
    original = service.compile_source

    def compile_source(db, agent, version, markdown, language, settings, *claim):
        return original(
            db,
            agent,
            version,
            markdown,
            language,
            settings.model_copy(update={"llm_provider_policy_hash": policy_hash}),
            *claim,
        )

    monkeypatch.setattr(service, "compile_source", compile_source)
    assert _save(client, version, csrf, "Ledgered retry source").status_code == 200
    assert _check(client, version, csrf).json()["card_status"] == "fallback"
    assert len(transport.calls) == 1
    _age_card(database, agent_id)
    transport.outcome = _ok(CARD)
    assert _check(client, version, csrf).json()["card"] == CARD
    assert len(transport.calls) == 2
    assert _check(client, version, csrf).json()["card"] == CARD
    assert len(transport.calls) == 2
    operations = ProviderRepository(database).operations(scope_id=f"agent_card:{agent_id}")
    base_item = f"{version}:{markdown_hash('Ledgered retry source')}"
    by_item = {op.logical_item_id: op for op in operations}
    assert set(by_item) == {base_item, base_item + ":r1"}
    assert by_item[base_item].state == "failed"
    assert by_item[base_item + ":r1"].state == "succeeded"
    assert len({op.export_manifest_hash for op in operations}) == 2
    for operation in operations:
        assert operation.attempt_no == 1 and operation.charged_request_count == 1
        assert ProviderRepository(database).get_export_confirmation(operation.export_manifest_hash)


def test_expired_queued_worker_is_fenced_before_provider_dispatch(
    client, database, monkeypatch
) -> None:
    from contextlib import contextmanager
    from datetime import UTC, datetime, timedelta

    agent_id, version, csrf = _agent(client)
    adapter, transport, policy_hash = _provider(database, _ok(CARD))
    monkeypatch.setattr(service, "llm_provider", lambda *args, **kwargs: adapter)
    entered, release = Event(), Event()
    original_slot = service.llm_admission_slot
    slots = []

    @contextmanager
    def delayed_admission(settings):
        slots.append(1)
        if len(slots) == 1:
            entered.set()
            assert release.wait(10)
        with original_slot(settings):
            yield

    monkeypatch.setattr(service, "llm_admission_slot", delayed_admission)
    settings = service.Settings(maya_env="test", llm_provider_policy_hash=policy_hash)
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(
            service.check_agent_card, database.engine, agent_id, version, "Queued source", settings
        )
        assert entered.wait(10)
        try:
            with database.session() as db:
                db.get(AgentDebateCard, agent_id).updated_at = datetime.now(UTC) - timedelta(
                    seconds=600
                )
            current = service.check_agent_card(
                database.engine, agent_id, version, "Queued source", settings
            )
            assert current.card_status == "ready"
        finally:
            release.set()
        assert first.result(10).card_status == "ready"
    assert len(transport.calls) == 1
    operations = ProviderRepository(database).operations(scope_id=f"agent_card:{agent_id}")
    assert len(operations) == 1
    assert operations[0].logical_item_id.endswith(":r1")
    assert operations[0].charged_request_count == 1


@pytest.mark.parametrize("reason", ["fallback", "abandoned"])
def test_concurrent_retry_and_recovery_claims_send_once(
    client, database, monkeypatch, reason
) -> None:
    from uuid import uuid4

    agent_id, version, csrf = _agent(client)
    assert _save(client, version, csrf, "Same source").status_code == 200
    _age_card(database, agent_id)
    if reason == "abandoned":
        with database.session() as db:
            row = db.get(AgentDebateCard, agent_id)
            row.card_status = "compiling"
            row.card_safe_error_code = None
            row.claim_token = str(uuid4())
    entered, release = Event(), Event()
    calls = []

    def compile_source(*args):
        calls.append(args[6])
        entered.set()
        assert release.wait(10)
        return CardOutcome("ready", card=CARD)

    monkeypatch.setattr(service, "compile_source", compile_source)
    settings = service.Settings(maya_env="test")
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            service.check_agent_card, database.engine, agent_id, version, "Same source", settings
        )
        assert entered.wait(10)
        try:
            second = pool.submit(
                service.check_agent_card,
                database.engine,
                agent_id,
                version,
                "Same source",
                settings,
            )
            assert second.result(10).card_status == "compiling"
        finally:
            release.set()
        assert first.result(10).card_status == "ready"
    assert calls == [1]


def test_accepted_crash_recovers_without_reusing_operation_or_losing_charge(
    client, database, monkeypatch
) -> None:
    from uuid import uuid4

    agent_id, version, csrf = _agent(client)
    adapter, transport, policy_hash = _provider(database, _ok(CARD))
    monkeypatch.setattr(service, "llm_provider", lambda *args, **kwargs: adapter)
    settings = service.Settings(maya_env="test", llm_provider_policy_hash=policy_hash)
    # Stop between supplier acceptance and terminal card publication.
    mark_succeeded = ProviderRepository.mark_succeeded
    monkeypatch.setattr(ProviderRepository, "mark_succeeded", lambda *args: None)
    original_dispatch = service.compile_source

    def interrupted(*args):
        result = original_dispatch(*args)
        assert result.status == "ready"
        raise RuntimeError("process interrupted before terminal card CAS")

    monkeypatch.setattr(service, "compile_source", interrupted)
    with database.session() as db:
        db.get(AgentVersion, version).agent_md = "Accepted crash recovery source"
        card = service.ensure_agent_card(db, agent_id, settings)
        card.card_status = "compiling"
        card.card_safe_error_code = None
        card.claim_token = str(uuid4())
    assert len(transport.calls) == 1
    original = ProviderRepository(database).operations(scope_id=f"agent_card:{agent_id}")[0]
    assert original.state == "accepted" and original.charged_request_count == 1
    monkeypatch.setattr(service, "compile_source", original_dispatch)
    with database.session() as db:
        assert (
            service.ensure_agent_card(db, agent_id, settings).card_safe_error_code
            == "debate_card_acceptance_unknown"
        )
    recovered = ProviderRepository(database).operation(original.id)
    assert recovered.state == "acceptance_unknown" and recovered.charged_request_count == 1
    assert len(transport.calls) == 1
    monkeypatch.setattr(ProviderRepository, "mark_succeeded", mark_succeeded)
    _age_card(database, agent_id)
    with database.session() as db:
        assert (
            service.ensure_agent_card(db, agent_id, settings, retry_failed=True).card_status
            == "ready"
        )
    operations = ProviderRepository(database).operations(scope_id=f"agent_card:{agent_id}")
    assert len(operations) == len(transport.calls) == 2
    assert len({op.logical_item_id for op in operations}) == 2
    assert ProviderRepository(database).operation(original.id).state == "acceptance_unknown"
    retried = next(op for op in operations if op.id != original.id)
    assert retried.state == "succeeded" and retried.charged_request_count == 1
    assert sum(op.charged_request_count for op in operations) == 2
