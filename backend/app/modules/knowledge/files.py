"""Contained, private file storage for the Wave 1A Demo.

The database stores only relative paths.  Every operation resolves and checks
containment before touching the filesystem, and uploads use a same-directory
temporary file followed by an atomic replace.
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
import unicodedata
from pathlib import Path
from urllib.parse import quote


class FileBoundaryError(ValueError):
    """Raised when a relative path escapes the configured data root."""


_DOWNLOAD_COMPONENT_RE = re.compile(r"[^\w.-]+", re.UNICODE)
_DOWNLOAD_ASCII_RE = re.compile(r"[^A-Za-z0-9._-]+")


def sanitize_download_component(value: str, fallback: str) -> str:
    """Return one safe, human-readable filename component.

    The original metadata is never used as a path.  Unicode letters/digits
    are retained for ``filename*`` while punctuation, whitespace and path
    separators become a stable hyphen.  Control/format characters are
    rejected from the output rather than copied into a response header.
    """

    normalized = unicodedata.normalize("NFKC", value).strip()
    kept: list[str] = []
    for char in normalized:
        category = unicodedata.category(char)
        if category in {"Cc", "Cf"}:
            continue
        kept.append(char)
    component = _DOWNLOAD_COMPONENT_RE.sub("-", "".join(kept)).strip(".-")
    return component or fallback


def download_base_name(source_filename: str, fallback: str = "document") -> str:
    """Sanitize a Markdown source's basename without accepting a path."""

    if not source_filename or "/" in source_filename or "\\" in source_filename:
        raise FileBoundaryError("invalid download filename")
    if any(unicodedata.category(char) in {"Cc", "Cf"} for char in source_filename):
        raise FileBoundaryError("invalid download filename")
    base = Path(source_filename).stem
    return sanitize_download_component(base, fallback)


def frozen_download_filename(
    source_filename: str,
    agent_name: str,
    version_label: str,
    *,
    ordinal: int | None = None,
) -> str:
    """Build the stable Agent/version-suffixed Markdown download name."""

    base = download_base_name(source_filename)
    agent = sanitize_download_component(agent_name, "agent")
    version = sanitize_download_component(version_label, "version")
    suffix = f"--{ordinal:02d}" if ordinal is not None else ""
    return f"{base}--{agent}--{version}{suffix}.md"


def content_disposition(filename: str) -> str:
    """Return safe ASCII fallback plus RFC 5987 UTF-8 filename metadata."""

    if not filename or "/" in filename or "\\" in filename:
        raise FileBoundaryError("invalid download filename")
    if any(ord(char) < 32 or ord(char) == 127 for char in filename):
        raise FileBoundaryError("invalid download filename")
    ascii_name = unicodedata.normalize("NFKD", filename).encode("ascii", "ignore").decode()
    ascii_name = _DOWNLOAD_ASCII_RE.sub("-", ascii_name).strip(".-") or "download"
    if not ascii_name.lower().endswith(".md"):
        ascii_name += ".md"
    encoded = quote(filename, safe="!#$&+-.^_`|~")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{encoded}"


def contained_path(root: Path, relative_path: str) -> Path:
    if not relative_path or Path(relative_path).is_absolute():
        raise FileBoundaryError("absolute or empty file path")
    candidate = (root / relative_path).resolve()
    base = root.resolve()
    try:
        candidate.relative_to(base)
    except ValueError:
        raise FileBoundaryError("file path is outside data root") from None
    return candidate


def ensure_private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)


def write_atomic(root: Path, relative_path: str, content: bytes) -> tuple[str, int]:
    target = contained_path(root, relative_path)
    base = root.resolve()
    directory = target.parent
    directory.mkdir(parents=True, exist_ok=True)
    while True:
        directory.chmod(0o700)
        if directory == base or directory.parent == directory:
            break
        directory = directory.parent
    fd, temp_name = tempfile.mkstemp(prefix=".maya-", dir=target.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temp_path.chmod(0o600)
        os.replace(temp_path, target)
        target.chmod(0o600)
        # A directory fsync closes the rename durability boundary on POSIX.
        directory_fd = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temp_path.exists():
            temp_path.unlink()
    return hashlib.sha256(content).hexdigest(), len(content)


def stage_atomic(root: Path, relative_path: str, content: bytes) -> tuple[str, int]:
    """Write durable bytes at an exact staging path without promoting them."""

    target = contained_path(root, relative_path)
    base = root.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    directory = target.parent
    while True:
        directory.chmod(0o700)
        if directory == base or directory.parent == directory:
            break
        directory = directory.parent
    fd, temp_name = tempfile.mkstemp(prefix=".maya-stage-", dir=target.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temp_path.chmod(0o600)
        # Both paths are under DATA_ROOT, hence on the same filesystem.  The
        # staging rename itself is atomic and durable before the journal moves
        # to ``staged``.
        os.replace(temp_path, target)
        target.chmod(0o600)
        directory_fd = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temp_path.exists():
            temp_path.unlink()
    return hashlib.sha256(content).hexdigest(), len(content)


def promote_atomic(root: Path, source_relative_path: str, target_relative_path: str) -> None:
    """Atomically promote one staged file or UUID directory to its target."""

    source = contained_path(root, source_relative_path)
    target = contained_path(root, target_relative_path)
    if source == root.resolve() or target == root.resolve():
        raise FileBoundaryError("cannot promote the data root")
    if not (source.exists() or source.is_symlink()):
        raise FileBoundaryError("staging path does not exist")
    if target.exists() or target.is_symlink():
        raise FileBoundaryError("promotion target already exists")
    target.parent.mkdir(parents=True, exist_ok=True)
    base = root.resolve()
    directory = target.parent
    while True:
        directory.chmod(0o700)
        if directory == base or directory.parent == directory:
            break
        directory = directory.parent
    os.replace(source, target)
    if target.is_file():
        target.chmod(0o600)
    directory_fd = os.open(target.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def verify_staged(
    root: Path,
    relative_path: str,
    expected_sha256: str,
    expected_size: int | None = None,
) -> tuple[str, int]:
    """Re-read staged bytes and verify their hash/size before promotion."""

    path = contained_path(root, relative_path)
    if not path.is_file():
        raise FileBoundaryError("staging path is not a regular file")
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    actual = digest.hexdigest()
    if actual != expected_sha256 or (expected_size is not None and size != expected_size):
        raise FileBoundaryError("staged file hash or size does not match")
    return actual, size


def remove_empty_directory(root: Path, relative_path: str) -> None:
    """Remove one exact staging directory when promotion left it empty."""

    target = contained_path(root, relative_path)
    if target == root.resolve() or not target.is_dir() or target.is_symlink():
        return
    try:
        target.rmdir()
    except OSError:
        # A non-empty or concurrently removed directory is recovered from its
        # durable journal; never recursively infer a parent path here.
        return
    parent_fd = os.open(target.parent, os.O_RDONLY)
    try:
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)


def read_contained(root: Path, relative_path: str) -> bytes:
    path = contained_path(root, relative_path)
    return path.read_bytes()


def mark_owned_files_private(root: Path) -> None:
    """Reapply 0600 to files under the application-owned data tree."""

    for path in root.rglob("*"):
        if path.is_symlink():
            continue
        if path.is_file():
            path.chmod(0o600)
        elif path.is_dir():
            path.chmod(0o700)
