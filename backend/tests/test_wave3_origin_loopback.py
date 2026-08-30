"""Wave 3 private-Demo WebSocket Origin compatibility checks."""

from __future__ import annotations

import asyncio
import socket
import time
from collections.abc import Callable
from threading import Thread
from types import SimpleNamespace
from uuid import uuid4

import pytest
import uvicorn
from app.core.config import Settings
from app.core.db import Database
from app.modules.debates.playback.router import _websocket_origin_allowed
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

PRIVATE_CLASSROOM_ORIGIN = "http://192.168.2.19:8080"


def _settings(*, demo_mode: bool = True) -> Settings:
    return Settings(
        maya_env="test",
        session_secret="x" * 32,
        demo_mode=demo_mode,
        classroom_public_base_url=PRIVATE_CLASSROOM_ORIGIN,
    )


def _websocket(origin: str | None) -> SimpleNamespace:
    return SimpleNamespace(
        headers={"origin": origin} if origin is not None else {},
        url=SimpleNamespace(scheme="http", netloc="127.0.0.1:8080"),
    )


@pytest.mark.parametrize(
    "origin",
    [
        PRIVATE_CLASSROOM_ORIGIN,
        "http://localhost:8080",
        "http://127.0.0.1:8080",
    ],
    ids=["private-lan", "localhost", "ipv4-loopback"],
)
def test_private_demo_accepts_lan_and_same_port_loopback_origins(origin: str) -> None:
    assert _websocket_origin_allowed(_websocket(origin), _settings())


@pytest.mark.parametrize(
    "origin",
    [
        "http://evil.example:8080",
        "http://192.168.2.20:8080",
        "http://localhost:8081",
        "http://127.0.0.1:8081",
        "https://localhost:8080",
        "http://localhost:8080/",
        "http://localhost:8080/classroom/secret",
        "http://localhost:8080?token=secret",
        "http://localhost:8080?",
        "http://localhost:8080#fragment",
        "http://teacher:password@localhost:8080",
        "http://@localhost:8080",
        "http://localhost:",
        "http://[::1]:8080",
    ],
    ids=[
        "evil-host",
        "other-private-ip",
        "localhost-wrong-port",
        "ipv4-wrong-port",
        "https-downgrade",
        "trailing-slash-path",
        "path",
        "query",
        "empty-query",
        "fragment",
        "credentials",
        "empty-credentials",
        "empty-port",
        "ipv6-loopback",
    ],
)
def test_private_demo_rejects_non_loopback_or_malformed_origins(origin: str) -> None:
    assert not _websocket_origin_allowed(_websocket(origin), _settings())


def test_loopback_exception_is_disabled_outside_demo_mode() -> None:
    assert not _websocket_origin_allowed(
        _websocket("http://localhost:8080"),
        _settings(demo_mode=False),
    )


@pytest.mark.parametrize(
    "origin",
    [PRIVATE_CLASSROOM_ORIGIN, "http://localhost:8080", "http://127.0.0.1:8080"],
    ids=["private-lan", "localhost", "ipv4-loopback"],
)
def test_testclient_loopback_upgrade_reaches_session_classification(
    app_factory: Callable[..., tuple[FastAPI, Database, Settings]],
    origin: str,
) -> None:
    app, _database, settings = app_factory()
    settings.classroom_public_base_url = PRIVATE_CLASSROOM_ORIGIN

    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as raised:
            with client.websocket_connect(
                f"/api/v1/debates/{uuid4()}/events",
                headers={"origin": origin},
            ) as socket:
                socket.receive_json()
    assert raised.value.code == 4401
    assert raised.value.reason == ""


def test_non_demo_loopback_upgrade_closes_4403(
    app_factory: Callable[..., tuple[FastAPI, Database, Settings]],
) -> None:
    app, _database, settings = app_factory(demo_mode=False)
    settings.classroom_public_base_url = PRIVATE_CLASSROOM_ORIGIN

    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as raised:
            with client.websocket_connect(
                f"/api/v1/debates/{uuid4()}/events",
                headers={"origin": "http://localhost:8080"},
            ) as socket:
                socket.receive_json()
    assert raised.value.code == 4403
    assert raised.value.reason == ""


@pytest.mark.parametrize("origin", ["http://localhost:8080", "http://127.0.0.1:8080"])
def test_demo_loopback_origin_reaches_rest_csrf_authorization_layer(
    app_factory: Callable[..., tuple[FastAPI, Database, Settings]],
    origin: str,
) -> None:
    app, _database, settings = app_factory()
    settings.classroom_public_base_url = PRIVATE_CLASSROOM_ORIGIN

    with TestClient(app) as client:
        payload = client.post(
            "/api/v1/auth/login",
            json={"username": "teacher-demo", "password": "demo-password"},
        ).json()
        response = client.post(
            "/api/v1/auth/logout",
            headers={"Origin": origin, "X-CSRF-Token": payload["csrf_token"]},
        )
    assert response.status_code == 204


def test_demo_evil_origin_is_rejected_by_rest_csrf(
    app_factory: Callable[..., tuple[FastAPI, Database, Settings]],
) -> None:
    app, _database, settings = app_factory()
    settings.classroom_public_base_url = PRIVATE_CLASSROOM_ORIGIN

    with TestClient(app, base_url="http://evil.example:8080") as client:
        login_response = client.post(
            "/api/v1/auth/login",
            json={"username": "teacher-demo", "password": "demo-password"},
        )
        assert login_response.status_code == 200
        payload = login_response.json()
        response = client.post(
            "/api/v1/auth/logout",
            headers={
                "Origin": "http://evil.example:8080",
                "X-CSRF-Token": payload["csrf_token"],
            },
        )
    assert response.status_code == 403


def test_non_demo_loopback_origin_is_rejected_by_rest_csrf(
    app_factory: Callable[..., tuple[FastAPI, Database, Settings]],
) -> None:
    app, _database, settings = app_factory(demo_mode=False)
    settings.classroom_public_base_url = PRIVATE_CLASSROOM_ORIGIN

    with TestClient(app) as client:
        login_response = client.post(
            "/api/v1/auth/login",
            json={"username": "teacher-demo", "password": "demo-password"},
        )
        assert login_response.status_code == 200
        response = client.post(
            "/api/v1/auth/logout",
            headers={
                "Origin": "http://localhost:8080",
                "X-CSRF-Token": login_response.json()["csrf_token"],
            },
        )
    assert response.status_code == 403


def test_uvicorn_wire_origin_matrix(
    app_factory: Callable[..., tuple[FastAPI, Database, Settings]],
) -> None:
    """Exercise the private close codes through a real Uvicorn socket."""

    app, _database, settings = app_factory()
    settings.classroom_public_base_url = PRIVATE_CLASSROOM_ORIGIN
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])

    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="critical",
            access_log=False,
        )
    )
    thread = Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started, "Uvicorn did not become ready"

        async def close_codes() -> list[tuple[str, int, str]]:
            origins = [
                PRIVATE_CLASSROOM_ORIGIN,
                "http://localhost:8080",
                "http://127.0.0.1:8080",
                "http://evil.example:8080",
                "http://192.168.2.20:8080",
                "http://localhost:8081",
                "https://localhost:8080",
                "http://localhost:8080/secret",
            ]
            results: list[tuple[str, int, str]] = []
            for origin in origins:
                try:
                    async with connect(
                        f"ws://127.0.0.1:{port}/api/v1/debates/{uuid4()}/events",
                        origin=origin,
                        proxy=None,
                        open_timeout=5,
                    ) as socket_connection:
                        await socket_connection.recv()
                except ConnectionClosed as error:
                    results.append((origin, error.code, error.reason))
            return results

        results = asyncio.run(close_codes())
    finally:
        server.should_exit = True
        thread.join(timeout=5)

    assert [(origin, code) for origin, code, _reason in results] == [
        (PRIVATE_CLASSROOM_ORIGIN, 4401),
        ("http://localhost:8080", 4401),
        ("http://127.0.0.1:8080", 4401),
        ("http://evil.example:8080", 4403),
        ("http://192.168.2.20:8080", 4403),
        ("http://localhost:8081", 4403),
        ("https://localhost:8080", 4403),
        ("http://localhost:8080/secret", 4403),
    ]
    assert all(reason == "" for _origin, _code, reason in results)
