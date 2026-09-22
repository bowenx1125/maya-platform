"""Streaming multipart reader and temporary-file lifecycle for voice uploads."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO
from uuid import UUID, uuid4

from fastapi import Request
from starlette.requests import ClientDisconnect

from app.modules.knowledge.files import contained_path, ensure_private_dir
from app.modules.voices.lease_lock import lock_exclusive, unlock
from app.providers.audio import MAX_UPLOAD_BYTES, safe_source_filename

MAX_FIELD_BYTES = 16 * 1024
MAX_MULTIPART_OVERHEAD = 64 * 1024
MAX_REQUEST_BYTES = MAX_UPLOAD_BYTES + MAX_MULTIPART_OVERHEAD
_BOUNDARY_RE = re.compile(r"(?:^|;)\s*boundary=(?:\"([^\"]+)\"|([^;\s]+))", re.I)
_DISPOSITION_NAME_RE = re.compile(r"(?:^|;)\s*name=\"([^\"]*)\"|(?:^|;)\s*name=([^;\s]+)", re.I)
_DISPOSITION_FILENAME_RE = re.compile(
    r"(?:^|;)\s*filename=\"([^\"]*)\"|(?:^|;)\s*filename=([^;\s]+)",
    re.I,
)


class VoiceUploadError(ValueError):
    """Raised when a bounded multipart request cannot be accepted."""


class VoiceUploadTooLarge(VoiceUploadError):
    """Raised as soon as the counted file/request limit is exceeded."""


class VoiceUploadDisconnected(VoiceUploadError):
    """Raised when the client disconnects while bytes are being copied."""


@dataclass(frozen=True)
class StreamedVoiceUpload:
    request_id: str
    request_directory: Path
    source_path: Path
    source_filename: str
    fields: dict[str, str]
    size_bytes: int
    sha256: str
    active_lease: BinaryIO

    def cleanup(self) -> None:
        """Remove this one validated UUID request directory."""

        if not self.active_lease.closed:
            try:
                unlock(self.active_lease)
            finally:
                self.active_lease.close()
        remove_voice_request_directory(self.request_directory.parent, self.request_id)


def _boundary(content_type: str) -> bytes:
    match = _BOUNDARY_RE.search(content_type)
    if not match:
        raise VoiceUploadError("audio_invalid")
    value = match.group(1) or match.group(2) or ""
    try:
        encoded = value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise VoiceUploadError("audio_invalid") from exc
    if not 1 <= len(encoded) <= 70 or any(byte < 33 or byte > 126 for byte in encoded):
        raise VoiceUploadError("audio_invalid")
    return encoded


def _header_map(header_bytes: bytes) -> dict[str, str]:
    try:
        text = header_bytes.decode("latin-1")
    except UnicodeDecodeError as exc:  # pragma: no cover - latin-1 never fails
        raise VoiceUploadError("audio_invalid") from exc
    result: dict[str, str] = {}
    for line in text.split("\r\n"):
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        result[key.strip().lower()] = value.strip()
    return result


def _disposition(value: str) -> tuple[str, str | None]:
    name_match = _DISPOSITION_NAME_RE.search(value)
    if not name_match:
        raise VoiceUploadError("audio_invalid")
    name = name_match.group(1) or name_match.group(2) or ""
    file_match = _DISPOSITION_FILENAME_RE.search(value)
    filename = None if file_match is None else (file_match.group(1) or file_match.group(2) or "")
    return name, filename


async def _request_chunks(request: Request) -> AsyncIterator[bytes]:
    try:
        async for item in request.stream():
            if not isinstance(item, bytes):
                raise VoiceUploadError("audio_invalid")
            if item:
                yield item
    except ClientDisconnect as exc:
        raise VoiceUploadDisconnected("audio_invalid") from exc
    except VoiceUploadError:
        raise
    except Exception as exc:
        # Do not preserve a framework/provider exception message; it can
        # contain request internals.  The route maps this to a safe code.
        raise VoiceUploadDisconnected("audio_invalid") from exc


async def stream_voice_upload(request: Request, data_root: Path) -> StreamedVoiceUpload:
    """Copy a multipart voice file to a private UUID directory incrementally.

    Only the file field is streamed to disk.  Form fields are bounded in
    memory, and the parser retains at most one multipart boundary plus the
    incoming transport chunk.  The request body is never materialised as one
    unbounded in-memory value.
    """

    content_type = request.headers.get("content-type", "")
    if not content_type.lower().startswith("multipart/form-data"):
        raise VoiceUploadError("audio_invalid")
    raw_length = request.headers.get("content-length")
    if raw_length:
        try:
            if int(raw_length) > MAX_REQUEST_BYTES:
                raise VoiceUploadTooLarge("audio_invalid")
        except ValueError as exc:
            raise VoiceUploadError("audio_invalid") from exc

    boundary = b"--" + _boundary(content_type)
    delimiter = b"\r\n" + boundary
    request_id = str(uuid4())
    temporary_root = data_root / "tmp" / "voice-enrollment"
    ensure_private_dir(temporary_root)
    directory = contained_path(temporary_root, request_id)
    if directory.exists() or directory.is_symlink():
        raise VoiceUploadError("audio_invalid")
    directory.mkdir(mode=0o700)
    directory.chmod(0o700)
    active_marker = directory / ".active"
    active_lease: BinaryIO | None = None
    source_path = directory / "source.upload"
    fields: dict[str, str] = {}
    source_filename = ""
    file_seen = False
    file_size = 0
    digest = hashlib.sha256()
    total_seen = 0
    buffer = bytearray()
    chunks = _request_chunks(request)
    iterator = chunks.__aiter__()
    exhausted = False

    async def fill(minimum: int = 1) -> None:
        nonlocal exhausted, total_seen
        while len(buffer) < minimum and not exhausted:
            try:
                chunk = await iterator.__anext__()
            except StopAsyncIteration:
                exhausted = True
                return
            total_seen += len(chunk)
            if total_seen > MAX_REQUEST_BYTES:
                raise VoiceUploadTooLarge("audio_invalid")
            buffer.extend(chunk)

    def consume(count: int) -> bytes:
        value = bytes(buffer[:count])
        del buffer[:count]
        return value

    async def finish_part(headers: dict[str, str], part_bytes: bytes) -> None:
        nonlocal source_filename, file_seen, file_size
        disposition = headers.get("content-disposition", "")
        name, filename = _disposition(disposition)
        if filename is not None:
            if name != "file" or file_seen:
                raise VoiceUploadError("audio_invalid")
            source_filename = safe_source_filename(filename)
            file_seen = True
            if len(part_bytes) > MAX_UPLOAD_BYTES:
                raise VoiceUploadTooLarge("audio_invalid")
            # ``part_bytes`` is only a bounded flush segment.  This branch is
            # retained for non-streamed final data and remains under the cap.
            with source_path.open("ab") as stream:
                stream.write(part_bytes)
            digest.update(part_bytes)
            file_size += len(part_bytes)
        else:
            if len(part_bytes) > MAX_FIELD_BYTES:
                raise VoiceUploadError("audio_invalid")
            try:
                value = part_bytes.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise VoiceUploadError("audio_invalid") from exc
            fields[name] = value

    try:
        active_lease = active_marker.open("xb")
        active_marker.chmod(0o600)
        lock_exclusive(active_lease)
        await fill(len(boundary) + 2)
        if not buffer.startswith(boundary):
            raise VoiceUploadError("audio_invalid")
        consume(len(boundary))
        await fill(2)
        if buffer.startswith(b"--"):
            raise VoiceUploadError("audio_invalid")
        if not buffer.startswith(b"\r\n"):
            raise VoiceUploadError("audio_invalid")
        consume(2)

        while True:
            header_end = -1
            while header_end < 0:
                header_end = buffer.find(b"\r\n\r\n")
                if header_end < 0 and len(buffer) > MAX_FIELD_BYTES:
                    raise VoiceUploadError("audio_invalid")
                if header_end < 0:
                    before = len(buffer)
                    await fill(before + 1)
                    if len(buffer) == before and exhausted:
                        raise VoiceUploadError("audio_invalid")
            headers = _header_map(bytes(buffer[:header_end]))
            consume(header_end + 4)
            _part_name, part_filename = _disposition(headers.get("content-disposition", ""))
            part_is_file = part_filename is not None
            if part_is_file and _part_name != "file":
                raise VoiceUploadError("audio_invalid")
            if part_is_file and file_seen:
                raise VoiceUploadError("audio_invalid")
            if part_is_file:
                source_filename = safe_source_filename(part_filename or "")
                file_seen = True

            # Stream part bytes out as soon as it is safe to distinguish them
            # from a boundary.  The file never accumulates in RAM.
            field_buffer = bytearray()
            while True:
                boundary_index = buffer.find(delimiter)
                if boundary_index >= 0:
                    segment = consume(boundary_index)
                    consume(len(delimiter))
                    if part_is_file:
                        # Write the final segment directly rather than letting
                        # a large upload enter ``field_buffer``.
                        with source_path.open("ab") as stream:
                            stream.write(segment)
                        final_part = segment
                        digest.update(final_part)
                        file_size += len(final_part)
                        if file_size > MAX_UPLOAD_BYTES:
                            raise VoiceUploadTooLarge("audio_invalid")
                    else:
                        field_buffer.extend(segment)
                        if len(field_buffer) > MAX_FIELD_BYTES:
                            raise VoiceUploadError("audio_invalid")
                        await finish_part(headers, bytes(field_buffer))
                    break
                # Keep enough bytes for a delimiter split across transport
                # chunks, and flush the rest to the destination as a stream.
                keep = len(delimiter) + 2
                if len(buffer) > keep:
                    flush = consume(len(buffer) - keep)
                    if part_is_file:
                        with source_path.open("ab") as stream:
                            stream.write(flush)
                        digest.update(flush)
                        file_size += len(flush)
                        if file_size > MAX_UPLOAD_BYTES:
                            raise VoiceUploadTooLarge("audio_invalid")
                    else:
                        field_buffer.extend(flush)
                        if len(field_buffer) > MAX_FIELD_BYTES:
                            raise VoiceUploadError("audio_invalid")
                before = len(buffer)
                await fill(before + 1)
                if len(buffer) == before and exhausted:
                    raise VoiceUploadError("audio_invalid")

            await fill(2)
            if buffer.startswith(b"--"):
                consume(2)
                await fill(2)
                if not buffer.startswith(b"\r\n"):
                    raise VoiceUploadError("audio_invalid")
                consume(2)
                break
            if not buffer.startswith(b"\r\n"):
                raise VoiceUploadError("audio_invalid")
            consume(2)

        if buffer or not exhausted:
            await fill(1)
            if buffer:
                raise VoiceUploadError("audio_invalid")
        if not file_seen or not source_filename or file_size <= 0:
            raise VoiceUploadError("audio_invalid")
        source_path.chmod(0o600)
        return StreamedVoiceUpload(
            request_id,
            directory,
            source_path,
            source_filename,
            fields,
            file_size,
            digest.hexdigest(),
            active_lease,
        )
    except BaseException:
        if active_lease is not None and not active_lease.closed:
            try:
                unlock(active_lease)
            finally:
                active_lease.close()
        remove_voice_request_directory(temporary_root, request_id)
        raise


def remove_voice_request_directory(temporary_root: Path, request_id: str) -> None:
    """Remove exactly one UUID-named request tree under the temp root."""

    try:
        UUID(request_id)
    except (ValueError, AttributeError):
        return
    try:
        target = contained_path(temporary_root, request_id)
    except (ValueError, OSError):
        return
    if target == temporary_root.resolve() or target.is_symlink() or not target.is_dir():
        return
    shutil.rmtree(target)


def cleanup_voice_temp_dirs(
    data_root: Path,
    *,
    age_seconds: float = 15 * 60,
    now: float | None = None,
) -> list[str]:
    """Remove only aged, UUID-named, non-active request directories.

    Symlinks, malformed names and recently touched active markers are left
    untouched.  The return value contains UUIDs only for test/operator
    evidence; no path or audio content is returned.
    """

    import time

    temporary_root = data_root / "tmp" / "voice-enrollment"
    if not temporary_root.exists() or temporary_root.is_symlink() or not temporary_root.is_dir():
        return []
    timestamp = time.time() if now is None else now
    removed: list[str] = []
    for child in temporary_root.iterdir():
        if child.is_symlink() or not child.is_dir():
            continue
        try:
            parsed = UUID(child.name)
        except ValueError:
            continue
        marker = child / ".active"
        if marker.is_symlink():
            continue
        active_lease: BinaryIO | None = None
        if marker.exists():
            try:
                active_lease = marker.open("r+b" if os.name == "nt" else "rb")
                lock_exclusive(active_lease)
            except (BlockingIOError, OSError):
                if active_lease is not None:
                    active_lease.close()
                continue
        try:
            newest = max(child.stat().st_mtime, marker.stat().st_mtime if marker.exists() else 0)
        except OSError:
            if active_lease is not None:
                active_lease.close()
            continue
        if timestamp - newest < age_seconds:
            if active_lease is not None:
                unlock(active_lease)
                active_lease.close()
            continue
        try:
            if os.name == "nt" and active_lease is not None:
                unlock(active_lease)
                active_lease.close()
                active_lease = None
            remove_voice_request_directory(temporary_root, str(parsed))
            if not child.exists():
                removed.append(str(parsed))
        finally:
            if active_lease is not None:
                try:
                    unlock(active_lease)
                finally:
                    active_lease.close()
    return removed
