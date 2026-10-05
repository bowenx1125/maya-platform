from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from typing import Any
from uuid import UUID, uuid5

from app.core.errors import not_found
from app.core.models import CourseMember
from app.modules.auth.service import get_auth_context
from app.modules.learning.models import LearningRecord
from app.modules.learning.schemas import AnswerRecordRequest
from app.modules.learning.service import record_learning_event
from app.modules.runtime_tools.models import RuntimeToolReceipt
from app.modules.runtime_tools.registry import (
    ToolCallIdentity,
    ToolSpec,
    execute_tool,
    exposed_tools,
)
from app.modules.workspace.models import (
    Conversation,
    ConversationTurn,
    TeamProviderCall,
    TeamTurnResult,
)
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select

from tests.test_team_provider_stage import _dispatch


class AnswerArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer_text: str


def _authorize(_db: Any, _actor: Any, _row: Any, _payload: Any) -> None:
    pass


def _answer(
    db: Any, actor: Any, row: Any, payload: Any, call_id: str, _identity: ToolCallIdentity
) -> dict[str, Any]:
    return record_learning_event(
        db,
        actor,
        row.id,
        AnswerRecordRequest(
            kind="answer",
            client_event_id=uuid5(UUID(row.id), call_id),
            answer_text=payload.answer_text,
        ),
    ).model_dump(mode="json")


REGISTRY = {
    "record_answer": ToolSpec(
        "record_answer", "Public", "Record own answer", AnswerArguments, _authorize, _answer
    ),
    "teacher_probe": ToolSpec(
        "teacher_probe",
        "Teacher",
        "Teacher authorization probe",
        AnswerArguments,
        _authorize,
        _answer,
    ),
    "student_probe": ToolSpec(
        "student_probe",
        "Student",
        "Student authorization probe",
        AnswerArguments,
        _authorize,
        _answer,
    ),
}


def test_accepted_tool_call_is_transactional_replayable_and_current_role_scoped(
    client: TestClient, app_bundle: Any
) -> None:
    wire = json.dumps(
        {
            "messages": [{"role": "user", "content": "My original answer"}],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "record_answer",
                        "parameters": {
                            "type": "object",
                            "properties": {"arguments": AnswerArguments.model_json_schema()},
                            "required": ["arguments"],
                            "additionalProperties": False,
                        },
                    },
                }
            ],
        }
    )
    database, repository, operation_id = _dispatch(client, app_bundle, wire=wire)
    arguments = {"answer_text": "My original answer"}
    response = json.dumps(
        {
            "tool_calls": [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {
                        "name": "record_answer",
                        "arguments": json.dumps({"arguments": arguments}),
                    },
                }
            ]
        }
    )
    response = json.dumps({"choices": [{"message": json.loads(response)}]})
    repository.stage_team_accepted(operation_id, response_json=response)
    raw_token = client.cookies.get("maya_session")
    with database.session() as db:
        actor = get_auth_context(db, app_bundle[2], raw_token)
        assert actor is not None
        stage = db.scalar(select(TeamProviderCall))
        result = db.get(TeamTurnResult, stage.result_id)
        identity = ToolCallIdentity(
            result.conversation_id, result.turn_id, result.participant_id, stage.id, "call-1"
        )
        assert [
            tool.name for tool in exposed_tools(db, actor, result.conversation_id, REGISTRY)
        ] == ["record_answer", "student_probe"]
        grant = {"edit": True}

        def authorize_edit(
            _db: Any, _actor: Any, _row: Any, _payload: Any, _identity: ToolCallIdentity
        ) -> None:
            if not grant["edit"]:
                raise not_found()

        scoped_registry = {
            **REGISTRY,
            "record_answer": ToolSpec(
                "record_answer",
                "Public",
                "Edit explicitly authorized synthetic practice evidence",
                AnswerArguments,
                _authorize,
                _answer,
                authorize_execution=authorize_edit,
            ),
        }
        first = execute_tool(db, actor, identity, "record_answer", arguments, scoped_registry)
        assert first["ok"]
        assert db.scalar(select(func.count()).select_from(LearningRecord)) == 1
        assert db.scalar(select(func.count()).select_from(RuntimeToolReceipt)) == 1
        conversation = db.get(Conversation, result.conversation_id)
        turn = db.get(ConversationTurn, result.turn_id)
        assert conversation is not None and turn is not None
        bound_identity = replace(
            identity, conversation_revision=conversation.revision, claim_token=turn.claim_token
        )
        conversation.revision += 1
        db.flush()
        assert (
            execute_tool(db, actor, bound_identity, "record_answer", arguments, scoped_registry)[
                "code"
            ]
            == "tool_run_superseded"
        )
        assert db.scalar(select(func.count()).select_from(LearningRecord)) == 1
        # Revocation applies even when the same accepted invocation has a receipt.
        grant["edit"] = False
        assert not execute_tool(db, actor, identity, "record_answer", arguments, scoped_registry)[
            "ok"
        ]
        grant["edit"] = True
        assert (
            execute_tool(db, actor, identity, "record_answer", arguments, scoped_registry) == first
        )
        assert db.scalar(select(func.count()).select_from(LearningRecord)) == 1
        accepted_body = stage.accepted_response_json
        accepted_hash = stage.accepted_response_hash
        stage.accepted_response_json = "{malformed"
        stage.accepted_response_hash = hashlib.sha256(b"{malformed").hexdigest()
        db.flush()
        assert (
            execute_tool(db, actor, identity, "record_answer", arguments, scoped_registry)["code"]
            == "tool_call_unverified"
        )
        stage.accepted_response_json = accepted_body
        stage.accepted_response_hash = accepted_hash
        db.flush()
        assert (
            execute_tool(db, actor, identity, "record_answer", arguments, scoped_registry) == first
        )
        assert (
            execute_tool(db, actor, identity, "teacher_probe", arguments, REGISTRY)["code"]
            == "tool_not_authorized"
        )
        assert (
            execute_tool(
                db, actor, identity, "record_answer", {"answer_text": "Changed"}, REGISTRY
            )["code"]
            == "tool_call_unverified"
        )
        member = db.get(CourseMember, (first["result"]["provenance"]["course_id"], actor.user.id))
        assert member is not None
        member.role = "teacher"
        db.flush()
        assert {
            tool.authorization_class
            for tool in exposed_tools(db, actor, result.conversation_id, REGISTRY)
        } == {"Public", "Teacher"}
        assert (
            execute_tool(db, actor, identity, "student_probe", arguments, REGISTRY)["code"]
            == "tool_not_authorized"
        )
