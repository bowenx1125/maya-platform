"""Debate Immerse/Live avatar comes from the live Agent, not the create snapshot."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.modules.avatars import DEFAULT_AVATAR_CONFIG, default_config_for
from app.modules.debates.display_avatar import participant_display_avatar
from app.modules.debates.playback._session import PlaybackSessionMixin


def test_participant_display_avatar_follows_live_agent_then_defaults() -> None:
    live = default_config_for("maya-warm-scholar").model_dump(mode="json")
    egg = default_config_for("egg").model_dump(mode="json")
    version = SimpleNamespace(
        id="version-1",
        agent_id="agent-1",
        state="published",
        avatar_config_json=json.dumps(live),
    )
    agent = SimpleNamespace(
        id="agent-1",
        deleted_at=None,
        status="active",
        current_published_version_id="version-1",
    )
    participant = SimpleNamespace(
        agent_id="agent-1",
        avatar_config_json=json.dumps(egg),
    )

    def get(model: type, key: str):  # noqa: ANN001
        name = getattr(model, "__name__", "")
        if name == "Agent" and key == "agent-1":
            return agent
        if name == "AgentVersion" and key == "version-1":
            return version
        return None

    db = MagicMock()
    db.get.side_effect = get

    assert participant_display_avatar(db, participant)["template_id"] == "maya-warm-scholar"

    agent.deleted_at = datetime.now(UTC)
    assert participant_display_avatar(db, participant) == DEFAULT_AVATAR_CONFIG.model_dump(
        mode="json"
    )

    participant.agent_id = None
    assert participant_display_avatar(db, participant) == DEFAULT_AVATAR_CONFIG.model_dump(
        mode="json"
    )

    # Invalid live config also falls back; stored create-time egg is ignored.
    participant.agent_id = "agent-1"
    agent.deleted_at = None
    version.avatar_config_json = '{"template_id": "retired-template"}'
    assert participant_display_avatar(db, participant) == DEFAULT_AVATAR_CONFIG.model_dump(
        mode="json"
    )
    assert json.loads(participant.avatar_config_json)["template_id"] == "egg"


def test_playback_avatar_states_use_live_expression_not_create_snapshot() -> None:
    """WS playback.started expression must follow the live Agent avatar."""

    live = default_config_for("maya-warm-scholar").model_dump(mode="json")
    egg = default_config_for("egg").model_dump(mode="json")
    assert live["default_expression"] != egg["default_expression"]
    version = SimpleNamespace(
        id="version-1",
        agent_id="agent-1",
        state="published",
        avatar_config_json=json.dumps(live),
    )
    agent = SimpleNamespace(
        id="agent-1",
        deleted_at=None,
        status="active",
        current_published_version_id="version-1",
    )

    def get(model: type, key: str):  # noqa: ANN001
        name = getattr(model, "__name__", "")
        if name == "Agent" and key == "agent-1":
            return agent
        if name == "AgentVersion" and key == "version-1":
            return version
        return None

    db = MagicMock()
    db.get.side_effect = get
    speaking = SimpleNamespace(
        id="p-speak",
        agent_id="agent-1",
        slot="A",
        avatar_config_json=json.dumps(egg),
    )
    listening = SimpleNamespace(
        id="p-listen",
        agent_id="agent-1",
        slot="B",
        avatar_config_json=json.dumps(egg),
    )
    turn = SimpleNamespace(participant_id="p-speak")
    harness = PlaybackSessionMixin.__new__(PlaybackSessionMixin)
    states = PlaybackSessionMixin._avatar_states(harness, db, [speaking, listening], turn)
    assert states[0]["expression"] == live["default_expression"]
    assert states[0]["expression_strength"] == live["expression_strength"]
    assert states[1]["expression"] == "attentive"
    assert states[1]["expression_strength"] == live["expression_strength"]
    assert (
        json.loads(speaking.avatar_config_json)["default_expression"] == egg["default_expression"]
    )
