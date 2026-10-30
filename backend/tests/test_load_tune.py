"""Pure logic of scripts/load_tune.py, the #140 tuning tool (no server needed)."""

from __future__ import annotations

import csv
import json
import sys
import threading
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import load_tune as lt  # noqa: E402


def test_login_ci_profile_parse_and_frozen_configuration() -> None:
    assert lt.selected_profile(None) == "classroom"
    assert lt.selected_profile("classroom") == "classroom"
    assert lt.selected_profile("other") == "classroom"
    assert lt.selected_profile("login-ci") == "login-ci"
    config = lt.load_login_ci_config()
    assert (config.warmup, config.samples, config.concurrency, config.repeat) == (2, 20, 2, 3)
    assert (config.errors_max, config.p95_ms_max) == (0, 200)
    assert "9c68d42b" in config.source


def test_login_ci_configuration_rejects_changed_fixed_workload(tmp_path: Path) -> None:
    config_path = Path(lt.__file__).with_name("load_tune_login_ci.json")
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["samples"] = 21
    altered = tmp_path / "login-ci.json"
    altered.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="frozen 2/20/2/3"):
        lt.load_login_ci_config(altered)


def test_login_ci_attempt_posts_only_login_and_counts_non_200_as_error(
    monkeypatch: Any,
) -> None:
    calls: list[tuple[str, str, dict[str, str]]] = []

    class FakeClient:
        def __init__(self, _base_url: str, _timeout: float) -> None:
            pass

        def call(self, method: str, path: str, body: dict[str, str]) -> lt.HttpResult:
            calls.append((method, path, body))
            return lt.HttpResult(204, "")

    monkeypatch.setattr(lt, "Client", FakeClient)
    attempt = lt.login_ci_attempt("http://example.test", "student", "secret", 3, 1.0)
    assert calls == [
        ("POST", "/api/v1/auth/login", {"username": "student-003", "password": "secret"})
    ]
    assert attempt.error is True
    assert attempt.latency_ms >= 0


def test_login_ci_report_fields_and_median_p95_gate() -> None:
    config = lt.load_login_ci_config()
    batches = [
        lt.LoginCiBatch([float(value) for value in range(start, start + 20)], 0, 2.0)
        for start in (100, 120, 140)
    ]
    report = lt.build_login_ci_report(config, batches)
    assert set(report) >= {
        "profile",
        "warmup",
        "samples",
        "concurrency",
        "repeat",
        "rounds",
        "aggregate",
        "gates",
        "passed",
    }
    assert report["profile"] == "login-ci"
    assert (report["warmup"], report["samples"], report["concurrency"], report["repeat"]) == (
        2,
        20,
        2,
        3,
    )
    assert [round_report["total_requests"] for round_report in report["rounds"]] == [20, 20, 20]
    assert [round_report["p95_ms"] for round_report in report["rounds"]] == [118.0, 138.0, 158.0]
    assert report["aggregate"] == {
        "total_requests": 60,
        "errors": 0,
        "p50_ms": 129.0,
        "p95_ms": 156.0,
        "p95_median_ms": 138.0,
        "throughput_rps": 10.0,
    }
    assert report["gates"]["errors_max"] == 0
    assert report["gates"]["p95_ms_max"] == 200
    assert "测试-性能压测-50用户-9c68d42b.md" in report["gates"]["source"]
    assert report["passed"] is True
    assert lt.login_ci_exit_code(report) == 0


def test_login_ci_failures_return_nonzero_for_errors_slow_p95_or_warmup_error() -> None:
    config = lt.load_login_ci_config()
    fast = [lt.LoginCiBatch([120.0] * 20, 0, 1.0) for _ in range(3)]
    request_error = fast.copy()
    request_error[0] = lt.LoginCiBatch([120.0] * 20, 1, 1.0)
    slow = [lt.LoginCiBatch([201.0] * 20, 0, 1.0) for _ in range(3)]
    assert lt.login_ci_exit_code(lt.build_login_ci_report(config, request_error)) != 0
    assert lt.login_ci_exit_code(lt.build_login_ci_report(config, slow)) != 0
    assert lt.login_ci_exit_code(lt.build_login_ci_report(config, fast, warmup_errors=1)) != 0


def test_login_ci_invalid_parameter_exits_nonzero_without_server() -> None:
    assert lt.main(["--profile", "login-ci", "--base-url", "not-a-url"]) == 2


def test_percentile_is_nearest_rank() -> None:
    assert lt.percentile([], 0.5) is None
    assert lt.percentile([5.0], 0.95) == 5.0
    values = [float(v) for v in range(1, 101)]
    assert lt.percentile(values, 0.5) == 50.0
    assert lt.percentile(values, 0.95) == 95.0


def test_parse_sse_reads_named_events_with_ids() -> None:
    body = [
        "id: 1\n",
        "event: turn_started\n",
        'data: {"turn_id":"t"}\n',
        "\n",
        ": keep-alive\n",
        "id: 2\n",
        "event: turn_done\n",
        'data: {"turn_id":"t"}\n',
        "\n",
    ]
    assert list(lt.parse_sse(iter(body))) == [
        ("turn_started", '{"turn_id":"t"}'),
        ("turn_done", '{"turn_id":"t"}'),
    ]


def test_stop_lines_are_load_above_8_and_memory_below_500() -> None:
    limits = lt.Limits()
    assert lt.stop_reason({"load_1m": 8.0, "mem_available_mb": 500.0}, limits) is None
    assert "load_1m" in str(lt.stop_reason({"load_1m": 8.01}, limits))
    assert "MemAvailable" in str(lt.stop_reason({"mem_available_mb": 499.0}, limits))
    assert lt.stop_reason({}, limits) is None


def _step(label: str, completed: int, seconds: float, **extra: Any) -> lt.StepResult:
    step = lt.StepResult(label=label, students=40, started=0.0, finished=seconds)
    step.completed_messages = completed
    for name, value in extra.items():
        setattr(step, name, value)
    return step


def test_sweep_recommends_best_throughput_that_never_hit_a_stop_line() -> None:
    results = [
        ("8", _step("8", 60, 60.0)),
        ("17", _step("17", 90, 60.0)),
        ("24", _step("24", 120, 60.0, stop_reason="load_1m 9.10 > 8")),
        ("32", _step("32", 150, 60.0, server_errors=1)),
    ]
    assert lt.recommend(results) == "17"
    assert lt.recommend([("8", _step("8", 10, 60.0, stop_reason="x"))]) is None


def test_health_sampler_tracks_peaks_and_raises_the_stop_flag() -> None:
    step = lt.StepResult(label="N=20", students=20)
    stop = threading.Event()
    sampler = lt.HealthSampler([], step, lt.Limits(), stop)
    sampler.absorb(
        {
            "load_1m": 3.0,
            "mem_available_mb": 1800.0,
            "queue_depth": 7,
            "brake": {"active_reason": "db_write_p95"},
            "backstop_usage": {"write_guard": {"in_flight": 8, "waiters": 5}},
            "message_timing": {"queue_wait_ms": {"p50": 12.0}},
        }
    )
    assert not stop.is_set()
    sampler.absorb({"load_1m": 8.5, "mem_available_mb": 1500.0, "danger": True})
    assert stop.is_set()
    assert step.max_load == 8.5 and step.min_mem_mb == 1500.0
    assert step.max_queue_depth == 7
    assert step.brake_reasons == {"db_write_p95"}
    assert step.backstop_peaks == {"write_guard": 13}
    assert step.danger_seen is True
    assert step.stop_reason is not None and "load_1m" in step.stop_reason


def test_busy_refusals_are_resent_and_counted_but_other_5xx_are_errors(
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(lt.time, "sleep", lambda _seconds: None)
    plan = lt.Plan(
        base_url="http://x",
        password="p",
        account_prefix="a",
        group_name="g",
        course_id="c",
        team_id="t",
        member_version_ids=[],
        messages=["m"],
        timeout=1.0,
        send_again=3,
    )
    step = lt.StepResult(label="N=1", students=1)
    lock = threading.Lock()
    answers = iter(
        [
            lt.HttpResult(503, "", "adaptive_admission_busy"),
            lt.HttpResult(503, "", "write_pressure"),
            lt.HttpResult(200, "{}"),
        ]
    )
    assert lt._with_send_again(plan, step, lock, lambda: next(answers)).status == 200
    assert step.refusals == 2 and step.server_errors == 0
    assert lt._with_send_again(plan, step, lock, lambda: lt.HttpResult(502, "")).status == 502
    assert step.server_errors == 1


def test_reports_are_written_as_csv_and_markdown(tmp_path: Path) -> None:
    step = _step("N=10", 30, 60.0)
    step.message_ms = [1000.0, 2000.0, 3000.0]
    step.timing = {"db_writes_per_msg": {"p50": 0.0}, "queue_wait_ms": {"p50": 4.0, "p95": 9.0}}
    csv_path, md_path = lt.write_reports(tmp_path, [step], "Stopped at N=10: test.")
    rows = list(csv.DictReader(csv_path.open(encoding="utf-8")))
    assert rows[0]["label"] == "N=10"
    assert rows[0]["msg_p50_ms"] == "2000"
    assert rows[0]["throughput_per_min"] == "30.0"
    assert rows[0]["server_db_writes_per_msg_p50"] == "0.0"
    markdown = md_path.read_text(encoding="utf-8")
    assert markdown.startswith("| label | students |")
    assert "Stopped at N=10: test." in markdown
