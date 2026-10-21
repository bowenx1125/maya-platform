"""One numeric-suffix name rule for Agents, RAG files and Voices.

``Zhu Xi`` taken -> ``Zhu Xi-2``; with ``-2`` and ``-5`` taken -> ``Zhu Xi-6``
(one above the highest existing suffix, skipping any still-taken candidate).
Names compare NFKC-normalized, trimmed and case-insensitive. For filenames
the suffix goes before the extension: ``notes.md`` -> ``notes-2.md``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from unicodedata import normalize

_SUFFIX_RE = re.compile(r"^(.*\S)-(\d{1,6})$")


def name_key(name: str) -> str:
    return normalize("NFKC", name).strip().casefold()


def _split_extension(name: str) -> tuple[str, str]:
    stem, dot, ext = name.rpartition(".")
    if dot and stem.strip() and ext and " " not in ext:
        return stem, "." + ext
    return name, ""


def dedup_name(name: str, taken: Iterable[str], *, keep_extension: bool = False) -> str:
    """Return ``name`` when free, else ``base-N`` with N = highest suffix + 1."""

    taken_keys = {name_key(item) for item in taken}
    if name_key(name) not in taken_keys:
        return name
    stem, ext = _split_extension(name.strip()) if keep_extension else (name.strip(), "")
    ext_key = name_key(ext)
    match = _SUFFIX_RE.match(stem)
    base = match.group(1) if match else stem
    base_key = name_key(base)
    highest = 1
    for existing in taken_keys:
        if ext_key:
            if not existing.endswith(ext_key):
                continue
            existing = existing[: -len(ext_key)]
        found = _SUFFIX_RE.match(existing)
        if found and found.group(1) == base_key:
            highest = max(highest, int(found.group(2)))
    candidate = highest + 1
    while name_key(f"{base}-{candidate}{ext}") in taken_keys:
        candidate += 1
    return f"{base}-{candidate}{ext}"
