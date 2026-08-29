"""Signed, stateless classroom access tokens.

The database stores only the random nonce.  A token is therefore a
reconstructible capability and never becomes a durable bearer value in an
idempotency response, audit row, event payload or log.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
from dataclasses import dataclass
from uuid import UUID

TOKEN_VERSION = "v1"
TOKEN_DOMAIN = b"maya.classroom.v1\x00"
NONCE_BYTES = 32
SIGNATURE_BYTES = 32
_B64URL = re.compile(r"^[A-Za-z0-9_-]+$")


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode(value: str, *, expected_bytes: int) -> bytes | None:
    if not _B64URL.fullmatch(value):
        return None
    # The frozen token uses unpadded base64url with a fixed byte shape.  The
    # length check rejects alternate encodings before any lookup.
    if len(value) != ((expected_bytes * 8 + 5) // 6):
        return None
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, TypeError):
        return None
    if len(decoded) != expected_bytes:
        return None
    # Reject non-canonical encodings whose unused base64 pad bits differ but
    # decode to the same bytes.  This keeps the fixed token representation
    # unambiguous before the constant-time HMAC comparison.
    return decoded if _encode(decoded) == value else None


@dataclass(frozen=True)
class ClassroomToken:
    window_id: UUID
    nonce: bytes
    payload: bytes


def issue_token(window_id: str | UUID, nonce: bytes, secret: bytes) -> str:
    """Create the exact frozen v1 token shape."""

    window_uuid = window_id if isinstance(window_id, UUID) else UUID(str(window_id))
    if len(nonce) != NONCE_BYTES:
        raise ValueError("classroom nonce must contain exactly 32 bytes")
    payload = window_uuid.bytes + nonce
    signature = hmac.new(secret, TOKEN_DOMAIN + payload, hashlib.sha256).digest()
    return f"{TOKEN_VERSION}.{_encode(payload)}.{_encode(signature)}"


def parse_token(value: str, secret: bytes) -> ClassroomToken | None:
    """Validate token shape and HMAC before a database lookup."""

    pieces = value.split(".")
    if len(pieces) != 3 or pieces[0] != TOKEN_VERSION:
        return None
    payload = _decode(pieces[1], expected_bytes=16 + NONCE_BYTES)
    signature = _decode(pieces[2], expected_bytes=SIGNATURE_BYTES)
    if payload is None or signature is None:
        return None
    expected = hmac.new(secret, TOKEN_DOMAIN + payload, hashlib.sha256).digest()
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        window_id = UUID(bytes=payload[:16])
    except (ValueError, IndexError):
        return None
    return ClassroomToken(window_id=window_id, nonce=payload[16:], payload=payload)


__all__ = ["ClassroomToken", "NONCE_BYTES", "TOKEN_DOMAIN", "issue_token", "parse_token"]
