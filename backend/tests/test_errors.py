from __future__ import annotations

from typing import Any, NoReturn

from fastapi.testclient import TestClient


def test_unhandled_exception_is_sanitized(app_factory: Any) -> None:
    app, _database, _settings = app_factory()

    @app.get("/explode", response_model=None)  # type: ignore[untyped-decorator]
    def explode() -> NoReturn:
        raise RuntimeError("provider secret and raw stack must not reach the client")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/explode")
    assert response.status_code == 503
    payload = response.json()
    assert payload["code"] == "provider_unavailable"
    assert payload["message"] == "The service is temporarily unavailable."
    assert payload["details"] == {}
    assert payload["request_id"] == response.headers["X-Request-ID"]
    assert "provider secret" not in response.text
    assert "Traceback" not in response.text
