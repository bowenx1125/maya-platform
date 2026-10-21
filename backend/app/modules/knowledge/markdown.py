"""Frozen deterministic Markdown normalization, chunking and Mock vectors."""

from __future__ import annotations

import hashlib
import re
import struct
import unicodedata
from dataclasses import dataclass

TOKEN_RE = re.compile(r"\S+")
EMBED_TOKEN_RE = re.compile(r"[a-z0-9]+(?:'[a-z0-9]+)?")
INVALID_MARKDOWN_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\ud800-\udfff]")
EMBEDDING_DIMENSION = 256
EMBEDDING_KEY = "mock-sha256-v1"
MAX_CHUNK_UTF8_BYTES = 15_000


class MarkdownInputError(ValueError):
    """A user Markdown upload failed frozen validation."""


@dataclass(frozen=True)
class MarkdownDocument:
    filename: str
    normalized: str
    char_count: int
    content_hash: str
    # The normalized content hash is used for immutable document semantics;
    # the raw source hash is additionally part of upload idempotency so that
    # CRLF and LF payloads cannot silently replay the same key.
    source_sha256: str = ""


@dataclass(frozen=True)
class Chunk:
    index: int
    text: str
    start_offset: int
    end_offset: int
    embedding: bytes


def validate_markdown_characters(text: str) -> None:
    match = INVALID_MARKDOWN_CHAR_RE.search(text)
    if match is not None:
        reason = (
            "invalid_utf8" if 0xD800 <= ord(match.group()) <= 0xDFFF else "invalid_control_chars"
        )
        raise MarkdownInputError(reason)


def normalize_markdown(filename: str, data: bytes) -> MarkdownDocument:
    if not filename or "/" in filename or "\\" in filename:
        raise MarkdownInputError("invalid_filename")
    if any(unicodedata.category(char) in {"Cc", "Cf"} for char in filename):
        raise MarkdownInputError("invalid_filename")
    if not filename.lower().endswith(".md"):
        raise MarkdownInputError("invalid_filename")
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise MarkdownInputError("invalid_utf8") from None
    if text.startswith("\ufeff"):
        text = text[1:]
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    validate_markdown_characters(text)
    if not text.strip():
        raise MarkdownInputError("empty_markdown")
    return MarkdownDocument(
        filename=filename,
        normalized=text,
        char_count=len(text),
        content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        source_sha256=hashlib.sha256(data).hexdigest(),
    )


def _boundaries(text: str, tokens: list[re.Match[str]]) -> set[int]:
    """Return token end indices at paragraph and heading line boundaries."""

    boundaries: set[int] = set()
    line_start = 0
    token_index = 0
    for line in text.splitlines(keepends=True):
        line_without_newline = line.rstrip("\r\n")
        is_heading = line_without_newline.lstrip().startswith("#")
        is_blank = not line_without_newline.strip()
        line_end = line_start + len(line_without_newline)
        while token_index < len(tokens) and tokens[token_index].end() <= line_end:
            token_index += 1
        if is_heading or is_blank:
            # Blank lines therefore close the preceding maximal nonblank
            # paragraph; a heading closes its own line.
            if token_index:
                boundaries.add(token_index)
        line_start += len(line)
    if tokens:
        boundaries.add(len(tokens))
    return boundaries


def _utf8_byte_length(character: str) -> int:
    codepoint = ord(character)
    if codepoint <= 0x7F:
        return 1
    if codepoint <= 0x7FF:
        return 2
    if codepoint <= 0xFFFF:
        return 3
    return 4


def _chunk_by_utf8_bytes(text: str) -> list[tuple[int, str, int, int]]:
    """Split oversized chunk payloads on Unicode codepoint boundaries."""

    output: list[tuple[int, str, int, int]] = []
    start = 0
    byte_count = 0
    for end, character in enumerate(text):
        size = _utf8_byte_length(character)
        if byte_count and byte_count + size > MAX_CHUNK_UTF8_BYTES:
            chunk_text = text[start:end]
            if chunk_text.strip():
                output.append((len(output), chunk_text, start, end))
            start = end
            byte_count = 0
        byte_count += size
    if start < len(text):
        chunk_text = text[start:]
        if chunk_text.strip():
            output.append((len(output), chunk_text, start, len(text)))
    return output


def chunk_markdown(text: str) -> list[tuple[int, str, int, int]]:
    tokens = list(TOKEN_RE.finditer(text))
    if not tokens:
        return []
    boundaries = _boundaries(text, tokens)
    total = len(tokens)
    start = 0
    output: list[tuple[int, str, int, int]] = []
    index = 0
    while start < total:
        desired = min(start + 600, total)
        hard = min(start + 800, total)
        if hard == total:
            end = total
        else:
            candidates = sorted(boundary for boundary in boundaries if desired <= boundary <= hard)
            if candidates:
                end = candidates[0]
            else:
                earlier = sorted(boundary for boundary in boundaries if start < boundary < desired)
                end = earlier[-1] if earlier else hard
        start_offset = tokens[start].start()
        end_offset = tokens[end - 1].end()
        output.append((index, text[start_offset:end_offset], start_offset, end_offset))
        index += 1
        if end == total:
            break
        start = max(end - 100, start + 1)
    if any(
        len(chunk_text.encode("utf-8")) > MAX_CHUNK_UTF8_BYTES for _, chunk_text, _, _ in output
    ):
        # Token-count boundaries alone can still produce an oversized UTF-8
        # payload when tokens are unusually long. Bound supplier inputs without
        # changing saved source text or the offsets attached to each chunk.
        return _chunk_by_utf8_bytes(text)
    return output


def mock_embedding(text: str) -> bytes:
    values = [0.0] * EMBEDDING_DIMENSION
    for token_match in EMBED_TOKEN_RE.finditer(unicodedata.normalize("NFKC", text).lower()):
        token = token_match.group(0).encode("utf-8")
        digest = hashlib.sha256(token).digest()
        index = int.from_bytes(digest[:4], "big") % EMBEDDING_DIMENSION
        values[index] += 1.0 if digest[4] % 2 == 0 else -1.0
    norm = sum(value * value for value in values) ** 0.5
    if norm:
        values = [value / norm for value in values]
    # Struct's float conversion guarantees the byte-frozen float32 payload.
    return struct.pack("<256f", *values)


def build_chunks(text: str) -> list[Chunk]:
    return [
        Chunk(index, chunk_text, start, end, mock_embedding(chunk_text))
        for index, chunk_text, start, end in chunk_markdown(text)
    ]


def query_embedding(text: str) -> bytes:
    return mock_embedding(text)
