"""Route-level checks for the ticket-gated performance timeline read."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from app.core.errors import PlatformError
from app.modules.debates.playback.router import stream_performance_route

PAYLOAD = b'{"version":2,"duration":1.0,"events":[],"visemes":[]}'


class _StubStore:
    def __init__(self, payload: bytes | None) -> None:
        self._payload = payload
        self.calls: list[tuple[str, str]] = []

    def read_performance(self, debate_id: str, turn_id: str) -> bytes | None:
        self.calls.append((debate_id, turn_id))
        return self._payload


class _RefusingService:
    """Mirrors authorize_audio's fail-closed behavior without a database."""

    def __init__(self, store: _StubStore | None) -> None:
        self.audio_store = store
        self.authorized: list[tuple[str, str, str | None]] = []

    async def authorize_audio(
        self,
        _db: Any,
        debate_id: str,
        turn_id: str,
        *,
        session_hash: str,
        media_ticket: str | None,
        context: Any = None,
    ) -> None:
        del session_hash, context
        self.authorized.append((debate_id, turn_id, media_ticket))
        if media_ticket is None:
            raise PlatformError("forbidden", "A media ticket is required.", 403)


def _ids() -> tuple[Any, Any, str]:
    debate_id, turn_id = uuid4(), uuid4()
    return debate_id, turn_id, f"{debate_id}/{turn_id}"


class _Context:
    raw_session_token = "raw-session-token"


@pytest.mark.asyncio
async def test_performance_route_serves_timeline_with_ticket() -> None:
    debate_id, turn_id, key = _ids()
    store = _StubStore(PAYLOAD)
    service = _RefusingService(store)

    response = await stream_performance_route(  # type: ignore[arg-type]
        debate_id,
        turn_id,
        media_ticket="T" * 43,
        context=_Context(),
        db=object(),
        service=service,
    )

    assert response.status_code == 200
    assert response.media_type == "application/json"
    assert response.body == PAYLOAD
    assert store.calls == [(str(debate_id), str(turn_id))]


@pytest.mark.asyncio
async def test_performance_route_404s_plain_audio_turns() -> None:
    debate_id, turn_id, _key = _ids()
    store = _StubStore(None)
    service = _RefusingService(store)

    with pytest.raises(PlatformError) as exc_info:
        await stream_performance_route(  # type: ignore[arg-type]
            debate_id,
            turn_id,
            media_ticket="T" * 43,
            context=_Context(),
            db=object(),
            service=service,
        )

    assert exc_info.value.status_code == 404
    assert service.authorized  # authorization still ran before the read


@pytest.mark.asyncio
async def test_performance_route_forwards_missing_ticket_refusal() -> None:
    debate_id, turn_id, _key = _ids()
    service = _RefusingService(_StubStore(PAYLOAD))

    with pytest.raises(PlatformError) as exc_info:
        await stream_performance_route(  # type: ignore[arg-type]
            debate_id,
            turn_id,
            media_ticket=None,
            context=_Context(),
            db=object(),
            service=service,
        )

    assert exc_info.value.code == "forbidden"


@pytest.mark.asyncio
async def test_performance_route_without_audio_store_is_not_found() -> None:
    debate_id, turn_id, _key = _ids()
    service = _RefusingService(None)

    with pytest.raises(PlatformError) as exc_info:
        await stream_performance_route(  # type: ignore[arg-type]
            debate_id,
            turn_id,
            media_ticket="T" * 43,
            context=_Context(),
            db=object(),
            service=service,
        )

    assert exc_info.value.status_code == 404
    assert service.authorized == []
