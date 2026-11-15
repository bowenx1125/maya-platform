"""MAYA-DEBATE-LIMITS-CARD-20261115-01: v5 caps, repair v2, and card corrections."""

from __future__ import annotations

import hashlib
from fractions import Fraction
from pathlib import Path

from app.modules.debates.cards import correct_card_payload, validate_card, CARD_MAX_LINE_CHARS
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
from tests.conftest import login
from tests.test_wave2_setup import COURSE_ID, debate_app as debate_app, headers


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


def test_repair_feedback_hashes_are_pinned() -> None:
    v1 = hashlib.sha256(
        (REPO / "contracts/llm-repair-feedback.v1.schema.json").read_bytes()
    ).hexdigest()
    v2 = hashlib.sha256(
        (REPO / "contracts/llm-repair-feedback.v2.schema.json").read_bytes()
    ).hexdigest()
    assert v1 == "d5b81d460ecd713f4b3d52b5732efc935b63455c2a29b5a5ab2471b17d00050b"
    assert v1 == LLM_REPAIR_FEEDBACK_POLICY_HASH
    assert v2 == "22ccaa931e2b17aa8b4ec6dd485ccbc864c0af37c47b32dcd070fe8cb3102ac1"
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
    minutes = estimated_duration_minutes(
        expected, language="zh", participants=2, voice_rate=1.0
    )
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
