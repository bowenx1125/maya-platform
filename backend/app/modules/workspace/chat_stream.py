"""SSE chat events: deltas, one full-text commit, then a single TTS URL."""

from __future__ import annotations

import asyncio
import contextvars
import io
import json
import threading
import wave
from collections.abc import AsyncIterator, Callable, Iterator
from concurrent import futures
from contextlib import contextmanager
from logging import getLogger
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.db import Database
from app.core.errors import PlatformError, not_found
from app.core.models import Agent, AgentVersion, VoiceProfile
from app.modules.knowledge.files import FileBoundaryError, contained_path, write_atomic
from app.modules.voices.service import baseline_configured_voice_id, ready_chat_voice
from app.providers.factory import tts_provider
from app.providers.tts import TTSProviderError, han_at_least_latin, spoken_text

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


def synthesis_language(lang: str, spoken: str) -> str:
    """DashScope language for one spoken reply.

    Han characters at least as numerous as Latin letters select Chinese.
    Otherwise the requested chat language is used, so one Han character in
    an English sentence stays English when the request says en.
    """

    requested = tts_language(lang)
    if han_at_least_latin(spoken):
        return "zh"
    return requested


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


def wav_duration_ms(source: bytes | Path) -> int | None:
    """Duration from the WAV header. Invalid audio returns None."""

    try:
        if isinstance(source, Path):
            with wave.open(str(source), "rb") as stream:
                rate = stream.getframerate()
                frames = stream.getnframes()
        else:
            with wave.open(io.BytesIO(source), "rb") as stream:
                rate = stream.getframerate()
                frames = stream.getnframes()
    except (OSError, EOFError, wave.Error):
        return None
    if rate <= 0 or frames < 0:
        return None
    return int(round(frames * 1000 / rate))


def _lexical_chat_path(settings: Settings, relative: str) -> Path | None:
    """A path inside the data root that is not itself a symlink.

    ``contained_path`` resolves links, so the symlink check has to happen on
    the lexical path first. A link is not a playable file and is not deleted.
    """

    lexical = settings.resolved_data_root / relative
    if lexical.is_symlink():
        return None
    try:
        path = contained_path(settings.resolved_data_root, relative)
    except FileBoundaryError:
        logger.warning("Chat audio path rejected code=file_operation_failed")
        return None
    return path


def turn_audio(
    settings: Settings, conversation_id: str, turn_id: str
) -> tuple[str | None, int | None]:
    """Owned playback URL and header duration, or nulls when no playable WAV."""

    path = _lexical_chat_path(settings, chat_audio_relative(conversation_id, turn_id))
    if path is None or not path.is_file():
        return None, None
    duration = wav_duration_ms(path)
    if duration is None:
        logger.warning(
            "Chat audio duration unreadable conversation_id=%s turn_id=%s code=tts_audio_invalid",
            conversation_id,
            turn_id,
        )
        return None, None
    return chat_audio_url(conversation_id, turn_id), duration


def remove_chat_audio(settings: Settings, conversation_id: str) -> None:
    """Delete one conversation's WAV directory after the row is gone.

    Symlinks are left in place so cleanup cannot follow a link out of this
    directory. Only regular .wav files are unlinked, then the directory is
    removed when nothing remains.
    """

    directory = _lexical_chat_path(settings, f"chat-audio/{conversation_id}")
    if directory is None or not directory.is_dir():
        return
    try:
        for child in directory.iterdir():
            if child.is_symlink() or not child.is_file() or child.suffix.lower() != ".wav":
                continue
            child.unlink()
        if any(directory.iterdir()):
            logger.warning(
                "Chat audio cleanup left files conversation_id=%s code=file_operation_failed",
                conversation_id,
            )
            return
        directory.rmdir()
    except OSError:
        logger.warning(
            "Chat audio cleanup failed conversation_id=%s code=file_operation_failed",
            conversation_id,
        )


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


def _call_with_context(
    context: contextvars.Context, function: Callable[..., object], args: tuple[object, ...]
) -> object:
    return context.run(function, *args)


# Independent of the request task. Cancelling the SSE task must not drop the
# worker result: the provider row is settled only after this future finishes.
_CHAT_POOL = futures.ThreadPoolExecutor(thread_name_prefix="maya-chat")


def _submit(function: Callable[..., object], *args: object) -> futures.Future[object]:
    """Run in a worker thread whose future stays live if this request is cancelled.

    ``asyncio.to_thread`` is tied to the request task. Cancelling that task
    drops the result while the thread can still mark the provider call
    accepted. This future completes only when the thread returns, so the
    operation is settled after that write and not before it.
    """

    context = contextvars.copy_context()
    return _CHAT_POOL.submit(_call_with_context, context, function, args)


def _when_workers_done(workers: list[futures.Future[object]], callback: Callable[[], None]) -> None:
    pending = [worker for worker in workers if not worker.done()]
    if not pending:
        callback()
        return
    remaining = {"count": len(pending)}
    gate = threading.Lock()

    def _finished(worker: futures.Future[object]) -> None:
        try:
            worker.exception()
        except Exception:
            logger.warning("Chat worker failed before cancel settle code=chat_cancelled")
        with gate:
            remaining["count"] -= 1
            last = remaining["count"] == 0
        if not last:
            return
        try:
            callback()
        except Exception:
            logger.warning("Chat cancel settle failed code=chat_cancelled")

    for worker in pending:
        worker.add_done_callback(_finished)


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
    A client disconnect fails a still-pending turn and closes its provider
    operation once the in-flight worker returns.
    """

    released = False
    outcome = "open"
    workers: list[futures.Future[object]] = []

    def release() -> None:
        nonlocal released
        if released or not created:
            return
        with _segment(database, settings) as db:
            from .chat import release_chat_request

            release_chat_request(db, conversation_id, request_id)
        released = True

    def abandon() -> None:
        from .chat import mark_abandoned_turn, settle_abandoned_operations

        try:
            mark_abandoned_turn(
                database,
                conversation_id=conversation_id,
                request_id=request_id,
                code="chat_cancelled",
            )
        except Exception:
            logger.warning(
                "Chat cancel close failed conversation_id=%s turn_id=%s code=chat_cancelled",
                conversation_id,
                request_id,
            )

        def _settle() -> None:
            settle_abandoned_operations(
                database,
                conversation_id=conversation_id,
                request_id=request_id,
                code="chat_cancelled",
            )

        _when_workers_done(workers, _settle)

    try:
        if not created:
            outcome = "replay"
            yield _replay_event(database, settings, conversation_id, request_id)
            return
        reply_worker = _submit(
            _reply_segment,
            database,
            settings,
            conversation_id,
            request_id,
            message,
            lang,
        )
        workers.append(reply_worker)
        try:
            reply, sources, operation_id = cast(
                tuple[str, list[ChatSource], str | None],
                await asyncio.wrap_future(reply_worker),
            )
        except Exception as exc:
            outcome = "failed"
            code = _failure_code(database, settings, conversation_id, request_id, exc)
            yield sse("error", {"request_id": request_id, "safe_error_code": code})
            return
        for seq, text in enumerate(text_deltas(reply), start=1):
            yield sse("delta", {"request_id": request_id, "seq": seq, "text": text})
        store_worker = _submit(
            _store_segment,
            database,
            settings,
            request_id,
            reply,
            sources,
            operation_id,
        )
        workers.append(store_worker)
        try:
            revision, stored_sources = cast(
                tuple[int, list[dict[str, Any]]],
                await asyncio.wrap_future(store_worker),
            )
        except Exception as exc:
            outcome = "failed"
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
        outcome = "done"
    finally:
        if created and outcome == "open":
            abandon()
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

    spoken = spoken_text(reply)
    if not spoken.strip():
        yield sse("tts_speech_empty", {"request_id": request_id})
        return
    voice = await asyncio.to_thread(_voice_segment, database, settings, conversation_id)
    if voice is None:
        return
    profile_id, external_id = voice
    if not external_id:
        yield sse("error", {"request_id": request_id, "safe_error_code": "tts_voice_unavailable"})
        return
    try:
        duration_ms = await asyncio.to_thread(
            _synthesize_segment,
            settings,
            conversation_id,
            request_id,
            spoken,
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
            "audio_duration_ms": duration_ms,
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
        if version is None:
            return None
        # A voice saved on the agent wins. Baseline characters cannot be
        # edited, so an operator map is the next choice, then the system
        # fallback. A bound voice that is not ready stays an error.
        if version.voice_profile_id:
            return (
                version.voice_profile_id,
                ready_chat_voice(db, version.voice_profile_id, settings),
            )
        agent = db.get(Agent, version.agent_id)
        group_id = agent.group_id if agent is not None else None
        configured = baseline_configured_voice_id(settings, version.agent_id)
        fallback_id = settings.fallback_voice_profile_id
        ordered: list[tuple[str, str]] = []
        if configured:
            ordered.append(("configured", configured))
        if fallback_id and fallback_id != configured:
            ordered.append(("fallback", fallback_id))
        for kind, profile_id in ordered:
            profile = db.get(VoiceProfile, profile_id)
            if profile is None or profile.status != "ready":
                continue
            # A configured id may be a ready voice in the character's group
            # or a system profile. The platform fallback is system-only, the
            # same rule debate setup already uses.
            if kind == "configured":
                allowed = (profile.scope == "group" and profile.group_id == group_id) or (
                    profile.scope == "system" and profile.group_id is None
                )
            else:
                allowed = profile.scope == "system" and profile.group_id is None
            if not allowed:
                continue
            external_id = ready_chat_voice(db, profile_id, settings)
            if external_id:
                return profile_id, external_id
        return None


def _synthesize_segment(
    settings: Settings,
    conversation_id: str,
    request_id: str,
    reply: str,
    external_id: str,
    lang: str,
) -> int:
    spoken = spoken_text(reply)
    if not spoken.strip():
        raise TTSProviderError("speech is empty", safe_code="tts_speech_empty")
    result = tts_provider(settings).synthesize(
        spoken,
        external_id,
        language=synthesis_language(lang, spoken),
    )
    if result.content_type != "audio/wav" or not result.audio_bytes:
        raise TTSProviderError("provider audio invalid", safe_code="tts_audio_invalid")
    duration_ms = wav_duration_ms(result.audio_bytes)
    if duration_ms is None:
        raise TTSProviderError("provider audio invalid", safe_code="tts_audio_invalid")
    write_atomic(
        settings.resolved_data_root,
        chat_audio_relative(conversation_id, request_id),
        result.audio_bytes,
    )
    return duration_ms


def chat_audio_path(settings: Settings, conversation_id: UUID, request_id: UUID) -> Path:
    path = _lexical_chat_path(settings, chat_audio_relative(str(conversation_id), str(request_id)))
    if path is None or not path.is_file():
        raise not_found()
    if wav_duration_ms(path) is None:
        logger.warning(
            "Chat audio unreadable conversation_id=%s turn_id=%s code=tts_audio_invalid",
            conversation_id,
            request_id,
        )
        raise not_found()
    return path
