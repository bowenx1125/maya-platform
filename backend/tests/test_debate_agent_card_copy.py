from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

import pytest
from app.core.config import get_settings
from app.core.models import AgentDebateCard, AgentVersion
from app.modules.agents import debate_cards as agent_cards
from app.modules.agents.markdown import markdown_hash
from app.modules.debates.agent_cards import ensure_participant_agent_card
from app.modules.debates.cards import CARD_OPERATION, CardOutcome
from app.modules.debates.models import DebateParticipant
from app.modules.debates.playback.generation_adapter import SqlTurnPreparer
from app.providers.control_repository import ProviderRepository
from app.providers.llm import MockLLMProvider
from sqlalchemy import select

from tests.conftest import login
from tests.test_debate_cards import CARD, _first_turn, _ok, _participants, _provider
from tests.test_wave2_setup import COURSE_ID, GROUP_DEMO_ID, _insert_published_agent, headers
from tests.test_wave2_setup import debate_app as debate_app


def _agents(database: Any) -> list[str]:
    return [
        _insert_published_agent(database, group_id=GROUP_DEMO_ID, name=f"Copy {index}")[0]
        for index in range(2)
    ]


def _create(client: Any, ids: list[str]) -> str:
    _, csrf = login(client)
    response = client.post(
        f"/api/v1/courses/{COURSE_ID}/debates",
        headers=headers(csrf, **{"Idempotency-Key": str(uuid4())}),
        json={
            "output_language": "en",
            "topic": "Should schools ban phones?",
            "participants": [{"agent_id": agent_id, "stance_mode": "open"} for agent_id in ids],
            "round_unit_caps": [200, 200, 200, 200],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _columns(row: Any) -> tuple[str, str | None, str | None]:
    return row.card_status, row.card_json, row.card_safe_error_code


@pytest.mark.parametrize("status", ["ready", "fallback"])
def test_snapshot_copies_terminal_card_without_call_and_never_follows_later_agent_edits(
    debate_app, monkeypatch, status
) -> None:
    _, database, client = debate_app
    ids = _agents(database)
    outcome = (
        CardOutcome("ready", card=CARD)
        if status == "ready"
        else CardOutcome("fallback", safe_error_code="debate_card_invalid")
    )
    monkeypatch.setattr(agent_cards, "compile_source", lambda *args: outcome)
    frozen = []
    with database.session() as db:
        for agent_id in ids:
            frozen.append(_columns(agent_cards.ensure_agent_card(db, agent_id, get_settings())))
    monkeypatch.setattr(
        agent_cards, "compile_source", lambda *args: pytest.fail("copy must not compile")
    )
    debate_id = _create(client, ids)
    rows = _participants(database, debate_id)
    assert [_columns(row) for row in rows] == frozen
    llm = MockLLMProvider()
    preparer = SqlTurnPreparer(llm=llm)
    with database.session() as db:
        debate, turn = _first_turn(db, debate_id)
        assert preparer(db, debate, turn, attempt=1, cancellation_generation=0).speech
    persona = json.loads(llm.prompts[0].messages[1][1])["persona"]["markdown"]
    assert ("## Identity" in persona) if status == "ready" else persona == rows[0].agent_md_snapshot
    monkeypatch.setattr(
        agent_cards,
        "compile_source",
        lambda *args: CardOutcome("ready", card={**CARD, "identity": "Later persona"}),
    )
    with database.session() as db:
        card = agent_cards.ensure_agent_card(
            db, ids[0], get_settings(), markdown="Later authored source"
        )
        assert "Later persona" in card.card_json
    assert [_columns(row) for row in _participants(database, debate_id)] == frozen
    assert not [
        op
        for op in ProviderRepository(database).operations(scope_id=debate_id)
        if op.provider_operation == CARD_OPERATION
    ]


@pytest.mark.parametrize("cache_state", ["missing", "stale"])
def test_first_turn_compiles_once_at_agent_scope_then_copies_and_next_debate_reuses(
    debate_app, monkeypatch, cache_state
) -> None:
    _, database, client = debate_app
    ids = _agents(database)
    if cache_state == "stale":
        with monkeypatch.context() as patch:
            patch.setattr(
                agent_cards,
                "compile_source",
                lambda *args: CardOutcome("ready", card={**CARD, "identity": "Stale persona"}),
            )
            with database.session() as db:
                agent_cards.ensure_agent_card(
                    db, ids[0], get_settings(), markdown="An unrelated cached source"
                )
    adapter, transport, policy_hash = _provider(database, _ok(CARD))
    monkeypatch.setattr(agent_cards, "llm_provider", lambda *args, **kwargs: adapter)
    settings = get_settings().model_copy(update={"llm_provider_policy_hash": policy_hash})
    debate_id = _create(client, ids)
    assert _participants(database, debate_id)[0].card_status == "compiling"
    assert not transport.calls
    # A later draft must not replace the Debate's frozen source at first turn.
    from datetime import UTC, datetime

    draft_id = str(uuid4())
    with database.session() as db:
        now = datetime.now(UTC)
        db.add(
            AgentVersion(
                id=draft_id,
                agent_id=ids[0],
                version_seq=1,
                state="draft",
                revision=0,
                agent_md="A newer draft persona",
                created_at=now,
                updated_at=now,
            )
        )
    preparer = SqlTurnPreparer(settings=settings, llm=MockLLMProvider())
    with database.session() as db:
        debate, turn = _first_turn(db, debate_id)
        assert preparer(db, debate, turn, attempt=1, cancellation_generation=0).speech
    first = _participants(database, debate_id)[0]
    with database.session() as db:
        card = db.get(AgentDebateCard, ids[0])
        assert card.agent_md_hash == markdown_hash(first.agent_md_snapshot)
        assert card.agent_version_id == first.agent_version_id
        assert _columns(first) == _columns(card)
        assert json.loads(card.card_json) == CARD
        assert db.get(AgentVersion, draft_id).agent_md == "A newer draft persona"
    operations = ProviderRepository(database).operations(scope_id=f"agent_card:{ids[0]}")
    assert len(operations) == 1
    assert (
        operations[0].logical_item_id
        == f"{first.agent_version_id}:{markdown_hash(first.agent_md_snapshot)}"
    )
    assert operations[0].charged_request_count == 1
    assert len(transport.calls) == 1
    assert (
        json.loads(transport.calls[0]["body"]["messages"][1]["content"])["agent_md"]
        == first.agent_md_snapshot
    )
    assert not [
        op
        for op in ProviderRepository(database).operations(scope_id=debate_id)
        if op.provider_operation == CARD_OPERATION
    ]
    second_id = _create(client, ids)
    assert _columns(_participants(database, second_id)[0]) == _columns(first)
    with database.session() as db:
        debate, turn = _first_turn(db, second_id)
        assert preparer(db, debate, turn, attempt=1, cancellation_generation=0).speech
    assert len(transport.calls) == 1
    assert not [
        op
        for op in ProviderRepository(database).operations(scope_id=second_id)
        if op.provider_operation == CARD_OPERATION
    ]


def test_legacy_null_status_never_reads_or_compiles_agent_card(debate_app, monkeypatch) -> None:
    _, database, client = debate_app
    debate_id = _create(client, _agents(database))
    monkeypatch.setattr(
        agent_cards, "compile_source", lambda *args: pytest.fail("legacy never compiles")
    )
    llm = MockLLMProvider()
    with database.session() as db:
        row = db.scalar(
            select(DebateParticipant)
            .where(DebateParticipant.debate_id == debate_id)
            .order_by(DebateParticipant.order_index)
        )
        row.card_status = None
        db.commit()
        ensure_participant_agent_card(db, row, get_settings())
        debate, turn = _first_turn(db, debate_id)
        assert SqlTurnPreparer(llm=llm)(
            db, debate, turn, attempt=1, cancellation_generation=0
        ).speech
    assert _participants(database, debate_id)[0].card_status is None
    assert not ProviderRepository(database).operations(scope_id=f"agent_card:{row.agent_id}")


def test_deleted_source_fails_open_without_debate_scoped_compile(debate_app, monkeypatch) -> None:
    from datetime import UTC, datetime

    from app.core.models import Agent

    _, database, client = debate_app
    ids = _agents(database)
    debate_id = _create(client, ids)
    monkeypatch.setattr(
        agent_cards, "compile_source", lambda *args: pytest.fail("deleted source cannot export")
    )
    llm = MockLLMProvider()
    with database.session() as db:
        db.get(Agent, ids[0]).deleted_at = datetime.now(UTC)
        db.commit()
        debate, turn = _first_turn(db, debate_id)
        assert SqlTurnPreparer(llm=llm)(
            db, debate, turn, attempt=1, cancellation_generation=0
        ).speech
    row = _participants(database, debate_id)[0]
    assert (
        row.card_status == "fallback"
        and row.card_safe_error_code == "debate_card_preflight_blocked"
    )
    assert json.loads(llm.prompts[0].messages[1][1])["persona"]["markdown"] == row.agent_md_snapshot
    assert not ProviderRepository(database).operations(scope_id=debate_id)
