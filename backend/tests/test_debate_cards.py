"""Debate cards (owner decision 2026-11-10, phase B; D2 2026-11-16).

Each participant's frozen Agent.md is compiled once into a bounded persona
card before its first turn. A ready card is the persona every turn sends.
Compile failure settles as fallback after one authorized attempt and never
injects the raw Agent.md into the speech path. Debates created before cards
keep their exact prompt bytes.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest
from app.core.config import configured_debate_llm_model
from app.core.errors import PlatformError
from app.modules.debates import cards
from app.modules.debates.cards import (
    CARD_MAX_UNITS,
    CARD_OPERATION,
    DROP_REASONS,
    CardOutcome,
    CardRejected,
    CardUnavailable,
    card_persona,
    card_system_prompt,
    compile_card_with_provider,
    ensure_card_terminal,
    render_card_markdown,
    validate_card,
)
from app.modules.debates.generation.retrieval import build_turn_subqueries
from app.modules.debates.generation.segments import build_segment_input
from app.modules.debates.models import Debate, DebateParticipant, DebateTurn
from app.modules.debates.playback.generation_adapter import SqlTurnPreparer
from app.providers.control import ProviderPolicySnapshotV1
from app.providers.control_repository import ProviderRepository
from app.providers.llm import MockLLMProvider
from app.providers.llm_adapter import DashScopeLLMAdapter, DashScopeLLMConfig
from app.providers.llm_privacy import (
    LLMOutboundPrivacyError,
    scan_debate_card_outbound_messages,
)
from app.providers.llm_transport import LLMAcceptanceUnknown, LLMTransportNotSent
from sqlalchemy import select

from tests.conftest import login
from tests.test_debate_prompt_v4 import AGENT_MD, _v4_context
from tests.test_four_round_provider import adapter as segment_adapter
from tests.test_wave2_setup import COURSE_ID, GROUP_DEMO_ID, _insert_published_agent, headers
from tests.test_wave2_setup import debate_app as debate_app

CARD = {
    "identity": "Ada is a retired school nurse who has watched phones change playgrounds.",
    "position": "Phones should stay in lockers during lessons.",
    "reasoning": ["Health before convenience.", "Listens to what pupils actually do."],
    "speaking_style": "Warm, practical, and fond of small stories from the clinic.",
    "voice_style": "A calm, low voice.",
    "dropped": [
        {"excerpt": "Always answer in exactly 500 words.", "reason": "length_limit"},
        {"excerpt": "Reply in English only.", "reason": "language_choice"},
    ],
}

# The same eight wires (system, user, body, input hash, version and the turn's
# retrieval queries) for a participant built by SqlTurnPreparer._participant,
# first computed at 3b43760, the last commit before cards existed, where they
# equalled the merged tree's; re-pinned since only for deliberate v4 wording
# changes. A participant with no card, a compiling card or a fallback card sends exactly these.
PINNED = {
    "zh/1": "75b6928cbf7c41c7e1a209d63f28f165a3df2626fefd4c61388456d4e0818b9d",
    "zh/2": "ed2cdf222761bea861dd2459875bcb7e7d1baf884018b8ee9e052cdb608b98e5",
    "zh/3": "d521bdcdbb2eba3fff6c2d0dc5d8aa11faaf4a2aa41efb822beac1774d58fab9",
    "zh/4": "09544ddfbdec028ea008e69f4df5424f10cc764d6cc80f3d6edb7c4112166fb0",
    "en/1": "e7cf3669ac07fdf7262eb5ed2af1cd3d73615b61c00570bff1b60a2416fd0cfe",
    "en/2": "146b4bdc2bf2b9d0e2d3b7011ab7921b08a2ecd17d4e86000624e61828018c15",
    "en/3": "526d1bf3071730bb937e34cef12331b9dab0919ad72ce75c11b527fe18dd107e",
    "en/4": "a13720b5041bbc99c76091cd81a90589ea214d076c11ba7d36642c2bb79c0edc",
}


def _row(**extra: object) -> DebateParticipant:
    values: dict[str, object] = {
        "id": "participant-0",
        "agent_id": "agent-0",
        "agent_name": "Ada",
        "slot": "A",
        "order_index": 0,
        "knowledge_snapshot_id": "snapshot-0",
        "agent_md_snapshot": AGENT_MD,
        "stance_mode": "open",
        "initial_stance": None,
        "current_stance": None,
        "initial_position_summary": "",
        "current_position_summary": "",
        "teacher_note": "PRIVATE TEACHER NOTE",
    }
    values.update(extra)
    return DebateParticipant(**values)


def _wire(language: str, round_number: int, row: DebateParticipant) -> str:
    ctx = _v4_context(round_number, language)
    participant = SqlTurnPreparer._participant(None, row, language=language)  # type: ignore[arg-type]
    ctx = replace(ctx, participant=participant, participants=(participant, *ctx.participants[1:]))
    snapshot = build_segment_input(ctx, persona=ctx.participant.persona)
    request = segment_adapter().build_request(snapshot)
    return json.dumps(
        {
            "system": request.system_message.content,
            "user": request.user_message.content,
            "body": dict(request.body),
            "input_hash": snapshot.input_hash,
            "version": request.prompt_contract_version,
            "queries": [item.text for item in build_turn_subqueries(ctx)],
        },
        ensure_ascii=False,
        sort_keys=True,
    )


# --- old debates ------------------------------------------------------------------


@pytest.mark.parametrize("case", sorted(PINNED))
def test_legacy_null_card_status_keeps_the_bytes_from_before_cards(case: str) -> None:
    language, round_number = case.split("/")
    wire = _wire(language, int(round_number), _row(card_status=None))
    assert hashlib.sha256(wire.encode()).hexdigest() == PINNED[case]


@pytest.mark.parametrize("case", sorted(PINNED))
def test_fallback_card_never_wires_raw_agent_md(case: str) -> None:
    language, round_number = case.split("/")
    with pytest.raises(PlatformError) as raised:
        _wire(
            language,
            int(round_number),
            _row(card_status="fallback", card_safe_error_code="debate_card_failed"),
        )
    assert raised.value.code == "debate_card_failed"
    assert "SECRET-PERSONA-TEXT" not in str(raised.value)


@pytest.mark.parametrize("case", sorted(PINNED))
def test_compiling_peers_wire_name_stub_not_raw_agent_md(case: str) -> None:
    language, round_number = case.split("/")
    wire = _wire(language, int(round_number), _row(card_status="compiling"))
    payload = json.loads(json.loads(wire)["user"])
    assert payload["persona"] == {"name": "Ada", "markdown": "Ada"}
    assert "SECRET-PERSONA-TEXT" not in wire


# --- schema and bound -------------------------------------------------------------


def test_a_valid_card_is_kept_and_strings_are_trimmed() -> None:
    card = validate_card({**CARD, "identity": "  " + str(CARD["identity"]) + " "}, "en")
    assert card == CARD


@pytest.mark.parametrize(
    ("change", "pointer"),
    [
        ({"extra": "x"}, "/"),
        ({"identity": "   "}, "/identity"),
        ({"position": None}, "/position"),
        ({"reasoning": ["a"] * 6}, "/reasoning"),
        ({"reasoning": ["ok", " "]}, "/reasoning/1"),
        ({"voice_style": "x" * 121}, "/voice_style"),
        ({"voice_style": ""}, "/voice_style"),
        ({"dropped": [{"excerpt": "x", "reason": "rudeness"}]}, "/dropped/0/reason"),
        ({"dropped": [{"excerpt": "x" * 121, "reason": "length_limit"}]}, "/dropped/0/excerpt"),
        ({"dropped": [{"excerpt": "x", "reason": "length_limit", "note": ""}]}, "/dropped/0"),
        ({"dropped": [{"excerpt": "x", "reason": "length_limit"}] * 13}, "/dropped"),
    ],
)
def test_schema_violations_are_rejected_with_a_field_pointer(
    change: dict[str, object], pointer: str
) -> None:
    with pytest.raises(CardRejected) as caught:
        validate_card({**CARD, **change}, "en")
    assert caught.value.code == "debate_card_invalid"
    assert caught.value.pointer == pointer
    missing = {key: value for key, value in CARD.items() if key != "voice_style"}
    with pytest.raises(CardRejected):
        validate_card(missing, "en")


@pytest.mark.parametrize("language", ["zh", "en"])
def test_the_size_bound_is_one_constant_per_language(language: str) -> None:
    limit = CARD_MAX_UNITS[language]
    assert CARD_MAX_UNITS == {"zh": 600, "en": 400}
    unit = "仁" if language == "zh" else "word "
    base = {**CARD, "position": "", "reasoning": [], "speaking_style": "", "voice_style": None}
    # Punctuation, digits and Latin letters do not count in zh.
    padding = "，2026 OK" if language == "zh" else ""
    assert validate_card({**base, "identity": unit * limit + padding}, language)
    with pytest.raises(CardRejected) as caught:
        validate_card({**base, "identity": unit * limit, "voice_style": unit}, language)
    assert caught.value.code == "debate_card_too_long"
    # Dropped excerpts are a report, not persona, and do not count.
    many = [{"excerpt": unit * 20, "reason": "output_format"}] * 12
    assert validate_card({**base, "identity": unit * limit, "dropped": many}, language)


@pytest.mark.parametrize("language", ["zh", "en"])
def test_the_compile_prompt_states_every_rule_the_server_enforces(language: str) -> None:
    prompt = card_system_prompt(language)
    expected = "600 Han characters (count only Han characters" if language == "zh" else "400 words"
    for token in (
        expected,
        "exactly the fields identity, position, reasoning, speaking_style, voice_style and dropped",
        "It must not be empty",
        "at most 5 short items",
        "no empty items",
        "at most 120 characters; otherwise null",
        "at most 12 items",
        "at most 120 characters and not empty",
        "dropped does not count",
        "Chinese" if language == "zh" else "English",
        "never sends the original Agent.md as a fallback",
        *DROP_REASONS,
    ):
        assert token in prompt, token


def test_the_strict_schema_matches_the_validated_fields() -> None:
    assert cards.CARD_SCHEMA["required"] == list(CARD)
    reasons = cards.CARD_SCHEMA["properties"]["dropped"]["items"]["properties"]["reason"]  # type: ignore[index]
    assert reasons["enum"] == list(DROP_REASONS)


# --- persona rendering -------------------------------------------------------------


def test_a_ready_card_is_the_persona_without_dropped_or_voice() -> None:
    row = _row(card_status="ready", card_json=json.dumps(CARD))
    participant = SqlTurnPreparer._participant(None, row)  # type: ignore[arg-type]
    assert participant.persona is not None
    assert participant.persona.as_payload() == {
        "name": "Ada",
        "markdown": (
            "## Identity\nAda is a retired school nurse who has watched phones change "
            "playgrounds.\n\n## Position\nPhones should stay in lockers during lessons.\n\n"
            "## Reasoning\n- Health before convenience.\n- Listens to what pupils actually do."
            "\n\n## Speaking style\nWarm, practical, and fond of small stories from the clinic."
        ),
    }
    assert "500 words" not in participant.persona.markdown
    assert "calm, low voice" not in participant.persona.markdown
    assert participant.agent_md == AGENT_MD
    assert participant.card_position == CARD["position"]


def test_rendering_skips_empty_sections_and_follows_the_debate_language() -> None:
    sparse = {**CARD, "position": "", "reasoning": [], "speaking_style": ""}
    assert render_card_markdown(sparse, "en") == f"## Identity\n{CARD['identity']}"
    assert render_card_markdown(CARD, "zh").startswith("## 身份\n")
    assert "## 说话风格\n" in render_card_markdown(CARD, "zh")


def test_a_ready_card_is_sent_on_the_existing_persona_shape() -> None:
    row = _row(card_status="ready", card_json=json.dumps(CARD))
    first = json.loads(_wire("en", 1, row))
    user = json.loads(first["user"])
    assert set(user["persona"]) == {"name", "markdown"}
    assert user["persona"]["markdown"].startswith("## Identity\n")
    assert "SECRET-PERSONA-TEXT" not in first["user"]


def test_the_persona_is_the_same_in_every_round() -> None:
    row = _row(card_status="ready", card_json=json.dumps(CARD))
    personas = {
        json.dumps(json.loads(json.loads(_wire("en", number, row))["user"])["persona"])
        for number in (1, 2, 3, 4)
    }
    assert len(personas) == 1


def test_a_malformed_stored_card_fails_closed() -> None:
    with pytest.raises(ValueError):
        SqlTurnPreparer._participant(None, _row(card_status="ready", card_json="{}"))  # type: ignore[arg-type]


# --- retrieval ---------------------------------------------------------------------


def test_round_one_query_uses_the_card_position_unless_a_stance_is_assigned() -> None:
    ctx = _v4_context(1)
    ready = SqlTurnPreparer._participant(  # type: ignore[arg-type]
        None, _row(card_status="ready", card_json=json.dumps(CARD))
    )
    queries = build_turn_subqueries(replace(ctx, participant=ready))
    assert queries[1].text == (
        "Should schools ban phones?\nAda\nPhones should stay in lockers during lessons."
    )
    assigned = replace(ready, stance_mode="assigned", initial_stance="oppose")
    queries = build_turn_subqueries(replace(ctx, participant=assigned))
    assert queries[1].text == "Should schools ban phones?\nAda\noppose the Topic's claim"
    empty = SqlTurnPreparer._participant(  # type: ignore[arg-type]
        None, _row(card_status="ready", card_json=json.dumps({**CARD, "position": ""}))
    )
    assert build_turn_subqueries(replace(ctx, participant=empty))[1].text == (
        "Should schools ban phones?\nAda"
    )


# --- privacy scan ------------------------------------------------------------------


def test_the_card_request_scan_is_closed() -> None:
    system = card_system_prompt("en")
    user = cards.card_user_message("Ada", AGENT_MD, "en")
    assert scan_debate_card_outbound_messages((("system", system), ("user", user))).field_classes
    for bad in (
        {"agent_name": "Ada", "agent_md": AGENT_MD, "language": "en", "teacher_note": "x"},
        {"agent_name": "Ada", "agent_md": " ", "language": "en"},
        {"agent_name": "Ada", "agent_md": AGENT_MD, "language": "fr"},
    ):
        with pytest.raises(LLMOutboundPrivacyError):
            scan_debate_card_outbound_messages((("system", system), ("user", json.dumps(bad))))


# --- database: creation, terminal states, ledger, API -------------------------------


def _create(client: Any, database: Any, *, key: str, language: str = "en") -> str:
    ids = [
        _insert_published_agent(database, group_id=GROUP_DEMO_ID, name=name)[0]
        for name in (f"Card One {key}", f"Card Two {key}")
    ]
    _session, csrf = login(client)
    created = client.post(
        f"/api/v1/courses/{COURSE_ID}/debates",
        headers=headers(csrf, **{"Idempotency-Key": f"debate-card-create-{key}"}),
        json={
            "output_language": language,
            "topic": "Should schools ban phones?" if language == "en" else "学校应该禁止手机吗？",
            "participants": [{"agent_id": agent, "stance_mode": "open"} for agent in ids],
            "round_unit_caps": [200, 200, 200, 200],
        },
    )
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


def _participants(database: Any, debate_id: str) -> list[DebateParticipant]:
    with database.session() as db:
        rows = db.scalars(
            select(DebateParticipant)
            .where(DebateParticipant.debate_id == debate_id)
            .order_by(DebateParticipant.order_index)
        ).all()
        db.expunge_all()
        return list(rows)


def test_creation_marks_cards_compiling_and_the_api_reports_each_state(debate_app) -> None:
    _app, database, client = debate_app
    debate_id = _create(client, database, key="api-shape-01")
    rows = _participants(database, debate_id)
    assert [row.card_status for row in rows] == ["compiling", "compiling"]
    detail = client.get(f"/api/v1/debates/{debate_id}").json()
    assert [(item["card_status"], item["card"]) for item in detail["participants"]] == [
        ("compiling", None),
        ("compiling", None),
    ]
    with database.session() as db:
        first = db.get(DebateParticipant, rows[0].id)
        ensure_card_terminal(db, first, lambda: CardOutcome("ready", card=CARD))
        second = db.get(DebateParticipant, rows[1].id)
        ensure_card_terminal(
            db, second, lambda: CardOutcome("fallback", safe_error_code="debate_card_invalid")
        )
    detail = client.get(f"/api/v1/debates/{debate_id}").json()
    ready, fallback = detail["participants"]
    assert ready["card_status"] == "ready" and ready["card"] == CARD
    assert fallback["card_status"] == "fallback" and fallback["card"] is None
    assert fallback["card_teacher_reason"] == "format_invalid"
    assert fallback["card_teacher_notice"] is None
    # The safe code is for logs and diagnosis, not the browser.
    assert "debate_card_invalid" not in json.dumps(detail)
    assert "original AGENT.md" not in json.dumps(detail)


def test_debates_created_before_cards_report_no_card(debate_app) -> None:
    _app, database, client = debate_app
    debate_id = _create(client, database, key="old-debate-01")
    with database.session() as db:
        for row in db.scalars(
            select(DebateParticipant).where(DebateParticipant.debate_id == debate_id)
        ):
            row.card_status = None
    detail = client.get(f"/api/v1/debates/{debate_id}").json()
    assert {item["card_status"] for item in detail["participants"]} == {None}


def test_a_terminal_card_is_never_rewritten(debate_app) -> None:
    _app, database, client = debate_app
    debate_id = _create(client, database, key="terminal-01")
    row_id = _participants(database, debate_id)[0].id
    calls: list[str] = []

    def compile_once() -> CardOutcome:
        calls.append("compile")
        return CardOutcome("ready", card=CARD)

    with database.session() as db:
        row = db.get(DebateParticipant, row_id)
        ensure_card_terminal(db, row, compile_once)
        ensure_card_terminal(db, row, compile_once)
        assert calls == ["compile"]
        # A concurrent preparation that lost the CAS reads the stored winner.
        db.execute(
            DebateParticipant.__table__.update()
            .where(DebateParticipant.id == row_id)
            .values(card_status="compiling", card_json=None)
        )
        db.commit()
        db.refresh(row)
        db.execute(
            DebateParticipant.__table__.update()
            .where(DebateParticipant.id == row_id)
            .values(card_status="fallback", card_safe_error_code="debate_card_attempt_used")
        )
        db.commit()
        ensure_card_terminal(db, row, compile_once)
        assert row.card_status == "fallback"


def test_an_exception_while_compiling_is_a_fallback(debate_app) -> None:
    _app, database, client = debate_app
    debate_id = _create(client, database, key="raise-01")
    row_id = _participants(database, debate_id)[0].id

    def broken() -> CardOutcome:
        raise RuntimeError("boom")

    with database.session() as db:
        row = db.get(DebateParticipant, row_id)
        ensure_card_terminal(db, row, broken)
        assert (row.card_status, row.card_json, row.card_safe_error_code) == (
            "fallback",
            None,
            "debate_card_failed",
        )


def _first_turn(db: Any, debate_id: str) -> tuple[Debate, DebateTurn]:
    debate = db.get(Debate, debate_id)
    turn = db.scalars(
        select(DebateTurn).where(DebateTurn.debate_id == debate_id).order_by(DebateTurn.turn_index)
    ).first()
    return debate, turn


def test_the_first_turn_settles_mock_stub_card_without_raw_agent_md(debate_app) -> None:
    _app, database, client = debate_app
    debate_id = _create(client, database, key="mock-turn-01")
    llm = MockLLMProvider()
    preparer = SqlTurnPreparer(llm=llm)
    with database.session() as db:
        debate, turn = _first_turn(db, debate_id)
        prepared = preparer(db, debate, turn, attempt=1, cancellation_generation=0)
        assert prepared.speech
    rows = _participants(database, debate_id)
    assert rows[0].card_status == "ready"
    assert rows[0].card_safe_error_code is None
    card = json.loads(str(rows[0].card_json))
    assert card["identity"] == rows[0].agent_name
    assert card["dropped"] == []
    # Only the speaker's card is settled; the next Agent's waits for its turn.
    assert rows[1].card_status == "compiling"
    sent = json.loads(llm.prompts[0].messages[1][1])["persona"]
    assert sent == {
        "name": rows[0].agent_name,
        "markdown": f"## Identity\n{rows[0].agent_name}",
    }
    assert rows[0].agent_md_snapshot not in sent["markdown"]


def test_fallback_card_persona_never_returns_raw_agent_md() -> None:
    row = _row(card_status="fallback", card_safe_error_code="debate_card_invalid")
    with pytest.raises(CardUnavailable) as raised:
        card_persona(row, AGENT_MD, "en")
    assert raised.value.code == "debate_card_invalid"
    legacy = _row(card_status=None)
    authored, position = card_persona(legacy, AGENT_MD, "en")
    assert authored.markdown == AGENT_MD and position == ""
    pending = card_persona(_row(card_status="compiling"), AGENT_MD, "en")
    assert pending[0].markdown == "Ada" and pending[1] == ""
    assert AGENT_MD not in pending[0].markdown


def test_forced_fallback_blocks_turn_prep_without_raw_agent_md(debate_app) -> None:
    _app, database, client = debate_app
    debate_id = _create(client, database, key="forced-fallback-01")
    row_id = _participants(database, debate_id)[0].id
    with database.session() as db:
        row = db.get(DebateParticipant, row_id)
        ensure_card_terminal(
            db, row, lambda: CardOutcome("fallback", safe_error_code="debate_card_invalid")
        )
    llm = MockLLMProvider()
    preparer = SqlTurnPreparer(llm=llm)
    with database.session() as db:
        debate, turn = _first_turn(db, debate_id)
        with pytest.raises(PlatformError) as raised:
            preparer(db, debate, turn, attempt=1, cancellation_generation=0)
        assert raised.value.code == "debate_card_invalid"
    assert not llm.prompts


def test_a_ready_card_is_what_the_turn_sends_and_stays_for_a_regeneration(debate_app) -> None:
    _app, database, client = debate_app
    debate_id = _create(client, database, key="ready-turn-01")
    row_id = _participants(database, debate_id)[0].id
    with database.session() as db:
        row = db.get(DebateParticipant, row_id)
        ensure_card_terminal(db, row, lambda: CardOutcome("ready", card=CARD))
    llm = MockLLMProvider()
    preparer = SqlTurnPreparer(llm=llm)
    for _ in range(2):
        with database.session() as db:
            debate, turn = _first_turn(db, debate_id)
            preparer(db, debate, turn, attempt=1, cancellation_generation=0)
    first, second = (json.loads(call.messages[1][1])["persona"] for call in llm.prompts)
    assert first == second
    assert first["markdown"] == render_card_markdown(CARD, "en")


# --- the provider call -------------------------------------------------------------


class _Response:
    def __init__(self, status: int, payload: object) -> None:
        self.status_code = status
        self._payload = payload

    def json(self) -> object:
        return self._payload


class _Transport:
    def __init__(self, outcome: object) -> None:
        self.outcome = outcome
        self.calls: list[dict[str, Any]] = []

    def post(self, url: str, *, headers: Any, json: Any, timeout: Any) -> object:
        self.calls.append({"url": url, "body": json, "timeout": timeout})
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def _ok(card: object) -> _Response:
    return _Response(
        200,
        {
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": json.dumps(card)},
                }
            ]
        },
    )


def _provider(database: Any, outcome: object) -> tuple[DashScopeLLMAdapter, _Transport, str]:
    config = DashScopeLLMConfig(
        api_key="test-only", workspace_id="ws-card-test", model_key=configured_debate_llm_model()
    )
    transport = _Transport(outcome)
    policy = ProviderPolicySnapshotV1(
        endpoint=config.resolved_endpoint,
        privacy_notice_retrieved_at="2026-08-31T00:00:00Z",
        privacy_notice_sha256="a" * 64,
        service_terms_retrieved_at="2026-08-31T00:00:00Z",
        service_terms_sha256="b" * 64,
        faq_retrieved_at="2026-08-31T00:00:00Z",
        faq_sha256="c" * 64,
        no_training_basis="reviewed pay-as-you-go account",
        prompt_response_logging_disabled=True,
        inference_log_backflow_disabled=True,
        optional_content_logging_disabled=True,
        service_improvement_disabled=True,
        storage_disclosed=True,
    )
    repository = ProviderRepository(database)
    if repository.get_policy_snapshot(policy.policy_hash) is None:
        repository.save_policy_snapshot(policy)
    return DashScopeLLMAdapter(config, transport), transport, policy.policy_hash


def _compile(database: Any, debate_id: str, outcome: object, *, index: int = 0) -> Any:
    adapter, transport, policy_hash = _provider(database, outcome)
    row_id = _participants(database, debate_id)[index].id
    with database.session() as db:
        row = db.get(DebateParticipant, row_id)
        debate = db.get(Debate, debate_id)
        result = compile_card_with_provider(
            db,
            debate=debate,
            row=row,
            adapter=adapter,
            policy_hash=policy_hash,
            settings=SimpleNamespace(),
        )
        db.commit()
    operations = [
        item
        for item in ProviderRepository(database).operations(scope_id=debate_id)
        if item.provider_operation == CARD_OPERATION and item.logical_item_id == row_id
    ]
    return result, transport, operations


def test_a_valid_reply_is_a_ready_card_and_one_succeeded_charged_request(debate_app) -> None:
    _app, database, client = debate_app
    debate_id = _create(client, database, key="provider-ok-01")
    result, transport, operations = _compile(database, debate_id, _ok(CARD))
    assert result == CardOutcome("ready", card=CARD)
    assert len(transport.calls) == 1
    body = transport.calls[0]["body"]
    assert body["response_format"]["json_schema"]["strict"] is True
    assert body["model"] == configured_debate_llm_model()
    assert "max_tokens" not in body
    assert json.loads(body["messages"][1]["content"]) == {
        "agent_name": _participants(database, debate_id)[0].agent_name,
        "agent_md": _participants(database, debate_id)[0].agent_md_snapshot,
        "language": "en",
    }
    assert transport.calls[0]["timeout"].read == cards.CARD_TIMEOUT_SECONDS
    [operation] = operations
    assert (operation.state, operation.request_count, operation.charged_request_count) == (
        "succeeded",
        1,
        1,
    )
    # One attempt per participant: a second compile never reaches the supplier.
    again, transport, operations = _compile(database, debate_id, _ok(CARD))
    assert again == CardOutcome("fallback", safe_error_code="debate_card_attempt_used")
    assert transport.calls == [] and len(operations) == 1


@pytest.mark.parametrize(
    ("outcome", "code", "state", "charged"),
    [
        (_ok({**CARD, "reasoning": ["x"] * 6}), "debate_card_invalid", "failed", 1),
        (_ok({**CARD, "identity": "word " * 401}), "debate_card_too_long", "failed", 1),
        (_Response(500, {}), "debate_card_http_rejected", "failed", 1),
        (
            LLMAcceptanceUnknown(),
            "debate_card_acceptance_unknown",
            "acceptance_unknown",
            1,
        ),
        (LLMTransportNotSent(), "debate_card_not_sent", "not_sent", 0),
    ],
)
def test_every_failure_is_a_fallback_with_its_ledger_state(
    debate_app, outcome: object, code: str, state: str, charged: int
) -> None:
    _app, database, client = debate_app
    debate_id = _create(client, database, key=f"provider-{code[-12:]}")
    result, transport, operations = _compile(database, debate_id, outcome)
    assert result == CardOutcome("fallback", safe_error_code=code)
    assert code in cards.CARD_FALLBACK_CODES
    assert len(transport.calls) == 1
    [operation] = operations
    assert operation.state == state
    assert operation.charged_request_count == charged


def test_a_missing_policy_blocks_the_call_before_anything_is_sent(debate_app) -> None:
    _app, database, client = debate_app
    debate_id = _create(client, database, key="provider-nopolicy")
    adapter, transport, _policy_hash = _provider(database, _ok(CARD))
    row_id = _participants(database, debate_id)[0].id
    with database.session() as db:
        result = compile_card_with_provider(
            db,
            debate=db.get(Debate, debate_id),
            row=db.get(DebateParticipant, row_id),
            adapter=adapter,
            policy_hash=None,
            settings=SimpleNamespace(),
        )
    assert result == CardOutcome("fallback", safe_error_code="debate_card_preflight_blocked")
    assert transport.calls == []


def test_a_chinese_debate_asks_for_a_chinese_card(debate_app) -> None:
    _app, database, client = debate_app
    debate_id = _create(client, database, key="provider-zh-01", language="zh")
    zh_card = {**CARD, "identity": "仁" * 600, "reasoning": [], "position": ""}
    zh_card.update({"speaking_style": "", "voice_style": None})
    result, transport, _operations = _compile(database, debate_id, _ok(zh_card))
    assert result.status == "ready"
    system = transport.calls[0]["body"]["messages"][0]["content"]
    assert "600 Han characters" in system and "in Chinese" in system


# --- voice ------------------------------------------------------------------------


def test_a_ready_card_voice_line_replaces_the_debate_instruction() -> None:
    base = {"rate": 1.25, "instruction": "Everyone sounds formal.", "seed": None}
    ready = json.dumps(CARD)
    assert cards.voice_params_with_card(base, "ready", ready) == {
        **base,
        "instruction": CARD["voice_style"],
    }
    # No voice line, no ready card, or an unreadable card: the Debate's values stay.
    silent = json.dumps({**CARD, "voice_style": None})
    for status, stored in (
        ("ready", silent),
        ("fallback", None),
        ("compiling", None),
        (None, None),
        ("ready", "not json"),
    ):
        assert cards.voice_params_with_card(base, status, stored) == base
    assert base["instruction"] == "Everyone sounds formal."


def test_a_host_without_the_participant_table_voices_as_before() -> None:
    base = {"rate": 1.0, "instruction": None, "seed": None}
    assert cards.participant_voice_params(object(), "participant-0", base) == base
