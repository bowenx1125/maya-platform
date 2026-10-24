from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, NoReturn

import httpx
import pytest
from app.core.errors import PlatformError, is_transient_infrastructure_error
from fastapi.testclient import TestClient
from sqlalchemy import exc as sa_exc


def _get(app: Any, raiser: Callable[[], NoReturn]) -> httpx.Response:
    @app.get("/explode", response_model=None)  # type: ignore[untyped-decorator]
    def explode() -> NoReturn:
        raiser()

    with TestClient(app, raise_server_exceptions=False) as client:
        return client.get("/explode")


def test_unhandled_exception_is_internal_error_and_sanitized(
    app_factory: Any, caplog: pytest.LogCaptureFixture
) -> None:
    app, _database, _settings = app_factory()

    def raiser() -> NoReturn:
        raise RuntimeError("provider secret and raw stack must not reach the client")

    target_logger = logging.getLogger("maya.backend")
    target_logger.disabled = False
    target_logger.propagate = True
    caplog.set_level(logging.ERROR, logger="maya.backend")
    response = _get(app, raiser)
    assert response.status_code == 500
    payload = response.json()
    assert payload["code"] == "internal_error"
    assert payload["message"] == "Something went wrong on the server."
    assert payload["details"] == {}
    assert payload["request_id"] == response.headers["X-Request-ID"]
    assert "provider secret" not in response.text
    assert "Traceback" not in response.text
    assert "Retry-After" not in response.headers
    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert f"request_id={payload['request_id']}" in logged
    assert "error_type=RuntimeError" in logged
    assert "provider secret" not in logged


def _psycopg_like_operational() -> sa_exc.OperationalError:
    return sa_exc.OperationalError("SELECT 1", {}, Exception("server closed the connection"))


def _postgres_undefined_table() -> sa_exc.ProgrammingError:
    return sa_exc.ProgrammingError(
        "SELECT 1 FROM missing", {}, Exception('relation "missing" does not exist')
    )


@pytest.mark.parametrize(
    ("make", "status", "code"),
    [
        (lambda: TimeoutError("slow"), 503, "provider_unavailable"),
        (lambda: ConnectionResetError("reset"), 503, "provider_unavailable"),
        (lambda: httpx.ConnectError("refused"), 503, "provider_unavailable"),
        (lambda: httpx.ReadTimeout("slow"), 503, "provider_unavailable"),
        (lambda: sa_exc.TimeoutError("pool exhausted"), 503, "provider_unavailable"),
        (_psycopg_like_operational, 503, "provider_unavailable"),
        (_postgres_undefined_table, 500, "internal_error"),
        (
            lambda: sa_exc.IntegrityError("DELETE", {}, Exception("fk violation")),
            500,
            "internal_error",
        ),
        (lambda: KeyError("missing"), 500, "internal_error"),
        (lambda: ValueError("bad"), 500, "internal_error"),
    ],
)
def test_unhandled_exception_classification(
    app_factory: Any, make: Callable[[], BaseException], status: int, code: str
) -> None:
    app, _database, _settings = app_factory()

    def raiser() -> NoReturn:
        raise make()

    response = _get(app, raiser)
    assert response.status_code == status
    assert response.json()["code"] == code
    assert is_transient_infrastructure_error(make()) is (status == 503)


@pytest.mark.parametrize(
    ("code", "status"),
    [
        ("host_memory_pressure", 503),
        ("adaptive_admission_busy", 503),
        ("llm_admission_busy", 429),
        ("provider_unavailable", 503),
    ],
)
def test_platform_errors_keep_their_own_code(app_factory: Any, code: str, status: int) -> None:
    """Admission, danger-latch and explicit provider outages are not remapped."""

    app, _database, _settings = app_factory()

    def raiser() -> NoReturn:
        raise PlatformError(code, "busy", status, {"retry_after_seconds": 3})

    response = _get(app, raiser)
    assert response.status_code == status
    assert response.json()["code"] == code
    # Both 429 limits and retryable 503 refusals say when to come back, so
    # pollers and retries slow down under load (60-student rerun, 2026-10-19).
    assert response.headers["Retry-After"] == "3"
