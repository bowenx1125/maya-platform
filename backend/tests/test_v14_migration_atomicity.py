"""A failed revision write must not leave a partially applied v1.4 schema."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import event
from sqlalchemy.engine import Engine

from tests.test_mayaform_team_conversations import _config, _fingerprint, _seed_0040

_REVISIONS = (
    ("0044_team_provider_stage", "0045_assessment_attempts"),
    ("0045_assessment_attempts", "0046_chat_withdrawal"),
    ("0046_chat_withdrawal", "0047_brainform_markdown"),
    ("0047_brainform_markdown", "0048_runtime_tool_receipts"),
    ("0048_runtime_tool_receipts", "0049_runtime_model_call_stages"),
    ("0049_runtime_model_call_stages", "0050_chat_provider_standing_grants"),
    ("0050_chat_provider_standing_grants", "0051_chat_memory_entry_actions"),
    ("0051_chat_memory_entry_actions", "0052_teacher_courseware"),
    ("0052_teacher_courseware", "0053_user_profile"),
    ("0053_user_profile", "0054_assessment_attempt_question_selection"),
    ("0054_assessment_attempt_question_selection", "0055_assessment_attempt_submission"),
)


@pytest.mark.parametrize(("previous", "current"), _REVISIONS)
@pytest.mark.parametrize("direction", ("upgrade", "downgrade"))
def test_v14_revision_failure_rolls_back_and_retry_preserves_history(
    tmp_path: Path, previous: str, current: str, direction: str
) -> None:
    path = tmp_path / "atomic.sqlite3"
    _seed_0040(path)
    command.upgrade(_config(path), previous if direction == "upgrade" else current)
    payload = '{"answer":"Retained original answer"}'
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute(
            "INSERT INTO learning_records "
            "(id,actor_user_id,course_id,conversation_id,origin,chat_visibility,"
            "record_kind,client_event_id,payload_json,payload_hash,created_at) "
            "SELECT ?,user_id,course_id,id,'single_agent','private','answer',?,?,?,created_at "
            "FROM agent_conversations LIMIT 1",
            (str(uuid4()), str(uuid4()), payload, hashlib.sha256(payload.encode()).hexdigest()),
        )
    before = _fingerprint(path)
    with sqlite3.connect(path) as db:
        history = db.execute(
            "SELECT id,conversation_id,position,user_text,assistant_text,state "
            "FROM agent_conversation_turns ORDER BY id"
        ).fetchall()
    assert len(history) == 3
    fired = False

    def fail_revision(
        _connection: Any,
        _cursor: Any,
        statement: str,
        _parameters: Any,
        _context: Any,
        _executemany: bool,
    ) -> None:
        nonlocal fired
        if statement.lstrip().upper().startswith("UPDATE ALEMBIC_VERSION"):
            fired = True
            raise RuntimeError("synthetic revision write failure")

    operation = command.upgrade if direction == "upgrade" else command.downgrade
    destination = current if direction == "upgrade" else previous
    event.listen(Engine, "before_cursor_execute", fail_revision)
    try:
        with pytest.raises(RuntimeError, match="synthetic revision write failure"):
            operation(_config(path), destination)
    finally:
        event.remove(Engine, "before_cursor_execute", fail_revision)
    assert fired
    assert _fingerprint(path) == before
    operation(_config(path), destination)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT version_num FROM alembic_version").fetchone() == (destination,)
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.execute("SELECT payload_json FROM learning_records").fetchall() == [(payload,)]
        assert (
            db.execute(
                "SELECT id,conversation_id,position,user_text,assistant_text,state "
                "FROM agent_conversation_turns ORDER BY id"
            ).fetchall()
            == history
        )
