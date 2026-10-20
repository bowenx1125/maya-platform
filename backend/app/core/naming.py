"""Numeric-suffix name dedup shared by RAG files and Voices (same rule as Agents).

``Zhu Xi`` taken -> ``Zhu Xi-2``; with ``-2`` and ``-5`` taken -> ``Zhu Xi-6``
(one above the highest existing suffix). Comparison is case-insensitive.
For filenames the suffix goes before the extension: ``notes.md`` -> ``notes-2.md``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable


def _split(name: str, keep_extension: bool) -> tuple[str, str]:
    if keep_extension and "." in name.strip(".")[1:]:
        stem, ext = name.rsplit(".", 1)
        return stem, "." + ext
    return name, ""


def dedup_name(name: str, taken: Iterable[str], *, keep_extension: bool = False) -> str:
    taken_keys = {t.strip().casefold() for t in taken}
    if name.strip().casefold() not in taken_keys:
        return name
    stem, ext = _split(name, keep_extension)
    base = re.sub(r"-\d+$", "", stem)
    pattern = re.compile(re.escape(base.casefold()) + r"(?:-(\d+))?" + re.escape(ext.casefold()))
    highest = 1
    for key in taken_keys:
        match = pattern.fullmatch(key)
        if match:
            highest = max(highest, int(match.group(1) or 1))
    return f"{base}-{highest + 1}{ext}"
