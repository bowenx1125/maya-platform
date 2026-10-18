"""Shared @mention parsing for Team chat (mirrors frontend/lib/mention-parse.ts).

Each ``@`` is matched against member names by the longest name that the
text right after the ``@`` starts with, so ``@Scorer你是干嘛的`` resolves to
``Scorer`` without a space and ``@Anna`` never counts as ``@Ann``. An ``@``
that names no known member is ignored: the message is treated as having no
mention and the default reply rules apply. Fenced code blocks are skipped.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

_FENCE = re.compile(r"```[\s\S]*?```")


def mentioned_names(text: str, names: Iterable[str]) -> list[str]:
    """Return the member names @-mentioned in ``text``, first-mention order."""

    candidates = sorted({name for name in names if name}, key=len, reverse=True)
    visible = _FENCE.sub(" ", text or "")
    found: list[str] = []
    index = visible.find("@")
    while index >= 0:
        rest = visible[index + 1 :]
        match = next((name for name in candidates if rest.startswith(name)), None)
        if match is not None and match not in found:
            found.append(match)
        index = visible.find("@", index + 1)
    return found
