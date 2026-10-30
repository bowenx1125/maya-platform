#!/usr/bin/env python3
"""Step a simulated class through the student flow and find the best limits (#140).

Each simulated student signs in, opens a Team chat (ChatForm) and sends its
answers; a turn counts once the stream reports ``turn_done``. N steps up
(default 10/20/30/40/60). While a step runs, ``/health/admission`` is sampled
every second for host load, MemAvailable, queue depth, gate usage and the
per-message timing window. A step stops the run when load > 8, MemAvailable
< 500 MB, or any 5xx that is not a retryable admission refusal appears.

Sweep mode holds every other limit and walks one limit through candidate
values: an operator-supplied command applies each value (for example a
compose restart with a new env value), the tool waits until
``/health/admission`` reports it, runs one step, and recommends the value
with the best throughput among those that never touched a stop line.

Only the standard library is used, so it runs on any load box:

    python3 scripts/load_tune.py --base-url https://maya.example \\
        --team-id <published assessment Team id> --steps 10,20,30,40,60

    python3 scripts/load_tune.py --base-url https://maya.example \\
        --team-id <id> --sweep WRITE_GUARD_LIMIT=8,12,17,24,32 \\
        --sweep-verify backstops.write_guard_limit --sweep-students 40 \\
        --apply-cmd './ops/set-limit.sh {name} {value}'

The server_* columns come from the rolling per-message window in
``/health/admission`` (15 minutes, one replica per URL), read right after the
step, so they also cover recent earlier steps; client-side columns are this
step only.

Accounts are registered once (``--account-prefix``, ``--password``) and
reused by every step, so a sweep stays inside the per-client registration
limit. Without ``--team-id`` each student builds a private Team from
``--member-version-ids`` (useful against a local Demo with mock providers).
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import functools
import http.cookiejar
import json
import math
import shlex
import statistics
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Admission refusals a student answers by pressing Send again; counted as
# refusals, never as 5xx.
RETRYABLE_CODES = frozenset({"adaptive_admission_busy", "write_pressure", "llm_admission_busy"})
DEFAULT_MESSAGES = ("我准备好了，开始吧。", "我的答案是第一个选项。", "我的答案是第二个选项。")


@dataclass
class Limits:
    max_load: float = 8.0
    min_mem_mb: float = 500.0


@dataclass
class HttpResult:
    status: int
    body: str
    code: str | None = None


@dataclass
class StepResult:
    label: str
    students: int
    started: float = 0.0
    finished: float = 0.0
    message_ms: list[float] = field(default_factory=list)
    completed_messages: int = 0
    failed_messages: int = 0
    assessment_turns: int = 0
    failure_codes: dict[str, int] = field(default_factory=dict)
    refusals: int = 0
    server_errors: int = 0
    max_load: float | None = None
    min_mem_mb: float | None = None
    max_queue_depth: int = 0
    brake_reasons: set[str] = field(default_factory=set)
    danger_seen: bool = False
    backstop_peaks: dict[str, int] = field(default_factory=dict)
    timing: dict[str, Any] = field(default_factory=dict)
    stop_reason: str | None = None

    @property
    def seconds(self) -> float:
        return max(0.0, self.finished - self.started)

    @property
    def throughput_per_min(self) -> float:
        return 60.0 * self.completed_messages / self.seconds if self.seconds else 0.0


def percentile(values: list[float], fraction: float) -> float | None:
    """Nearest-rank percentile; None for no samples."""

    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(fraction * len(ordered)))
    return ordered[rank - 1]


def parse_sse(lines: Iterator[str]) -> Iterator[tuple[str, str]]:
    """Yield (event, data) pairs from a text/event-stream body."""

    event, data = "message", list[str]()
    for raw in lines:
        line = raw.rstrip("\r\n")
        if not line:
            if data or event != "message":
                yield event, "\n".join(data)
            event, data = "message", list[str]()
            continue
        if line.startswith(":"):
            continue
        name, _, value = line.partition(":")
        value = value[1:] if value.startswith(" ") else value
        if name == "event":
            event = value
        elif name == "data":
            data.append(value)
    if data:
        yield event, "\n".join(data)


def lookup(payload: Any, dotted: str) -> Any:
    """Read ``a.b.c`` from nested dicts; None when any part is missing."""

    current = payload
    for part in dotted.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def stop_reason(sample: dict[str, Any], limits: Limits) -> str | None:
    load = sample.get("load_1m")
    mem = sample.get("mem_available_mb")
    if isinstance(load, (int, float)) and load > limits.max_load:
        return f"load_1m {load:.2f} > {limits.max_load:g}"
    if isinstance(mem, (int, float)) and mem < limits.min_mem_mb:
        return f"MemAvailable {mem:.0f} MB < {limits.min_mem_mb:g} MB"
    return None


def recommend(results: list[tuple[str, StepResult]]) -> str | None:
    """Best throughput among sweep values that never touched a stop line."""

    clean = [
        (value, step)
        for value, step in results
        if step.stop_reason is None and step.server_errors == 0 and step.completed_messages
    ]
    if not clean:
        return None
    return max(clean, key=lambda item: item[1].throughput_per_min)[0]


class Client:
    """One student's cookie jar and CSRF token."""

    def __init__(self, base_url: str, timeout: float) -> None:
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        self.csrf = ""
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )

    def _request(self, method: str, path: str, body: Any = None, **headers: str) -> Any:
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(self.base + path, data=data, method=method)
        request.add_header("Origin", self.base)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        if self.csrf:
            request.add_header("X-CSRF-Token", self.csrf)
        for name, value in headers.items():
            request.add_header(name.replace("_", "-"), value)
        return self.opener.open(request, timeout=self.timeout)

    def call(self, method: str, path: str, body: Any = None, **headers: str) -> HttpResult:
        try:
            with self._request(method, path, body, **headers) as response:
                return HttpResult(response.status, response.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as error:
            text = error.read().decode("utf-8", "replace")
            return HttpResult(error.code, text, _error_code(text))
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            return HttpResult(599, str(error), "transport_error")

    def stream(self, path: str, body: Any) -> HttpResult:
        """POST a message and read events until turn_done (or the stream ends)."""

        try:
            with self._request("POST", path, body, Accept="text/event-stream") as response:
                lines = (raw.decode("utf-8", "replace") for raw in response)
                for event, data in parse_sse(lines):
                    kind = event
                    if event == "message":
                        kind = str(_json(data).get("kind") or _json(data).get("type") or "")
                    if kind == "turn_done":
                        return HttpResult(200, data)
                    if kind in {"error", "turn_failed"}:
                        return HttpResult(500, data, _error_code(data) or kind)
                return HttpResult(200, "", "stream_ended_without_turn_done")
        except urllib.error.HTTPError as error:
            text = error.read().decode("utf-8", "replace")
            return HttpResult(error.code, text, _error_code(text))
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            return HttpResult(599, str(error), "transport_error")


def latest_turn(session: dict[str, Any], user_text: str) -> dict[str, Any] | None:
    """The newest turn carrying this message (turns are listed oldest first)."""

    for turn in reversed(session.get("turns") or []):
        if isinstance(turn, dict) and turn.get("user_text") == user_text:
            return turn
    return None


def _json(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except (ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _error_code(text: str) -> str | None:
    payload = _json(text)
    error = payload.get("error") if isinstance(payload.get("error"), dict) else payload
    code = error.get("code") if isinstance(error, dict) else None
    return str(code) if code else None


class HealthSampler(threading.Thread):
    """Sample /health/admission every second while a step runs."""

    def __init__(self, urls: list[str], step: StepResult, limits: Limits, stop: threading.Event):
        super().__init__(daemon=True)
        self.urls, self.step, self.limits, self.stop_event = urls, step, limits, stop
        self.done = threading.Event()
        self.last: dict[str, Any] = {}

    def run(self) -> None:
        while not self.done.is_set():
            for url in self.urls:
                sample = fetch_health(url)
                if sample:
                    self.absorb(sample)
            self.done.wait(1.0)

    def absorb(self, sample: dict[str, Any]) -> None:
        step = self.step
        self.last = sample
        load, mem = sample.get("load_1m"), sample.get("mem_available_mb")
        if isinstance(load, (int, float)):
            step.max_load = max(step.max_load or 0.0, float(load))
        if isinstance(mem, (int, float)):
            step.min_mem_mb = min(step.min_mem_mb or float("inf"), float(mem))
        step.max_queue_depth = max(step.max_queue_depth, int(sample.get("queue_depth") or 0))
        step.danger_seen = step.danger_seen or bool(sample.get("danger"))
        reason = lookup(sample, "brake.active_reason")
        if reason:
            step.brake_reasons.add(str(reason))
        for gate, usage in (sample.get("backstop_usage") or {}).items():
            if isinstance(usage, dict):
                busy = int(usage.get("in_flight") or 0) + int(usage.get("waiters") or 0)
                step.backstop_peaks[gate] = max(step.backstop_peaks.get(gate, 0), busy)
        why = stop_reason(sample, self.limits)
        if why and step.stop_reason is None:
            step.stop_reason = why
            self.stop_event.set()


def fetch_health(url: str, timeout: float = 5.0) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return _json(response.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, TimeoutError, OSError):
        return {}


@dataclass
class Plan:
    base_url: str
    password: str
    account_prefix: str
    group_name: str
    course_id: str
    team_id: str | None
    member_version_ids: list[str]
    messages: list[str]
    timeout: float
    send_again: int


@dataclass(frozen=True)
class LoginCiConfig:
    profile: str
    warmup: int
    samples: int
    concurrency: int
    repeat: int
    errors_max: int
    p95_ms_max: float
    source: str


@dataclass(frozen=True)
class LoginCiBatch:
    latencies_ms: list[float]
    errors: int
    elapsed_seconds: float


@dataclass(frozen=True)
class LoginCiAttempt:
    latency_ms: float
    error: bool


def selected_profile(value: str | None) -> str:
    """Select login-ci explicitly; all other values retain the classroom flow."""

    return "login-ci" if value == "login-ci" else "classroom"


def load_login_ci_config(path: Path | None = None) -> LoginCiConfig:
    config_path = path or Path(__file__).with_name("load_tune_login_ci.json")
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ValueError("could not read login-ci configuration") from None
    if not isinstance(payload, dict) or set(payload) != {
        "profile",
        "warmup",
        "samples",
        "concurrency",
        "repeat",
        "gates",
    }:
        raise ValueError("invalid login-ci configuration fields")
    expected_workload = {"warmup": 2, "samples": 20, "concurrency": 2, "repeat": 3}
    for name, expected in expected_workload.items():
        value = payload.get(name)
        if type(value) is not int or value != expected:
            raise ValueError("login-ci workload must match the frozen 2/20/2/3 profile")
    gates = payload.get("gates")
    if not isinstance(gates, dict) or set(gates) != {"errors_max", "p95_ms_max", "source"}:
        raise ValueError("invalid login-ci gate configuration")
    if payload.get("profile") != "login-ci":
        raise ValueError("login-ci configuration profile is invalid")
    if type(gates.get("errors_max")) is not int or gates["errors_max"] != 0:
        raise ValueError("login-ci errors_max must remain 0")
    if type(gates.get("p95_ms_max")) not in (int, float) or gates["p95_ms_max"] != 200:
        raise ValueError("login-ci p95_ms_max must remain 200")
    source = gates.get("source")
    required_sources = (
        "测试-性能压测-50用户-9c68d42b.md",
        "§3",
        "方案-性能稳定性-会话哈希与知识库NUL-架构A.md",
        "§5",
        "9c68d42b",
    )
    if not isinstance(source, str) or any(
        reference not in source for reference in required_sources
    ):
        raise ValueError("login-ci gate source must cite the approved reports and tip")
    return LoginCiConfig(
        profile="login-ci",
        warmup=2,
        samples=20,
        concurrency=2,
        repeat=3,
        errors_max=0,
        p95_ms_max=200.0,
        source=source,
    )


def login_ci_attempt(
    base_url: str, account_prefix: str, password: str, index: int, timeout: float
) -> LoginCiAttempt:
    username = f"{account_prefix}-{index:03d}"
    started = time.perf_counter()
    try:
        result = Client(base_url, timeout).call(
            "POST", "/api/v1/auth/login", {"username": username, "password": password}
        )
        error = result.status != 200
    except Exception:
        error = True
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return LoginCiAttempt(latency_ms=elapsed_ms, error=error)


def _run_login_ci_batch(
    base_url: str,
    account_prefix: str,
    password: str,
    count: int,
    concurrency: int,
    timeout: float,
) -> LoginCiBatch:
    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        attempts = list(
            executor.map(
                lambda index: login_ci_attempt(
                    base_url, account_prefix, password, index, timeout
                ),
                range(count),
            )
        )
    elapsed = max(0.0, time.perf_counter() - started)
    return LoginCiBatch(
        latencies_ms=[attempt.latency_ms for attempt in attempts],
        errors=sum(attempt.error for attempt in attempts),
        elapsed_seconds=elapsed,
    )


def build_login_ci_report(
    config: LoginCiConfig, rounds: list[LoginCiBatch], warmup_errors: int = 0
) -> dict[str, Any]:
    if len(rounds) != config.repeat or warmup_errors < 0:
        raise ValueError("login-ci round count or warmup error count is invalid")
    if any(
        len(batch.latencies_ms) != config.samples
        or batch.errors < 0
        or batch.elapsed_seconds < 0
        for batch in rounds
    ):
        raise ValueError("login-ci sample batch is invalid")
    round_reports: list[dict[str, Any]] = []
    all_latencies: list[float] = []
    for number, batch in enumerate(rounds, start=1):
        all_latencies.extend(batch.latencies_ms)
        round_reports.append(
            {
                "round": number,
                "total_requests": len(batch.latencies_ms),
                "errors": batch.errors,
                "p50_ms": percentile(batch.latencies_ms, 0.5),
                "p95_ms": percentile(batch.latencies_ms, 0.95),
                "throughput_rps": (
                    len(batch.latencies_ms) / batch.elapsed_seconds
                    if batch.elapsed_seconds
                    else 0.0
                ),
            }
        )
    total_requests = len(all_latencies)
    total_errors = sum(batch.errors for batch in rounds)
    round_p95s = [float(report["p95_ms"]) for report in round_reports]
    p95_median = statistics.median(round_p95s)
    elapsed_total = sum(batch.elapsed_seconds for batch in rounds)
    passed = (
        warmup_errors == 0
        and total_errors <= config.errors_max
        and p95_median <= config.p95_ms_max
    )
    return {
        "profile": config.profile,
        "warmup": config.warmup,
        "samples": config.samples,
        "concurrency": config.concurrency,
        "repeat": config.repeat,
        "warmup_errors": warmup_errors,
        "rounds": round_reports,
        "aggregate": {
            "total_requests": total_requests,
            "errors": total_errors,
            "p50_ms": percentile(all_latencies, 0.5),
            "p95_ms": percentile(all_latencies, 0.95),
            "p95_median_ms": p95_median,
            "throughput_rps": total_requests / elapsed_total if elapsed_total else 0.0,
        },
        "gates": {
            "errors_max": config.errors_max,
            "p95_ms_max": config.p95_ms_max,
            "source": config.source,
        },
        "passed": passed,
    }


def login_ci_exit_code(report: dict[str, Any]) -> int:
    return 0 if report.get("passed") is True else 1


def run_login_ci(
    base_url: str, account_prefix: str, password: str, timeout: float
) -> dict[str, Any]:
    parsed_url = urllib.parse.urlsplit(base_url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        raise ValueError("base URL must be an absolute HTTP(S) URL")
    if not account_prefix or not password or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("account prefix, password, and positive timeout are required")
    config = load_login_ci_config()
    warmup = _run_login_ci_batch(
        base_url, account_prefix, password, config.warmup, config.concurrency, timeout
    )
    rounds = [
        _run_login_ci_batch(
            base_url,
            account_prefix,
            password,
            config.samples,
            config.concurrency,
            timeout,
        )
        for _ in range(config.repeat)
    ]
    return build_login_ci_report(config, rounds, warmup.errors)


def ensure_account(plan: Plan, index: int) -> None:
    client = Client(plan.base_url, plan.timeout)
    username = f"{plan.account_prefix}-{index:03d}"
    result = client.call(
        "POST",
        "/api/v1/auth/register",
        {"username": username, "password": plan.password, "group_name": plan.group_name},
    )
    if result.status not in (200, 201, 409):
        raise SystemExit(f"registering {username} failed: {result.status} {result.body[:200]}")


def _with_send_again(
    plan: Plan, step: StepResult, lock: threading.Lock, call: Callable[[], HttpResult]
) -> HttpResult:
    result = call()
    for _ in range(plan.send_again):
        if not (result.status == 503 and result.code in RETRYABLE_CODES):
            break
        with lock:
            step.refusals += 1
        time.sleep(1.0)
        result = call()
    if result.status == 503 and result.code in RETRYABLE_CODES:
        with lock:
            step.refusals += 1
    elif result.status >= 500:
        with lock:
            step.server_errors += 1
    return result


def _setup_failed(
    step: StepResult, lock: threading.Lock, plan: Plan, stage: str, result: HttpResult
) -> None:
    code = f"{stage}:{result.code or result.status}"
    with lock:
        step.failed_messages += len(plan.messages)
        step.failure_codes[code] = step.failure_codes.get(code, 0) + 1


def run_student(
    plan: Plan,
    index: int,
    step: StepResult,
    lock: threading.Lock,
    start: threading.Barrier,
    stop: threading.Event,
) -> None:
    client = Client(plan.base_url, plan.timeout)
    username = f"{plan.account_prefix}-{index:03d}"
    try:
        start.wait(timeout=120)
    except threading.BrokenBarrierError:
        return

    def guarded(call: Callable[[], HttpResult]) -> HttpResult:
        result = _with_send_again(plan, step, lock, call)
        if result.status >= 500 and not (result.status == 503 and result.code in RETRYABLE_CODES):
            if step.stop_reason is None:
                step.stop_reason = f"{result.status} {result.code or ''}".strip()
            stop.set()
        return result

    signed_in = guarded(
        lambda: client.call(
            "POST", "/api/v1/auth/login", {"username": username, "password": plan.password}
        )
    )
    if signed_in.status != 200:
        _setup_failed(step, lock, plan, "login", signed_in)
        return
    client.csrf = str(_json(signed_in.body).get("csrf_token") or "")
    team_id = plan.team_id
    if team_id is None:
        members = [
            {"agent_version_id": version, "position": position, "is_leader": position == 0}
            for position, version in enumerate(plan.member_version_ids)
        ]
        team = guarded(
            lambda: client.call(
                "POST",
                f"/api/v1/courses/{plan.course_id}/teams",
                {
                    "display_name": f"{username} load team",
                    "visibility": "private",
                    "members": members,
                },
                Idempotency_Key=f"load-team-{uuid.uuid4()}",
            )
        )
        team_id = str(_json(team.body).get("id") or "")
        if team.status != 201 or not team_id:
            _setup_failed(step, lock, plan, "team", team)
            return
    chat = guarded(
        lambda: client.call(
            "POST", "/api/v1/conversations", {"entry": {"kind": "team", "team_id": team_id}}
        )
    )
    conversation = _json(chat.body)
    if chat.status != 200 or not conversation.get("id"):
        _setup_failed(step, lock, plan, "chat", chat)
        return
    conversation_id = str(conversation["id"])
    revision = int(conversation.get("revision") or 0)
    for text in plan.messages:
        if stop.is_set():
            return
        request_id = str(uuid.uuid4())
        started = time.perf_counter()
        body = {
            "request_id": request_id,
            "expected_revision": revision,
            "message": text,
            "routing": {"mode": "all", "participant_ids": []},
        }
        path = f"/api/v1/conversations/{conversation_id}/messages:stream"
        sent = guarded(functools.partial(client.stream, path, body))
        elapsed = (time.perf_counter() - started) * 1000.0
        current = _json(client.call("GET", f"/api/v1/conversations/{conversation_id}").body)
        turn = latest_turn(current, text)
        state = str(turn.get("state") or "") if turn else ""
        with lock:
            if sent.status == 200 and sent.code is None and state in {"ready", "partial"}:
                step.completed_messages += 1
                step.message_ms.append(elapsed)
                if turn and turn.get("assessment_result"):
                    step.assessment_turns += 1
            else:
                step.failed_messages += 1
                code = (turn or {}).get("safe_error_code") or sent.code or state or "unknown"
                step.failure_codes[str(code)] = step.failure_codes.get(str(code), 0) + 1
        revision = int(current.get("revision") or revision + 1)


def run_step(
    plan: Plan, students: int, health_urls: list[str], limits: Limits, label: str
) -> StepResult:
    step = StepResult(label=label, students=students)
    stop = threading.Event()
    lock = threading.Lock()
    barrier = threading.Barrier(students)
    sampler = HealthSampler(health_urls, step, limits, stop)
    sampler.start()
    threads = [
        threading.Thread(
            target=run_student, args=(plan, index, step, lock, barrier, stop), daemon=True
        )
        for index in range(students)
    ]
    step.started = time.time()
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    step.finished = time.time()
    time.sleep(1.5)  # one more sample after the last turn
    sampler.done.set()
    sampler.join()
    step.timing = dict(sampler.last.get("message_timing") or {})
    return step


def wait_for_quiet(urls: list[str], settle_load: float, timeout: float) -> None:
    """Between steps: wait until nothing is queued or in flight and load settles."""

    deadline = time.time() + timeout
    while time.time() < deadline:
        samples = [fetch_health(url) for url in urls]
        if all(
            s
            and not s.get("in_flight")
            and not s.get("queue_depth")
            and float(s.get("load_1m") or 0.0) <= settle_load
            for s in samples
        ):
            return
        time.sleep(5.0)


def apply_value(command: str, name: str, value: str) -> None:
    rendered = command.format(name=shlex.quote(name), value=shlex.quote(value))
    print(f"applying {name}={value}: {rendered}", flush=True)
    subprocess.run(rendered, shell=True, check=True)  # noqa: S602 - operator's own command


def wait_for_value(urls: list[str], dotted: str, value: str, timeout: float) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        seen = [lookup(fetch_health(url), dotted) for url in urls]
        if seen and all(str(item) == value for item in seen):
            return
        time.sleep(3.0)
    raise SystemExit(f"/health/admission never reported {dotted}={value}")


COLUMNS = (
    "label",
    "students",
    "seconds",
    "completed",
    "failed",
    "failure_codes",
    "assessment_turns",
    "throughput_per_min",
    "msg_p50_ms",
    "msg_p95_ms",
    "refusals",
    "5xx",
    "max_load",
    "min_mem_mb",
    "max_queue",
    "server_queue_wait_p50_ms",
    "server_queue_wait_p95_ms",
    "server_db_write_p95_ms",
    "server_db_writes_per_msg_p50",
    "brake",
    "danger",
    "gate_peaks",
    "stop_reason",
)


def _cell(value: Any) -> Any:
    return "" if value is None else value


def row(step: StepResult) -> dict[str, Any]:
    def fmt(value: float | None) -> str:
        return "" if value is None else f"{value:.0f}"

    timing = step.timing
    return {
        "label": step.label,
        "students": step.students,
        "seconds": f"{step.seconds:.0f}",
        "completed": step.completed_messages,
        "failed": step.failed_messages,
        "failure_codes": " ".join(f"{k}={v}" for k, v in sorted(step.failure_codes.items())),
        "assessment_turns": step.assessment_turns,
        "throughput_per_min": f"{step.throughput_per_min:.1f}",
        "msg_p50_ms": fmt(percentile(step.message_ms, 0.5)),
        "msg_p95_ms": fmt(percentile(step.message_ms, 0.95)),
        "refusals": step.refusals,
        "5xx": step.server_errors,
        "max_load": "" if step.max_load is None else f"{step.max_load:.2f}",
        "min_mem_mb": fmt(step.min_mem_mb),
        "max_queue": step.max_queue_depth,
        "server_queue_wait_p50_ms": _cell(lookup(timing, "queue_wait_ms.p50")),
        "server_queue_wait_p95_ms": _cell(lookup(timing, "queue_wait_ms.p95")),
        "server_db_write_p95_ms": _cell(lookup(timing, "db_write_ms.p95")),
        "server_db_writes_per_msg_p50": _cell(lookup(timing, "db_writes_per_msg.p50")),
        "brake": ",".join(sorted(step.brake_reasons)),
        "danger": "yes" if step.danger_seen else "",
        "gate_peaks": " ".join(f"{k}={v}" for k, v in sorted(step.backstop_peaks.items())),
        "stop_reason": step.stop_reason or "",
    }


def write_reports(out_dir: Path, steps: list[StepResult], note: str = "") -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    csv_path = out_dir / f"load_tune-{stamp}.csv"
    md_path = out_dir / f"load_tune-{stamp}.md"
    rows = [row(step) for step in steps]
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    lines = ["| " + " | ".join(COLUMNS) + " |", "|" + "---|" * len(COLUMNS)]
    lines += ["| " + " | ".join(str(r[c]) for c in COLUMNS) + " |" for r in rows]
    md_path.write_text("\n".join(lines) + ("\n\n" + note if note else "") + "\n", encoding="utf-8")
    return csv_path, md_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--base-url", required=True)
    parser.add_argument(
        "--profile",
        help="login-ci uses existing <prefix>-000..019 accounts; otherwise classroom",
    )
    parser.add_argument("--json-out", help="write the login-ci report to this path")
    parser.add_argument(
        "--health-url",
        action="append",
        default=[],
        help="defaults to <base-url>/health/admission; repeat once per replica if reachable",
    )
    parser.add_argument("--course-id", default="b1ae79ed-e4a6-5b02-9abd-3a3ae944284b")
    parser.add_argument("--team-id", help="published assessment Team every student opens")
    parser.add_argument("--member-version-ids", default="", help="comma list; without --team-id")
    parser.add_argument("--steps", default="10,20,30,40,60")
    parser.add_argument("--message", action="append", default=[], help="repeat; default 3 answers")
    parser.add_argument("--account-prefix", default="loadtune")
    parser.add_argument("--password", default="load-tune-password-1")
    parser.add_argument("--group-name", default="Load tune")
    parser.add_argument("--max-load", type=float, default=8.0)
    parser.add_argument("--min-mem-mb", type=float, default=500.0)
    parser.add_argument("--send-again", type=int, default=3, help="re-sends after a busy 503")
    parser.add_argument("--timeout", type=float, default=240.0, help="per request, seconds")
    parser.add_argument("--settle-load", type=float, default=2.0)
    parser.add_argument("--settle-timeout", type=float, default=600.0)
    parser.add_argument("--out-dir", default="load_tune_results")
    parser.add_argument("--sweep", help="NAME=v1,v2,... (one limit, other limits fixed)")
    parser.add_argument("--sweep-verify", help="dotted /health/admission key holding the value")
    parser.add_argument("--sweep-students", type=int, default=40)
    parser.add_argument("--apply-cmd", help="shell template with {name} and {value}")
    parser.add_argument("--apply-timeout", type=float, default=300.0)
    args = parser.parse_args(argv)

    if selected_profile(args.profile) == "login-ci":
        try:
            report = run_login_ci(args.base_url, args.account_prefix, args.password, args.timeout)
        except ValueError as error:
            print(f"login-ci configuration/parameter error: {error}", file=sys.stderr)
            return 2
        encoded = json.dumps(report, ensure_ascii=False, allow_nan=False)
        if args.json_out:
            try:
                Path(args.json_out).write_text(encoded + "\n", encoding="utf-8")
            except OSError:
                print("could not write login-ci JSON report", file=sys.stderr)
                return 2
        print(encoded)
        return login_ci_exit_code(report)

    if args.team_id is None and not args.member_version_ids:
        parser.error("give --team-id, or --member-version-ids for private Teams")
    health_urls = args.health_url or [args.base_url.rstrip("/") + "/health/admission"]
    limits = Limits(max_load=args.max_load, min_mem_mb=args.min_mem_mb)
    plan = Plan(
        base_url=args.base_url,
        password=args.password,
        account_prefix=args.account_prefix,
        group_name=args.group_name,
        course_id=args.course_id,
        team_id=args.team_id,
        member_version_ids=[v for v in args.member_version_ids.split(",") if v],
        messages=args.message or list(DEFAULT_MESSAGES),
        timeout=args.timeout,
        send_again=args.send_again,
    )
    steps = [int(v) for v in args.steps.split(",") if v]
    largest = args.sweep_students if args.sweep else max(steps)
    print(f"preparing {largest} accounts ({args.account_prefix}-NNN)", flush=True)
    for index in range(largest):
        ensure_account(plan, index)

    results: list[StepResult] = []
    note = ""
    if args.sweep:
        if not (args.apply_cmd and args.sweep_verify):
            parser.error("--sweep needs --apply-cmd and --sweep-verify")
        name, _, raw_values = args.sweep.partition("=")
        swept: list[tuple[str, StepResult]] = []
        for value in [v for v in raw_values.split(",") if v]:
            apply_value(args.apply_cmd, name, value)
            wait_for_value(health_urls, args.sweep_verify, value, args.apply_timeout)
            wait_for_quiet(health_urls, args.settle_load, args.settle_timeout)
            step = run_step(plan, args.sweep_students, health_urls, limits, f"{name}={value}")
            results.append(step)
            swept.append((value, step))
            print(json.dumps(row(step), ensure_ascii=False), flush=True)
        best = recommend(swept)
        note = (
            f"Recommended {name}={best}: best throughput without touching a stop line."
            if best
            else f"No {name} value stayed clear of every stop line."
        )
    else:
        for students in steps:
            wait_for_quiet(health_urls, args.settle_load, args.settle_timeout)
            step = run_step(plan, students, health_urls, limits, f"N={students}")
            results.append(step)
            print(json.dumps(row(step), ensure_ascii=False), flush=True)
            if step.stop_reason or step.server_errors:
                note = f"Stopped at N={students}: {step.stop_reason or '5xx'}."
                break
    csv_path, md_path = write_reports(Path(args.out_dir), results, note)
    if note:
        print(note)
    print(f"wrote {csv_path} and {md_path}")
    p50s = [percentile(s.message_ms, 0.5) for s in results if s.message_ms]
    if p50s:
        print(f"message p50 across steps: {statistics.median([p for p in p50s if p]):.0f} ms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
