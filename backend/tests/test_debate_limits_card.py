"""MAYA-DEBATE-LIMITS-CARD-20261115-01: v5 caps, repair v2, and card corrections."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from fractions import Fraction
from pathlib import Path

import pytest
from app.modules.debates.cards import CARD_MAX_LINE_CHARS, correct_card_payload, validate_card
from app.modules.debates.generation.four_round import (
    OVER_LENGTH_RATIO,
    default_round_unit_caps,
    estimated_duration_minutes,
    over_length_limit,
    speech_language_mismatch,
)
from app.modules.debates.generation_params import (
    CONTRACT_VERSION,
    RULESET_CONTRACT_V5,
    uses_code_contract,
    uses_v5_speech_limits,
)
from app.modules.debates.teaching_rules import (
    freeze_teaching_rules,
    frozen_round_unit_caps,
    frozen_speech_length,
)
from app.providers.llm_privacy import (
    LLM_REPAIR_FEEDBACK_POLICY_HASH,
    LLM_REPAIR_FEEDBACK_V2_HASH,
)
from app.providers.llm_segments import (
    SEGMENT_NO_HISTORY_COPY_RULE,
    SEGMENT_NO_HISTORY_COPY_RULE_ZH,
)

from tests.conftest import login
from tests.test_debate_prompt_v4 import PARAMS, _snapshot, _v4_context
from tests.test_four_round_provider import adapter
from tests.test_wave2_setup import COURSE_ID, headers
from tests.test_wave2_setup import debate_app as debate_app

REPO = Path(__file__).resolve().parents[2]


def test_v4_over_length_ratio_is_unchanged() -> None:
    assert OVER_LENGTH_RATIO == Fraction(5, 4)
    assert over_length_limit(100) == 125
    assert over_length_limit(100, Fraction(3, 2)) == 150


def test_speech_language_mismatch_is_conservative() -> None:
    assert speech_language_mismatch("Hello world today", "zh") is True
    assert speech_language_mismatch("这是一句中文", "en") is True
    assert speech_language_mismatch("这是一句中文", "zh") is False
    assert speech_language_mismatch("Hello world today", "en") is False
    # Mixed or empty text must not fire the heuristic.
    assert speech_language_mismatch("Hello 中文 world", "zh") is False
    assert speech_language_mismatch("", "en") is False


def test_freeze_without_caps_stays_v4_and_caps_freeze_v5() -> None:
    v4 = freeze_teaching_rules(target_minutes=5)
    assert v4["contract_version"] == CONTRACT_VERSION
    assert v4["target_minutes"] == 5
    assert "round_unit_caps" not in v4
    assert frozen_speech_length(__import__("json").dumps(v4)) == (5, 1.0)
    assert uses_v5_speech_limits(v4) is False
    assert uses_code_contract(v4) is True

    caps = [200, 160, 160, 240]
    v5 = freeze_teaching_rules(round_unit_caps=caps)
    assert v5["contract_version"] == RULESET_CONTRACT_V5
    assert v5["round_unit_caps"] == list(caps)
    assert v5["over_length_ratio"] == "3/2"
    assert v5["repair_feedback_version"] == "repair_feedback_v2"
    assert "target_minutes" not in v5
    assert frozen_speech_length(__import__("json").dumps(v5)) == (None, 1.0)
    assert frozen_round_unit_caps(__import__("json").dumps(v5)) == tuple(caps)
    assert uses_v5_speech_limits(v5) is True


def test_v5_with_history_does_not_append_the_old_no_copy_rule() -> None:
    caps = (200, 160, 160, 240)
    frozen = {
        "contract_version": RULESET_CONTRACT_V5,
        "params": PARAMS,
        "round_unit_caps": list(caps),
        "over_length_ratio": "3/2",
        "repair_feedback_version": "repair_feedback_v2",
    }
    snapshot = _snapshot(replace(_v4_context(3, frozen_llm=frozen), round_unit_caps=caps))
    assert snapshot.history
    content = adapter().build_request(snapshot).system_message.content
    assert SEGMENT_NO_HISTORY_COPY_RULE not in content
    zh = _snapshot(replace(_v4_context(3, "zh", frozen_llm=frozen), round_unit_caps=caps))
    assert SEGMENT_NO_HISTORY_COPY_RULE_ZH not in adapter().build_request(zh).system_message.content


def test_repair_feedback_hashes_are_pinned() -> None:
    v1 = hashlib.sha256(
        (REPO / "contracts/llm-repair-feedback.v1.schema.json").read_bytes()
    ).hexdigest()
    v2 = hashlib.sha256(
        (REPO / "contracts/llm-repair-feedback.v2.schema.json").read_bytes()
    ).hexdigest()
    assert v1 == "d5b81d460ecd713f4b3d52b5732efc935b63455c2a29b5a5ab2471b17d00050b"
    assert v1 == LLM_REPAIR_FEEDBACK_POLICY_HASH
    assert v2 == "d911e9af5381af8cea22f171fdd11f1a07f18ccdf2f703bdfbee1e4d096292f7"
    assert v2 == LLM_REPAIR_FEEDBACK_V2_HASH


def test_openapi_sha256_matches_checked_in_pin() -> None:
    digest = hashlib.sha256((REPO / "contracts/openapi-v0.1.yaml").read_bytes()).hexdigest()
    pin = (REPO / "contracts/openapi-v0.1.sha256").read_text(encoding="utf-8").split()[0]
    assert digest == pin


def test_correct_card_payload_fixes_metadata_only() -> None:
    payload = {
        "identity": "A careful student who keeps a long identity sentence as written.",
        "position": "Phones should stay in bags.",
        "reasoning": ["", "Evidence first.", "   "],
        "speaking_style": "Calm and direct.",
        "voice_style": "  ",
        "dropped": [
            {"excerpt": "", "reason": ""},
            {"excerpt": "x" * (CARD_MAX_LINE_CHARS + 8), "reason": "length_limit"},
            *[{"excerpt": f"keep {index}", "reason": "length_limit"} for index in range(20)],
        ],
    }
    fixed = correct_card_payload(payload)
    assert isinstance(fixed, dict)
    assert fixed["identity"] == payload["identity"]
    assert fixed["position"] == payload["position"]
    assert fixed["speaking_style"] == payload["speaking_style"]
    assert fixed["voice_style"] is None
    assert fixed["reasoning"] == ["Evidence first."]
    dropped = fixed["dropped"]
    assert isinstance(dropped, list)
    assert dropped[0]["excerpt"] == "x" * CARD_MAX_LINE_CHARS
    assert len(dropped) == 12
    validated = validate_card(fixed, "en")
    assert validated["voice_style"] is None
    assert validated["reasoning"] == ["Evidence first."]


def test_default_caps_and_estimated_duration_endpoint(debate_app) -> None:
    _app, _database, client = debate_app
    _session, csrf = login(client)
    expected = default_round_unit_caps("zh", participants=2, voice_rate=1.0)
    minutes = estimated_duration_minutes(expected, language="zh", participants=2, voice_rate=1.0)
    response = client.get(
        f"/api/v1/courses/{COURSE_ID}/debate-round-unit-cap-defaults",
        params={"language": "zh", "participants": 2},
        headers=headers(csrf),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["language"] == "zh"
    assert body["participants"] == 2
    assert body["rate"] == 1.0
    assert body["round_unit_caps"] == expected
    assert body["estimated_duration_minutes"] == minutes
    missing = client.get(
        f"/api/v1/courses/{COURSE_ID}/debate-round-unit-cap-defaults",
        headers=headers(csrf),
    )
    assert missing.status_code == 400
    assert missing.json()["code"] == "malformed_request"


@pytest.mark.parametrize("bad", [True, False, "100", 100.0, 100.5, 39, 2001])
def test_caps_reject_coercion_and_out_of_range_values(bad: object) -> None:
    from uuid import uuid4

    from app.modules.debates.schemas import DebateDraftRequest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        DebateDraftRequest.model_validate(
            {
                "topic": "Classroom phones?",
                "output_language": "zh",
                "participants": [
                    {"agent_id": str(uuid4()), "stance_mode": "open"} for _ in range(2)
                ],
                "round_unit_caps": [bad, 100, 100, 100],
            }
        )


@pytest.mark.parametrize("language,minimum", [("zh", 40), ("en", 25)])
def test_caps_accept_language_bounds(language: str, minimum: int) -> None:
    from uuid import uuid4

    from app.modules.debates.schemas import DebateDraftRequest

    request = DebateDraftRequest.model_validate(
        {
            "topic": "Classroom phones?",
            "output_language": language,
            "participants": [{"agent_id": str(uuid4()), "stance_mode": "open"} for _ in range(2)],
            "round_unit_caps": [minimum, 2000, minimum, 2000],
        }
    )
    assert request.round_unit_caps == [minimum, 2000, minimum, 2000]


@pytest.mark.parametrize("rate", ["nan", "inf", "1e309", "0", "-1", "0.49", "2.01"])
def test_defaults_reject_nonfinite_or_unsupported_rate(debate_app, rate: str) -> None:
    _app, _database, client = debate_app
    login(client)
    response = client.get(
        f"/api/v1/courses/{COURSE_ID}/debate-round-unit-cap-defaults",
        params={"language": "en", "participants": 2, "rate": rate},
    )
    assert response.status_code in (400, 422), response.text


def test_defaults_authentication_and_course_authorization(debate_app) -> None:
    from uuid import uuid4

    _app, _database, client = debate_app
    url = f"/api/v1/courses/{COURSE_ID}/debate-round-unit-cap-defaults"
    params = {"language": "en", "participants": 2}
    assert client.get(url, params=params).status_code == 401
    login(client, "bowen")
    assert client.get(url, params=params).status_code == 403
    login(client)
    assert (
        client.get(
            f"/api/v1/courses/{uuid4()}/debate-round-unit-cap-defaults", params=params
        ).status_code
        == 404
    )


def test_two_attempt_manifest_requires_known_repair_policy() -> None:
    from app.providers.control import ExportFieldV1, ExportManifestError, ExportManifestV1

    with pytest.raises(ExportManifestError) as rejected:
        ExportManifestV1(
            scope_id="debate",
            provider_operation="llm_debate_turn",
            model_key="test-model",
            policy_hash="a" * 64,
            build_manifest_hash="b" * 64,
            persona_spec_hash="c" * 64,
            fields=(ExportFieldV1("server_authored_structure_repair_feedback", "d" * 64),),
            max_attempts=2,
        )
    assert rejected.value.code == "repair_policy_invalid"


@pytest.mark.parametrize(
    "text,code",
    [
        (" ".join(["one"] * 101), "segment_over_length"),
        ("Brief point.", "segment_too_short"),
        ("中文发言" * 20, "segment_language_mismatch"),
    ],
)
def test_v5_soft_failures_request_one_rewrite_then_keep_complete_speech(
    text: str, code: str
) -> None:
    from app.modules.debates.generation.segments import (
        SegmentProtocolError,
        validate_segment_output,
    )

    from tests.test_debate_prompt_v4 import _output

    frozen = {"contract_version": RULESET_CONTRACT_V5, "params": PARAMS}
    snapshot = _snapshot(replace(_v4_context(1, frozen_llm=frozen), round_unit_caps=(100,) * 4))
    with pytest.raises(SegmentProtocolError) as rejected:
        validate_segment_output(_output(text), snapshot)
    assert rejected.value.code == code
    assert rejected.value.unit_cap == 100
    assert rejected.value.language == "en"
    accepted = validate_segment_output(_output(text), snapshot, repairable=False)
    assert accepted.speech == text.strip()
