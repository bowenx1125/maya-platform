#!/usr/bin/env python3
"""HTTP concurrency ladder for Classroom Quiz submit (GET + submit + DUP).

Postgres-only load entry for team2 testers. Does not call DashScope; point
``BASE_URL`` at a stack with ``LLM_PROVIDER=mock`` (or equivalent) when AI
items are present. Objective-only papers need no provider.

Pool / workers sizing
---------------------
Per-process SQLAlchemy capacity = ``POSTGRES_POOL_SIZE`` + ``POSTGRES_MAX_OVERFLOW``
(defaults 15 + 25 = 40). Total DB connections ≈ ``uvicorn_workers × capacity``.
Keep under Postgres ``max_connections`` with headroom. For L2=1500 concurrent
submits, size the pool so workers×(size+overflow) covers concurrency — do not
silently lower the client count. Also raise load-test dials that already exist
in Settings when running ladders (do not disable production safety by default):

- ``WRITE_GUARD_LIMIT`` (default 8/process) — primary submit backstop
- ``ADAPTIVE_ADMISSION_*`` / ``CREATE_ADMISSION_*`` as needed
- ``AUTH_HASH_CONCURRENCY`` for login waves
- ``POSTGRES_POOL_SIZE`` / ``POSTGRES_MAX_OVERFLOW`` / ``POSTGRES_POOL_TIMEOUT``

Example::

    export BASE_URL=http://127.0.0.1:8765
    export COURSE_ID=<uuid>
    # sessions.json: {"accounts":[{"username":"...","password":"..."}, ...]}
    # First account should be a teacher if --create-quiz is used; students follow.
    python3 scripts/load_quiz_http.py \\
        --sessions-file /path/sessions.json \\
        --levels 40,200,1500 --dup 40 \\
        --out-dir /tmp/quiz-m4-metrics

Thresholds (scheme §3): L0 p95≤800ms, L1≤1500ms, L2≤3000ms; 5xx=0;
non-2xx/409 error rate ≤0.5%; DUP expects one 2xx + rest 409.
"""

from __future__ import annotations

import argparse
import collections
import concurrent.futures
import http.cookiejar
import json
import math
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

THRESHOLDS_MS = {"L0": 800.0, "L1": 1500.0, "L2": 3000.0}

OBJECTIVE_ITEMS = [
    {
        "id": "q1",
        "type": "single",
        "required": True,
        "prompt": "Which layer handles auth?",
        "choices": [
            {"id": "a", "label": "API gateway"},
            {"id": "b", "label": "Database"},
            {"id": "c", "label": "CDN"},
        ],
        "answer": {"choice_ids": ["a"]},
        "points": 1,
    },
    {
        "id": "q2",
        "type": "multiple",
        "required": True,
        "prompt": "Select all HTTP safe methods.",
        "choices": [
            {"id": "a", "label": "GET"},
            {"id": "b", "label": "POST"},
            {"id": "c", "label": "HEAD"},
        ],
        "answer": {"choice_ids": ["a", "c"]},
        "points": 2,
    },
]

OBJECTIVE_ANSWERS = [
    {"item_id": "q1", "choice_ids": ["a"]},
    {"item_id": "q2", "choice_ids": ["c", "a"]},
]


class Client:
    def __init__(self, base_url: str, timeout: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPCookieProcessor(self.jar),
        )
        self.csrf: str | None = None
        self.user_id: str | None = None
        self.username: str | None = None

    def session_cookie(self) -> str | None:
        for cookie in self.jar:
            if cookie.name == "maya_session":
                return cookie.value
        return None

    def call(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        mutate: bool = False,
    ) -> dict[str, Any]:
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Origin": self.base_url}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if mutate:
            if not self.csrf:
                raise RuntimeError("CSRF token missing; login first")
            headers["X-CSRF-Token"] = self.csrf
        request = urllib.request.Request(
            self.base_url + path, data=data, headers=headers, method=method
        )
        started = time.perf_counter()
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                status, raw = response.status, response.read()
        except urllib.error.HTTPError as error:
            status, raw = error.code, error.read()
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            return {
                "status": 599,
                "code": type(error).__name__,
                "payload": {},
                "ms": (time.perf_counter() - started) * 1000,
            }
        try:
            payload = json.loads(raw) if raw else {}
        except (ValueError, UnicodeDecodeError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        code = payload.get("code")
        if not isinstance(code, str):
            err = payload.get("error")
            code = err.get("code") if isinstance(err, dict) else None
        return {
            "status": status,
            "code": code,
            "payload": payload,
            "ms": (time.perf_counter() - started) * 1000,
        }


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(len(ordered) * fraction) - 1)], 2)


def summarize(results: list[dict[str, Any]], *, duration_s: float) -> dict[str, Any]:
    submits = [item for item in results if item.get("phase") == "submit"]
    statuses = collections.Counter(int(item["status"]) for item in submits)
    codes = collections.Counter(str(item.get("code") or "") for item in submits)
    ms = [float(item["ms"]) for item in submits]
    count = len(submits)
    five = sum(n for status, n in statuses.items() if 500 <= status <= 599)
    not_ok = sum(
        n for status, n in statuses.items() if not (200 <= status < 300 or status == 409)
    )
    error_rate = (not_ok / count) if count else 1.0
    return {
        "count": count,
        "statuses": {str(k): v for k, v in sorted(statuses.items())},
        "codes": {k: v for k, v in codes.items() if k},
        "p50_ms": percentile(ms, 0.5),
        "p95_ms": percentile(ms, 0.95),
        "max_ms": round(max(ms), 2) if ms else None,
        "error_rate": round(error_rate, 6),
        "error_count": not_ok,
        "5xx": five,
        "throughput_rps": round(count / duration_s, 3) if duration_s > 0 else None,
        "wall_seconds": round(duration_s, 3),
        "get_p95_ms": percentile(
            [float(item["ms"]) for item in results if item.get("phase") == "get"], 0.95
        ),
    }


def login(client: Client, username: str, password: str) -> None:
    result = client.call(
        "POST",
        "/api/v1/auth/login",
        {"username": username, "password": password},
    )
    if result["status"] != 200:
        raise RuntimeError(f"login {username} -> {result['status']} {result.get('code')}")
    payload = result["payload"]
    client.csrf = payload.get("csrf_token") or client.csrf
    user = payload.get("user") or {}
    client.user_id = user.get("id")
    client.username = username
    if not client.session_cookie() or not client.csrf:
        raise RuntimeError(f"login {username} missing cookie/csrf")


def login_many(
    base_url: str,
    accounts: list[dict[str, str]],
    *,
    timeout: float,
    workers: int,
) -> list[Client]:
    """Each account gets a fresh Client so cookies never cross-revoke sessions."""

    clients: list[Client | None] = [None] * len(accounts)

    def one(index: int, account: dict[str, str]) -> None:
        client = Client(base_url, timeout)
        login(client, account["username"], account["password"])
        clients[index] = client

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [
            pool.submit(one, index, account) for index, account in enumerate(accounts)
        ]
        for future in concurrent.futures.as_completed(futures):
            future.result()
    return [client for client in clients if client is not None]


def create_open_quiz(teacher: Client, course_id: str, title: str) -> str:
    created = teacher.call(
        "POST",
        f"/api/v1/courses/{course_id}/quizzes",
        {"title": title, "items": OBJECTIVE_ITEMS},
        mutate=True,
    )
    if created["status"] != 201:
        raise RuntimeError(f"create quiz failed: {created['status']} {created.get('code')}")
    quiz_id = created["payload"]["id"]
    for action in ("publish", "start-taking"):
        result = teacher.call(
            "POST",
            f"/api/v1/courses/{course_id}/quizzes/{quiz_id}/{action}",
            {},
            mutate=True,
        )
        if result["status"] != 200:
            raise RuntimeError(f"{action} failed: {result['status']} {result.get('code')}")
    return str(quiz_id)


def wave_get_submit(
    clients: list[Client],
    course_id: str,
    quiz_id: str,
    answers: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], float]:
    barrier = threading.Barrier(len(clients))
    results: list[dict[str, Any]] = []
    lock = threading.Lock()

    def one(client: Client) -> None:
        barrier.wait()
        got = client.call("GET", f"/api/v1/courses/{course_id}/quizzes/{quiz_id}")
        got["phase"] = "get"
        got["username"] = client.username
        posted = client.call(
            "POST",
            f"/api/v1/courses/{course_id}/quizzes/{quiz_id}/attempts",
            {"answers": answers},
            mutate=True,
        )
        posted["phase"] = "submit"
        posted["username"] = client.username
        posted["actor_id"] = client.user_id
        with lock:
            results.append(got)
            results.append(posted)

    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(clients)) as pool:
        list(pool.map(one, clients))
    return results, time.perf_counter() - started


def _inject_session(client: Client, cookie: str) -> None:
    host = urllib.parse.urlparse(client.base_url).hostname or "127.0.0.1"
    session = http.cookiejar.Cookie(
        version=0,
        name="maya_session",
        value=cookie,
        port=None,
        port_specified=False,
        domain=host,
        domain_specified=True,
        domain_initial_dot=False,
        path="/",
        path_specified=True,
        secure=False,
        expires=None,
        discard=True,
        comment=None,
        comment_url=None,
        rest={},
        rfc2109=False,
    )
    client.jar.set_cookie(session)


def wave_dup(
    client: Client,
    course_id: str,
    quiz_id: str,
    answers: list[dict[str, Any]],
    n: int,
) -> tuple[list[dict[str, Any]], float]:
    """Fan out n concurrent submits with the same session (expect 1×2xx + (n-1)×409)."""

    cookie = client.session_cookie()
    csrf = client.csrf
    if not cookie or not csrf:
        raise RuntimeError("dup wave needs logged-in session")

    clones: list[Client] = []
    for _ in range(n):
        clone = Client(client.base_url, client.timeout)
        clone.csrf = csrf
        clone.username = client.username
        clone.user_id = client.user_id
        _inject_session(clone, cookie)
        clones.append(clone)

    client.call("GET", f"/api/v1/courses/{course_id}/quizzes/{quiz_id}")
    barrier = threading.Barrier(n)
    results: list[dict[str, Any]] = []
    lock = threading.Lock()

    def one(index: int, clone: Client) -> None:
        barrier.wait()
        posted = clone.call(
            "POST",
            f"/api/v1/courses/{course_id}/quizzes/{quiz_id}/attempts",
            {"answers": answers},
            mutate=True,
        )
        posted["phase"] = "submit"
        posted["username"] = client.username
        posted["dup_index"] = index
        with lock:
            results.append(posted)

    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=n) as pool:
        futures = [pool.submit(one, i, c) for i, c in enumerate(clones)]
        for future in concurrent.futures.as_completed(futures):
            future.result()
    return results, time.perf_counter() - started


def evaluate(level: str, summary: dict[str, Any], *, p95_limit: float | None) -> list[str]:
    failures: list[str] = []
    if summary.get("5xx", 0) != 0:
        failures.append(f"{level} 5xx={summary['5xx']} (need 0)")
    if float(summary.get("error_rate") or 0) > 0.005:
        failures.append(f"{level} error_rate={summary['error_rate']} (need <=0.005)")
    if p95_limit is not None:
        p95 = summary.get("p95_ms")
        if p95 is None or float(p95) > p95_limit:
            failures.append(f"{level} p95_ms={p95} (need <= {p95_limit})")
    return failures


def load_sessions(path: Path) -> list[dict[str, str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        accounts = payload
    else:
        accounts = payload.get("accounts") or []
    out: list[dict[str, str]] = []
    for row in accounts:
        out.append(
            {
                "username": str(row["username"]),
                "password": str(row["password"]),
            }
        )
    if not out:
        raise RuntimeError(f"no accounts in {path}")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("BASE_URL") or os.environ.get("MAYA_M4_BASE_URL"),
        help="API origin (env BASE_URL / MAYA_M4_BASE_URL)",
    )
    parser.add_argument(
        "--course-id",
        default=os.environ.get("COURSE_ID"),
        help="Course UUID (env COURSE_ID)",
    )
    parser.add_argument(
        "--quiz-id",
        default=os.environ.get("QUIZ_ID"),
        help="Existing open quiz UUID; omit with --create-quiz",
    )
    parser.add_argument(
        "--create-quiz",
        action="store_true",
        help="Teacher (first account) creates/publishes/opens an objective quiz",
    )
    parser.add_argument(
        "--sessions-file",
        type=Path,
        required=True,
        help="JSON with accounts[{username,password}, ...] (teacher first if creating)",
    )
    parser.add_argument(
        "--levels",
        default="40,200,1500",
        help="Comma ladder sizes (default 40,200,1500 → L0/L1/L2)",
    )
    parser.add_argument("--dup", type=int, default=40, help="Dual-submit fanout (0 to skip)")
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--login-workers", type=int, default=16)
    parser.add_argument(
        "--teacher-index",
        type=int,
        default=0,
        help="Index of teacher account in sessions file",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Write metrics_L*.json / metrics_all.json here",
    )
    parser.add_argument(
        "--answers-file",
        type=Path,
        default=None,
        help="Optional JSON list of answers; default objective sample",
    )
    args = parser.parse_args()
    if not args.base_url:
        parser.error("BASE_URL / --base-url required")
    if not args.course_id:
        parser.error("COURSE_ID / --course-id required")
    if not args.quiz_id and not args.create_quiz:
        parser.error("pass --quiz-id or --create-quiz")

    levels = [int(part.strip()) for part in args.levels.split(",") if part.strip()]
    if not levels:
        parser.error("no levels")
    level_names = []
    for index, size in enumerate(levels):
        if index == 0:
            level_names.append("L0")
        elif index == 1:
            level_names.append("L1")
        elif index == 2:
            level_names.append("L2")
        else:
            level_names.append(f"L{index}")

    accounts = load_sessions(args.sessions_file)
    answers = OBJECTIVE_ANSWERS
    if args.answers_file:
        answers = json.loads(args.answers_file.read_text(encoding="utf-8"))

    print(
        json.dumps(
            {
                "phase": "config",
                "base_url": args.base_url,
                "course_id": args.course_id,
                "levels": levels,
                "dup": args.dup,
                "accounts": len(accounts),
                "pool_hint": (
                    "per_process=POSTGRES_POOL_SIZE+POSTGRES_MAX_OVERFLOW; "
                    "total≈workers×per_process; raise WRITE_GUARD_LIMIT for ladders"
                ),
                "env_pool": {
                    "POSTGRES_POOL_SIZE": os.environ.get("POSTGRES_POOL_SIZE"),
                    "POSTGRES_MAX_OVERFLOW": os.environ.get("POSTGRES_MAX_OVERFLOW"),
                    "POSTGRES_POOL_TIMEOUT": os.environ.get("POSTGRES_POOL_TIMEOUT"),
                    "WRITE_GUARD_LIMIT": os.environ.get("WRITE_GUARD_LIMIT"),
                },
            }
        ),
        flush=True,
    )

    clients = login_many(
        args.base_url,
        accounts,
        timeout=args.timeout,
        workers=args.login_workers,
    )
    print(json.dumps({"phase": "login", "count": len(clients)}), flush=True)

    teacher = clients[args.teacher_index]
    students = [c for i, c in enumerate(clients) if i != args.teacher_index]
    quiz_id = str(args.quiz_id) if args.quiz_id else ""

    if args.out_dir:
        args.out_dir.mkdir(parents=True, exist_ok=True)

    all_metrics: dict[str, Any] = {"quiz_id": quiz_id, "levels": {}}
    failures: list[str] = []

    if len(levels) > 1 and not args.create_quiz and args.quiz_id:
        # Reusing one quiz_id across levels would 409 after L0; require create.
        parser.error("multi-level ladder needs --create-quiz (fresh quiz per level)")

    for name, size in zip(level_names, levels, strict=True):
        if size > len(students):
            raise RuntimeError(
                f"{name} needs {size} students but sessions file has {len(students)} "
                f"(excluding teacher index {args.teacher_index})"
            )
        wave_clients = students[:size]
        # Fresh quiz per level so prior submits do not 409 the ladder.
        if args.create_quiz:
            quiz_id = create_open_quiz(
                teacher, args.course_id, title=f"load-{name}-{int(time.time())}"
            )
        results, duration = wave_get_submit(
            wave_clients, args.course_id, quiz_id, answers
        )
        summary = summarize(results, duration_s=duration)
        summary["level"] = name
        summary["concurrency"] = size
        summary["quiz_id"] = quiz_id
        p95_limit = THRESHOLDS_MS.get(name)
        level_failures = evaluate(name, summary, p95_limit=p95_limit)
        summary["failures"] = level_failures
        summary["passed"] = not level_failures
        failures.extend(level_failures)
        all_metrics["levels"][name] = summary
        print(json.dumps({"phase": "level", **summary}), flush=True)
        if args.out_dir:
            (args.out_dir / f"metrics_{name}.json").write_text(
                json.dumps(summary, indent=2) + "\n", encoding="utf-8"
            )

    if args.dup > 0:
        dup_quiz = create_open_quiz(
            teacher, args.course_id, title=f"load-DUP-{int(time.time())}"
        )
        # Use first student; clone session for fanout.
        results, duration = wave_dup(
            students[0], args.course_id, dup_quiz, answers, args.dup
        )
        summary = summarize(results, duration_s=duration)
        summary["level"] = "DUP"
        summary["concurrency"] = args.dup
        summary["quiz_id"] = dup_quiz
        statuses = summary.get("statuses") or {}
        ok = sum(int(statuses.get(str(code), 0)) for code in range(200, 300))
        conflicted = int(statuses.get("409", 0))
        dup_failures: list[str] = []
        if ok != 1:
            dup_failures.append(f"DUP 2xx count={ok} (need 1)")
        if conflicted != args.dup - 1:
            dup_failures.append(
                f"DUP 409 count={conflicted} (need {args.dup - 1})"
            )
        if summary.get("5xx", 0) != 0:
            dup_failures.append(f"DUP 5xx={summary['5xx']} (need 0)")
        codes = summary.get("codes") or {}
        if conflicted and codes.get("quiz_attempt_exists", 0) != conflicted:
            dup_failures.append(
                f"DUP codes={codes} (409 should be quiz_attempt_exists)"
            )
        summary["failures"] = dup_failures
        summary["passed"] = not dup_failures
        failures.extend(dup_failures)
        all_metrics["levels"]["DUP"] = summary
        print(json.dumps({"phase": "level", **summary}), flush=True)
        if args.out_dir:
            (args.out_dir / "metrics_DUP.json").write_text(
                json.dumps(summary, indent=2) + "\n", encoding="utf-8"
            )

    all_metrics["failures"] = failures
    all_metrics["passed"] = not failures
    print(json.dumps({"phase": "done", **all_metrics}), flush=True)
    if args.out_dir:
        (args.out_dir / "metrics_all.json").write_text(
            json.dumps(all_metrics, indent=2) + "\n", encoding="utf-8"
        )
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
