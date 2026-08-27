"""Private, same-origin playback audio and current-only media tickets."""

from __future__ import annotations

import hashlib
import io
import re
import secrets
import threading
import wave
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import HTTPException

from app.modules.knowledge.files import contained_path, ensure_private_dir, write_atomic
from app.providers.tts import MockTTSProvider, TTSProvider, TTSProviderError

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

    def synthesize_and_store(
        self,
        *,
        course_id: str,
        debate_id: str,
        turn_id: str,
        speech: str,
        voice_token: str,
    ) -> AudioMetadata:
        """Use the injected (Mock by default) TTS provider and atomically store WAV."""

        if not speech.strip():
            raise TTSProviderError("speech is empty")
        # The caller supplies a server-side kind/profile token; it never leaves
        # the store or appears in a public DTO.
        result = self.tts_provider.synthesize(speech, voice_token, language="en")
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
        path = self.path_for(metadata.relative_path)
        if path.is_symlink() or not path.is_file():
            return None
        return metadata

    def read(self, debate_id: str, turn_id: str) -> bytes | None:
        metadata = self.metadata(debate_id, turn_id)
        if metadata is None:
            return None
        path = self.path_for(metadata.relative_path)
        try:
            return path.read_bytes()
        except OSError:
            return None

    def remove_debate(self, debate_id: str) -> None:
        """Remove only this debate's exact files; never infer a parent deletion."""

        with self._lock:
            items = [
                metadata
                for (candidate, _), metadata in self._metadata.items()
                if candidate == debate_id
            ]
            for key in [key for key in self._metadata if key[0] == debate_id]:
                self._metadata.pop(key, None)
        for metadata in items:
            path = self.path_for(metadata.relative_path)
            if path.is_symlink() or not path.exists():
                if path.is_symlink():
                    path.unlink(missing_ok=True)
                continue
            if path.is_file():
                path.unlink()

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

        source = self.path_for(
            f"courses/{_uuid_part(course_id)}/current-debate-audio/{_uuid_part(debate_id)}"
        )
        target = self.path_for(staging_relative_path)
        if source.is_symlink() or target.is_symlink():
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

        source = self.path_for(staging_relative_path)
        target = self.path_for(
            f"courses/{_uuid_part(course_id)}/current-debate-audio/{_uuid_part(debate_id)}"
        )
        if source.is_symlink() or target.is_symlink():
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

        target = self.path_for(staging_relative_path)
        if target.is_symlink():
            target.unlink()
            return
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
        body = self.read(debate_id, turn_id)
        if body is None:
            raise FileNotFoundError("audio_not_retained")
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


@contextmanager
def private_audio_root(data_root: Path) -> Iterator[Path]:
    """Create the exact private audio root for callers that need a lease."""

    root = data_root / "courses"
    ensure_private_dir(root)
    try:
        yield root
    finally:
        # Never recursively remove data here; lifecycle cleanup is owned by
        # the audio swap journal/service.
        pass


def http_audio_error(status_code: int, code: str) -> HTTPException:
    """Small adapter for routes that need framework-native status handling."""

    return HTTPException(status_code=status_code, detail=code)
