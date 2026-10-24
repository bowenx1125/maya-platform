#!/usr/bin/env python3
"""Summarise request, Debate and browser timings from backend logs. Read-only.

Reads log text from files or standard input, for example:

    docker logs --since 24h maya-production-backend-1 2>&1 \\
      | python3 scripts/slow_endpoints_report.py
    docker logs --since 24h maya-production-backend-2 > b2.log 2>&1
    python3 scripts/slow_endpoints_report.py b1.log b2.log --top 30

It understands three line kinds written by the backend:

- ``request_timing`` JSON: per route (method + template) count, p50/p95/p99,
  max, mean database time and query count, mean provider time, slow count;
  sorted by p95, top N (default 20);
- ``client_metric`` JSON: the browser's sampled timings per metric name;
- ``debate_timing stage=... ms=...``: per Debate stage.

Only standard library; it never connects to a database or a service.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any, TextIO

_DEBATE_STAGE = re.compile(r"debate_timing stage=(\w+)")
_DEBATE_MS = re.compile(r"(?:^|\s)ms=(\d+)")


@dataclass
class Series:
    values: list[float] = field(default_factory=list)
    db_ms: float = 0.0
    db_queries: int = 0
    provider_ms: float = 0.0
    slow: int = 0
    errors: int = 0

    def add(self, value: float) -> None:
        self.values.append(value)


def percentile(values: list[float], fraction: float) -> float:
    """Nearest-rank percentile; 0 for an empty series."""

    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, math.ceil(fraction * len(ordered)))
    return ordered[min(rank, len(ordered)) - 1]


def _json_payload(line: str) -> dict[str, Any] | None:
    start = line.find("{")
    if start < 0:
        return None
    try:
        payload = json.loads(line[start:])
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


@dataclass
class Report:
    routes: dict[str, Series] = field(default_factory=lambda: defaultdict(Series))
    client: dict[str, Series] = field(default_factory=lambda: defaultdict(Series))
    debate: dict[str, Series] = field(default_factory=lambda: defaultdict(Series))
    lines: int = 0

    def feed(self, lines: Iterable[str]) -> None:
        for line in lines:
            self.lines += 1
            if '"request_timing"' in line:
                self._request(_json_payload(line))
            elif '"client_metric"' in line:
                self._client(_json_payload(line))
            elif "debate_timing stage=" in line:
                self._debate(line)

    def _request(self, payload: dict[str, Any] | None) -> None:
        if not payload or payload.get("event") != "request_timing":
            return
        try:
            ms = float(payload["ms"])
        except (KeyError, TypeError, ValueError):
            return
        key = f"{payload.get('method', '?')} {payload.get('route', '?')}"
        series = self.routes[key]
        series.add(ms)
        series.db_ms += float(payload.get("db_ms") or 0)
        series.db_queries += int(payload.get("db_queries") or 0)
        series.provider_ms += float(payload.get("provider_ms") or 0)
        series.slow += 1 if payload.get("slow") else 0
        status = payload.get("status")
        series.errors += 1 if isinstance(status, int) and status >= 500 else 0

    def _client(self, payload: dict[str, Any] | None) -> None:
        if not payload or payload.get("event") != "client_metric":
            return
        try:
            self.client[str(payload["name"])].add(float(payload["ms"]))
        except (KeyError, TypeError, ValueError):
            return

    def _debate(self, line: str) -> None:
        stage = _DEBATE_STAGE.search(line)
        ms = _DEBATE_MS.search(line)
        if stage and ms:
            self.debate[stage.group(1)].add(float(ms.group(1)))

    def summary(self, top: int) -> dict[str, Any]:
        def stats(series: Series) -> dict[str, Any]:
            count = len(series.values)
            return {
                "count": count,
                "p50": round(percentile(series.values, 0.50), 1),
                "p95": round(percentile(series.values, 0.95), 1),
                "p99": round(percentile(series.values, 0.99), 1),
                "max": round(max(series.values, default=0.0), 1),
            }

        routes = []
        for key, series in self.routes.items():
            count = len(series.values)
            routes.append(
                {
                    "route": key,
                    **stats(series),
                    "avg_db_ms": round(series.db_ms / count, 1) if count else 0.0,
                    "avg_queries": round(series.db_queries / count, 1) if count else 0.0,
                    "avg_provider_ms": round(series.provider_ms / count, 1) if count else 0.0,
                    "slow": series.slow,
                    "5xx": series.errors,
                }
            )
        routes.sort(key=lambda row: (row["p95"], row["count"]), reverse=True)
        return {
            "lines": self.lines,
            "requests": sum(len(series.values) for series in self.routes.values()),
            "routes": routes[:top],
            "client": {name: stats(series) for name, series in sorted(self.client.items())},
            "debate": {name: stats(series) for name, series in sorted(self.debate.items())},
        }


def _table(rows: list[dict[str, Any]], columns: list[tuple[str, str]]) -> Iterator[str]:
    widths = [
        max(len(title), *(len(str(row[key])) for row in rows)) if rows else len(title)
        for key, title in columns
    ]
    yield "  ".join(title.ljust(width) for (_, title), width in zip(columns, widths, strict=True))
    for row in rows:
        cells = (str(row[key]) for key, _ in columns)
        yield "  ".join(cell.ljust(width) for cell, width in zip(cells, widths, strict=True))


def render_text(summary: dict[str, Any], top: int) -> str:
    out = [f"{summary['requests']} requests in {summary['lines']} log lines"]
    out.append("")
    out.append(f"Slowest routes by p95 (top {top}, ms)")
    out.extend(
        _table(
            summary["routes"],
            [
                ("route", "route"),
                ("count", "count"),
                ("p50", "p50"),
                ("p95", "p95"),
                ("p99", "p99"),
                ("max", "max"),
                ("avg_db_ms", "db_ms"),
                ("avg_queries", "queries"),
                ("avg_provider_ms", "provider_ms"),
                ("slow", "slow"),
                ("5xx", "5xx"),
            ],
        )
    )
    for title, section in (("Browser metrics (ms)", "client"), ("Debate stages (ms)", "debate")):
        rows = [{"name": name, **values} for name, values in summary[section].items()]
        out.append("")
        out.append(title)
        out.extend(
            _table(
                rows,
                [
                    ("name", "name"),
                    ("count", "count"),
                    ("p50", "p50"),
                    ("p95", "p95"),
                    ("p99", "p99"),
                    ("max", "max"),
                ],
            )
        )
    return "\n".join(out)


def _lines(paths: list[str], stdin: TextIO) -> Iterator[str]:
    if not paths:
        yield from stdin
        return
    for path in paths:
        with open(path, encoding="utf-8", errors="replace") as handle:
            yield from handle


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="*", help="log files; standard input when omitted")
    parser.add_argument("--top", type=int, default=20, help="routes to list (default 20)")
    parser.add_argument("--json", action="store_true", help="print the summary as JSON")
    args = parser.parse_args(argv)
    report = Report()
    report.feed(_lines(args.paths, sys.stdin))
    summary = report.summary(max(1, args.top))
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(render_text(summary, max(1, args.top)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
