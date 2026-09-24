"""SSE chat events: deltas, one full-text commit, then a single TTS URL."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from logging import getLogger
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.db import Database
from app.core.errors import PlatformError, not_found
from app.core.models import AgentVersion
from app.modules.knowledge.files import FileBoundaryError, contained_path, write_atomic
from app.modules.voices.service import ready_chat_voice
from app.providers.factory import tts_provider
from app.providers.tts import TTSProviderError

from .models import Conversation, ConversationTurn
from .schemas import ChatSource

logger = getLogger("maya.workspace")

CHAT_LANGUAGES = frozenset({"zh-CN", "en"})
DELTA_CHARS = 48


def language_supported(lang: str) -> bool:
    return lang in CHAT_LANGUAGES


def tts_language(lang: str) -> str:
    if lang == "zh-CN":
        return "zh"
    if lang == "en":
        return "en"
    raise ValueError("unsupported chat language")


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


def chat_audio_url(conversation_id: str, request_id: str) -> str:
    return f"/api/v1/conversations/{conversation_id}/audio/{request_id}"


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
    lang: str,
    request_id: str,
) -> AsyncIterator[bytes]:
    """Yield delta, text_done, then at most one tts_ready or error.

    The request session is not used here.  Each database segment closes
    before the LLM or TTS call, and the conversation lock is released
    immediately after text_done so speech does not keep the chat busy.
    """

    released = False

    def release() -> None:
        nonlocal released
        if released or not created:
            return
        with _segment(database, settings) as db:
            from .chat import release_chat_request

            release_chat_request(db, conversation_id, request_id)
        released = True

    try:
        if not created:
            yield _replay_event(database, settings, conversation_id, request_id)
            return
        try:
            reply, sources, operation_id = await asyncio.to_thread(
                _reply_segment,
                database,
                settings,
                conversation_id,
                request_id,
                message,
                lang,
            )
        except Exception as exc:
            code = _failure_code(database, settings, conversation_id, request_id, exc)
            yield sse("error", {"request_id": request_id, "safe_error_code": code})
            return
        for seq, text in enumerate(text_deltas(reply), start=1):
            yield sse("delta", {"request_id": request_id, "seq": seq, "text": text})
        try:
            revision, stored_sources = await asyncio.to_thread(
                _store_segment,
                database,
                settings,
                request_id,
                reply,
                sources,
                operation_id,
            )
        except Exception as exc:
            code = _failure_code(database, settings, conversation_id, request_id, exc)
            yield sse("error", {"request_id": request_id, "safe_error_code": code})
            return
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
        async for event in _tts_events(
            database, settings, conversation_id, request_id, reply, lang
        ):
            yield event
    finally:
        release()


def _replay_event(
    database: Database,
    settings: Settings,
    conversation_id: str,
    request_id: str,
) -> bytes:
    with _segment(database, settings) as db:
        row = db.get(Conversation, conversation_id)
        turn = db.get(ConversationTurn, request_id)
        if row is None or turn is None or turn.conversation_id != conversation_id:
            return sse("error", {"request_id": request_id, "safe_error_code": "chat_failed"})
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
    message: str,
    lang: str,
) -> tuple[str, list[ChatSource], str | None]:
    from .chat import generate_reply

    with _segment(database, settings) as db:
        row = db.get(Conversation, conversation_id)
        if row is None:
            raise not_found()
        return generate_reply(db, settings, row, request_id, message, lang=lang)


def _store_segment(
    database: Database,
    settings: Settings,
    request_id: str,
    reply: str,
    sources: list[ChatSource],
    operation_id: str | None,
) -> tuple[int, list[dict[str, Any]]]:
    from .chat import store_assistant_text

    with _segment(database, settings) as db:
        revision, stored = store_assistant_text(db, request_id, reply, sources, operation_id)
        return revision, stored


def _failure_code(
    database: Database,
    settings: Settings,
    conversation_id: str,
    request_id: str,
    exc: Exception,
) -> str:
    from .chat import record_chat_failure

    try:
        with _segment(database, settings) as db:
            return record_chat_failure(db, conversation_id, request_id, exc)
    except PlatformError:
        return "chat_failed"


async def _tts_events(
    database: Database,
    settings: Settings,
    conversation_id: str,
    request_id: str,
    reply: str,
    lang: str,
) -> AsyncIterator[bytes]:
    """Synthesize once after the text commit.  A failure leaves that text stored."""

    voice = await asyncio.to_thread(_voice_segment, database, settings, conversation_id)
    if voice is None:
        return
    profile_id, external_id = voice
    if not external_id:
        yield sse("error", {"request_id": request_id, "safe_error_code": "tts_voice_unavailable"})
        return
    try:
        await asyncio.to_thread(
            _synthesize_segment,
            settings,
            conversation_id,
            request_id,
            reply,
            external_id,
            lang,
        )
    except Exception as exc:
        code = exc.safe_code if isinstance(exc, TTSProviderError) else "tts_failed"
        if not isinstance(code, str) or not code:
            code = "tts_failed"
        logger.warning(
            "Chat TTS failed conversation_id=%s turn_id=%s code=%s",
            conversation_id,
            request_id,
            code,
        )
        yield sse("error", {"request_id": request_id, "safe_error_code": code})
        return
    yield sse(
        "tts_ready",
        {
            "request_id": request_id,
            "audio_url": chat_audio_url(conversation_id, request_id),
            "voice_profile_id": profile_id,
            "content_type": "audio/wav",
        },
    )


def _voice_segment(
    database: Database,
    settings: Settings,
    conversation_id: str,
) -> tuple[str, str | None] | None:
    with _segment(database, settings) as db:
        row = db.get(Conversation, conversation_id)
        if row is None:
            return None
        version = db.get(AgentVersion, row.agent_version_id)
        profile_id = version.voice_profile_id if version is not None else None
        if not profile_id:
            return None
        return profile_id, ready_chat_voice(db, profile_id, settings)


def _synthesize_segment(
    settings: Settings,
    conversation_id: str,
    request_id: str,
    reply: str,
    external_id: str,
    lang: str,
) -> None:
    result = tts_provider(settings).synthesize(
        reply,
        external_id,
        language=tts_language(lang),
    )
    if result.content_type != "audio/wav" or not result.audio_bytes:
        raise TTSProviderError("provider audio invalid", safe_code="tts_audio_invalid")
    write_atomic(
        settings.resolved_data_root,
        chat_audio_relative(conversation_id, request_id),
        result.audio_bytes,
    )


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
