"""Offline isolation, actual wire messages and frozen recovery for teaching Markdown."""

import json
from dataclasses import replace

import pytest
from app.modules.debates.generation.segments import SegmentInputSnapshot, build_segment_input
from app.modules.debates.models import Debate
from app.modules.debates.teaching_rules import (
    compile_code_contract_prompt,
    compile_system_prompt,
    default_teaching_prompts,
    execution_contracts,
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
        "# 本场独有规则\n\n第 {round} 轮：解释一个实用案例。"
        if language == "zh"
        else "# Unique lesson\n\nRound {round}: explain one practical example."
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
    # v4 (2026-11-10) overturns the 2026-10-24 template decision: the wire
    # carries the teacher's Markdown word for word, then the code-owned
    # contract for this round, and nothing else.
    teacher = custom.replace("{round}", str(round_number))
    contract_heading = "# 执行约定" if language == "zh" else "# Execution contract"
    assert system == compile_code_contract_prompt(custom, round_number, language)
    assert system.startswith(teacher + "\n\n" + contract_heading)
    assert system.count(contract_heading) == 1
    assert "{round}" not in system
    assert "Output speech in" not in system
    assert "First-person pronouns in a history entry" not in system
    assert "preserve who gave it and whom it was addressed to" not in system
    assert "frozen_system_prompt" not in json.loads(request.user_message.content)


def test_identity_guidance_does_not_rewrite_previously_frozen_prompts():
    original = "# Frozen teaching rules\nAn earlier exact execution contract."
    stored = {"system_prompts": {"en": [original] * 4, "zh": [original] * 4}}
    assert frozen_system_prompt(json.dumps(stored), 2, "zh") == original


def test_recovery_preserves_exact_prompt_and_detects_changed_rule_hash(monkeypatch):
    system = compile_system_prompt("# Original\nUse a concrete counterexample.", 1)
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
    assert compile_system_prompt("", 2) == ""


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
    assert defaults.json() == {**default_teaching_prompts(), "contract": execution_contracts()}
    body = {
        "output_language": "en",
        "topic": "Water?",
        "participants": [{"agent_id": agent, "stance_mode": "open"} for agent in ids],
        "teaching_prompts": {"zh": "# 中文课堂", "en": "# Original English lesson"},
        "round_unit_caps": [200, 200, 200, 200]
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
            **{k: v for k, v in body.items() if k not in {"teaching_prompts", "output_language"}},
            "background": "New context",
            "expected_revision": 0,
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["output_language"] == "en"
    with database.session() as db:
        assert db.get(Debate, debate_id).rule_snapshot_json == frozen


def test_selected_language_only_uses_its_own_frozen_prompt():
    from app.modules.debates.schemas import DebateDraftRequest

    defaults = default_teaching_prompts()
    rules = freeze_teaching_rules({**defaults, "zh": "# Chinese-only revision"})
    english = frozen_system_prompt(json.dumps(rules), 1, "en")
    assert english == compile_code_contract_prompt(defaults["en"], 1, "en")
    assert "Chinese-only revision" not in english
    assert "Chinese-only revision" in frozen_system_prompt(json.dumps(rules), 1, "zh")
    assert DebateDraftRequest.model_fields["output_language"].default == "zh"


@pytest.mark.parametrize(
    "language,heading",
    [
        ("zh", "## 发言身份与指代"),
        ("en", "## Speaker identity and attribution"),
    ],
)
def test_attribution_guidance_is_editable_ruleset_not_hidden_execution(language, heading):
    authored = default_teaching_prompts()[language]
    assert heading in authored
    rules = freeze_teaching_rules()
    assert rules["teaching_prompts"][language] == authored
    message = frozen_system_prompt(json.dumps(rules), 2, language)
    contract_heading = "# 执行约定" if language == "zh" else "# Execution contract"
    assert heading in message.split(contract_heading, 1)[0]
    edited = authored.split(heading, 1)[0] + "\n## Custom discussion\nUse my teaching rules."
    edited_message = compile_system_prompt(edited, 2, language)
    assert heading not in edited_message
    assert "First-person pronouns" not in edited_message
    assert "preserve who gave it" not in edited_message
    assert edited_message == edited
    assert (
        "只以 discussion.self_id 的身份发言"
        if language == "zh"
        else "Only act as discussion.self_id"
    ) in message.split(contract_heading, 1)[1]
