"""Text-only SSE chat events publish deltas after committing the full reply."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.db import Database
from app.core.errors import PlatformError, not_found
from app.modules.auth.service import AuthContext
from app.modules.knowledge.files import FileBoundaryError, contained_path

from .models import Conversation, ConversationTurn
from .schemas import ChatSource
from .team_runtime import TeamClaim

_TEAM_BACKGROUND_RUNS: set[asyncio.Task[None]] = set()

DELTA_CHARS = 48


def accepts_event_stream(value: str | None) -> bool:
    if not value:
        return False
    for part in value.split(","):
        media = part.split(";", 1)[0].strip().lower()
        if media == "text/event-stream":
            return True
    return False


def text_deltas(text: str) -> list[str]:
    if not text:
        return []
    return [text[index : index + DELTA_CHARS] for index in range(0, len(text), DELTA_CHARS)]


def sse(event: str, payload: dict[str, object]) -> bytes:
    line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {line}\n\n".encode()


def chat_audio_relative(conversation_id: str, request_id: str) -> str:
    return f"chat-audio/{conversation_id}/{request_id}.wav"


@contextmanager
def _segment(database: Database, settings: Settings) -> Iterator[Session]:
    """Open one short session and close it before the next provider call."""

    db = database.session_factory()
    db.info["maya_settings"] = settings
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


async def stream_events(
    database: Database,
    settings: Settings,
    *,
    conversation_id: str,
    created: bool,
    message: str,
    request_id: str,
    claim_revision: int,
    actor_context: AuthContext | None = None,
    generation_waker: Callable[[str], None] | None = None,
) -> AsyncIterator[bytes]:
    """Yield deltas only after the current request has committed its full reply.

    The request session is not used here. Each database segment closes
    before the LLM call; the claim stays held through deltas and is released
    before a terminal event is published.
    """

    released = False
    settled = False

    def release() -> None:
        nonlocal released
        if released or not created:
            return
        with _segment(database, settings) as db:
            from .chat import release_chat_request

            release_chat_request(db, conversation_id, request_id, claim_revision)
        released = True

    def settle(exc: Exception) -> str:
        nonlocal settled
        if settled or not created:
            return "chat_failed"
        code = _failure_code(database, settings, conversation_id, request_id, claim_revision, exc)
        settled = True
        return code

    try:
        if not created:
            yield _replay_event(
                database,
                settings,
                conversation_id,
                request_id,
                claim_revision,
            )
            return
        try:
            reply, sources, operation_id = await asyncio.to_thread(
                _reply_segment,
                database,
                settings,
                conversation_id,
                request_id,
                claim_revision,
                message,
                actor_context,
                generation_waker,
            )
        except Exception as exc:
            code = settle(exc)
            release()
            yield sse("error", {"request_id": request_id, "safe_error_code": code})
            return
        try:
            revision, stored_sources = await asyncio.to_thread(
                _store_segment,
                database,
                settings,
                conversation_id,
                request_id,
                claim_revision,
                reply,
                sources,
                operation_id,
            )
        except Exception as exc:
            code = settle(exc)
            release()
            yield sse("error", {"request_id": request_id, "safe_error_code": code})
            return
        settled = True
        for seq, text in enumerate(text_deltas(reply), start=1):
            yield sse("delta", {"request_id": request_id, "seq": seq, "text": text})
        release()
        yield sse(
            "text_done",
            {
                "request_id": request_id,
                "assistant_text": reply,
                "revision": revision,
                "sources": stored_sources,
            },
        )
        release()
    finally:
        if created and not settled:
            settle(PlatformError("chat_interrupted", "This chat request was interrupted.", 503))
        release()


def _replay_event(
    database: Database,
    settings: Settings,
    conversation_id: str,
    request_id: str,
    claim_revision: int,
) -> bytes:
    with _segment(database, settings) as db:
        row = db.get(Conversation, conversation_id)
        turn = db.get(ConversationTurn, request_id)
        if row is None or turn is None or turn.conversation_id != conversation_id:
            return sse("error", {"request_id": request_id, "safe_error_code": "chat_failed"})
        if turn.position != claim_revision:
            return sse("error", {"request_id": request_id, "safe_error_code": "chat_failed"})
        if turn.state == "pending":
            return sse("pending", {"request_id": request_id})
        from .chat import release_chat_request

        release_chat_request(db, conversation_id, request_id, claim_revision)
        if turn.state == "ready" and turn.assistant_text:
            sources = _stored_sources(turn.sources_json)
            if sources is None:
                return sse(
                    "error",
                    {"request_id": request_id, "safe_error_code": "chat_sources_invalid"},
                )
            return sse(
                "text_done",
                {
                    "request_id": request_id,
                    "assistant_text": turn.assistant_text,
                    "revision": row.revision,
                    "sources": sources,
                },
            )
        return sse(
            "error",
            {"request_id": request_id, "safe_error_code": turn.safe_error_code or "chat_failed"},
        )


def _stored_sources(raw: str) -> list[object] | None:
    try:
        loaded = json.loads(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(loaded, list):
        return None
    return loaded


def _reply_segment(
    database: Database,
    settings: Settings,
    conversation_id: str,
    request_id: str,
    claim_revision: int,
    message: str,
    actor_context: AuthContext | None = None,
    generation_waker: Callable[[str], None] | None = None,
) -> tuple[str, list[ChatSource], str | None]:
    from .chat import generate_reply

    with _segment(database, settings) as db:
        row = db.get(Conversation, conversation_id)
        if row is None:
            raise not_found()
        return generate_reply(
            db,
            settings,
            row,
            request_id,
            claim_revision,
            message,
            actor_context=actor_context,
            generation_waker=generation_waker,
        )


def _store_segment(
    database: Database,
    settings: Settings,
    conversation_id: str,
    request_id: str,
    claim_revision: int,
    reply: str,
    sources: list[ChatSource],
    operation_id: str | None,
) -> tuple[int, list[dict[str, Any]]]:
    from .chat import store_assistant_text

    with _segment(database, settings) as db:
        revision, stored = store_assistant_text(
            db,
            conversation_id,
            request_id,
            claim_revision,
            reply,
            sources,
            operation_id,
        )
        return revision, stored


def _failure_code(
    database: Database,
    settings: Settings,
    conversation_id: str,
    request_id: str,
    claim_revision: int,
    exc: Exception,
) -> str:
    from .chat import record_chat_failure

    try:
        with _segment(database, settings) as db:
            return record_chat_failure(db, conversation_id, request_id, claim_revision, exc)
    except PlatformError:
        return "chat_failed"


def chat_audio_path(settings: Settings, conversation_id: UUID, request_id: UUID) -> Path:
    try:
        path = contained_path(
            settings.resolved_data_root,
            chat_audio_relative(str(conversation_id), str(request_id)),
        )
    except FileBoundaryError:
        raise not_found() from None
    if path.is_symlink() or not path.is_file():
        raise not_found()
    return path


async def stream_team_events(
    database: Database,
    conversation_id: str,
    actor_id: str,
    claim: TeamClaim,
    after_sequence: int = 0,
) -> AsyncIterator[bytes]:
    from .team_runtime import (
        execute_team_turn_with_natural_assessment_resume,
        poll_team_events,
    )

    cursor = after_sequence

    def poll() -> tuple[list[tuple[int, str, dict[str, Any]]], str, bool]:
        return poll_team_events(
            database.session_factory,
            conversation_id,
            claim.turn_id,
            actor_id,
            after_sequence=cursor,
        )

    if claim.created:
        task = asyncio.create_task(
            asyncio.to_thread(
                execute_team_turn_with_natural_assessment_resume,
                database.session_factory,
                claim,
            )
        )
        _TEAM_BACKGROUND_RUNS.add(task)
        task.add_done_callback(_TEAM_BACKGROUND_RUNS.discard)
    while True:
        events, state, active = await asyncio.to_thread(poll)
        for sequence, kind, payload in events:
            cursor = sequence
            yield f"id: {sequence}\n".encode() + sse(kind, payload)
        if not active or state != "pending":
            return
        await asyncio.sleep(0.05)
