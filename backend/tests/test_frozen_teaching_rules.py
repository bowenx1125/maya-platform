"""Offline isolation, actual wire messages and frozen recovery for teaching Markdown."""

import json
from dataclasses import replace

import pytest
from app.modules.debates.generation.segments import SegmentInputSnapshot, build_segment_input
from app.modules.debates.models import Debate
from app.modules.debates.teaching_rules import (
    compile_system_prompt,
    default_teaching_prompts,
    freeze_teaching_rules,
    frozen_system_prompt,
)
from app.providers.llm_adapter import LLMAdapterError
from app.providers.llm_segments import SegmentRecoveryInputV2

from tests.conftest import login
from tests.test_four_round_content import context
from tests.test_four_round_provider import adapter, snapshot
from tests.test_wave2_setup import (
    COURSE_ID,
    GROUP_DEMO_ID,
    _insert_published_agent,
    headers,
)
from tests.test_wave2_setup import (
    debate_app as debate_app,
)


@pytest.mark.parametrize("language", ["zh", "en"])
@pytest.mark.parametrize("round_number", [1, 2, 3, 4])
def test_actual_wire_uses_only_frozen_markdown_and_execution_contract(language, round_number):
    custom = (
        "# 本场独有规则\n\n解释一个实用案例。"
        if language == "zh"
        else "# Unique lesson\n\nExplain one practical example."
    )
    prompts = {"zh": custom, "en": custom}
    rules = freeze_teaching_rules(prompts)
    system = frozen_system_prompt(json.dumps(rules), round_number, language)
    frozen = replace(
        snapshot(),
        language=language,
        round=replace(snapshot().round, number=round_number),
        frozen_system_prompt=system,
    )
    request = adapter().build_request(frozen)
    assert request.system_message.content == system
    assert custom in system
    assert default_teaching_prompts()[language] not in system
    assert f"Execute round {round_number} of 4" in system
    assert "# Execution contract" in system
    assert "segments" in system
    assert "frozen_system_prompt" not in json.loads(request.user_message.content)


def test_recovery_preserves_exact_prompt_and_detects_changed_rule_hash(monkeypatch):
    system = compile_system_prompt("# Original\nUse a concrete counterexample.", 1, "en")
    frozen = replace(snapshot(), frozen_system_prompt=system)
    request = adapter().build_request(
        frozen,
        debate_id="debate-1",
        turn_id="turn-1",
        policy_hash="a" * 64,
        export_manifest_hash="b" * 64,
        build_manifest_hash="c" * 64,
    )
    recovery = SegmentRecoveryInputV2.from_request(request)
    monkeypatch.setattr(
        "app.modules.debates.teaching_rules.default_teaching_prompts",
        lambda: {"zh": "CHANGED", "en": "CHANGED"},
    )
    restored = SegmentInputSnapshot.from_server_payload(frozen.to_server_payload())
    assert restored.input_hash == frozen.input_hash
    assert adapter().build_request(restored).system_message.content == system
    payload = request.frozen_payload()
    payload["snapshot"]["frozen_system_prompt"] += " CHANGED"
    from app.providers.llm_segments import load_segment_request_v2

    with pytest.raises(LLMAdapterError):
        load_segment_request_v2(payload)
    assert recovery.input_json


def test_blank_markdown_does_not_restore_old_teaching_rules():
    system = compile_system_prompt("", 2, "en")
    assert "# Execution contract" in system
    assert "initial_position" not in system
    assert "question_target_id" in system


def test_generation_context_binds_prompt_into_snapshot_identity():
    ctx = context(1)
    first = build_segment_input(
        replace(ctx, frozen_system_prompt="Rule A"), persona=ctx.participant.persona
    )
    second = build_segment_input(
        replace(ctx, frozen_system_prompt="Rule B"), persona=ctx.participant.persona
    )
    assert first.to_user_payload() == second.to_user_payload()
    assert first.input_hash != second.input_hash
    assert first.frozen_system_prompt == "Rule A"


def test_creation_freezes_two_languages_and_other_debates_remain_independent(
    debate_app, monkeypatch
):
    _app, database, client = debate_app
    ids = [
        _insert_published_agent(database, group_id=GROUP_DEMO_ID, name=name)[0]
        for name in ("Rules One", "Rules Two")
    ]
    _session, csrf = login(client)
    defaults = client.get(f"/api/v1/courses/{COURSE_ID}/debate-ruleset")
    assert defaults.status_code == 200
    assert defaults.json() == default_teaching_prompts()
    body = {
        "topic": "Water?",
        "participants": [{"agent_id": agent, "stance_mode": "open"} for agent in ids],
        "teaching_prompts": {"zh": "# 中文课堂", "en": "# Original English lesson"},
    }
    response = client.post(
        f"/api/v1/courses/{COURSE_ID}/debates",
        headers=headers(csrf, **{"Idempotency-Key": "frozen-teaching-create-001"}),
        json=body,
    )
    assert response.status_code == 201, response.text
    debate_id = response.json()["id"]
    with database.session() as db:
        frozen = db.get(Debate, debate_id).rule_snapshot_json
    assert json.loads(frozen)["teaching_prompts"] == body["teaching_prompts"]
    monkeypatch.setattr(
        "app.modules.debates.teaching_rules.default_teaching_prompts",
        lambda: {"zh": "NEW CN", "en": "NEW EN"},
    )
    other = client.post(
        f"/api/v1/courses/{COURSE_ID}/debates",
        headers=headers(csrf, **{"Idempotency-Key": "frozen-teaching-create-002"}),
        json={key: value for key, value in body.items() if key != "teaching_prompts"},
    )
    assert other.status_code == 201, other.text
    with database.session() as db:
        assert db.get(Debate, debate_id).rule_snapshot_json == frozen
        assert (
            json.loads(db.get(Debate, other.json()["id"]).rule_snapshot_json)["teaching_prompts"][
                "en"
            ]
            == "NEW EN"
        )
    replay = client.post(
        f"/api/v1/courses/{COURSE_ID}/debates",
        headers=headers(csrf, **{"Idempotency-Key": "frozen-teaching-create-001"}),
        json=body,
    )
    assert replay.json()["id"] == debate_id
    rejected = client.patch(
        f"/api/v1/debates/{debate_id}",
        headers=headers(csrf),
        json={
            **body,
            "expected_revision": 0,
            "teaching_prompts": {"zh": "Changed", "en": "Changed"},
        },
    )
    assert rejected.status_code == 409
    updated = client.patch(
        f"/api/v1/debates/{debate_id}",
        headers=headers(csrf),
        json={
            **{k: v for k, v in body.items() if k != "teaching_prompts"},
            "background": "New context",
            "expected_revision": 0,
        },
    )
    assert updated.status_code == 200, updated.text
    with database.session() as db:
        assert db.get(Debate, debate_id).rule_snapshot_json == frozen


def test_migration_freezes_existing_rules_without_overwriting_custom_records(monkeypatch):
    from importlib import import_module

    from sqlalchemy import create_engine, text

    migration = import_module("migrations.versions.0027_frozen_teaching_markdown")
    engine = create_engine("sqlite://")
    with engine.begin() as db:
        db.execute(text("CREATE TABLE debates (id TEXT PRIMARY KEY, rule_snapshot_json TEXT)"))
        legacy = {"teaching_protocol": "four_round_v1", "round_count": 4}
        custom = {**legacy, **freeze_teaching_rules({"zh": "Custom CN", "en": "Custom EN"})}
        other = {"round_count": 2}
        for name, rules in (("legacy", legacy), ("custom", custom), ("other", other)):
            db.execute(
                text("INSERT INTO debates VALUES (:id, :rules)"),
                {"id": name, "rules": json.dumps(rules)},
            )
        monkeypatch.setattr(migration.op, "get_bind", lambda: db)
        migration.upgrade()
        rows = {row[0]: json.loads(row[1]) for row in db.execute(text("SELECT * FROM debates"))}
        assert rows["legacy"]["teaching_prompts"] == default_teaching_prompts()
        assert rows["custom"] == custom
        assert rows["other"] == other
        migration.upgrade()
        assert {
            row[0]: json.loads(row[1]) for row in db.execute(text("SELECT * FROM debates"))
        } == rows
