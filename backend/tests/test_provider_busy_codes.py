"""A busy provider is named, never retried (2026-11-03).

Rush hour on the shared model key answered 429 or 503, and the chat only
said "The Provider rejected the request." The person now reads that the AI
service is busy and sends again; the server still makes exactly one call.
"""

from __future__ import annotations

from typing import Any

import pytest
from app.core.db import Database
from app.modules.demo_baseline.service import BASELINE_VERSION_ID
from app.providers.llm_transport import rejected_status_code
from fastapi.testclient import TestClient
from httpx import Response

from tests.conftest import login
from tests.test_agent_chat_attachments_reports import _real_provider, _send
from tests.test_mayaform_team_conversations import _headers


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (429, "provider_rate_limited"),
        (502, "provider_busy"),
        (503, "provider_busy"),
        (504, "provider_busy"),
        (529, "provider_busy"),
        (401, "provider_auth_failed"),
        (403, "provider_auth_failed"),
        (400, "fallback"),
        (500, "fallback"),
        (None, "fallback"),
    ],
)
def test_rejected_status_names_busy_and_limited(status: object, code: str) -> None:
    assert rejected_status_code(status, "fallback") == code


@pytest.mark.parametrize(
    ("status", "code"), [(429, "provider_rate_limited"), (503, "provider_busy")]
)
def test_agent_chat_says_the_provider_is_busy_and_calls_once(
    client: TestClient,
    database: Database,
    app_bundle: Any,
    monkeypatch: Any,
    status: int,
    code: str,
) -> None:
    client.headers["Origin"] = "http://testserver"
    transport = _real_provider(
        app_bundle, monkeypatch, [Response(status, json={"error": {"message": "busy"}})]
    )
    _, csrf = login(client, "bowen")
    session = client.post(
        "/api/v1/conversations", headers=_headers(csrf), json={"version_id": BASELINE_VERSION_ID}
    ).json()

    response = _send(client, csrf, session["id"], "你好")

    assert transport.call_count == 1
    assert response.status_code == 200, response.text
    turn = response.json()["turns"][-1]
    assert turn["state"] == "failed", turn
    assert turn["safe_error_code"] == code


def test_team_member_says_the_provider_is_busy_and_calls_once(
    client: TestClient, database: Database, app_bundle: Any, monkeypatch: Any
) -> None:
    from app.modules.workspace import team_runtime as runtime
    from app.modules.workspace.models import ConversationTurn, TeamTurnResult
    from sqlalchemy import select

    from tests.test_team_tool_argument_retries import _report_member_turn

    claim, _settings, _conversation_id = _report_member_turn(client, database, app_bundle)
    calls: list[bytes] = []

    class Busy:
        status_code = 503
        content = b'{"error":{"message":"busy"}}'

    class Transport:
        @staticmethod
        def timeout() -> float:
            return 30.0

        def post_bytes(self, _endpoint: str, *, content: bytes, **_kwargs: Any) -> Any:
            calls.append(content)
            return Busy()

    monkeypatch.setattr("app.modules.workspace.chat_team_provider.HttpxLLMTransport", Transport)
    runtime.execute_team_turn(database.session_factory, claim)

    assert len(calls) == 1
    with database.session() as db:
        turn = db.get(ConversationTurn, claim.turn_id)
        assert turn is not None
        [result] = db.scalars(select(TeamTurnResult).where(TeamTurnResult.turn_id == turn.id))
    assert (result.state, result.safe_error_code) == ("failed", "provider_busy")
