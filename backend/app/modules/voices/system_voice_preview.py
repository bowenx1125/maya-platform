"""Controlled system-voice preview API for the flash listen gate.

Bypasses VoiceProfile.external_id and clone enrollment. Fixed scripts only;
teachers (or ops with a teacher course seat) may synthesize Cherry/Kiki via
the qwen3-tts-flash path when the trial switch is on.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, cast
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import PlatformError, forbidden, not_found, validation_failure
from app.core.models import CourseMember
from app.modules.auth.service import AuthContext
from app.modules.knowledge.files import contained_path, ensure_private_dir, write_atomic
from app.modules.voices.preview import read_pcm16_wav_bytes
from app.modules.voices.service import PREVIEW_TTL, now_utc
from app.providers.audio import AudioValidationError, validate_technical_audio
from app.providers.dashscope import FLASH_SYSTEM_VOICES, FLASH_TTS_MODEL_KEY
from app.providers.factory import tts_provider
from app.providers.tts import TTSProvider, TTSProviderError

LOGGER = logging.getLogger("maya.voices.system_preview")

SegmentId = Literal["mandarin", "cantonese", "mixed", "numbers"]
SEGMENT_IDS: tuple[SegmentId, ...] = ("mandarin", "cantonese", "mixed", "numbers")

_SAFE_SYNTH_ERRORS = frozenset(
    {
        "tts_http_rejected",
        "tts_response_invalid",
        "tts_result_url_rejected",
        "tts_result_dns_failed",
        "tts_result_download_failed",
        "tts_audio_invalid",
        "tts_timeout",
        "tts_voice_unavailable",
    }
)


@dataclass(frozen=True)
class SystemVoiceScript:
    segment_id: SegmentId
    voice: str
    language: str
    text: str
    expected_reading: str


SCRIPTS: dict[SegmentId, SystemVoiceScript] = {
    "mandarin": SystemVoiceScript(
        segment_id="mandarin",
        voice="Cherry",
        language="zh",
        text="今天是二零二六年十月十五日。欢迎来到 Maya 课堂，请认真听讲。",
        expected_reading="标准普通话；无漏字；「二零二六年十月十五日」清晰可读。",
    ),
    "cantonese": SystemVoiceScript(
        segment_id="cantonese",
        voice="Kiki",
        language="auto",
        text="今日天氣好好，我哋一齊去公園行吓啦。記得帶水同遮呀。",
        expected_reading="粤语腔（Kiki）；不可用普通话或 Cherry 冒充达标。",
    ),
    "mixed": SystemVoiceScript(
        segment_id="mixed",
        voice="Cherry",
        language="auto",
        text=(
            "Welcome to Maya classroom. 今天我们学习 machine learning 的基础概念，请跟我一起读。"
        ),
        expected_reading="中英切换自然；machine learning 按英文词可读。",
    ),
    "numbers": SystemVoiceScript(
        segment_id="numbers",
        voice="Cherry",
        language="zh",
        text="日期是2026年10月15日，金额是￥1,234.56，订单编号是001203。",
        expected_reading=(
            "「2026年10月15日」→二零二六年十月十五日；"
            "「￥1,234.56」→一千二百三十四点五六元；"
            "「001203」→零零一二零三（前导零逐位保留）。"
        ),
    ),
}


@dataclass(frozen=True)
class SystemVoicePreviewResult:
    request_id: str
    segment_id: SegmentId
    voice: str
    language: str
    text: str
    expected_reading: str
    playback_url: str
    expires_at: datetime
    provider_request_id: str | None
    deduplicated: bool


def require_system_voice_teacher(db: Session, context: AuthContext) -> None:
    """Refuse anyone who is not a teacher on at least one course."""

    role = db.scalar(
        select(CourseMember.role)
        .where(
            CourseMember.user_id == context.user.id,
            CourseMember.role == "teacher",
        )
        .limit(1)
    )
    if role != "teacher":
        raise forbidden("Teacher access is required for system voice previews.")


def list_system_voice_scripts() -> list[SystemVoiceScript]:
    return [SCRIPTS[segment_id] for segment_id in SEGMENT_IDS]


def _preview_root(data_root: Path) -> Path:
    return data_root / "system" / "voices" / "system-previews"


def _content_key(script: SystemVoiceScript) -> str:
    payload = (
        f"{script.segment_id}|{script.voice}|{script.language}|{script.text}|{FLASH_TTS_MODEL_KEY}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _index_path(data_root: Path) -> Path:
    return _preview_root(data_root) / "_index.json"


def _entry_path(data_root: Path, request_id: str) -> Path:
    return _preview_root(data_root) / f"{request_id}.json"


def _wav_relative(request_id: str) -> str:
    return f"system/voices/system-previews/{request_id}.wav"


def _read_index(data_root: Path) -> dict[str, str]:
    path = _index_path(data_root)
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {str(key): str(value) for key, value in raw.items() if isinstance(value, str)}


def _write_index(data_root: Path, index: dict[str, str]) -> None:
    ensure_private_dir(_preview_root(data_root))
    path = _index_path(data_root)
    path.write_text(json.dumps(index, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)


def _load_entry(data_root: Path, request_id: str) -> dict[str, object] | None:
    path = _entry_path(data_root, request_id)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def _parse_expires(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


def _expire_entry(data_root: Path, request_id: str, entry: dict[str, object]) -> None:
    relative = entry.get("relative_path")
    if isinstance(relative, str) and relative:
        try:
            path = contained_path(data_root, relative)
            if path.exists() or path.is_symlink():
                path.unlink()
        except (ValueError, OSError):
            pass
    try:
        meta = _entry_path(data_root, request_id)
        if meta.exists() or meta.is_symlink():
            meta.unlink()
    except OSError:
        pass
    index = _read_index(data_root)
    content_key = entry.get("content_key")
    if isinstance(content_key, str) and index.get(content_key) == request_id:
        index.pop(content_key, None)
        _write_index(data_root, index)


def _active_entry(data_root: Path, request_id: str) -> tuple[dict[str, object], Path] | None:
    entry = _load_entry(data_root, request_id)
    if entry is None:
        return None
    expires = _parse_expires(entry.get("expires_at"))
    relative = entry.get("relative_path")
    if (
        entry.get("state") != "active"
        or expires is None
        or expires <= now_utc()
        or not isinstance(relative, str)
        or not relative
    ):
        _expire_entry(data_root, request_id, entry)
        return None
    try:
        path = contained_path(data_root, relative)
    except (ValueError, OSError):
        _expire_entry(data_root, request_id, entry)
        return None
    if path.is_symlink() or not path.is_file():
        _expire_entry(data_root, request_id, entry)
        return None
    return entry, path


def _result_from_entry(entry: dict[str, object], *, deduplicated: bool) -> SystemVoicePreviewResult:
    request_id = str(entry["request_id"])
    segment_id = str(entry["segment_id"])
    if segment_id not in SCRIPTS:
        raise not_found()
    expires = _parse_expires(entry.get("expires_at"))
    if expires is None:
        raise not_found()
    provider_request_id = entry.get("provider_request_id")
    return SystemVoicePreviewResult(
        request_id=request_id,
        segment_id=segment_id,
        voice=str(entry["voice"]),
        language=str(entry["language"]),
        text=str(entry["text"]),
        expected_reading=str(entry["expected_reading"]),
        playback_url=f"/api/v1/system-voice-previews/{request_id}/media",
        expires_at=expires,
        provider_request_id=(
            str(provider_request_id) if isinstance(provider_request_id, str) else None
        ),
        deduplicated=deduplicated,
    )


def resolve_segment_id(raw: str) -> SegmentId | Literal["all"]:
    value = raw.strip().lower()
    if value == "all":
        return "all"
    if value in SCRIPTS:
        return value
    raise validation_failure(
        "Unknown system voice segment.",
        code="invalid_segment",
    )


def create_system_voice_preview(
    db: Session,
    context: AuthContext,
    settings: Settings,
    segment_id: str,
    *,
    provider: TTSProvider | None = None,
) -> SystemVoicePreviewResult | list[SystemVoicePreviewResult]:
    """Synthesize one fixed script or all four; dedupe active identical content."""

    require_system_voice_teacher(db, context)
    resolved = resolve_segment_id(segment_id)
    if resolved == "all":
        return [
            cast(
                SystemVoicePreviewResult,
                create_system_voice_preview(db, context, settings, item, provider=provider),
            )
            for item in SEGMENT_IDS
        ]

    if not settings.tts_qwen3_flash_enabled:
        LOGGER.warning("System voice preview refused flash_disabled segment_id=%s", resolved)
        raise PlatformError(
            "provider_unavailable",
            "System voice preview requires the flash trial switch.",
            503,
        )

    script = SCRIPTS[resolved]
    if script.voice not in FLASH_SYSTEM_VOICES:
        # Fixed table must stay on the flash allowlist; refuse closed.
        raise PlatformError(
            "provider_unavailable",
            "The configured system voice is unavailable.",
            503,
        )

    data_root = settings.resolved_data_root
    ensure_private_dir(_preview_root(data_root))
    content_key = _content_key(script)
    index = _read_index(data_root)
    existing_id = index.get(content_key)
    if existing_id:
        active = _active_entry(data_root, existing_id)
        if active is not None:
            return _result_from_entry(active[0], deduplicated=True)
        index.pop(content_key, None)
        _write_index(data_root, index)

    try:
        tts = provider or tts_provider(settings)
    except (RuntimeError, OSError) as exc:
        LOGGER.warning(
            "System voice preview failed segment_id=%s safe_code=tts_configuration_unavailable",
            resolved,
        )
        raise PlatformError(
            "provider_unavailable",
            "The voice service is temporarily unavailable.",
            503,
        ) from exc

    try:
        output = tts.synthesize(
            script.text,
            script.voice,
            language=script.language,
            target_model_key=FLASH_TTS_MODEL_KEY,
        )
        raw = read_pcm16_wav_bytes(output.audio_bytes)
        validate_technical_audio(raw)
    except (TTSProviderError, AudioValidationError, OSError) as exc:
        code = getattr(exc, "safe_code", None)
        if not isinstance(code, str) or code not in _SAFE_SYNTH_ERRORS:
            code = "tts_audio_invalid" if isinstance(exc, AudioValidationError) else "tts_failed"
        LOGGER.warning("System voice preview failed segment_id=%s safe_code=%s", resolved, code)
        raise PlatformError(
            "provider_unavailable",
            "The system voice preview could not be generated.",
            503,
        ) from exc

    request_id = str(uuid4())
    relative_path = _wav_relative(request_id)
    timestamp = now_utc()
    expires_at = timestamp + PREVIEW_TTL
    try:
        digest, size = write_atomic(data_root, relative_path, raw)
        entry = {
            "request_id": request_id,
            "segment_id": script.segment_id,
            "voice": script.voice,
            "language": script.language,
            "text": script.text,
            "expected_reading": script.expected_reading,
            "content_key": content_key,
            "relative_path": relative_path,
            "sha256": digest,
            "size_bytes": size,
            "state": "active",
            "created_by": context.user.id,
            "created_at": timestamp.isoformat(),
            "expires_at": expires_at.isoformat(),
            "provider_request_id": output.request_id,
            "target_model_key": FLASH_TTS_MODEL_KEY,
        }
        meta_path = _entry_path(data_root, request_id)
        meta_path.write_text(
            json.dumps(entry, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        meta_path.chmod(0o600)
        index[content_key] = request_id
        _write_index(data_root, index)
    except Exception as exc:
        try:
            path = contained_path(data_root, relative_path)
            if path.exists() or path.is_symlink():
                path.unlink()
        except (ValueError, OSError):
            pass
        LOGGER.warning(
            "System voice preview failed segment_id=%s safe_code=voice_preview_storage_failed",
            resolved,
        )
        raise PlatformError(
            "file_operation_failed",
            "The system voice preview could not be stored.",
            503,
        ) from exc

    return _result_from_entry(entry, deduplicated=False)


def media_path_for_system_voice_preview(
    db: Session,
    context: AuthContext,
    request_id: str,
    settings: Settings,
) -> tuple[Path, str]:
    """Authorize a teacher and resolve one active system-voice preview WAV."""

    require_system_voice_teacher(db, context)
    active = _active_entry(settings.resolved_data_root, request_id)
    if active is None:
        raise not_found()
    return active[1], "audio/wav"
