from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, cast

from app.core.models import VoiceProfile
from app.modules.debates.owned_copies import voice_snapshot
from app.modules.debates.playback.generation_adapter import SqlTurnPreparer


def _row(**extra: object) -> Any:
    base: dict[str, object] = {
        "id": "p1",
        "agent_id": None,
        "agent_version_id": None,
        "agent_name": "Confucius",
        "slot": "A",
        "order_index": 0,
        "knowledge_snapshot_id": "s1",
        "stance_mode": "open",
        "initial_stance": None,
        "current_stance": None,
        "initial_position_summary": "",
        "current_position_summary": "",
        "teacher_note": "",
        "agent_md_snapshot": "# Confucius\nBe kind.",
    }
    base.update(extra)
    return SimpleNamespace(**base)


class _NoDb:
    def get(self, *_args: object) -> None:
        raise AssertionError("a Debate with its own copy must not read live versions")


def test_participant_reads_its_own_agent_md_after_version_deleted() -> None:
    context = SqlTurnPreparer._participant(cast(Any, _NoDb()), _row())
    assert context.agent_md == "# Confucius\nBe kind."
    assert context.agent_id is None
    assert context.agent_name == "Confucius"


def test_voice_snapshot_copies_config_and_ciphertext() -> None:
    profile = VoiceProfile(
        id="v1",
        scope="personal",
        display_name="Kong",
        provider_key="dashscope",
        target_model_key="cosyvoice-v2",
        external_id_encrypted=b"cipher",
    )
    payload, cipher = voice_snapshot(profile)
    assert payload is not None and cipher == b"cipher"
    assert json.loads(payload) == {
        "display_name": "Kong",
        "provider_key": "dashscope",
        "scope": "personal",
        "target_model_key": "cosyvoice-v2",
        "voice_profile_id": "v1",
    }
    assert voice_snapshot(None) == (None, None)
