"""Small canonical-manifest helpers for SnapshotBuildV1.

Keeping these helpers in their own module gives ORM/publish code a narrow
import without making it depend on the build constructor implementation.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping


def canonical_json_bytes(value: Mapping[str, object]) -> bytes:
    """Serialize a manifest with one stable UTF-8 JSON representation."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_hex(value: bytes | str) -> str:
    """Return a lowercase SHA-256 digest for manifest/hash persistence."""

    raw = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(raw).hexdigest()


def canonical_manifest_hash(value: Mapping[str, object]) -> str:
    """Hash one already-composed canonical manifest mapping."""

    return sha256_hex(canonical_json_bytes(value))


__all__ = ["canonical_json_bytes", "canonical_manifest_hash", "sha256_hex"]
