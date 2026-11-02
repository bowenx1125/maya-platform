"""Text-only SSE chat events publish deltas after committing the full reply.

While the reply is still being written, ``draft`` events carry its text as it
streams from the model. Drafts are unsaved and provisional: ``text_done``
(after the commit) is the reply, and a client replaces any draft with it.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy.orm import Session

from app.core.chat_turn_locks import chat_turn_locks
from app.core.config import Settings
from app.core.db import Database
from app.core.errors import PlatformError, not_found
from app.core.write_guard import WriteSlot
from app.modules.auth.service import AuthContext

from .models import Conversation, ConversationTurn
from .schemas import ChatSource
from .team_event_signals import TeamEventWatch
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
    write_slot: WriteSlot | None = None,
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

    # Marks this turn as running in this process, so an orphan sweep never
    # takes it while the reply is still being written (core/chat_turn_locks).
    turn_locks = chat_turn_locks(database.engine) if created else None
    try:
        if turn_locks is not None:
            await asyncio.to_thread(turn_locks.hold, request_id)
        if not created:
            if write_slot is not None:
                write_slot.release()
            yield _replay_event(
                database,
                settings,
                conversation_id,
                request_id,
                claim_revision,
            )
            return
        loop = asyncio.get_running_loop()
        drafts: asyncio.Queue[tuple[int, str]] = asyncio.Queue()

        def on_draft(call: int, text: str) -> None:
            loop.call_soon_threadsafe(drafts.put_nowait, (call, text))

        reply_task = asyncio.ensure_future(
            asyncio.to_thread(
                _reply_segment,
                database,
                settings,
                conversation_id,
                request_id,
                claim_revision,
                message,
                actor_context,
                generation_waker,
                write_slot,
                on_draft,
            )
        )
        try:
            async for event in _draft_events(reply_task, drafts, request_id):
                yield event
            reply, sources, operation_id = await reply_task
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
        # A stream closed before the reply thread adopted the reserved slot
        # must still give it back (release is idempotent).
        if write_slot is not None:
            write_slot.release_if_unadopted()
        if created and not settled:
            settle(PlatformError("chat_interrupted", "This chat request was interrupted.", 503))
        release()
        if turn_locks is not None:
            turn_locks.release(request_id)


async def _draft_events(
    reply_task: asyncio.Future[Any],
    drafts: asyncio.Queue[tuple[int, str]],
    request_id: str,
) -> AsyncIterator[bytes]:
    """Yield the reply's text pieces until the reply thread finishes.

    Pieces that arrived together are sent as one event per model call. What is
    still queued when the thread ends is dropped: ``text_done`` follows.
    """

    seq = 0
    while not reply_task.done():
        getter = asyncio.ensure_future(drafts.get())
        try:
            done, _pending = await asyncio.wait(
                {reply_task, getter}, return_when=asyncio.FIRST_COMPLETED
            )
        finally:
            if not getter.done():
                getter.cancel()
        if getter not in done or getter.cancelled():
            return
        pieces = [getter.result()]
        while not drafts.empty():
            pieces.append(drafts.get_nowait())
        merged: list[tuple[int, str]] = []
        for call, text in pieces:
            if merged and merged[-1][0] == call:
                merged[-1] = (call, merged[-1][1] + text)
            else:
                merged.append((call, text))
        for call, text in merged:
            seq += 1
            yield sse("draft", {"request_id": request_id, "call": call, "seq": seq, "text": text})


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
    write_slot: WriteSlot | None = None,
    on_draft: Callable[[int, str], None] | None = None,
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
            write_slot=write_slot,
            on_draft=on_draft,
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


# A waiting stream polls quickly right after an event and backs off while
# nothing changes: 20 polls a second per waiting student was the largest
# database load of a class, most of them finding nothing new.
POLL_MIN_SECONDS = 0.05
POLL_MAX_SECONDS = 0.5
# A stream its turn's commits wake (team_event_signals) only polls as a
# fallback, so it can back off much further while a member is thinking.
WOKEN_POLL_MAX_SECONDS = 2.0


def next_poll_delay(previous: float, got_events: bool, ceiling: float = POLL_MAX_SECONDS) -> float:
    """Back to the minimum after an event; otherwise double, up to the cap."""

    if got_events:
        return POLL_MIN_SECONDS
    return min(ceiling, previous * 2)


async def stream_team_events(
    database: Database,
    conversation_id: str,
    actor_id: str,
    claim: TeamClaim,
    after_sequence: int = 0,
    on_finished: Callable[[], None] | None = None,
    write_slot: WriteSlot | None = None,
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

    # A replay runs too: it executes nothing new but resumes an old turn whose
    # receipt a crash left unclaimed.
    task = asyncio.create_task(
        asyncio.to_thread(
            execute_team_turn_with_natural_assessment_resume,
            database.session_factory,
            claim,
            write_slot,
        )
    )
    _TEAM_BACKGROUND_RUNS.add(task)
    task.add_done_callback(_TEAM_BACKGROUND_RUNS.discard)
    if on_finished is not None:
        # Runs even if the browser left; the run itself is not tied to it.
        task.add_done_callback(lambda _task: on_finished())
    delay = POLL_MIN_SECONDS
    with TeamEventWatch(claim.turn_id) as watch:
        while True:
            watch.clear()
            events, state, active = await asyncio.to_thread(poll)
            for sequence, kind, payload in events:
                cursor = sequence
                yield f"id: {sequence}\n".encode() + sse(kind, payload)
            if not active or state != "pending":
                return
            delay = next_poll_delay(delay, bool(events), WOKEN_POLL_MAX_SECONDS)
            # Wake at once on a committed event or when the run finishes, so
            # a result is not held back by an idle interval.
            woken = asyncio.ensure_future(watch.wait())
            try:
                await asyncio.wait(
                    {woken} if task.done() else {woken, task},
                    timeout=delay,
                    return_when=asyncio.FIRST_COMPLETED,
                )
            finally:
                woken.cancel()
