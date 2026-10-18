"""A single Agent chat call waits for its LLM slot before it is marked "sending".

#141: Team was fixed in #133; single chat still wrote "sending" first, so a
process that died while queued for a slot left a row that recovery had to
call acceptance_unknown, and the row blocked pause while it waited.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from typing import Any
from unittest.mock import Mock
from uuid import uuid4

from app.core.errors import PlatformError
from app.core.models import ProviderOperation
from app.modules.demo_baseline.service import BASELINE_VERSION_ID, ensure_demo_baseline
from app.providers.control_repository import ProviderRepository
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import select

from tests.conftest import login, post_message
from tests.test_wave4_llm_adapter import _adapter
from tests.test_wave4_llm_ledger import _valid_policy


def _ready(app_bundle: Any, client: TestClient, monkeypatch: Any) -> tuple[Any, Mock]:
    app, database, settings = app_bundle
    client.headers["Origin"] = "http://testserver"
    with database.session() as db:
        ensure_demo_baseline(db, settings.resolved_data_root)
    adapter = _adapter(None)
    policy = replace(_valid_policy(), endpoint=adapter.config.resolved_endpoint)
    ProviderRepository(database).save_policy_snapshot(policy)
    app.state.settings = settings.model_copy(
        update={
            "llm_provider": "dashscope",
            "llm_provider_policy_hash": policy.policy_hash,
            "demo_auto_confirm_provider": True,
        }
    )
    monkeypatch.setattr("app.modules.workspace.chat_provider.llm_provider", lambda _: adapter)
    monkeypatch.setattr("app.modules.workspace.chat.retrieve_sources", lambda *a, **kw: [])
    transport = Mock(
        return_value=Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "Single reply"},
                        "finish_reason": "stop",
                    }
                ]
            },
        )
    )
    return database, transport


def _states(database: Any) -> list[str]:
    with database.session() as db:
        return [
            op.state
            for op in db.scalars(
                select(ProviderOperation).where(
                    ProviderOperation.provider_operation == "llm_agent_chat"
                )
            )
        ]


def _send(client: TestClient) -> Any:
    _, csrf = login(client, "bowen")
    created = client.post(
        "/api/v1/conversations",
        headers={"X-CSRF-Token": csrf},
        json={"version_id": BASELINE_VERSION_ID},
    ).json()
    return post_message(
        client,
        f"/api/v1/conversations/{created['id']}/messages",
        headers={"X-CSRF-Token": csrf},
        json={"request_id": str(uuid4()), "expected_revision": 0, "message": "Hello."},
    )


def test_single_chat_admission_is_granted_before_sending(
    app_bundle: Any, client: TestClient, monkeypatch: Any
) -> None:
    database, transport = _ready(app_bundle, client, monkeypatch)
    seen: list[list[str]] = []
    held = {"now": False}

    @contextmanager
    def slot(*_args: Any, **_kwargs: Any) -> Iterator[None]:
        seen.append(_states(database))
        held["now"] = True
        try:
            yield
        finally:
            held["now"] = False

    def post_bytes(*args: Any, **kwargs: Any) -> Any:
        assert held["now"], "the model request must run inside the LLM slot"
        assert _states(database) == ["sending"]
        return transport(*args, **kwargs)

    monkeypatch.setattr("app.modules.workspace.chat_provider.llm_admission_slot", slot)
    monkeypatch.setattr(
        "app.modules.workspace.chat_provider.HttpxLLMTransport.post_bytes", post_bytes
    )

    response = _send(client)

    assert response.status_code == 200, response.text
    assert seen == [["reserved"]]
    assert transport.call_count == 1
    assert _states(database) == ["succeeded"]


def test_single_chat_admission_refusal_is_not_sent_and_never_sending(
    app_bundle: Any, client: TestClient, monkeypatch: Any
) -> None:
    database, transport = _ready(app_bundle, client, monkeypatch)
    transitions: list[tuple[str, str]] = []
    original_transition = ProviderRepository.transition

    def transition(self: Any, operation_id: str, **kwargs: Any) -> Any:
        transitions.append((str(kwargs.get("expected")), str(kwargs.get("state"))))
        return original_transition(self, operation_id, **kwargs)

    @contextmanager
    def busy(*_args: Any, **_kwargs: Any) -> Iterator[None]:
        raise PlatformError("adaptive_admission_busy", "busy", 503, {"retryable": True})
        yield  # pragma: no cover

    monkeypatch.setattr(ProviderRepository, "transition", transition)
    monkeypatch.setattr("app.modules.workspace.chat_provider.llm_admission_slot", busy)
    monkeypatch.setattr(
        "app.modules.workspace.chat_provider.HttpxLLMTransport.post_bytes", transport
    )

    _send(client)

    assert transport.call_count == 0
    assert ("reserved", "sending") not in transitions
    assert _states(database) == ["not_sent"]
