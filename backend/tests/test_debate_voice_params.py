"""Voice parameters (rate / instruction / seed) for cloned voices (2026-10-25).

DEBATE_TTS_* hold the defaults, the parameter card overrides them, the values
freeze into the Debate snapshot, and every speech of that Debate (preview,
live, regenerated) sends them. The browser playback rate is gone: every
Debate plays at 1.0.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from app.core.config import Settings
from app.modules.debates.generation_params import (
    defaults_payload,
    frozen_voice_params,
    voice_request_fields,
)
from app.modules.debates.models import Debate
from app.modules.debates.playback.audio import AudioStore
from app.modules.debates.playback.service import PlaybackService
from app.providers.tts import MockTTSProvider
from pydantic import ValidationError

from tests.conftest import login
from tests.test_wave2_setup import (
    COURSE_ID,
    GROUP_DEMO_ID,
    _insert_published_agent,
    headers,
)
from tests.test_wave2_setup import (
    debate_app as debate_app,
)


def _settings(**env: Any) -> Settings:
    return Settings.model_validate({"DATABASE_URL": "postgresql://x@localhost/x", **env})


def test_env_defaults_and_empty_values() -> None:
    settings = _settings()
    assert settings.debate_tts_rate == 1.25
    assert settings.debate_tts_instruction is None
    assert settings.debate_tts_seed is None
    # Compose forwards ${VAR:-} as an empty string: that means "not set".
    blank = _settings(DEBATE_TTS_RATE="", DEBATE_TTS_INSTRUCTION=" ", DEBATE_TTS_SEED="")
    assert (blank.debate_tts_rate, blank.debate_tts_instruction, blank.debate_tts_seed) == (
        None,
        None,
        None,
    )
    with pytest.raises(ValidationError):
        _settings(DEBATE_TTS_RATE="2.5")
    with pytest.raises(ValidationError):
        _settings(DEBATE_TTS_SEED="70000")
    assert not hasattr(settings, "debate_playback_rate")


def test_defaults_payload_lists_voice_params_and_no_playback_rate() -> None:
    payload = defaults_payload(_settings(DEBATE_TTS_INSTRUCTION="语气坚定", DEBATE_TTS_SEED="9"))
    assert "playback_rate" not in payload
    voice = {item["name"]: item for item in payload["voice_params"]}
    assert voice["rate"]["default"] == 1.25
    assert (voice["rate"]["minimum"], voice["rate"]["maximum"]) == (0.5, 2.0)
    assert voice["instruction"] == {
        "name": "instruction",
        "kind": "text",
        "default": "语气坚定",
        "minimum": None,
        "maximum": None,
        "step": None,
        "max_length": 500,
    }
    assert voice["seed"]["default"] == 9
    assert (voice["seed"]["minimum"], voice["seed"]["maximum"]) == (0, 65535)


def test_request_fields_leave_out_empty_values() -> None:
    assert voice_request_fields({"rate": 1.2, "instruction": "  ", "seed": None}) == {"rate": 1.2}
    assert voice_request_fields(None) == {}


def test_a_debate_without_frozen_voice_values_uses_the_defaults() -> None:
    settings = _settings(DEBATE_TTS_RATE="1.1")
    assert frozen_voice_params(None, settings) == {"rate": 1.1, "instruction": None, "seed": None}
    frozen = {"rate": 0.9, "instruction": "平静", "seed": 4}
    assert frozen_voice_params({"voice_params": frozen}, settings) == frozen


def test_create_freezes_voice_values_and_patch_cannot_change_them(debate_app: Any) -> None:
    _app, database, client = debate_app
    ids = [
        _insert_published_agent(database, group_id=GROUP_DEMO_ID, name=name)[0]
        for name in ("Voice One", "Voice Two")
    ]
    _session, csrf = login(client)
    defaults = client.get(f"/api/v1/courses/{COURSE_ID}/debate-llm-defaults")
    assert defaults.status_code == 200, defaults.text
    assert "playback_rate" not in defaults.json()
    assert [item["name"] for item in defaults.json()["voice_params"]] == [
        "rate",
        "instruction",
        "seed",
    ]
    body = {
        "topic": "Water?",
        "participants": [{"agent_id": agent, "stance_mode": "open"} for agent in ids],
        "voice_params": {"rate": 1.1, "instruction": "语气坚定，像辩论赛选手", "seed": 12},
    }
    created = client.post(
        f"/api/v1/courses/{COURSE_ID}/debates",
        headers=headers(csrf, **{"Idempotency-Key": "voice-params-create-0001"}),
        json=body,
    )
    assert created.status_code == 201, created.text
    assert "playback_rate" not in created.json()["playback"]
    debate_id = created.json()["id"]
    with database.session() as db:
        snapshot = json.loads(db.get(Debate, debate_id).rule_snapshot_json)
    assert snapshot["voice_params"] == body["voice_params"]

    plain = client.post(
        f"/api/v1/courses/{COURSE_ID}/debates",
        headers=headers(csrf, **{"Idempotency-Key": "voice-params-create-0002"}),
        json={key: value for key, value in body.items() if key != "voice_params"},
    )
    assert plain.status_code == 201, plain.text
    with database.session() as db:
        plain_snapshot = json.loads(db.get(Debate, plain.json()["id"]).rule_snapshot_json)
    assert plain_snapshot["voice_params"] == {"rate": 1.25, "instruction": None, "seed": None}

    changed = client.patch(
        f"/api/v1/debates/{debate_id}",
        headers=headers(csrf),
        json={**body, "expected_revision": 0, "voice_params": {"rate": 1.5}},
    )
    assert changed.status_code == 409


def test_playback_sends_the_frozen_voice_values_to_tts(tmp_path: Path) -> None:
    frozen = {"rate": 1.3, "instruction": "平静", "seed": 5}
    debate = SimpleNamespace(rule_snapshot_json=json.dumps({"voice_params": frozen}))
    service = PlaybackService.__new__(PlaybackService)
    service.settings = _settings()
    params = service._voice_params(debate)
    assert params == frozen

    provider = MockTTSProvider()
    store = AudioStore(tmp_path, tts_provider=provider)
    course_id, debate_id, turn_id = (str(uuid4()) for _ in range(3))
    store.synthesize_and_store(
        course_id=course_id,
        debate_id=debate_id,
        turn_id=turn_id,
        speech="Speech.",
        voice_token="mock",
        voice_params=params,
    )
    assert provider.last_voice_params == frozen
    staged = store.stage_synthesis(
        course_id=course_id,
        debate_id=debate_id,
        turn_id=str(uuid4()),
        speech="Preview speech.",
        voice_token="mock",
        voice_params={"rate": 1.0},
    )
    assert staged.size_bytes > 0
    assert provider.last_voice_params == {"rate": 1.0}
