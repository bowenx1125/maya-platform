"""Private, same-origin playback audio and current-only media tickets."""

from __future__ import annotations

import hashlib
import io
import re
import secrets
import threading
import wave
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from app.core.errors import PlatformError
from app.core.llm_admission import llm_admission_slot
from app.modules.knowledge.files import (
    contained_path,
    promote_atomic,
    stage_atomic,
    verify_staged,
    write_atomic,
)
from app.providers.tts import (
    MockTTSProvider,
    TTSProvider,
    TTSProviderError,
    TTSProviderUnavailableError,
    TTSResult,
)

MEDIA_TICKET_TTL = timedelta(minutes=5)
MEDIA_TICKET_GRACE = timedelta(seconds=60)
MEDIA_TICKET_BYTES = 32
_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")
_SAFE_UUID = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89aAbB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _uuid_part(value: str | UUID) -> str:
    text = str(value)
    if not _SAFE_UUID.fullmatch(text):
        raise ValueError("invalid UUID path component")
    return text


def audio_relative_path(course_id: str | UUID, debate_id: str | UUID, turn_id: str | UUID) -> str:
    """Construct a server-owned relative path from validated UUIDs only."""

    return (
        f"courses/{_uuid_part(course_id)}/current-debate-audio/"
        f"{_uuid_part(debate_id)}/{_uuid_part(turn_id)}.wav"
    )


def audio_staging_relative_path(
    course_id: str | UUID,
    debate_id: str | UUID,
    turn_id: str | UUID,
    operation_id: str | UUID,
) -> str:
    """Construct a unique per-operation WAV staging path."""

    return (
        f"staging/debate-turn-tts/{_uuid_part(course_id)}/"
        f"{_uuid_part(debate_id)}/{_uuid_part(turn_id)}/{_uuid_part(operation_id)}.wav"
    )


@dataclass(frozen=True)
class AudioMetadata:
    course_id: str
    debate_id: str
    turn_id: str
    relative_path: str
    sha256: str
    size_bytes: int
    duration_ms: int
    modified_at: datetime


@dataclass(frozen=True)
class StagedAudio:
    """One provider WAV held outside the canonical playback path.

    The operation UUID is part of the lexical path.  A staged result can
    therefore be discarded or recovered by its exact journal row without
    ever guessing which worker owns a canonical turn file.
    """

    operation_id: str
    course_id: str
    debate_id: str
    turn_id: str
    relative_path: str
    target_relative_path: str
    sha256: str
    size_bytes: int
    duration_ms: int


@dataclass(frozen=True)
class ByteRange:
    start: int
    end: int

    @property
    def length(self) -> int:
        return self.end - self.start + 1


@dataclass(frozen=True)
class AudioResponse:
    status_code: Literal[200, 206, 416]
    body: bytes
    etag: str
    headers: dict[str, str]


class AudioStore:
    """Durable current-debate WAV store with no path supplied by the browser."""

    def __init__(self, data_root: Path, *, tts_provider: TTSProvider | None = None) -> None:
        self.data_root = data_root
        self.tts_provider = tts_provider or MockTTSProvider()
        self._metadata: dict[tuple[str, str], AudioMetadata] = {}
        self._lock = threading.RLock()
        self._load_existing()

    def _load_existing(self) -> None:
        """Rebuild the metadata index from the durable audio tree on restart.

        StoredFile/turn rows remain the authoritative database metadata in the
        full application; scanning the typed, UUID-only path here makes the
        file service safe and immediately usable during process restart before
        SQLAlchemy has rehydrated its identity map.  No arbitrary user path is
        accepted and malformed entries are ignored rather than traversed.
        """

        root = self.data_root / "courses"
        if not root.is_dir() or root.is_symlink():
            return
        for course_dir in root.iterdir():
            if course_dir.is_symlink() or not _SAFE_UUID.fullmatch(course_dir.name):
                continue
            audio_root = course_dir / "current-debate-audio"
            if audio_root.is_symlink() or not audio_root.is_dir():
                continue
            for debate_dir in audio_root.iterdir():
                if debate_dir.is_symlink() or not _SAFE_UUID.fullmatch(debate_dir.name):
                    continue
                for path in debate_dir.iterdir():
                    if (
                        path.is_symlink()
                        or path.suffix.lower() != ".wav"
                        or not _SAFE_UUID.fullmatch(path.stem)
                    ):
                        continue
                    try:
                        raw = path.read_bytes()
                        digest = hashlib.sha256(raw).hexdigest()
                        stat = path.stat()
                        metadata = AudioMetadata(
                            course_id=course_dir.name,
                            debate_id=debate_dir.name,
                            turn_id=path.stem,
                            relative_path=str(path.relative_to(self.data_root)),
                            sha256=digest,
                            size_bytes=stat.st_size,
                            duration_ms=wav_duration_ms(raw),
                            modified_at=datetime.fromtimestamp(stat.st_mtime, UTC),
                        )
                    except (OSError, TTSProviderError, ValueError, wave.Error):
                        continue
                    self._metadata[(metadata.debate_id, metadata.turn_id)] = metadata

    def relative_path(self, course_id: str, debate_id: str, turn_id: str) -> str:
        return audio_relative_path(course_id, debate_id, turn_id)

    def path_for(self, relative_path: str) -> Path:
        # contained_path resolves symlinks and rejects escapes.  A final
        # symlink is refused by all read/write methods below as an additional
        # defense against a stale local data directory.
        return contained_path(self.data_root, relative_path)

    def _non_symlink_path(self, relative_path: str) -> Path | None:
        """Return an exact path only when no component is a symlink.

        ``contained_path`` intentionally resolves links before checking
        containment.  That is the right boundary for ordinary file access,
        but replay retention has a stricter contract: a StoredFile must point
        at the exact canonical WAV and the bytes must not be reached through a
        link.  Walk the lexical path first, then retain the containment check
        as a second defence.
        """

        try:
            if not relative_path or Path(relative_path).is_absolute():
                return None
            base = self.data_root.absolute()
            if base.is_symlink():
                return None
            candidate = base / relative_path
            candidate.relative_to(base)
            current = candidate
            while current != base:
                if current.is_symlink():
                    return None
                current = current.parent
            resolved = contained_path(self.data_root, relative_path)
            if resolved != candidate.resolve(strict=False):
                return None
            return candidate
        except (OSError, TypeError, ValueError):
            return None

    def _validated_file_snapshot(
        self,
        *,
        course_id: str,
        debate_id: str,
        turn_id: str,
        relative_path: str,
        expected_sha256: str | None,
        expected_size_bytes: int | None,
        expected_duration_ms: int | None = None,
    ) -> tuple[AudioMetadata, bytes] | None:
        """Return metadata and bytes from one validated file read.

        The in-memory metadata index is deliberately not consulted here.  A
        caller must provide the database facts (hash/size/path); this method
        reads the canonical path, rejects symlink components, verifies the
        digest and size, and decodes the WAV.  Returning the bytes from that
        same read prevents a path replacement between validation and response
        construction from serving unvalidated content.
        """

        try:
            canonical = self.relative_path(course_id, debate_id, turn_id)
        except (TypeError, ValueError):
            return None
        if relative_path != canonical:
            return None
        if expected_sha256 is None or expected_size_bytes is None:
            return None
        if not isinstance(expected_sha256, str) or len(expected_sha256) != 64:
            return None
        try:
            expected_size = int(expected_size_bytes)
        except (TypeError, ValueError):
            return None
        if expected_size < 0:
            return None
        path = self._non_symlink_path(relative_path)
        if path is None or path.is_symlink() or not path.is_file():
            return None
        try:
            raw = path.read_bytes()
            stat = path.stat()
            if stat.st_size != expected_size or len(raw) != expected_size:
                return None
            digest = hashlib.sha256(raw).hexdigest()
            if digest != expected_sha256:
                return None
            duration = wav_duration_ms(raw)
            if expected_duration_ms is not None and duration != int(expected_duration_ms):
                return None
        except (OSError, TypeError, ValueError, TTSProviderError, wave.Error):
            return None
        metadata = AudioMetadata(
            course_id=course_id,
            debate_id=debate_id,
            turn_id=turn_id,
            relative_path=relative_path,
            sha256=digest,
            size_bytes=expected_size,
            duration_ms=duration,
            modified_at=datetime.fromtimestamp(stat.st_mtime, UTC),
        )
        return metadata, raw

    def validate_file(
        self,
        *,
        course_id: str,
        debate_id: str,
        turn_id: str,
        relative_path: str,
        expected_sha256: str | None,
        expected_size_bytes: int | None,
        expected_duration_ms: int | None = None,
    ) -> AudioMetadata | None:
        """Validate durable StoredFile facts and return fresh byte metadata."""

        snapshot = self._validated_file_snapshot(
            course_id=course_id,
            debate_id=debate_id,
            turn_id=turn_id,
            relative_path=relative_path,
            expected_sha256=expected_sha256,
            expected_size_bytes=expected_size_bytes,
            expected_duration_ms=expected_duration_ms,
        )
        return snapshot[0] if snapshot is not None else None

    def rehydrate(self, metadata: AudioMetadata) -> None:
        """Cache metadata only after a caller has verified durable facts."""

        with self._lock:
            self._metadata[(metadata.debate_id, metadata.turn_id)] = metadata

    def _synthesize(
        self,
        speech: str,
        voice_token: str,
        *,
        language: str,
        target_model_key: str | None,
    ) -> TTSResult:
        """One TTS provider call, holding an LLM admission slot like a model call.

        2026-10-19: Debate speech was the one provider call outside global
        pressure protection, so a busy lesson could crowd out assessment
        scoring and chat. A real provider call now waits for a slot in the
        lowest ("llm") class; the transport-style wait is bounded by the
        shared deadline. A retryable refusal is ``tts_provider_unavailable``:
        the turn plays as text and its audio can be regenerated later, so the
        lesson never stalls on it. The local Mock makes no outbound call.
        """

        if getattr(self.tts_provider, "key", "mock") == "mock":
            return self.tts_provider.synthesize(
                speech, voice_token, language=language, target_model_key=target_model_key
            )
        try:
            with llm_admission_slot():
                return self.tts_provider.synthesize(
                    speech, voice_token, language=language, target_model_key=target_model_key
                )
        except PlatformError as exc:
            if not exc.details.get("retryable"):
                raise
            raise TTSProviderUnavailableError(
                "speech admission refused", safe_code="tts_provider_unavailable"
            ) from exc

    def synthesize_and_store(
        self,
        *,
        course_id: str,
        debate_id: str,
        turn_id: str,
        speech: str,
        voice_token: str,
        language: str = "en",
        target_model_key: str | None = None,
    ) -> AudioMetadata:
        """Use the injected (Mock by default) TTS provider and atomically store WAV."""

        if not speech.strip():
            raise TTSProviderError("speech is empty")
        # The caller supplies a server-side kind/profile token; it never leaves
        # the store or appears in a public DTO. The model is the profile's
        # own target, so a preset is not sent to the clone model.
        result = self._synthesize(
            speech,
            voice_token,
            language=language,
            target_model_key=target_model_key,
        )
        raw = result.audio_bytes
        relative = self.relative_path(course_id, debate_id, turn_id)
        digest, size = write_atomic(self.data_root, relative, raw)
        duration = wav_duration_ms(raw)
        metadata = AudioMetadata(
            course_id=course_id,
            debate_id=debate_id,
            turn_id=turn_id,
            relative_path=relative,
            sha256=digest,
            size_bytes=size,
            duration_ms=duration,
            modified_at=datetime.fromtimestamp(self.path_for(relative).stat().st_mtime, UTC),
        )
        with self._lock:
            self._metadata[(debate_id, turn_id)] = metadata
        return metadata

    def stage_synthesis(
        self,
        *,
        course_id: str,
        debate_id: str,
        turn_id: str,
        speech: str,
        voice_token: str,
        language: str = "en",
        operation_id: str | UUID | None = None,
        target_model_key: str | None = None,
    ) -> StagedAudio:
        """Synthesize one WAV into a unique journal-owned staging file.

        The canonical path is intentionally untouched.  Promotion is a
        separate operation performed only after the caller wins its database
        revision and Job claim fences.
        """

        if not speech.strip():
            raise TTSProviderError("speech is empty")
        operation = _uuid_part(operation_id or uuid4())
        relative = audio_staging_relative_path(course_id, debate_id, turn_id, operation)
        target = self.relative_path(course_id, debate_id, turn_id)
        path = self._non_symlink_path(relative)
        if path is None or path.exists() or path.is_symlink():
            raise TTSProviderError("audio staging path is unavailable")
        result = self._synthesize(
            speech,
            voice_token,
            language=language,
            target_model_key=target_model_key,
        )
        raw = result.audio_bytes
        if not isinstance(raw, bytes) or not raw:
            raise TTSProviderError("audio output is empty")
        duration = wav_duration_ms(raw)
        digest, size = stage_atomic(self.data_root, relative, raw)
        staged = self._non_symlink_path(relative)
        if staged is None or staged.is_symlink() or not staged.is_file():
            self.discard_staged_audio(relative)
            raise TTSProviderError("audio staging path is unavailable")
        try:
            verify_staged(self.data_root, relative, digest, size)
        except Exception:
            self.discard_staged_audio(relative)
            raise
        return StagedAudio(
            operation_id=operation,
            course_id=_uuid_part(course_id),
            debate_id=_uuid_part(debate_id),
            turn_id=_uuid_part(turn_id),
            relative_path=relative,
            target_relative_path=target,
            sha256=digest,
            size_bytes=size,
            duration_ms=duration,
        )

    def promote_staged_audio(self, staged: StagedAudio) -> AudioMetadata:
        """Promote one verified staging file to its empty canonical path."""

        if not isinstance(staged, StagedAudio):
            raise TypeError("staged audio has the wrong type")
        expected_target = self.relative_path(staged.course_id, staged.debate_id, staged.turn_id)
        if staged.target_relative_path != expected_target:
            raise ValueError("audio promotion target is outside the turn boundary")
        source = self._non_symlink_path(staged.relative_path)
        target = self._non_symlink_path(staged.target_relative_path)
        if source is None or target is None or source.is_symlink() or target.is_symlink():
            raise ValueError("audio promotion path cannot be a symlink")
        if source == target or not source.is_file():
            raise ValueError("audio staging file is unavailable")
        if target.exists():
            raise FileExistsError("audio promotion target is already occupied")
        verify_staged(self.data_root, staged.relative_path, staged.sha256, staged.size_bytes)
        promote_atomic(self.data_root, staged.relative_path, staged.target_relative_path)
        promoted = self._non_symlink_path(staged.target_relative_path)
        if promoted is None or promoted.is_symlink() or not promoted.is_file():
            raise TTSProviderError("audio promotion output is unavailable")
        raw = promoted.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest != staged.sha256 or len(raw) != staged.size_bytes:
            raise TTSProviderError("audio promotion output changed")
        duration = wav_duration_ms(raw)
        if duration != staged.duration_ms:
            raise TTSProviderError("audio promotion duration changed")
        metadata = AudioMetadata(
            course_id=staged.course_id,
            debate_id=staged.debate_id,
            turn_id=staged.turn_id,
            relative_path=staged.target_relative_path,
            sha256=digest,
            size_bytes=len(raw),
            duration_ms=duration,
            modified_at=datetime.fromtimestamp(promoted.stat().st_mtime, UTC),
        )
        with self._lock:
            self._metadata[(staged.debate_id, staged.turn_id)] = metadata
        return metadata

    def discard_staged_audio(self, relative_path: str | StagedAudio) -> None:
        """Remove exactly one stage file and no sibling or canonical file."""

        relative = (
            relative_path.relative_path if isinstance(relative_path, StagedAudio) else relative_path
        )
        path = self._non_symlink_path(relative)
        if path is None or path.is_symlink() or not path.is_file():
            return
        path.unlink(missing_ok=True)

    def remove_promoted_audio_if_owned(self, staged: StagedAudio) -> bool:
        """Remove a canonical file only when its bytes still match this stage."""

        if not isinstance(staged, StagedAudio):
            raise TypeError("staged audio has the wrong type")
        path = self._non_symlink_path(staged.target_relative_path)
        if path is None or path.is_symlink() or not path.is_file():
            return False
        try:
            raw = path.read_bytes()
        except OSError:
            return False
        if hashlib.sha256(raw).hexdigest() != staged.sha256 or len(raw) != staged.size_bytes:
            return False
        path.unlink(missing_ok=True)
        with self._lock:
            current = self._metadata.get((staged.debate_id, staged.turn_id))
            if current is not None and current.sha256 == staged.sha256:
                self._metadata.pop((staged.debate_id, staged.turn_id), None)
        return True

    def store_bytes(
        self,
        *,
        course_id: str,
        debate_id: str,
        turn_id: str,
        raw: bytes,
    ) -> AudioMetadata:
        """Store already validated Mock/test bytes without a provider call."""

        relative = self.relative_path(course_id, debate_id, turn_id)
        digest, size = write_atomic(self.data_root, relative, raw)
        metadata = AudioMetadata(
            course_id=course_id,
            debate_id=debate_id,
            turn_id=turn_id,
            relative_path=relative,
            sha256=digest,
            size_bytes=size,
            duration_ms=wav_duration_ms(raw),
            modified_at=datetime.fromtimestamp(self.path_for(relative).stat().st_mtime, UTC),
        )
        with self._lock:
            self._metadata[(debate_id, turn_id)] = metadata
        return metadata

    def metadata(self, debate_id: str, turn_id: str) -> AudioMetadata | None:
        with self._lock:
            metadata = self._metadata.get((debate_id, turn_id))
        if metadata is None:
            return None
        path = self._non_symlink_path(metadata.relative_path)
        if path is None or path.is_symlink() or not path.is_file():
            return None
        return metadata

    def read(self, debate_id: str, turn_id: str) -> bytes | None:
        metadata = self.metadata(debate_id, turn_id)
        if metadata is None:
            return None
        path = self._non_symlink_path(metadata.relative_path)
        if path is None:
            return None
        try:
            return path.read_bytes()
        except OSError:
            return None

    def remove_debate(self, debate_id: str) -> None:
        """Remove only this debate's exact files; never infer a parent deletion."""

        with self._lock:
            for key in [key for key in self._metadata if key[0] == debate_id]:
                self._metadata.pop(key, None)
        if not _SAFE_UUID.fullmatch(debate_id):
            return
        # The process-local index is only a cache.  On a fresh service it is
        # empty even when the durable debate directory still has bytes, so
        # cleanup must resolve the exact UUID directory independently.
        course_root = self.data_root / "courses"
        if not course_root.is_dir() or course_root.is_symlink():
            return
        for course_dir in course_root.iterdir():
            if course_dir.is_symlink() or not _SAFE_UUID.fullmatch(course_dir.name):
                continue
            debate_root = course_dir / "current-debate-audio" / debate_id
            if debate_root.is_symlink() or not debate_root.is_dir():
                continue
            for path in debate_root.iterdir():
                if path.is_symlink():
                    path.unlink(missing_ok=True)
                elif path.is_file():
                    path.unlink()
            try:
                debate_root.rmdir()
            except OSError:
                # Never recursively infer a parent deletion from an
                # unexpected directory.  The journal keeps the boundary
                # recoverable for a later startup pass.
                pass

    def remove_turn(self, debate_id: str, turn_id: str) -> None:
        """Remove one unpublished/stale turn without touching retained siblings."""

        with self._lock:
            metadata = self._metadata.pop((debate_id, turn_id), None)
        if metadata is None:
            return
        path = self.path_for(metadata.relative_path)
        if path.is_symlink():
            path.unlink(missing_ok=True)
        elif path.is_file():
            path.unlink()

    def stage_debate_directory(
        self,
        *,
        course_id: str,
        debate_id: str,
        staging_relative_path: str,
    ) -> bool:
        """Atomically move one retained debate directory to audio-swap staging."""

        source = self._non_symlink_path(
            f"courses/{_uuid_part(course_id)}/current-debate-audio/{_uuid_part(debate_id)}"
        )
        target = self._non_symlink_path(staging_relative_path)
        if source is None or target is None:
            raise ValueError("audio swap path cannot be a symlink")
        if not source.exists():
            return False
        if not source.is_dir() or target.exists():
            raise ValueError("audio swap path is not available")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.parent.chmod(0o700)
        source.replace(target)
        target.chmod(0o700)
        with self._lock:
            for key, metadata in list(self._metadata.items()):
                if metadata.debate_id != debate_id:
                    continue
                self._metadata[key] = AudioMetadata(
                    course_id=metadata.course_id,
                    debate_id=metadata.debate_id,
                    turn_id=metadata.turn_id,
                    relative_path=f"{staging_relative_path}/{metadata.turn_id}.wav",
                    sha256=metadata.sha256,
                    size_bytes=metadata.size_bytes,
                    duration_ms=metadata.duration_ms,
                    modified_at=metadata.modified_at,
                )
        return True

    def restore_staged_debate(
        self,
        *,
        course_id: str,
        debate_id: str,
        staging_relative_path: str,
    ) -> bool:
        """Restore one staged directory after a failed start transaction."""

        source = self._non_symlink_path(staging_relative_path)
        target = self._non_symlink_path(
            f"courses/{_uuid_part(course_id)}/current-debate-audio/{_uuid_part(debate_id)}"
        )
        if source is None or target is None:
            raise ValueError("audio swap path cannot be a symlink")
        if not source.exists():
            return False
        if target.exists():
            raise ValueError("audio swap restore target already exists")
        target.parent.mkdir(parents=True, exist_ok=True)
        source.replace(target)
        target.chmod(0o700)
        with self._lock:
            for key, metadata in list(self._metadata.items()):
                if metadata.debate_id != debate_id:
                    continue
                self._metadata[key] = AudioMetadata(
                    course_id=metadata.course_id,
                    debate_id=metadata.debate_id,
                    turn_id=metadata.turn_id,
                    relative_path=audio_relative_path(course_id, debate_id, metadata.turn_id),
                    sha256=metadata.sha256,
                    size_bytes=metadata.size_bytes,
                    duration_ms=metadata.duration_ms,
                    modified_at=metadata.modified_at,
                )
        return True

    def delete_staging(self, staging_relative_path: str) -> None:
        """Delete a journal-approved staging directory after DB commit."""

        target = self._non_symlink_path(staging_relative_path)
        if target is None:
            raise ValueError("audio staging target cannot be a symlink")
        if not target.exists():
            return
        if not target.is_dir():
            raise ValueError("audio staging target is not a directory")
        for child in target.iterdir():
            if child.is_symlink() or not child.is_file():
                raise ValueError("audio staging contains an invalid entry")
            child.unlink()
        target.rmdir()

    def retained(self, debate_id: str) -> bool:
        with self._lock:
            keys = [key for key in self._metadata if key[0] == debate_id]
        return any(self.metadata(*key) is not None for key in keys)

    def response(
        self,
        debate_id: str,
        turn_id: str,
        *,
        range_header: str | None = None,
        if_range: str | None = None,
    ) -> AudioResponse:
        metadata = self.metadata(debate_id, turn_id)
        if metadata is None:
            raise FileNotFoundError("audio_not_retained")
        # The index is only a cache.  Re-read and validate the canonical bytes
        # before every response so a file replaced after authorization cannot
        # be served under stale hash/size metadata.
        snapshot = self._validated_file_snapshot(
            course_id=metadata.course_id,
            debate_id=debate_id,
            turn_id=turn_id,
            relative_path=metadata.relative_path,
            expected_sha256=metadata.sha256,
            expected_size_bytes=metadata.size_bytes,
            expected_duration_ms=metadata.duration_ms,
        )
        if snapshot is None:
            raise FileNotFoundError("audio_not_retained")
        metadata, body = snapshot
        self.rehydrate(metadata)
        etag = f'"{metadata.sha256}"'
        use_range = bool(range_header)
        if use_range and if_range:
            use_range = if_range == etag or _if_range_matches_date(if_range, metadata)
        if not use_range:
            return AudioResponse(
                status_code=200,
                body=body,
                etag=etag,
                headers=_audio_headers(etag, len(body)),
            )
        byte_range = parse_single_range(range_header or "", len(body))
        if byte_range is None:
            headers = _audio_headers(etag, 0)
            headers["Content-Range"] = f"bytes */{len(body)}"
            return AudioResponse(status_code=416, body=b"", etag=etag, headers=headers)
        sliced = body[byte_range.start : byte_range.end + 1]
        headers = _audio_headers(etag, len(sliced))
        headers["Content-Range"] = f"bytes {byte_range.start}-{byte_range.end}/{len(body)}"
        return AudioResponse(status_code=206, body=sliced, etag=etag, headers=headers)


def wav_duration_ms(raw: bytes) -> int:
    try:
        with wave.open(io.BytesIO(raw), "rb") as stream:
            rate = stream.getframerate()
            frames = stream.getnframes()
            if rate <= 0 or frames < 0:
                raise ValueError
            return int(round(frames * 1000 / rate))
    except (OSError, EOFError, ValueError, wave.Error) as exc:
        raise TTSProviderError("audio output is not a valid WAV") from exc


def parse_single_range(value: str, size: int) -> ByteRange | None:
    """Parse exactly one RFC 9110 byte range, returning None if unsatisfied."""

    if size < 0 or "," in value:
        return None
    match = _RANGE_RE.fullmatch(value.strip())
    if match is None:
        return None
    raw_start, raw_end = match.groups()
    if not raw_start and not raw_end:
        return None
    if raw_start:
        start = int(raw_start)
        if start >= size:
            return None
        end = int(raw_end) if raw_end else size - 1
        if end < start:
            return None
        return ByteRange(start, min(end, size - 1))
    suffix_length = int(raw_end)
    if suffix_length <= 0 or size == 0:
        return None
    return ByteRange(max(0, size - suffix_length), size - 1)


def _audio_headers(etag: str, content_length: int) -> dict[str, str]:
    return {
        "Accept-Ranges": "bytes",
        "ETag": etag,
        "Content-Length": str(content_length),
        "Cache-Control": "no-store, max-age=0",
        "Pragma": "no-cache",
        "X-Content-Type-Options": "nosniff",
    }


def _if_range_matches_date(value: str, metadata: AudioMetadata) -> bool:
    """Date validators are accepted only when they are not older than bytes."""

    try:
        candidate = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        return False
    if candidate.tzinfo is None:
        candidate = candidate.replace(tzinfo=UTC)
    # The generated files carry no HTTP Last-Modified field in the public
    # contract; use the durable file mtime as the last-modified validator.
    # HTTP dates have one-second precision.  A file with an mtime no later
    # than the supplied validator permits the range; otherwise the client
    # must receive the complete representation.
    return _utc(candidate).timestamp() >= int(metadata.modified_at.timestamp())


@dataclass(frozen=True)
class MediaTicketBinding:
    token_hash: str
    session_hash: str
    controller_epoch: str
    debate_id: str
    turn_id: str
    action: Literal["start", "resume", "next", "replay"]
    control_version: int
    issued_at: datetime
    expires_at: datetime
    started: bool = False


class MediaTicketStore:
    """Opaque hash-only ticket registry scoped to one controller/item."""

    def __init__(self, *, ttl: timedelta = MEDIA_TICKET_TTL) -> None:
        self.ttl = ttl
        self._tickets: dict[str, MediaTicketBinding] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _hash(token: str) -> str:
        return hashlib.sha256(token.encode("ascii")).hexdigest()

    def issue(
        self,
        *,
        session_hash: str,
        controller_epoch: str,
        debate_id: str,
        turn_id: str,
        action: Literal["start", "resume", "next", "replay"],
        control_version: int = 0,
        now: datetime | None = None,
    ) -> tuple[str, MediaTicketBinding]:
        issued = _utc(now or datetime.now(UTC))
        token = secrets.token_urlsafe(MEDIA_TICKET_BYTES)
        # token_urlsafe(32) is exactly 43 URL-safe characters.  Refuse a
        # surprising runtime implementation rather than issuing a schema-
        # invalid token.
        if len(token) != 43:
            raise RuntimeError("media ticket generator returned an invalid token")
        binding = MediaTicketBinding(
            token_hash=self._hash(token),
            session_hash=session_hash,
            controller_epoch=controller_epoch,
            debate_id=debate_id,
            turn_id=turn_id,
            action=action,
            control_version=control_version,
            issued_at=issued,
            expires_at=issued + self.ttl,
        )
        with self._lock:
            self._tickets[binding.token_hash] = binding
        return token, binding

    def get(self, token: str, *, now: datetime | None = None) -> MediaTicketBinding | None:
        if len(token) != 43 or not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
            return None
        current = _utc(now or datetime.now(UTC))
        key = self._hash(token)
        with self._lock:
            binding = self._tickets.get(key)
            if binding is None or current > binding.expires_at:
                if binding is not None:
                    self._tickets.pop(key, None)
                return None
            return binding

    def find(
        self,
        *,
        session_hash: str,
        controller_epoch: str,
        debate_id: str,
        turn_id: str,
        action: str,
        started: bool | None = None,
        now: datetime | None = None,
    ) -> tuple[str, MediaTicketBinding] | None:
        """Find the current ticket by its complete server-side binding.

        The browser acknowledgement intentionally carries no bearer ticket;
        lookup therefore remains bound to the live session, controller epoch,
        debate, turn and action.  Raw tokens are never retained in this index.
        """

        current = _utc(now or datetime.now(UTC))
        with self._lock:
            values = tuple(self._tickets.items())
        for token_hash, binding in values:
            if current > binding.expires_at:
                with self._lock:
                    self._tickets.pop(token_hash, None)
                continue
            if (
                binding.session_hash == session_hash
                and binding.controller_epoch == controller_epoch
                and binding.debate_id == debate_id
                and binding.turn_id == turn_id
                and binding.action == action
                and (started is None or binding.started is started)
            ):
                return token_hash, binding
        return None

    def mark_binding_started(
        self,
        binding: MediaTicketBinding,
        *,
        now: datetime | None = None,
        audio_duration_ms: int | None = None,
    ) -> MediaTicketBinding:
        """Promote a previously issued binding without exposing its token."""

        current = _utc(now or datetime.now(UTC))
        expires = binding.expires_at
        if audio_duration_ms is not None:
            expires = min(
                expires,
                current + timedelta(milliseconds=max(0, audio_duration_ms)) + MEDIA_TICKET_GRACE,
            )
        updated = MediaTicketBinding(
            token_hash=binding.token_hash,
            session_hash=binding.session_hash,
            controller_epoch=binding.controller_epoch,
            debate_id=binding.debate_id,
            turn_id=binding.turn_id,
            action=binding.action,
            control_version=binding.control_version,
            issued_at=binding.issued_at,
            expires_at=expires,
            started=True,
        )
        with self._lock:
            self._tickets[updated.token_hash] = updated
        return updated

    def mark_started(
        self,
        token: str,
        *,
        session_hash: str,
        controller_epoch: str,
        debate_id: str,
        turn_id: str,
        now: datetime | None = None,
        audio_duration_ms: int | None = None,
    ) -> MediaTicketBinding | None:
        binding = self.get(token, now=now)
        if binding is None or (
            binding.session_hash != session_hash
            or binding.controller_epoch != controller_epoch
            or binding.debate_id != debate_id
            or binding.turn_id != turn_id
        ):
            return None
        return self.mark_binding_started(
            binding,
            now=now,
            audio_duration_ms=audio_duration_ms,
        )

    def revoke_token(self, token: str) -> None:
        with self._lock:
            self._tickets.pop(self._hash(token), None)

    def revoke_epoch(self, controller_epoch: str) -> int:
        return self._revoke(lambda value: value.controller_epoch == controller_epoch)

    def revoke_item(self, debate_id: str, turn_id: str) -> int:
        return self._revoke(lambda value: value.debate_id == debate_id and value.turn_id == turn_id)

    def revoke_debate(self, debate_id: str) -> int:
        return self._revoke(lambda value: value.debate_id == debate_id)

    def _revoke(self, predicate: object) -> int:
        removed = 0
        with self._lock:
            for key, value in list(self._tickets.items()):
                if callable(predicate) and predicate(value):
                    self._tickets.pop(key, None)
                    removed += 1
        return removed
