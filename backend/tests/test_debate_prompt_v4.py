"""Debate prompt contract v4 (owner decisions 2026-11-10).

New Debates freeze a code-owned execution contract beside the teacher's
Ruleset, a per-turn task group with a hard length cap, enforced repetition
rules and a Topic-led round-1 retrieval query. Debates frozen before keep the
exact bytes they always sent.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import replace

import pytest
from app.modules.agents.markdown import AgentMarkdown
from app.modules.debates.generation import GenerationContext, MutualLearningPolicy
from app.modules.debates.generation.four_round import speech_units, turn_unit_cap
from app.modules.debates.generation.retrieval import build_turn_subqueries
from app.modules.debates.generation.segments import (
    SegmentInputSnapshot,
    SegmentProtocolError,
    build_segment_input,
    self_repetition_ratio,
    validate_segment_output,
)
from app.modules.debates.generation.types import ParticipantContext
from app.modules.debates.generation_params import CONTRACT_VERSION
from app.modules.debates.models import Debate
from app.modules.debates.setup.rules import canonical_rule_snapshot_json
from app.modules.debates.teaching_rules import (
    default_teaching_prompts,
    execution_contracts,
    freeze_teaching_rules,
    frozen_speech_length,
    frozen_system_prompt,
    strip_execution_contract,
)
from app.providers.llm_segments import OWNED_CONTRACT_PROMPT_VERSION

from tests.conftest import login
from tests.test_four_round_content import context
from tests.test_four_round_provider import adapter
from tests.test_segments_protocol import _ready
from tests.test_wave2_setup import COURSE_ID, GROUP_DEMO_ID, _insert_published_agent, headers
from tests.test_wave2_setup import debate_app as debate_app

PARAMS = {
    "temperature": 0.7,
    "top_p": 0.9,
    "presence_penalty": 0.1,
    "frequency_penalty": 0.2,
    "repetition_penalty": 1.05,
    "max_tokens": 900,
    "enable_thinking": False,
    "seed": 7,
}
V4 = {"contract_version": CONTRACT_VERSION, "params": PARAMS}
AGENT_MD = (
    "# Persona\n\nI always answer in exactly 500 words of classical prose. SECRET-PERSONA-TEXT"
)

# sha256 of the system message, user message, request body, input hash and
# prompt version, computed on origin/main (d59b6c1) before v4 existed. A v3
# Debate, a Debate frozen before parameters, and a pre-editor Debate must keep
# sending these exact bytes.
PINNED = {
    "ruleset_contract_v3/zh/1": "32717d240b45b3ca8325fcc9a0089cc9820dc1fca77b5a82183cec7544ffdc5d",
    "ruleset_contract_v3/zh/2": "c825335c049a7b38fa082968d8f284057b810aa045ad84afe7b64a5ae718a9e8",
    "ruleset_contract_v3/zh/3": "da1c891419f616982aeff8c9151565180965b0b6c668dd80e2f52a36a3666b05",
    "ruleset_contract_v3/zh/4": "70ae574347a55fb528281019e3eeb3079952d34bbbbac9b15df7f10cae059288",
    "ruleset_contract_v3/en/1": "216ba17b202cf177a6cbc50d1af5d4380a31cd30891b6906c074c3a2d8fe9dd2",
    "ruleset_contract_v3/en/2": "c58305d9bfe508674d29bbe2970a8e4306efd6a4f009508513d3c21d2f42ec4f",
    "ruleset_contract_v3/en/3": "c54ee0bf9984ceee313ead44943dd1f82e55b9ca48e0081202036e84fece2a31",
    "ruleset_contract_v3/en/4": "6de500ad95841761a237e69210a7560d657e382c16b4029fd493e8efbd8891dc",
    "pre_params/zh/1": "9064c097f0382c7d83b202a77c09e287d0ada7ee7346ad81d383304ca6af2efc",
    "pre_params/zh/2": "aeba10d38e41f4934d30f34c1d78ea993e8906a01663c58588dc7194e33f8563",
    "pre_params/zh/3": "3cc5194ebba096fcbe5ea5a9491dad0af9e3a61f4a4403f18cbc7398a5d4fc7c",
    "pre_params/zh/4": "191668f2935adf30cbf7465231b53c2b5065b8ad219617ee47116b6feb6fa873",
    "pre_params/en/1": "29d041d234eef537b3c517bdf7a5bbe02a998456165a244a4d6cfd49c7c4056e",
    "pre_params/en/2": "7db3f1d83d4950166daa6c78ff5e3c09119cb03a84cb67ba81d5c5c1df722011",
    "pre_params/en/3": "96a6cc63952cdcd8b18653dce47f75be9c655c1e96cfa9f5f9d0239e32f74b69",
    "pre_params/en/4": "37c04b48e830004d7cfeedf03e3692be786056548b0e42e32421093ca46e5d44",
    "pre_editor/zh/1": "06b32795574b439841a89339acf8175b5ef87ad50e168540c2a7bcd9211f2757",
    "pre_editor/zh/2": "9dd2bd5d54cabd9e2efdc27ece5c7402511d1680aa8c6b40b1a4b87bbfd57235",
    "pre_editor/zh/3": "813b85cfb43eba316875247d723611949f68534364c3f756e53e1bba454cacc7",
    "pre_editor/zh/4": "664d29fbbd22bf953d6135d19030ab7c5993acfcaa300606a1df7aeaf49cc9ad",
    "pre_editor/en/1": "343c04dc157ddfab928532d7918a6500fcfcfc08a9d174e71e9642947ca4fb6a",
    "pre_editor/en/2": "c6d83d73a095535e52934305813d4dc10a6c768308580f5e18c03fe8792a5a42",
    "pre_editor/en/3": "0074f50fc0cee24a2a401fa92790791874c9ee875868b646a18905af7d1a637b",
    "pre_editor/en/4": "1570a7d7361d41e9fa57f9bbdb42e40d0e47eb5fce919ec2ffa157f04d67558d",
}
ENV_PARAMS = {
    "temperature",
    "top_p",
    "presence_penalty",
    "repetition_penalty",
    "max_tokens",
    "enable_thinking",
    "seed",
}


def _wire(language: str, round_number: int, contract: str) -> str:
    ctx = context(round_number, language)
    prompt = (
        None if contract == "pre_editor" else f"# Frozen {language} lesson\n\nRound {round_number}."
    )
    frozen = (
        None
        if contract in {"pre_editor", "pre_params"}
        else {"contract_version": contract, "params": PARAMS}
    )
    ctx = replace(ctx, frozen_system_prompt=prompt, frozen_llm=frozen)
    snapshot = build_segment_input(ctx, persona=ctx.participant.persona)
    request = adapter().build_request(snapshot)
    body = dict(request.body)
    if frozen is None:
        # Those Debates send the current environment defaults.
        body = {key: value for key, value in body.items() if key not in ENV_PARAMS}
    return json.dumps(
        {
            "system": request.system_message.content,
            "user": request.user_message.content,
            "body": body,
            "input_hash": snapshot.input_hash,
            "version": request.prompt_contract_version,
        },
        ensure_ascii=False,
        sort_keys=True,
    )


@pytest.mark.parametrize("case", sorted(PINNED))
def test_debates_frozen_before_v4_send_the_same_bytes(case: str) -> None:
    contract, language, round_number = case.split("/")
    wire = _wire(language, int(round_number), contract)
    assert hashlib.sha256(wire.encode()).hexdigest() == PINNED[case]
    assert '"task"' not in json.loads(wire)["user"]


def _participants(count: int, *, stance: str | None = None) -> tuple[ParticipantContext, ...]:
    names = ("Ada", "Bao", "Chen", "Dara", "Eli")
    return tuple(
        ParticipantContext(
            participant_id=f"participant-{index}",
            agent_id=f"agent-{index}",
            agent_name=names[index],
            slot="ABCDE"[index],
            order_index=index,
            snapshot_id=f"snapshot-{index}",
            agent_md=AGENT_MD,
            stance_mode="assigned" if stance and index == 0 else "open",
            initial_stance=stance if index == 0 else None,
            teacher_note="PRIVATE TEACHER NOTE",
            persona=AgentMarkdown(name=names[index], markdown=AGENT_MD),
        )
        for index in range(count)
    )


def _v4_context(
    round_no: int,
    language: str = "en",
    *,
    count: int = 3,
    speaker: int = 0,
    stance: str | None = None,
    speeches: dict[int, str] | None = None,
    frozen_llm: dict[str, object] | None = V4,
) -> GenerationContext:
    people = _participants(count, stance=stance)
    plans = MutualLearningPolicy().plan(
        [item.participant_id for item in people],
        round_count=4,
        teaching_protocol="four_round_v1",
    )
    plan = next(
        item
        for item in plans
        if item.round_no == round_no and item.participant_id == people[speaker].participant_id
    )
    predecessors = tuple(
        _ready(
            item.turn_id,
            item.participant_id,
            item.round_no,
            item.turn_index,
            (speeches or {}).get(item.turn_index, f"Completed point number {item.turn_index}."),
        )
        for item in plans
        if item.turn_index < plan.turn_index
    )
    return GenerationContext(
        debate_id="debate-v4",
        topic="Should schools ban phones?",
        turn=plan,
        participant=people[speaker],
        participants=people,
        predecessors=predecessors,
        round_count=4,
        turn_protocol="segments_v2",
        teaching_protocol="four_round_v1",
        output_language=language,
        frozen_llm=frozen_llm,
        target_minutes=5,
        voice_rate=1.0,
    )


def _snapshot(ctx: GenerationContext) -> SegmentInputSnapshot:
    return build_segment_input(ctx, persona=ctx.participant.persona)


# --- 1. contract / Ruleset split ------------------------------------------------


@pytest.mark.parametrize("language", ["zh", "en"])
def test_default_ruleset_is_teacher_content_only(language: str) -> None:
    ruleset = default_teaching_prompts()[language]
    assert "# 执行约定" not in ruleset and "# Execution contract" not in ruleset
    assert "discussion.self_id" not in ruleset and "source_ids" not in ruleset
    # No parroted example phrases and no length numbers; the server supplies those.
    assert not re.search(r"[“”\"]", ruleset)
    assert not re.search(r"\d+\s*(字|words?)", ruleset)
    headings = re.findall(r"^## (?:第.轮|Round \d)$", ruleset, re.M)
    assert len(headings) == 4


@pytest.mark.parametrize("language", ["zh", "en"])
@pytest.mark.parametrize("round_number", [1, 2, 3, 4])
def test_v4_prompt_has_only_this_rounds_task_and_fields(language: str, round_number: int) -> None:
    rules = freeze_teaching_rules()
    assert rules["contract_version"] == CONTRACT_VERSION
    system = frozen_system_prompt(json.dumps(rules), round_number, language)
    zh_rounds = ("第一轮", "第二轮", "第三轮", "第四轮")
    for other in range(1, 5):
        heading = f"## {zh_rounds[other - 1]}" if language == "zh" else f"## Round {other}"
        assert (heading in system) == (other == round_number), heading
    assert ("{target_agent_id,text}" in system) == (round_number == 2)
    assert ("{position,change,reason,influence,unresolved_question}" in system) == (
        round_number == 3
    )
    assert ("B 编号" in system or "B ID" in system) == (round_number == 4)
    assert "{round}" not in system
    # Every rule the server enforces is stated.
    for token in ("task.max_units", "40%", "task.round_task"):
        assert token in system, token
    assert "四分之一时" in system or "by more than a quarter" in system


@pytest.mark.parametrize("language", ["zh", "en"])
def test_legacy_contract_section_is_stripped_on_save_and_read(language: str) -> None:
    heading = "# 执行约定" if language == "zh" else "# Execution contract"
    old = f"# Lesson\n\n## Round 1\n\n- Open boldly.\n\n{heading}\n\n- Old copied contract text.\n"
    assert strip_execution_contract(old) == "# Lesson\n\n## Round 1\n\n- Open boldly.\n"
    rules = freeze_teaching_rules({"zh": old, "en": old})
    assert rules["teaching_prompts"][language] == strip_execution_contract(old)
    system = frozen_system_prompt(json.dumps(rules), 1, language)
    assert "Old copied contract text." not in system
    assert system.count(heading) == 1
    assert system.startswith("# Lesson\n\n## Round 1\n\n- Open boldly.")


def test_ruleset_without_round_headings_is_kept_whole() -> None:
    custom = "# Unique lesson\n\nAlways give one practical example."
    rules = freeze_teaching_rules({"zh": custom, "en": custom})
    assert frozen_system_prompt(json.dumps(rules), 3, "en").startswith(custom + "\n\n")


# --- 2. task group ---------------------------------------------------------------


def test_task_group_names_real_targets_and_keeps_cyclic_order() -> None:
    second = _snapshot(_v4_context(2, speaker=1))
    payload = json.loads(second.to_user_json())
    assert set(payload) == {
        "topic",
        "language",
        "round",
        "persona",
        "history",
        "sources",
        "barrages",
        "discussion",
        "task",
    }
    # Bao (index 1) questions the next Agent, exactly as question_target_id says.
    assert payload["discussion"]["question_target_id"] == "participant-2"
    assert payload["task"]["round_task"].startswith(
        "Rebut Chen's opening and end the speech by asking Chen one question. Use "
    )
    # A question put to this speaker earlier in round 2 waits for round 3.
    assert payload["discussion"]["received_questions"] == []
    third = _snapshot(_v4_context(3, "zh", speaker=1))
    assert third.task is not None
    assert third.task["round_task"].startswith("回答Ada向你提的问题，再就一个观点提出反驳。写")
    assert _snapshot(_v4_context(1, speaker=0)).task["round_task"].startswith("State your own")


def test_task_group_carries_cap_and_assigned_stance_but_no_teacher_note() -> None:
    snapshot = _snapshot(_v4_context(1, stance="oppose"))
    assert snapshot.task == {
        "round_task": (
            "State your own judgment on the Topic and your reason. "
            "Use 3 to 4 sentences and come close to max_units."
        ),
        "max_units": 60,
        "stance": "oppose the Topic's claim",
    }
    # The export manifest forbids teacher notes, so they never reach the wire.
    request = adapter().build_request(snapshot)
    assert "PRIVATE TEACHER NOTE" not in request.user_message.content
    assert request.prompt_contract_version == OWNED_CONTRACT_PROMPT_VERSION
    assert "task" not in _snapshot(_v4_context(1, frozen_llm=None)).to_user_payload()


def test_task_group_is_only_accepted_under_v4() -> None:
    v4 = _snapshot(_v4_context(2))
    restored = SegmentInputSnapshot.from_server_payload(v4.to_server_payload())
    assert restored.task == v4.task and restored.input_hash == v4.input_hash
    payload = v4.to_user_payload()
    with pytest.raises(SegmentProtocolError):
        SegmentInputSnapshot.from_user_payload(payload, frozen_llm_json=None)
    without = {key: value for key, value in payload.items() if key != "task"}
    with pytest.raises(SegmentProtocolError):
        SegmentInputSnapshot.from_user_payload(without, frozen_llm_json=v4.frozen_llm_json)


def test_v4_does_not_append_the_old_no_copy_rule() -> None:
    request = adapter().build_request(_snapshot(_v4_context(3)))
    assert "Verbatim repeats are removed by the server." not in request.system_message.content


# --- 3. length --------------------------------------------------------------------


CAPS = {
    # participants: (round 1/4, round 2/3) at 5 minutes, voice rate 1.0
    "zh": {2: (140, 115), 3: (90, 75), 4: (70, 55), 5: (55, 45)},
    "en": {2: (90, 75), 3: (60, 50), 4: (45, 35), 5: (35, 30)},
}


@pytest.mark.parametrize("language", ["zh", "en"])
@pytest.mark.parametrize("participants", [2, 3, 4, 5])
def test_turn_cap_arithmetic(language: str, participants: int) -> None:
    outer, inner = CAPS[language][participants]
    caps = [
        turn_unit_cap(
            language,
            minutes=5,
            voice_rate=1.0,
            participants=participants,
            round_number=round_number,
        )
        for round_number in (1, 2, 3, 4)
    ]
    assert caps == [outer, inner, inner, outer]


def test_turn_cap_follows_voice_rate_and_never_drops_below_the_floor() -> None:
    # 5 × 230 × 1.25 × 0.9 / 8 × 1.1 = 177.9, down to a multiple of five.
    assert turn_unit_cap("zh", minutes=5, voice_rate=1.25, participants=2, round_number=1) == 175
    assert turn_unit_cap("zh", minutes=3, voice_rate=1.0, participants=5, round_number=2) == 40
    assert turn_unit_cap("en", minutes=3, voice_rate=1.0, participants=5, round_number=2) == 25


def test_units_count_han_characters_or_words() -> None:
    assert speech_units("我们，今天 2026 年。OK", "zh") == 5
    assert speech_units("It's a well-known fact, 2026.", "en") == 5


def _output(*texts: str, question: str | None = None) -> dict[str, object]:
    return {
        "segments": [
            {"text": text, "source_ids": [], "reply_to": None, "support_mode": "no_match"}
            for text in texts
        ],
        "question": {"target_agent_id": "participant-1", "text": question} if question else None,
        "discussion_memory": None,
    }


def _sentences(count: int, word: str = "reason") -> str:
    return " ".join(f"Sentence {index} gives one more {word} here." for index in range(count))


def test_over_length_speech_is_trimmed_by_whole_sentences_without_a_repair() -> None:
    snapshot = _snapshot(_v4_context(1))  # cap 60 words, limit 75
    long = _output(_sentences(6), _sentences(6, "example"))  # 84 words
    # The first attempt is trimmed at once: a rewrite for length made the
    # model repeat itself and spent the repair the repetition rules need.
    accepted = validate_segment_output(long, snapshot)
    assert validate_segment_output(long, snapshot, allow_history_copy=True).speech == (
        accepted.speech
    )
    assert speech_units(accepted.speech, "en") <= 75
    assert accepted.speech.endswith(".")
    # Only whole sentences go: every kept one still ends where it ended.
    for segment in accepted.segments:
        assert segment.text.count("Sentence") == len(re.findall(r"here\.", segment.text))
    assert [item.as_payload()["text"] for item in accepted.lineage] == [
        item.text for item in accepted.segments
    ]
    assert accepted.lineage[-1].end_offset == len(accepted.speech)
    # Within the limit nothing changes, and a fitting stored speech reloads unchanged.
    fits = _output(_sentences(5))
    assert validate_segment_output(fits, snapshot).speech == _sentences(5)


def test_trimming_keeps_one_sentence_and_the_spoken_question() -> None:
    snapshot = _snapshot(_v4_context(2))  # cap 50 words, limit 62
    one = " ".join(["word"] * 90) + "."
    assert validate_segment_output(_output(one), snapshot, repairable=False).speech == one
    question = "Would you still ban phones during lunch breaks?"
    accepted = validate_segment_output(
        _output(_sentences(9) + " " + question, question=question), snapshot, repairable=False
    )
    assert accepted.speech.endswith(question)
    assert accepted.question == {"target_agent_id": "participant-1", "text": question}
    assert speech_units(accepted.speech, "en") <= 62


def test_unauthorized_repair_never_fails_a_turn_for_length() -> None:
    snapshot = _snapshot(_v4_context(1))
    accepted = validate_segment_output(_output(_sentences(12)), snapshot, repairable=False)
    assert speech_units(accepted.speech, "en") <= 75


# --- 4. repetition ---------------------------------------------------------------


COPY = "Phones split attention in every single lesson we have ever observed."
# New, but well under 40% of the 50-word cap once the copy is removed.
SHORT = "Still, lunch breaks differ from lessons for most students."


def test_stripping_that_leaves_a_stump_is_repaired_not_published() -> None:
    ctx = _v4_context(2, speeches={0: COPY})
    snapshot = _snapshot(ctx)
    with pytest.raises(SegmentProtocolError) as caught:
        validate_segment_output(_output(COPY + " " + SHORT), snapshot)
    assert caught.value.code == "segment_history_stump"
    # After the repair the whole speech is kept rather than a stump.
    accepted = validate_segment_output(
        _output(COPY + " " + SHORT), snapshot, allow_history_copy=True
    )
    assert accepted.speech == COPY + " " + SHORT
    # Enough new text left: the copy is simply removed, as before.
    fresh = _sentences(4)
    assert validate_segment_output(_output(COPY + " " + fresh), snapshot).speech == fresh


def test_self_repetition_is_repaired_once_then_accepted() -> None:
    own = (
        "Banning phones protects attention because students cannot check messages during class "
        "and teachers see calmer rooms within weeks."
    )
    ctx = _v4_context(2, speaker=0, speeches={0: own})
    snapshot = _snapshot(ctx)
    restated = (
        "As I said, banning phones protects attention because students cannot check messages "
        "during class and teachers see calmer rooms. Chen, do you agree?"
    )
    with pytest.raises(SegmentProtocolError) as caught:
        validate_segment_output(_output(restated), snapshot)
    assert caught.value.code == "segment_self_repetition"
    assert validate_segment_output(_output(restated), snapshot, allow_history_copy=True).speech
    # Another speaker's words are not self-repetition.
    other = _snapshot(_v4_context(2, speaker=1, speeches={0: own}))
    assert validate_segment_output(_output(restated), other).speech == restated


def test_new_codes_get_the_existing_single_repair() -> None:
    from app.modules.debates.generation.segments_runtime import SEGMENT_REPAIR_CODES

    assert {"segment_history_stump", "segment_self_repetition"} <= SEGMENT_REPAIR_CODES
    assert "segment_too_long" not in SEGMENT_REPAIR_CODES


def test_v3_snapshot_keeps_old_validation() -> None:
    snapshot = _snapshot(_v4_context(1, frozen_llm=None))
    long = _output(_sentences(40))
    assert validate_segment_output(long, snapshot).speech == _sentences(40)


# --- 6. retrieval -----------------------------------------------------------------


def test_round_one_query_uses_topic_name_and_stance_not_agent_md() -> None:
    queries = build_turn_subqueries(_v4_context(1, stance="support"))
    texts = [item.text for item in queries]
    assert texts[0] == "Should schools ban phones?"
    assert texts[1] == "Should schools ban phones?\nAda\nsupport the Topic's claim"
    assert all("SECRET-PERSONA-TEXT" not in text for text in texts)
    open_queries = build_turn_subqueries(_v4_context(1))
    assert open_queries[1].text == "Should schools ban phones?\nAda"
    # A Debate frozen before v4 still queries its persona text.
    old = build_turn_subqueries(_v4_context(1, frozen_llm=None))
    assert any("SECRET-PERSONA-TEXT" in item.text for item in old)


# --- 7. snapshot fields -----------------------------------------------------------


def test_v4_snapshot_drops_dead_fields_and_freezes_minutes() -> None:
    snapshot = json.loads(
        canonical_rule_snapshot_json(
            rule_set_id="ordered_multi_expert_mutual_learning_v1",
            round_count=4,
            teaching_protocol="four_round_v1",
            frozen_teaching=freeze_teaching_rules(llm_params=PARAMS, target_minutes=7),
        )
    )
    for name in (
        "min_words",
        "max_words",
        "target_min_words",
        "target_max_words",
        "retrieval_policy_id",
    ):
        assert name not in snapshot, name
    assert "frequency_penalty" not in snapshot["llm_params"]
    assert snapshot["target_minutes"] == 7
    assert frozen_speech_length(json.dumps(snapshot)) == (7, 1.0)
    old = {**snapshot, "contract_version": "ruleset_contract_v3"}
    assert frozen_speech_length(json.dumps(old)) == (None, 1.0)


def test_ruleset_endpoint_contract_and_creation_with_minutes(debate_app) -> None:
    _app, database, client = debate_app
    ids = [
        _insert_published_agent(database, group_id=GROUP_DEMO_ID, name=name)[0]
        for name in ("Minutes One", "Minutes Two")
    ]
    _session, csrf = login(client)
    defaults = client.get(f"/api/v1/courses/{COURSE_ID}/debate-ruleset").json()
    assert defaults["contract"] == execution_contracts()
    body = {
        "output_language": "en",
        "topic": "Water?",
        "participants": [{"agent_id": agent, "stance_mode": "open"} for agent in ids],
        # An editor that echoes the whole read response still creates the Debate.
        "teaching_prompts": defaults,
        "llm_params": PARAMS,
        "target_minutes": 4,
    }
    rejected = client.post(
        f"/api/v1/courses/{COURSE_ID}/debates",
        headers=headers(csrf, **{"Idempotency-Key": "prompt-v4-create-bad-01"}),
        json={**body, "target_minutes": 11},
    )
    assert rejected.status_code == 400
    assert rejected.json()["code"] == "malformed_request"
    created = client.post(
        f"/api/v1/courses/{COURSE_ID}/debates",
        headers=headers(csrf, **{"Idempotency-Key": "prompt-v4-create-ok-001"}),
        json=body,
    )
    assert created.status_code == 201, created.text
    debate_id = created.json()["id"]
    with database.session() as db:
        frozen = db.get(Debate, debate_id).rule_snapshot_json
    stored = json.loads(frozen)
    assert stored["contract_version"] == CONTRACT_VERSION
    assert stored["target_minutes"] == 4
    assert "min_words" not in stored and "frequency_penalty" not in stored["llm_params"]
    # Resending the same form values (with the unstored parameter) is not a change.
    updated = client.patch(
        f"/api/v1/debates/{debate_id}",
        headers=headers(csrf),
        json={**body, "background": "New context", "expected_revision": 0},
    )
    assert updated.status_code == 200, updated.text
    with database.session() as db:
        assert db.get(Debate, debate_id).rule_snapshot_json == frozen
    changed = client.patch(
        f"/api/v1/debates/{debate_id}",
        headers=headers(csrf),
        json={**body, "target_minutes": 6, "expected_revision": 1},
    )
    assert changed.status_code == 409


def test_round_two_question_missing_from_the_speech_is_added_as_its_last_sentence() -> None:
    snapshot = _snapshot(_v4_context(2, speaker=1, speeches={0: "Ada opened with one claim."}))
    question = "Why would that hold for a case nobody rehearsed?"
    silent = validate_segment_output(_output(_sentences(2), question=question), snapshot)
    assert silent.speech.endswith(question)
    assert silent.lineage[-1].end_offset == len(silent.speech)
    spoken = _output(f"{_sentences(2)} {question}", question=question)
    assert validate_segment_output(spoken, snapshot).speech.count(question) == 1


def test_a_reworded_repeat_is_caught_and_an_older_contract_keeps_its_stated_rule() -> None:
    own = (
        "它没朋友、不会痛、不改过，只算闻见之知，非良知。我讲知行合一：真知必能行，做不到就是未知。"
    )
    reworded = (
        "孔子说它没修德行，我补一句：知行合一，做不到就是未知。"
        "它无朋友、不会痛、不改过，只算闻见之知，非良知。"
    )
    ctx = _v4_context(2, speaker=0, language="zh", speeches={0: own})
    snapshot = _snapshot(ctx)
    with pytest.raises(SegmentProtocolError) as caught:
        validate_segment_output(_output(reworded), snapshot)
    assert caught.value.code == "segment_self_repetition"
    # A Debate frozen while the contract said 35% over 8-grams is held to that.
    stated = replace(
        snapshot, frozen_system_prompt=(snapshot.frozen_system_prompt or "") + " 重合超过 35% 时"
    )
    assert self_repetition_ratio(reworded, [own], "zh", legacy=True) <= 0.35
    assert validate_segment_output(_output(reworded), stated).speech
