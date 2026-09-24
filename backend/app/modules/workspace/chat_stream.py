"""SSE chat events: deltas, one full-text commit, then a single TTS URL."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import PlatformError, not_found
from app.core.models import AgentVersion
from app.modules.knowledge.files import FileBoundaryError, contained_path, write_atomic
from app.modules.voices.service import ready_chat_voice
from app.providers.factory import tts_provider
from app.providers.tts import TTSProviderError

from .models import Conversation, ConversationTurn

logger = logging.getLogger("maya.workspace")

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


async def stream_events(
    db: Session,
    settings: Settings,
    row: Conversation,
    turn: ConversationTurn,
    *,
    created: bool,
    message: str,
    lang: str,
    request_id: str,
) -> AsyncIterator[bytes]:
    """Yield the chat event sequence for one claimed or replayed request."""

    from .chat import generate_reply, release_chat_request, store_assistant_text

    try:
        if not created:
            if turn.state == "ready" and turn.assistant_text:
                yield sse(
                    "text_done",
                    {
                        "request_id": request_id,
                        "assistant_text": turn.assistant_text,
                        "revision": row.revision,
                        "sources": json.loads(turn.sources_json),
                    },
                )
            else:
                yield sse(
                    "error",
                    {
                        "request_id": request_id,
                        "safe_error_code": turn.safe_error_code or "chat_failed",
                    },
                )
            return
        try:
            reply, sources, operation_id = generate_reply(
                db,
                settings,
                row,
                request_id,
                message,
                lang=lang,
            )
        except Exception as exc:
            code = _failure_code(db, row.id, request_id, exc)
            yield sse("error", {"request_id": request_id, "safe_error_code": code})
            return
        for seq, text in enumerate(text_deltas(reply), start=1):
            yield sse("delta", {"request_id": request_id, "seq": seq, "text": text})
        try:
            revision, stored_sources = store_assistant_text(
                db,
                request_id,
                reply,
                sources,
                operation_id,
            )
        except Exception as exc:
            code = _failure_code(db, row.id, request_id, exc)
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
        async for event in _tts_events(db, settings, row, request_id, reply, lang):
            yield event
    finally:
        if created:
            release_chat_request(db, row.id, request_id)
            db.commit()


def _failure_code(db: Session, conversation_id: str, request_id: str, exc: Exception) -> str:
    from .chat import record_chat_failure

    try:
        return record_chat_failure(db, conversation_id, request_id, exc)
    except PlatformError:
        return "chat_failed"


async def _tts_events(
    db: Session,
    settings: Settings,
    row: Conversation,
    request_id: str,
    reply: str,
    lang: str,
) -> AsyncIterator[bytes]:
    """Synthesize once after the text commit.  A failure leaves that text stored."""

    version = db.get(AgentVersion, row.agent_version_id)
    profile_id = version.voice_profile_id if version is not None else None
    if not profile_id:
        return
    external_id = ready_chat_voice(db, profile_id, settings)
    if not external_id:
        yield sse("error", {"request_id": request_id, "safe_error_code": "tts_voice_unavailable"})
        return
    try:
        result = tts_provider(settings).synthesize(
            reply,
            external_id,
            language=tts_language(lang),
        )
        if result.content_type != "audio/wav" or not result.audio_bytes:
            raise TTSProviderError("provider audio invalid", safe_code="tts_audio_invalid")
        write_atomic(
            settings.resolved_data_root,
            chat_audio_relative(row.id, request_id),
            result.audio_bytes,
        )
    except Exception as exc:
        # The assistant text is already committed.  Roll back only an open
        # transaction so the request lock can still be released.
        db.rollback()
        code = exc.safe_code if isinstance(exc, TTSProviderError) else "tts_failed"
        if not isinstance(code, str) or not code:
            code = "tts_failed"
        logger.warning(
            "Chat TTS failed conversation_id=%s turn_id=%s code=%s",
            row.id,
            request_id,
            code,
        )
        yield sse("error", {"request_id": request_id, "safe_error_code": code})
        return
    yield sse(
        "tts_ready",
        {
            "request_id": request_id,
            "audio_url": chat_audio_url(row.id, request_id),
            "voice_profile_id": profile_id,
            "content_type": "audio/wav",
        },
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
