"""Opt-in: per request, how often one SQL statement repeats (N+1 finder).

Set MAYA_N_PLUS_ONE_REPORT=<dir> and run the suite; every API request a test
makes appends one JSON line to <dir>/<pid>.jsonl with its route, statement
count and the most repeated statement. scripts or a one-liner rank them.
Nothing is recorded without the variable.
"""

from __future__ import annotations

import collections
import json
import os
import re
from typing import Any

from app.core import request_timing
from sqlalchemy import event
from sqlalchemy.engine import Engine

_DIR = os.environ.get("MAYA_N_PLUS_ONE_REPORT")
_NUMBERS = re.compile(r"_\d+(_\d+)?\b")
_SPACE = re.compile(r"\s+")


def _shape(statement: str) -> str:
    return _NUMBERS.sub("_N", _SPACE.sub(" ", statement))[:240]


def _before(conn, cursor, statement, parameters, context, executemany):  # type: ignore[no-untyped-def]
    timing = request_timing.current()
    if timing is None:
        return
    counter = timing.__dict__.setdefault("_shapes", collections.Counter())
    counter[_shape(statement)] += 1


def install() -> None:
    if not _DIR:
        return
    os.makedirs(_DIR, exist_ok=True)
    event.listen(Engine, "before_cursor_execute", _before)
    original = request_timing.finish

    def finish(timing: Any, token: object, **kwargs: Any) -> dict[str, Any]:
        record = original(timing, token, **kwargs)
        shapes = timing.__dict__.get("_shapes")
        if shapes and str(kwargs.get("route", "")).startswith("/api/"):
            statement, repeats = shapes.most_common(1)[0]
            line = {
                "method": kwargs.get("method"),
                "route": kwargs.get("route"),
                "status": kwargs.get("status"),
                "db_queries": record["db_queries"],
                "distinct": len(shapes),
                "top_repeats": repeats,
                "top_statement": statement,
                "test": os.environ.get("PYTEST_CURRENT_TEST", "").split(" ")[0],
            }
            with open(os.path.join(_DIR, f"{os.getpid()}.jsonl"), "a") as handle:
                handle.write(json.dumps(line) + "\n")
        return record

    request_timing.finish = finish  # type: ignore[assignment]
