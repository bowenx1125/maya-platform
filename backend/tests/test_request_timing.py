from __future__ import annotations

import importlib.util
import io
import json
import logging
import sys
from pathlib import Path
from typing import Any

import pytest
from app.core import request_timing
from fastapi.testclient import TestClient

from tests.conftest import login

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "slow_endpoints_report.py"


def _lines(caplog: pytest.LogCaptureFixture, logger: str) -> list[dict[str, Any]]:
    return [json.loads(record.getMessage()) for record in caplog.records if record.name == logger]


def test_each_request_logs_route_template_status_and_db_time(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    _, csrf = login(client)
    with caplog.at_level(logging.INFO, logger="maya.request_timing"):
        missing = client.get(
            "/api/v1/debates/3f2b1c4d-0000-4000-8000-123456789abc",
            headers={"X-CSRF-Token": csrf, "Origin": "http://testserver"},
        )
        me = client.get("/api/v1/auth/me")
    lines = _lines(caplog, "maya.request_timing")
    assert missing.status_code == 404
    assert me.status_code == 200
    debate = next(line for line in lines if line["route"] == "/api/v1/debates/{debate_id}")
    assert debate["method"] == "GET"
    assert debate["status"] == 404
    # The concrete id never reaches the log line.
    assert "3f2b1c4d" not in json.dumps(lines)
    session_line = next(line for line in lines if line["route"] == "/api/v1/auth/me")
    assert session_line["db_queries"] >= 1
    assert session_line["db_ms"] >= 0
    assert session_line["host"] == request_timing.HOST
    assert session_line["slow"] is False
    assert set(session_line) >= {
        "event",
        "method",
        "route",
        "status",
        "ms",
        "db_ms",
        "db_queries",
        "provider_ms",
        "provider_calls",
        "host",
        "slow",
    }


def test_unmatched_paths_and_health_probes(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="maya.request_timing"):
        client.get("/api/v1/no-such-route/abc")
        client.get("/health/live")
    lines = _lines(caplog, "maya.request_timing")
    assert any(line["route"] == "unmatched" and line["status"] == 404 for line in lines)
    # A fast probe writes nothing.
    assert not any(line["route"] == "/health/live" for line in lines)


def test_provider_time_and_slow_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = iter([0.0, 0.0, 1.5, 1.5])
    monkeypatch.setattr(request_timing.time, "perf_counter", lambda: next(clock))
    timing, token = request_timing.begin()
    with request_timing.provider_call("tts"):
        pass
    record = request_timing.finish(
        timing, token, method="POST", route="/x", status=200, stream=False, log=False
    )
    assert record["tts_ms"] == 1500.0
    assert record["provider_ms"] == 1500.0
    assert record["provider_calls"] == 1
    assert record["slow"] is True
    # A closed collector ignores late work from background tasks.
    timing.add_provider("llm", 5.0)
    timing.add_query(5.0)
    assert timing.provider_calls == 1
    assert timing.db_queries == 0


def test_provider_time_outside_a_request_is_ignored() -> None:
    request_timing.add_provider_time("llm", 10.0)
    assert request_timing.current() is None


def test_client_metrics_are_logged_without_ids(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    _, csrf = login(client)
    with caplog.at_level(logging.INFO, logger="maya.client_metrics"):
        response = client.post(
            "/api/v1/client-metrics",
            headers={"X-CSRF-Token": csrf, "Origin": "http://testserver"},
            json={
                "metrics": [
                    {
                        "name": "debate_next_to_play",
                        "ms": 812.4,
                        "page": "/teacher/debates/3f2b1c4d-0000-4000-8000-123456789abc",
                    },
                    {"name": "page_first_render", "ms": 340},
                ]
            },
        )
    assert response.status_code == 204, response.text
    lines = _lines(caplog, "maya.client_metrics")
    assert lines[0] == {
        "event": "client_metric",
        "name": "debate_next_to_play",
        "ms": 812.4,
        "page": "/teacher/debates/{id}",
        "host": request_timing.HOST,
    }
    assert lines[1]["page"] is None


def test_client_metrics_need_a_session_and_a_known_name(client: TestClient) -> None:
    anonymous = client.post(
        "/api/v1/client-metrics",
        headers={"X-CSRF-Token": "x" * 32, "Origin": "http://testserver"},
        json={"metrics": [{"name": "page_first_render", "ms": 1}]},
    )
    assert anonymous.status_code == 401
    _, csrf = login(client)
    for body in (
        {"metrics": [{"name": "free_text", "ms": 1}]},
        {"metrics": [{"name": "page_first_render", "ms": -1}]},
        {"metrics": [{"name": "page_first_render", "ms": 1, "page": "/a?email=x@y"}]},
        {"metrics": []},
        {"metrics": [{"name": "page_first_render", "ms": 1}] * 21},
    ):
        response = client.post(
            "/api/v1/client-metrics",
            headers={"X-CSRF-Token": csrf, "Origin": "http://testserver"},
            json=body,
        )
        assert response.status_code == 400, body


def _load_report_script() -> Any:
    spec = importlib.util.spec_from_file_location("slow_endpoints_report", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolve string annotations through sys.modules.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_report_ranks_routes_by_p95_and_summarises_client_and_debate() -> None:
    script = _load_report_script()

    def request(route: str, ms: float, db_ms: float = 1.0, status: int = 200) -> str:
        record = {
            "event": "request_timing",
            "method": "GET",
            "route": route,
            "status": status,
            "ms": ms,
            "db_ms": db_ms,
            "db_queries": 2,
            "provider_ms": 0,
            "host": "b1",
            "slow": ms >= 1000,
        }
        return "INFO [maya.request_timing] " + json.dumps(record)

    lines = [request("/fast", ms) for ms in (5, 6, 7, 8)]
    lines += [request("/slow", ms, db_ms=40) for ms in (100, 200, 1500, 3000)]
    lines.append(request("/slow", 50, status=503))
    lines.append(
        'INFO [maya.client_metrics] {"event":"client_metric","name":"debate_next_to_play",'
        '"ms":900,"page":null,"host":"b1"}'
    )
    lines.append(
        "INFO [app.modules.debates.playback.router] debate_timing stage=next_request "
        "debate_id=x outcome=ok ms=420"
    )
    lines.append("INFO [uvicorn] unrelated line {not json")
    report = script.Report()
    report.feed(lines)
    summary = report.summary(top=20)
    assert [row["route"] for row in summary["routes"]] == ["GET /slow", "GET /fast"]
    slow = summary["routes"][0]
    assert slow["count"] == 5
    assert slow["p95"] == 3000.0
    assert slow["p50"] == 200.0
    assert slow["max"] == 3000.0
    assert slow["slow"] == 2
    assert slow["5xx"] == 1
    assert slow["avg_db_ms"] == round((40 * 4 + 1) / 5, 1)
    assert summary["client"]["debate_next_to_play"]["count"] == 1
    assert summary["debate"]["next_request"]["p95"] == 420.0

    out = io.StringIO()
    stdin = io.StringIO("\n".join(lines))
    monkey_stdout = __import__("contextlib").redirect_stdout(out)
    original_stdin = script.sys.stdin
    script.sys.stdin = stdin
    try:
        with monkey_stdout:
            assert script.main(["--top", "1"]) == 0
    finally:
        script.sys.stdin = original_stdin
    text = out.getvalue()
    assert "GET /slow" in text
    assert "GET /fast" not in text
    assert "debate_next_to_play" in text


def test_route_template_keeps_the_mount_prefix_and_drops_ids() -> None:
    class Route:
        def __init__(self, path: str) -> None:
            self.path = path

    template = request_timing.route_template
    assert (
        template(
            {"path": "/api/v1/debates/abc/audio/def", "route": Route("/debates/{d}/audio/{t}")}
        )
        == "/api/v1/debates/{d}/audio/{t}"
    )
    assert template({"path": "/health/ready", "route": Route("/health/ready")}) == "/health/ready"
    assert template({"path": "/api/v1/x"}) == "unmatched"
