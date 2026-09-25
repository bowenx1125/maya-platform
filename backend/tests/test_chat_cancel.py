"""A disconnected chat stream must not leave a pending turn or an accepted call."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import threading
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.core.config import Settings
from app.core.db import Database
from app.core.models import ProviderOperation, ProviderScopeBudget
from app.modules.demo_baseline.service import BASELINE_VERSION_ID, ensure_demo_baseline
from app.modules.workspace.chat import claim_chat_send
from app.modules.workspace.chat_stream import stream_events
from app.modules.workspace.models import Conversation, ConversationTurn
from app.providers.control import (
    LLM_DEBATE_TURN_BUCKET,
    ProviderReservationRequestV1,
    ProviderScopeBudgetV1,
)
from app.providers.control_repository import ProviderRepository
from app.providers.tts import TTSResult
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.conftest import login
from tests.test_wave1b_voices import _wav


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@pytest.fixture
def voice_app(
    app_factory: Callable[..., tuple[FastAPI, Database, Settings]],
) -> Iterator[tuple[TestClient, Database, Settings]]:
    app, database, settings = app_factory()
    with TestClient(app) as client:
        client.headers["Origin"] = "http://testserver"
        yield client, database, settings


def _conversation(client: TestClient, database: Database, settings: Settings) -> tuple[str, str]:
    with database.session() as session:
        ensure_demo_baseline(session, settings.resolved_data_root)
    _user, csrf = login(client, "bowen")
    created = client.post(
        "/api/v1/conversations",
        headers={"X-CSRF-Token": csrf},
        json={"version_id": BASELINE_VERSION_ID},
    )
    assert created.status_code == 200, created.text
    return csrf, str(created.json()["id"])


def _claim(database: Database, settings: Settings, conversation_id: str, message: str) -> str:
    request_id = str(uuid4())
    with database.session() as session:
        row = session.get(Conversation, conversation_id)
        assert row is not None
        _turn, created = claim_chat_send(
            session,
            row,
            database=database,
            request_id=request_id,
            expected_revision=row.revision,
            message=message,
            settings=settings,
        )
        assert created
    return request_id


def _plant(database: Database, *, scope_id: str, request_id: str, state: str) -> str:
    repository = ProviderRepository(database, require_export_confirmation=False)
    repository.save_scope_budget(
        scope_id,
        ProviderScopeBudgetV1(
            max_requests=4,
            max_total_tokens=8000,
            max_cost_cny=1,
            budget_bucket=LLM_DEBATE_TURN_BUCKET,
        ),
    )
    operation = repository.create_prepared(
        ProviderReservationRequestV1(
            scope_id=scope_id,
            provider_operation="llm_agent_chat",
            logical_item_id=request_id,
            attempt_no=1,
            request_hash=_digest(request_id),
            max_tokens=100,
            max_cost_cny=0.01,
            policy_hash=_digest("policy"),
            export_manifest_hash=_digest("manifest"),
            build_manifest_hash=_digest("build"),
            model_key="qwen3.8-max-2026-09-02",
        )
    )
    if state == "prepared":
        return operation.id
    repository.reserve(operation.id)
    if state == "reserved":
        return operation.id
    repository.transition(operation.id, expected="reserved", state="sending")
    if state == "sending":
        return operation.id
    repository.mark_accepted(operation.id, response_hash=_digest("reply"))
    return operation.id


def _allocated(database: Database, scope_id: str) -> int:
    with database.session() as session:
        budget = session.get(ProviderScopeBudget, (scope_id, LLM_DEBATE_TURN_BUCKET))
        assert budget is not None
        return int(budget.allocated_requests)


def _wait_operation(database: Database, operation_id: str, state: str) -> ProviderOperation:
    deadline = time.monotonic() + 5
    seen = None
    while time.monotonic() < deadline:
        with database.session() as session:
            operation = session.get(ProviderOperation, operation_id)
            seen = None if operation is None else operation.state
            if operation is not None and operation.state == state:
                session.expunge(operation)
                return operation
        time.sleep(0.02)
    raise AssertionError(seen)


def _send(client: TestClient, csrf: str, conversation_id: str, message: str) -> dict[str, object]:
    current = client.get(f"/api/v1/conversations/{conversation_id}")
    assert current.status_code == 200, current.text
    response = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers={"X-CSRF-Token": csrf},
        json={
            "request_id": str(uuid4()),
            "expected_revision": current.json()["revision"],
            "message": message,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body, dict)
    return body


def test_abort_before_first_token_refunds_unsent_call(
    voice_app: tuple[TestClient, Database, Settings], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, database, settings = voice_app
    csrf, conversation_id = _conversation(client, database, settings)
    message = "Hold before any token"
    request_id = _claim(database, settings, conversation_id, message)
    started = threading.Event()
    release = threading.Event()
    planted: dict[str, str] = {}

    def blocked(db, settings, row, request_id, message, lang=None):  # type: ignore[no-untyped-def]
        del db, settings, row, lang
        planted["id"] = _plant(
            database, scope_id=conversation_id, request_id=request_id, state="reserved"
        )
        started.set()
        assert release.wait(5)
        return "hidden", [], planted["id"]

    monkeypatch.setattr("app.modules.workspace.chat.generate_reply", blocked)

    async def drive() -> None:
        agen = stream_events(
            database,
            settings,
            conversation_id=conversation_id,
            created=True,
            message=message,
            lang="en",
            request_id=request_id,
        )
        task = asyncio.create_task(agen.__anext__())
        assert await asyncio.to_thread(started.wait, 5)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        with contextlib.suppress(Exception):
            await agen.aclose()

    asyncio.run(drive())
    release.set()
    operation = _wait_operation(database, planted["id"], "not_sent")
    assert operation.safe_error_code == "chat_cancelled"
    assert _allocated(database, conversation_id) == 0
    with database.session() as session:
        turn = session.get(ConversationTurn, request_id)
        row = session.get(Conversation, conversation_id)
        assert turn is not None and row is not None
        assert turn.state == "failed"
        assert turn.safe_error_code == "chat_cancelled"
        assert turn.assistant_text is None
        assert row.active_request_id is None
    sent = _send(client, csrf, conversation_id, "Next after cancel")
    assert sent["revision"] == 2


def test_abort_mid_stream_keeps_the_accepted_charge(
    voice_app: tuple[TestClient, Database, Settings], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, database, settings = voice_app
    csrf, conversation_id = _conversation(client, database, settings)
    message = "Stop after the first words"
    request_id = _claim(database, settings, conversation_id, message)
    planted: dict[str, str] = {}

    def accepted(db, settings, row, request_id, message, lang=None):  # type: ignore[no-untyped-def]
        del db, settings, row, message, lang
        planted["id"] = _plant(
            database, scope_id=conversation_id, request_id=request_id, state="accepted"
        )
        return "x" * 80, [], planted["id"]

    monkeypatch.setattr("app.modules.workspace.chat.generate_reply", accepted)

    async def drive() -> None:
        agen = stream_events(
            database,
            settings,
            conversation_id=conversation_id,
            created=True,
            message=message,
            lang="en",
            request_id=request_id,
        )
        first = await agen.__anext__()
        assert b"event: delta" in first
        await agen.aclose()

    asyncio.run(drive())
    operation = _wait_operation(database, planted["id"], "failed")
    assert operation.safe_error_code == "chat_cancelled"
    assert operation.charged_request_count == 1
    assert _allocated(database, conversation_id) == 1
    with database.session() as session:
        turn = session.get(ConversationTurn, request_id)
        assert turn is not None
        assert turn.state == "failed"
        assert turn.assistant_text is None
    sent = _send(client, csrf, conversation_id, "Next after a partial reply")
    assert any(turn["state"] == "ready" for turn in sent["turns"])


def test_abort_during_tts_keeps_the_stored_reply(
    voice_app: tuple[TestClient, Database, Settings], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, database, settings = voice_app
    csrf, conversation_id = _conversation(client, database, settings)
    message = "Speak then stop"
    request_id = _claim(database, settings, conversation_id, message)
    planted: dict[str, str] = {}
    started = threading.Event()
    release = threading.Event()

    def accepted(db, settings, row, request_id, message, lang=None):  # type: ignore[no-untyped-def]
        del db, settings, row, message, lang
        planted["id"] = _plant(
            database, scope_id=conversation_id, request_id=request_id, state="accepted"
        )
        return "A stored reply that should stay.", [], planted["id"]

    class _BlockedTTS:
        def synthesize(self, text: str, external_voice_id: str, language: str = "en") -> TTSResult:
            del text, external_voice_id, language
            started.set()
            assert release.wait(5)
            return TTSResult(audio_bytes=_wav(1), content_type="audio/wav", request_id="tts")

    monkeypatch.setattr("app.modules.workspace.chat.generate_reply", accepted)
    monkeypatch.setattr(
        "app.modules.workspace.chat_stream._voice_segment",
        lambda *_args, **_kwargs: ("profile", "external"),
    )
    monkeypatch.setattr(
        "app.modules.workspace.chat_stream.tts_provider", lambda _settings: _BlockedTTS()
    )

    async def drive() -> None:
        agen = stream_events(
            database,
            settings,
            conversation_id=conversation_id,
            created=True,
            message=message,
            lang="en",
            request_id=request_id,
        )
        task = asyncio.create_task(_consume(agen))
        assert await asyncio.to_thread(started.wait, 5)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        with contextlib.suppress(Exception):
            await agen.aclose()

    try:
        asyncio.run(drive())
    finally:
        release.set()
    operation = _wait_operation(database, planted["id"], "succeeded")
    assert _allocated(database, conversation_id) == 1
    with database.session() as session:
        turn = session.get(ConversationTurn, request_id)
        row = session.get(Conversation, conversation_id)
        assert turn is not None and row is not None
        assert turn.state == "ready"
        assert turn.assistant_text == "A stored reply that should stay."
        assert row.active_request_id is None
        assert operation.id == planted["id"]
    sent = _send(client, csrf, conversation_id, "Next after speech was cut")
    assert sent["revision"] == 2


async def _consume(agen: object) -> None:
    assert hasattr(agen, "__aiter__")
    async for _chunk in agen:  # type: ignore[attr-defined]
        pass


def test_stale_pending_turns_do_not_block_the_next_message(
    voice_app: tuple[TestClient, Database, Settings],
) -> None:
    client, database, settings = voice_app
    csrf, conversation_id = _conversation(client, database, settings)
    locked_id = str(uuid4())
    unlocked_id = str(uuid4())
    interrupted_id = str(uuid4())
    with database.session() as session:
        row = session.get(Conversation, conversation_id)
        assert row is not None
        row.active_request_id = locked_id
        session.add(
            ConversationTurn(
                id=locked_id,
                conversation_id=conversation_id,
                position=0,
                user_text="old lock",
                assistant_text=None,
                sources_json="[]",
                mode="real",
                state="pending",
                created_at=datetime.now(UTC) - timedelta(minutes=10),
            )
        )
        session.add(
            ConversationTurn(
                id=unlocked_id,
                conversation_id=conversation_id,
                position=1,
                user_text="dead request",
                assistant_text=None,
                sources_json="[]",
                mode="mock",
                state="pending",
                created_at=datetime.now(UTC),
            )
        )
        session.add(
            ConversationTurn(
                id=interrupted_id,
                conversation_id=conversation_id,
                position=2,
                user_text="old interrupt",
                assistant_text=None,
                sources_json="[]",
                mode="real",
                state="acceptance_unknown",
                safe_error_code="chat_interrupted",
                created_at=datetime.now(UTC),
            )
        )
    sent = _send(client, csrf, conversation_id, "This send must be accepted")
    assert sent["revision"] == 1
    with database.session() as session:
        for turn_id in (locked_id, unlocked_id, interrupted_id):
            turn = session.get(ConversationTurn, turn_id)
            assert turn is not None
            assert turn.state == "failed"
            assert turn.safe_error_code == "chat_interrupted"
        row = session.get(Conversation, conversation_id)
        assert row is not None
        assert row.active_request_id is None


def test_young_locked_pending_turn_still_reports_busy(
    voice_app: tuple[TestClient, Database, Settings],
) -> None:
    client, database, settings = voice_app
    csrf, conversation_id = _conversation(client, database, settings)
    request_id = str(uuid4())
    with database.session() as session:
        row = session.get(Conversation, conversation_id)
        assert row is not None
        row.active_request_id = request_id
        session.add(
            ConversationTurn(
                id=request_id,
                conversation_id=conversation_id,
                position=0,
                user_text="still running",
                assistant_text=None,
                sources_json="[]",
                mode="mock",
                state="pending",
                created_at=datetime.now(UTC),
            )
        )
    response = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers={"X-CSRF-Token": csrf},
        json={"request_id": str(uuid4()), "expected_revision": 0, "message": "Too soon"},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "chat_busy"
    with database.session() as session:
        turn = session.get(ConversationTurn, request_id)
        assert turn is not None
        assert turn.state == "pending"


def test_startup_repair_fails_pending_turns_and_closes_open_calls(
    voice_app: tuple[TestClient, Database, Settings],
) -> None:
    from app.modules.workspace.chat import repair_abandoned_chats

    client, database, settings = voice_app
    csrf, conversation_id = _conversation(client, database, settings)
    pending_id = str(uuid4())
    genuine_id = str(uuid4())
    accepted_id = _plant(
        database, scope_id=conversation_id, request_id=pending_id, state="accepted"
    )
    with database.session() as session:
        row = session.get(Conversation, conversation_id)
        assert row is not None
        row.active_request_id = pending_id
        session.add(
            ConversationTurn(
                id=pending_id,
                conversation_id=conversation_id,
                position=0,
                user_text="died mid-call",
                assistant_text=None,
                sources_json="[]",
                mode="real",
                state="pending",
                created_at=datetime.now(UTC),
            )
        )
        session.add(
            ConversationTurn(
                id=genuine_id,
                conversation_id=conversation_id,
                position=1,
                user_text="provider outcome unknown",
                assistant_text=None,
                sources_json="[]",
                mode="real",
                state="acceptance_unknown",
                safe_error_code="chat_acceptance_unknown",
                created_at=datetime.now(UTC),
            )
        )
    repair_abandoned_chats(database, only_stale=False)
    operation = _wait_operation(database, accepted_id, "failed")
    assert operation.safe_error_code == "chat_interrupted"
    assert _allocated(database, conversation_id) == 1
    with database.session() as session:
        pending = session.get(ConversationTurn, pending_id)
        genuine = session.get(ConversationTurn, genuine_id)
        row = session.get(Conversation, conversation_id)
        assert pending is not None and genuine is not None and row is not None
        assert pending.state == "failed"
        assert pending.safe_error_code == "chat_interrupted"
        assert genuine.state == "acceptance_unknown"
        assert genuine.safe_error_code == "chat_acceptance_unknown"
        assert row.active_request_id is None
    blocked = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers={"X-CSRF-Token": csrf},
        json={"request_id": str(uuid4()), "expected_revision": 0, "message": "Still blocked"},
    )
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "chat_acceptance_unknown"
