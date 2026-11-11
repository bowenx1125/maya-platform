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

# The chunker is versioned because a frozen build is re-chunked to prove it
# still matches its sources: a build keeps the chunker it was made with.
LEGACY_CHUNKING_VERSION = "markdown-heading-paragraph-v2"
CHUNKING_VERSION = "markdown-structure-600t-v3"
# Nov 2026: section-sized v2 chunks (median ~4,000 characters on production)
# gave most Agents the same single chunk every round, so retrieval selected
# nothing. 600 matches the supplier knowledge base's default maximum segment.
CHUNK_TARGET_TOKENS = 600
# Below a quarter of the target a chunk is a heading or a stray line with no
# context of its own; it is merged into a neighbour instead.
CHUNK_MIN_TOKENS = 150
# One whole sentence may carry a chunk past the target up to here; only a
# single sentence longer than this is cut (at a clause, a space, then anywhere).
CHUNK_MAX_TOKENS = 900
_CJK_RE = re.compile(r"[぀-ヿ㐀-䶿一-鿿가-힯豈-﫿\U00020000-\U0002ffff]")
_HEADING_LINE_RE = re.compile(r"^ {0,3}#{1,6}(?:\s|$)")
_SENTENCE_END_RE = re.compile(r"[。！？!?；;…]+[”’」』\"')）]*|\.(?=\s|$)[”’\"')]*")
_CLAUSE_END_RE = re.compile(r"[，,、：:]")
_LINE_END_RE = re.compile(r"\n")


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


def chunk_markdown(text: str, version: str = CHUNKING_VERSION) -> list[tuple[int, str, int, int]]:
    """Chunk with the named chunker; an unknown version is refused, never guessed."""

    if version == CHUNKING_VERSION:
        return _chunk_markdown_v3(text)
    if version == LEGACY_CHUNKING_VERSION:
        return _chunk_markdown_v2(text)
    raise ValueError("unsupported chunking version")


def estimate_tokens(text: str) -> int:
    """Embedding-token estimate: one per CJK character, one per four other characters.

    No supplier tokenizer is pinned here. Counting every Han character as a
    token over-counts Chinese (the supplier's tokenizer joins common pairs), so
    a chunk is never larger than its target, only sometimes smaller.
    """

    cjk = len(_CJK_RE.findall(text))
    other = sum(1 for char in text if not char.isspace()) - cjk
    return cjk + (other + 3) // 4


@dataclass(frozen=True)
class _Piece:
    start: int
    end: int
    heading: bool = False
    # For a heading: where its section (up to the next heading) ends.
    section_end: int = 0


def _trim(text: str, start: int, end: int) -> tuple[int, int] | None:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return (start, end) if start < end else None


def _fits(text: str, start: int, end: int, limit: int) -> bool:
    span = text[start:end]
    return estimate_tokens(span) <= limit and len(span.encode("utf-8")) <= MAX_CHUNK_UTF8_BYTES


def _cut_after(text: str, start: int, end: int, pattern: re.Pattern[str]) -> list[tuple[int, int]]:
    """Split a span after each separator; the separator stays with the text before it."""

    spans: list[tuple[int, int]] = []
    cursor = start
    for match in pattern.finditer(text, start, end):
        if match.end() > cursor:
            spans.append((cursor, match.end()))
            cursor = match.end()
    if cursor < end:
        spans.append((cursor, end))
    return [span for item in spans if (span := _trim(text, *item)) is not None]


def _hard_split(text: str, start: int, end: int) -> list[tuple[int, int]]:
    """Cut one unbroken run into pieces that fit the hard maximum and byte cap."""

    output: list[tuple[int, int]] = []
    piece_start = start
    cjk = other = byte_count = 0
    for index in range(start, end):
        character = text[index]
        is_cjk = _CJK_RE.match(character) is not None
        is_other = not is_cjk and not character.isspace()
        size = _utf8_byte_length(character)
        tokens = cjk + is_cjk + (other + is_other + 3) // 4
        if index > piece_start and (
            tokens > CHUNK_MAX_TOKENS or byte_count + size > MAX_CHUNK_UTF8_BYTES
        ):
            output.append((piece_start, index))
            piece_start = index
            cjk = other = byte_count = 0
        cjk += is_cjk
        other += is_other
        byte_count += size
    output.append((piece_start, end))
    return [span for item in output if (span := _trim(text, *item)) is not None]


def _oversized_sentence(text: str, start: int, end: int) -> list[tuple[int, int]]:
    output: list[tuple[int, int]] = []
    for clause in _cut_after(text, start, end, _CLAUSE_END_RE):
        if _fits(text, *clause, CHUNK_MAX_TOKENS):
            output.append(clause)
            continue
        for word in (match.span() for match in TOKEN_RE.finditer(text, *clause)):
            if _fits(text, *word, CHUNK_MAX_TOKENS):
                output.append(word)
            else:
                output.extend(_hard_split(text, *word))
    return output


def _block_pieces(text: str, start: int, end: int) -> list[tuple[int, int]]:
    """A paragraph whole if it fits the target, else its lines, else its sentences."""

    if _fits(text, start, end, CHUNK_TARGET_TOKENS):
        return [(start, end)]
    output: list[tuple[int, int]] = []
    for line in _cut_after(text, start, end, _LINE_END_RE):
        if _fits(text, *line, CHUNK_TARGET_TOKENS):
            output.append(line)
            continue
        for sentence in _cut_after(text, *line, _SENTENCE_END_RE):
            if _fits(text, *sentence, CHUNK_MAX_TOKENS):
                output.append(sentence)
            else:
                output.extend(_oversized_sentence(text, *sentence))
    return output


def _structure_pieces(text: str) -> list[_Piece]:
    blocks: list[tuple[int, int, bool]] = []
    block: tuple[int, int] | None = None
    offset = 0
    for line in text.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        line_end = offset + len(content)
        if not content.strip() or _HEADING_LINE_RE.match(content):
            if block is not None:
                blocks.append((*block, False))
                block = None
            if content.strip():
                blocks.append((offset, line_end, True))
        else:
            block = (offset if block is None else block[0], line_end)
        offset += len(line)
    if block is not None:
        blocks.append((*block, False))
    pieces: list[_Piece] = []
    for start, end, heading in blocks:
        trimmed = _trim(text, start, end)
        if trimmed is None:
            continue
        for index, (piece_start, piece_end) in enumerate(_block_pieces(text, *trimmed)):
            pieces.append(_Piece(piece_start, piece_end, heading and index == 0))
    section_end = len(text)
    for index in range(len(pieces) - 1, -1, -1):
        if index + 1 == len(pieces) or pieces[index + 1].heading:
            section_end = pieces[index].end
        if pieces[index].heading:
            pieces[index] = _Piece(pieces[index].start, pieces[index].end, True, section_end)
    return pieces


def _chunk_markdown_v3(text: str) -> list[tuple[int, str, int, int]]:
    """Pack whole paragraphs, lines or sentences into chunks of about 600 tokens.

    A heading starts a new chunk when the current one has reached the minimum
    and the whole section would not fit the target beside it; a heading never
    ends a chunk. A chunk below the minimum is merged into the next piece; the
    last chunk is merged into the one before. A small chunk survives only where
    merging would pass the hard maximum. Chunks do not overlap.
    """

    chunks: list[list[_Piece]] = []
    current: list[_Piece] = []

    def tokens(pieces: list[_Piece]) -> int:
        return estimate_tokens(text[pieces[0].start : pieces[-1].end])

    for piece in _structure_pieces(text):
        if current:
            big_enough = tokens(current) >= CHUNK_MIN_TOKENS
            if (
                (
                    piece.heading
                    and big_enough
                    and not _fits(text, current[0].start, piece.section_end, CHUNK_TARGET_TOKENS)
                )
                or (
                    big_enough and not _fits(text, current[0].start, piece.end, CHUNK_TARGET_TOKENS)
                )
                or not _fits(text, current[0].start, piece.end, CHUNK_MAX_TOKENS)
            ):
                carried: list[_Piece] = []
                while current and current[-1].heading:
                    carried.insert(0, current.pop())
                if current:
                    chunks.append(current)
                current = carried
                if current and not _fits(text, current[0].start, piece.end, CHUNK_MAX_TOKENS):
                    chunks.append(current)
                    current = []
        current.append(piece)
    if current:
        chunks.append(current)
    if (
        len(chunks) > 1
        and tokens(chunks[-1]) < CHUNK_MIN_TOKENS
        and _fits(text, chunks[-2][0].start, chunks[-1][-1].end, CHUNK_MAX_TOKENS)
    ):
        chunks[-2].extend(chunks.pop())
    return [
        (index, text[pieces[0].start : pieces[-1].end], pieces[0].start, pieces[-1].end)
        for index, pieces in enumerate(chunks)
    ]


def _chunk_markdown_v2(text: str) -> list[tuple[int, str, int, int]]:
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
