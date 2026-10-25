"""Offline coverage for the explicit Internet-facing runtime profile."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier, Event, Lock
from typing import Any

import pytest
from app.core.config import Settings
from app.core.db import Database
from app.core.errors import PlatformError
from app.core.models import CourseMember, SessionRecord, User
from app.core.origin import origin_allowed, origin_tuple
from app.main import create_app
from app.modules.auth.abuse import AuthAbuseLimiter, client_key
from app.modules.auth.models import UserCredential
from app.modules.auth.service import session_hash
from app.modules.interactions.service import _public_origin
from app.seed import COURSE_ID, TEACHER_ID, seed_demo_data
from fastapi import Request
from fastapi.testclient import TestClient
from pwdlib import PasswordHash
from sqlalchemy import func, select

from tests.postgres_db import named_url

PUBLIC_ORIGIN = "https://maya.example.com"
PUBLIC_TEACHER_PASSWORD = "Teacher-account-strong-2026!"
DATABASE_OVERRIDE_PASSWORD = "Teacher-database-override-2026!"


def _settings(tmp_path: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "node_env": "production",
        "maya_env": "production",
        "demo_mode": False,
        "demo_quick_login": False,
        "demo_auto_confirm_provider": False,
        "session_secret": "production-profile-test-secret-0123456789",
        "classroom_public_base_url": PUBLIC_ORIGIN,
        "database_url": named_url(f"{tmp_path / 'maya.sqlite3'}"),
        "data_root": tmp_path / "data",
        "demo_accounts_file": tmp_path / "production-accounts.private.md",
        "demo_users_file": tmp_path / "legacy-demo-users.yaml",
        "auth_login_account_failure_limit": 10,
        "auth_login_client_failure_limit": 240,
        "auth_login_failure_window_seconds": 900,
        "auth_register_client_limit": 120,
        "auth_register_window_seconds": 3600,
        "auth_abuse_max_buckets": 8192,
        "auth_trust_gateway_x_forwarded_for": False,
        "llm_provider": "mock",
        "report_provider": "mock",
        "embedding_provider": "mock",
        "tts_provider": "mock",
        "voice_provider": "mock",
    }
    values.update(overrides)
    return Settings(**values)


def _write_teacher_catalog(path: Path, password: str = PUBLIC_TEACHER_PASSWORD) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "| account_key | username | display_name | password | role | group |\n"
        "| --- | --- | --- | --- | --- | --- |\n"
        f"| maya | maya | Maya | {password} | teacher | |\n",
        encoding="utf-8",
    )
    path.chmod(0o600)


def _new_app(
    tmp_path: Path,
    *,
    catalog: bool = True,
    settings_overrides: dict[str, Any] | None = None,
) -> tuple[Any, Database, Settings]:
    settings = _settings(tmp_path, **(settings_overrides or {}))
    if catalog:
        _write_teacher_catalog(settings.resolved_demo_accounts_file)
    database = Database(settings.database_url, settings.data_root)
    return create_app(settings, database), database, settings


def _origin_headers(origin: str = PUBLIC_ORIGIN) -> dict[str, str]:
    return {"Origin": origin}


def _post_login(client: TestClient, username: str, password: str) -> Any:
    return client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
        headers=_origin_headers(),
    )


def test_production_runtime_is_explicit_fail_closed_and_offline(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    settings.validate_runtime()

    assert settings.is_production
    assert not settings.is_test
    assert settings.classroom_public_origin == PUBLIC_ORIGIN
    assert _public_origin(settings) == PUBLIC_ORIGIN


def test_production_gateway_limits_only_auth_bodies_and_defers_error_headers() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    gateway = (repo_root / "infra/Caddyfile.production").read_text(encoding="utf-8")

    assert (
        "@auth_credentials path /api/v1/auth/login /api/v1/auth/register\n"
        "\trequest_body @auth_credentials {\n"
        "\t\tmax_size 16KB\n"
        "\t}"
    ) in gateway
    assert '@private_api path /api/*\n\theader @private_api >Cache-Control "private, no-store"' in (
        gateway
    )
    for response_header in (
        '>X-Frame-Options "DENY"',
        '>X-Content-Type-Options "nosniff"',
        '?Referrer-Policy "strict-origin-when-cross-origin"',
        '>Strict-Transport-Security "max-age=31536000"',
        ">Content-Security-Policy ",
    ):
        assert response_header in gateway
    # `>` would replace the classroom API's stricter `no-referrer` after the
    # backend sets it. `?` only fills the header when the upstream omitted it.
    assert ">Referrer-Policy" not in gateway


def test_production_gateway_discovers_every_backend_replica() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    gateway = (repo_root / "infra/Caddyfile.production").read_text(encoding="utf-8")
    compose = (repo_root / "docker-compose.yml").read_text(encoding="utf-8")

    # A static `backend:8000` is one upstream to Caddy however many replicas
    # answer behind it: the cookie cannot pin one and a single failed health
    # check takes the whole API down.
    assert "reverse_proxy backend:8000" not in gateway
    assert (
        "\t\treverse_proxy {\n\t\t\tdynamic a {\n\t\t\t\tname backend\n\t\t\t\tport 8000\n"
    ) in gateway
    for directive in ("lb_policy cookie", "fail_duration 10s", "max_fails 3"):
        assert directive in gateway
    # Active checks never run on dynamic upstreams; passive ones replace them.
    assert "health_uri" not in gateway
    # Busy 503s are admission answers, not a broken replica.
    assert "unhealthy_status" not in gateway
    # Caddy 2.10 kept routing a pinned cookie to a dead dynamic upstream.
    assert "image: caddy:2.11." in compose


def test_production_compose_requires_dedicated_data_and_config_roots() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    compose = (repo_root / "docker-compose.production.yml").read_text(encoding="utf-8")

    assert "${MAYA_PRODUCTION_DATA_DIR:?Set a dedicated production data directory}:/app/data" in (
        compose
    )
    assert (
        "${MAYA_PRODUCTION_CONFIG_DIR:?Set a dedicated production config directory}:/app/config:ro"
        in compose
    )
    database_url = (
        "DATABASE_URL: postgresql+psycopg://maya:"
        "${POSTGRES_PASSWORD:?Set POSTGRES_PASSWORD}@postgres:5432/maya"
    )
    assert database_url in compose
    # SQLite is gone: there is no startup import from a SQLite snapshot.
    assert "MAYA_POSTGRES_IMPORT_SOURCE" not in compose
    assert "replicas: ${BACKEND_REPLICAS:-2}" in compose
    assert 'command: ["postgres", "-c", "max_connections=200"]' in compose
    assert "ADAPTIVE_ADMISSION_MAX_IN_FLIGHT:" in compose
    assert "AUTH_HASH_CONCURRENCY: ${AUTH_HASH_CONCURRENCY:-2}" in compose
    assert "DATA_ROOT: /app/data" in compose
    assert "./data:/app/data" not in compose
    assert "./backend/config:/app/config" not in compose


def test_compose_passes_session_lifetime_to_backend() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    compose = (repo_root / "docker-compose.yml").read_text(encoding="utf-8")
    assert "SESSION_TTL_DAYS: ${SESSION_TTL_DAYS:-30}" in compose


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("demo_mode", True),
        ("demo_quick_login", True),
        ("demo_auto_confirm_provider", True),
    ],
)
def test_production_rejects_every_passwordless_or_standing_consent_flag(
    tmp_path: Path, field: str, value: bool
) -> None:
    settings = _settings(tmp_path, **{field: value})
    with pytest.raises(RuntimeError, match="DEMO_MODE"):
        settings.validate_runtime()


@pytest.mark.parametrize(
    "origin",
    [
        "http://maya.example.com",
        "https://localhost",
        "https://127.0.0.1",
        "https://8.8.8.8",
        "https://maya.local",
    ],
)
def test_production_requires_a_public_https_dns_origin(tmp_path: Path, origin: str) -> None:
    settings = _settings(tmp_path, classroom_public_base_url=origin)
    with pytest.raises(RuntimeError, match="HTTPS DNS origin"):
        settings.validate_runtime()


@pytest.mark.parametrize(
    "origin",
    [
        "https://user:secret@maya.example.com",
        "https://@maya.example.com",
        "https://maya.example.com/path",
        "https://maya.example.com?query",
        "https://maya.example.com?",
        "https://maya.example.com#fragment",
        "https://maya.example.com#",
        "https://maya.example.com\t.evil",
        " https://maya.example.com",
    ],
)
def test_configured_origin_rejects_url_components_and_controls(origin: str, tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        _settings(tmp_path, classroom_public_base_url=origin)


def test_production_marker_disables_pytest_test_mode_bypass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MAYA_TESTING", "1")
    settings = _settings(
        tmp_path,
        node_env="development",
        maya_env="production",
        session_secret=None,
    )

    assert settings.is_production
    assert not settings.is_test
    with pytest.raises(RuntimeError, match="SESSION_SECRET"):
        settings.validate_runtime()


def test_origin_parser_normalizes_default_ports_and_rejects_raw_delimiters() -> None:
    assert origin_tuple("https://maya.example.com:443") == origin_tuple(PUBLIC_ORIGIN)
    assert origin_tuple("http://maya.local:80") == origin_tuple("http://maya.local")
    for value in (
        "https://@maya.example.com",
        "https://maya.example.com?",
        "https://maya.example.com#",
        "https://maya.example.com\n.evil",
        "https://maya.example.com/path",
    ):
        assert origin_tuple(value) is None


def test_classroom_public_origin_keeps_demo_lan_and_allows_public_profile() -> None:
    assert (
        Settings(
            maya_env="test", classroom_public_base_url="http://192.168.1.20:8080"
        ).classroom_public_origin
        == "http://192.168.1.20:8080"
    )
    assert (
        Settings(
            maya_env="test", classroom_public_base_url="http://maya.local:8080"
        ).classroom_public_origin
        == "http://maya.local:8080"
    )
    settings = Settings(
        node_env="production",
        maya_env="production",
        demo_mode=False,
        demo_quick_login=False,
        demo_auto_confirm_provider=False,
        session_secret="production-profile-test-secret-0123456789",
        classroom_public_base_url=PUBLIC_ORIGIN,
    )
    assert settings.classroom_public_origin == PUBLIC_ORIGIN
    assert origin_allowed("https://maya.example.com:443", settings)
    assert not origin_allowed("https://maya.example.com.evil", settings)
    assert not origin_allowed("https://attacker.example", settings)


def test_production_catalog_provisions_teacher_and_demo_entrypoints_stay_hidden(
    tmp_path: Path,
) -> None:
    app, database, _settings_value = _new_app(tmp_path)
    with TestClient(app, base_url=PUBLIC_ORIGIN) as client:
        logged_in = _post_login(client, "maya", PUBLIC_TEACHER_PASSWORD)
        assert logged_in.status_code == 200, logged_in.text
        assert logged_in.json()["user"]["courses"] == [{"course_id": COURSE_ID, "role": "teacher"}]
        assert "Secure" in logged_in.headers["set-cookie"]
        for path in ("/api/v1/auth/demo-identities",):
            response = client.get(path)
            assert response.status_code == 404
        assert (
            client.post(
                "/api/v1/auth/quick-login",
                json={"user_id": TEACHER_ID},
            ).status_code
            == 404
        )
        assert (
            client.post(
                "/api/v1/auth/switch",
                json={"user_id": TEACHER_ID},
                headers={
                    **_origin_headers(),
                    "X-CSRF-Token": logged_in.json()["csrf_token"],
                },
            ).status_code
            == 404
        )
        for response in (logged_in, client.get("/api/v1/auth/demo-identities")):
            assert response.headers["cache-control"] == "private, no-store"
            assert response.headers["x-content-type-options"] == "nosniff"
            assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    with database.session() as session:
        assert (
            session.scalar(
                select(CourseMember.user_id).where(
                    CourseMember.course_id == COURSE_ID,
                    CourseMember.user_id == TEACHER_ID,
                    CourseMember.role == "teacher",
                )
            )
            == TEACHER_ID
        )


def test_production_auth_requires_exact_origin_before_hash_or_session_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, database, _settings_value = _new_app(tmp_path)
    with TestClient(app, base_url=PUBLIC_ORIGIN) as client:
        called = False

        def unexpected_hash(*_args: Any, **_kwargs: Any) -> tuple[bool, str | None]:
            nonlocal called
            called = True
            raise AssertionError("password verification must not run for a foreign origin")

        monkeypatch.setattr("app.modules.auth.router.verify_database_password", unexpected_hash)
        response = client.post(
            "/api/v1/auth/login",
            json={"username": "maya", "password": PUBLIC_TEACHER_PASSWORD},
            headers={"Origin": "https://attacker.example", "Host": "attacker.example"},
        )
        assert response.status_code == 403
        assert not called
        assert (
            client.post(
                "/api/v1/auth/register",
                json={
                    "username": "foreign-origin",
                    "password": "student-password-1",
                    "group_name": "Class A",
                },
                headers={"Origin": "https://attacker.example", "Host": "attacker.example"},
            ).status_code
            == 403
        )
    with database.session() as session:
        assert session.scalar(select(func.count(SessionRecord.id_hash))) == 0
        assert session.scalar(select(User.id).where(User.username == "foreign-origin")) is None


def test_auth_inputs_are_bounded_before_password_verification(tmp_path: Path) -> None:
    app, _database, _settings_value = _new_app(tmp_path)
    with TestClient(app, base_url=PUBLIC_ORIGIN) as client:
        for body in (
            {"username": "u" * 65, "password": "short"},
            {"username": "maya", "password": "p" * 129},
        ):
            response = client.post("/api/v1/auth/login", json=body, headers=_origin_headers())
            assert response.status_code == 400
            assert response.json()["code"] == "malformed_request"


def test_login_failures_preserve_account_not_found_and_password_incorrect_then_limit(
    tmp_path: Path,
) -> None:
    app, database, _settings_value = _new_app(
        tmp_path,
        settings_overrides={
            "auth_login_account_failure_limit": 1,
            "auth_login_client_failure_limit": 20,
            "auth_login_failure_window_seconds": 30,
        },
    )
    with TestClient(app, base_url=PUBLIC_ORIGIN) as client:
        register = client.post(
            "/api/v1/auth/register",
            json={
                "username": "known-student",
                "password": "student-password-1",
                "group_name": "Class A",
            },
            headers=_origin_headers(),
        )
        assert register.status_code == 201
        assert _post_login(client, "known-student", "wrong-password-1").json()["code"] == (
            "password_incorrect"
        )
        client.cookies.clear()
        missing = _post_login(client, "missing-student", "wrong-password-1")
        assert missing.status_code == 401
        assert missing.json()["code"] == "account_not_found"
        limited = _post_login(client, "missing-student", "wrong-password-1")
        assert limited.status_code == 429
        retry_after = limited.json()["details"]["retry_after_seconds"]
        assert retry_after >= 1
        assert limited.headers["retry-after"] == str(retry_after)
        unit = "second" if retry_after == 1 else "seconds"
        assert limited.json()["message"] == (
            f"Too many authentication attempts. Try again in {retry_after} {unit}."
        )
        assert limited.headers["cache-control"] == "private, no-store"
    with database.session() as session:
        assert session.scalar(select(func.count(SessionRecord.id_hash))) == 1


def test_successful_logins_from_many_accounts_do_not_consume_shared_client_failures(
    tmp_path: Path,
) -> None:
    app, _database, _settings_value = _new_app(
        tmp_path,
        settings_overrides={
            "auth_login_account_failure_limit": 2,
            "auth_login_client_failure_limit": 3,
        },
    )
    with TestClient(app, base_url=PUBLIC_ORIGIN) as client:
        for index in range(12):
            response = client.post(
                "/api/v1/auth/register",
                json={
                    "username": f"classmate-{index:02d}",
                    "password": "student-password-1",
                    "group_name": "Class A",
                },
                headers=_origin_headers(),
            )
            assert response.status_code == 201, response.text
        for index in range(12):
            client.cookies.clear()
            response = _post_login(client, f"classmate-{index:02d}", "student-password-1")
            assert response.status_code == 200, response.text


def test_client_wide_login_limit_counts_failures_across_accounts(tmp_path: Path) -> None:
    app, database, _settings_value = _new_app(
        tmp_path,
        settings_overrides={
            "auth_login_account_failure_limit": 10,
            "auth_login_client_failure_limit": 2,
        },
    )
    with TestClient(app, base_url=PUBLIC_ORIGIN) as client:
        for username in ("missing-one", "missing-two"):
            response = _post_login(client, username, "wrong-password-1")
            assert response.status_code == 401
            assert response.json()["code"] == "account_not_found"
        limited = _post_login(client, "missing-three", "wrong-password-1")
        assert limited.status_code == 429
        assert int(limited.headers["retry-after"]) >= 1
    with database.session() as session:
        assert session.scalar(select(func.count(SessionRecord.id_hash))) == 0


def test_signup_limit_denial_does_not_create_an_account_or_session(tmp_path: Path) -> None:
    app, database, _settings_value = _new_app(
        tmp_path,
        settings_overrides={"auth_register_client_limit": 1},
    )
    with TestClient(app, base_url=PUBLIC_ORIGIN) as client:
        first = client.post(
            "/api/v1/auth/register",
            json={
                "username": "first-student",
                "password": "student-password-1",
                "group_name": "Class A",
            },
            headers=_origin_headers(),
        )
        assert first.status_code == 201
        limited = client.post(
            "/api/v1/auth/register",
            json={
                "username": "second-student",
                "password": "student-password-1",
                "group_name": "Class A",
            },
            headers=_origin_headers(),
        )
        assert limited.status_code == 429
        assert (
            int(limited.headers["retry-after"]) == limited.json()["details"]["retry_after_seconds"]
        )
    with database.session() as session:
        assert session.scalar(select(User.id).where(User.username == "second-student")) is None
        assert session.scalar(select(func.count(SessionRecord.id_hash))) == 1


def _register(client: TestClient, username: str, group_name: str = "Class A") -> Any:
    return client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": "student-password-1", "group_name": group_name},
        headers=_origin_headers(),
    )


def test_signup_over_its_limit_gets_429_without_entering_the_pressure_queue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#141: a rate-limited client must not hold a place in the shared queue."""

    from contextlib import contextmanager

    from app.modules.auth import router as auth_router

    app, _database, _settings_value = _new_app(
        tmp_path, settings_overrides={"auth_register_client_limit": 1}
    )
    real_slot = auth_router.adaptive_slot
    entered: list[str] = []

    @contextmanager
    def tracked_slot(kind: str, settings: Any) -> Any:
        entered.append(kind)
        with real_slot(kind, settings):
            yield

    monkeypatch.setattr(auth_router, "adaptive_slot", tracked_slot)
    with TestClient(app, base_url=PUBLIC_ORIGIN) as client:
        assert _register(client, "first-student").status_code == 201
        assert entered == ["login"]
        limited = _register(client, "second-student")
    assert limited.status_code == 429
    assert entered == ["login"]


def test_signup_rejects_a_bad_group_name_before_hashing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.modules.auth import router as auth_router

    app, _database, _settings_value = _new_app(tmp_path)
    hashed: list[str] = []
    monkeypatch.setattr(
        auth_router,
        "hash_registration_password",
        lambda password, settings: hashed.append(password) or "unused",
    )
    with TestClient(app, base_url=PUBLIC_ORIGIN) as client:
        response = _register(client, "valid-student", group_name="   ")
    assert response.status_code == 422, response.text
    assert hashed == []


def test_signup_busy_refusal_does_not_spend_the_client_allowance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from contextlib import contextmanager

    from app.modules.auth import router as auth_router

    app, database, _settings_value = _new_app(
        tmp_path, settings_overrides={"auth_register_client_limit": 1}
    )
    real_turn = auth_router.registration_turn
    refusals = {"left": 1}

    @contextmanager
    def busy_once(settings: Any) -> Any:
        if refusals["left"]:
            refusals["left"] -= 1
            raise PlatformError("adaptive_admission_busy", "busy", 503, {"retryable": True})
        with real_turn(settings):
            yield

    monkeypatch.setattr(auth_router, "registration_turn", busy_once)
    with TestClient(app, base_url=PUBLIC_ORIGIN) as client:
        assert _register(client, "retrying-student").status_code == 503
        # The one allowed attempt is still available for the retry.
        assert _register(client, "retrying-student").status_code == 201
        assert _register(client, "third-student").status_code == 429
    with database.session() as session:
        assert session.scalar(select(User.id).where(User.username == "retrying-student"))


def test_limiter_recovery_expiry_concurrency_and_bounded_memory() -> None:
    class FakeClock:
        now = 100.0

        def __call__(self) -> float:
            return self.now

    clock = FakeClock()
    settings = Settings(
        maya_env="test",
        auth_login_account_failure_limit=3,
        auth_login_client_failure_limit=8,
        auth_login_failure_window_seconds=10,
        auth_register_client_limit=2,
        auth_register_window_seconds=10,
        auth_abuse_max_buckets=128,
    )
    limiter = AuthAbuseLimiter(clock=clock)
    barriers = Barrier(8)
    completed = Event()
    release = Event()
    state_lock = Lock()
    accepted = 0
    attempted = 0

    def attempt() -> str:
        nonlocal accepted, attempted
        barriers.wait(timeout=2)
        try:
            reservation = limiter.reserve_login("ip:192.0.2.1", " Maya ", settings)
        except PlatformError as error:
            assert error.status_code == 429
            with state_lock:
                attempted += 1
                if attempted == 8:
                    completed.set()
            return "limited"
        with state_lock:
            accepted += 1
            attempted += 1
            if attempted == 8:
                completed.set()
        release.wait(timeout=2)
        limiter.finish_login(reservation, failed=True)
        return "admitted"

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(attempt) for _ in range(8)]
        assert completed.wait(timeout=2)
        release.set()
        outcomes = [future.result(timeout=2) for future in futures]

    assert accepted == 3
    assert outcomes.count("admitted") == 3
    assert outcomes.count("limited") == 5
    with pytest.raises(PlatformError) as blocked:
        limiter.reserve_login("ip:192.0.2.1", "maya", settings)
    assert blocked.value.details["retry_after_seconds"] == 10

    clock.now += 11
    recovered = limiter.reserve_login("ip:192.0.2.1", "MAYA", settings)
    limiter.finish_login(recovered, failed=False)
    limiter.consume_registration("ip:198.51.100.250", settings)
    limiter.consume_registration("ip:198.51.100.250", settings)
    with pytest.raises(PlatformError):
        limiter.consume_registration("ip:198.51.100.250", settings)
    clock.now += 11
    limiter.consume_registration("ip:198.51.100.250", settings)
    capacity_denials = 0
    for index in range(140):
        try:
            limiter.consume_registration(f"ip:198.51.100.{index}", settings)
        except PlatformError as error:
            assert error.status_code == 429
            capacity_denials += 1
    assert capacity_denials > 0
    assert limiter.bucket_count() <= 3 * settings.auth_abuse_max_buckets


@pytest.mark.parametrize(
    ("account_limit", "client_limit"),
    [(1, 10), (10, 1)],
)
def test_small_capacity_preserves_live_login_history(account_limit: int, client_limit: int) -> None:
    class FakeClock:
        now = 100.0

        def __call__(self) -> float:
            return self.now

    clock = FakeClock()
    settings = Settings(
        maya_env="test",
        auth_login_account_failure_limit=account_limit,
        auth_login_client_failure_limit=client_limit,
        auth_login_failure_window_seconds=10,
    ).model_copy(update={"auth_abuse_max_buckets": 2})
    limiter = AuthAbuseLimiter(clock=clock)

    target = limiter.reserve_login("ip:192.0.2.10", "target", settings)
    limiter.finish_login(target, failed=True)
    unrelated = limiter.reserve_login("ip:192.0.2.11", "unrelated", settings)
    limiter.finish_login(unrelated, failed=True)

    with pytest.raises(PlatformError) as capacity_denied:
        limiter.reserve_login("ip:192.0.2.12", "rotating", settings)
    assert capacity_denied.value.status_code == 429
    assert capacity_denied.value.details["retry_after_seconds"] == 10

    with pytest.raises(PlatformError) as target_denied:
        limiter.reserve_login("ip:192.0.2.10", "target", settings)
    assert target_denied.value.status_code == 429
    assert target_denied.value.details["retry_after_seconds"] == 10

    clock.now = 110.0
    recovered = limiter.reserve_login("ip:192.0.2.10", "target", settings)
    limiter.finish_login(recovered, failed=False)
    assert limiter.bucket_count() <= 3 * settings.auth_abuse_max_buckets


def test_default_capacity_preserves_registration_history_until_exact_expiry() -> None:
    class FakeClock:
        now = 1_000.0

        def __call__(self) -> float:
            return self.now

    clock = FakeClock()
    settings = Settings(maya_env="test")
    assert settings.auth_abuse_max_buckets == 8_192
    limiter = AuthAbuseLimiter(clock=clock)
    victim = "ip:2001:db8::1"

    for _ in range(settings.auth_register_client_limit):
        limiter.consume_registration(victim, settings)
    with pytest.raises(PlatformError) as initial_denial:
        limiter.consume_registration(victim, settings)
    assert initial_denial.value.details["retry_after_seconds"] == 3_600

    for index in range(settings.auth_abuse_max_buckets - 1):
        limiter.consume_registration(f"ip:2001:db8::{index + 2}", settings)
    assert limiter.bucket_count() == settings.auth_abuse_max_buckets

    with pytest.raises(PlatformError) as unseen_denial:
        limiter.consume_registration("ip:2001:db8::ffff", settings)
    assert unseen_denial.value.status_code == 429
    assert unseen_denial.value.details["retry_after_seconds"] == 3_600
    with pytest.raises(PlatformError) as victim_denial:
        limiter.consume_registration(victim, settings)
    assert victim_denial.value.details["retry_after_seconds"] == 3_600

    clock.now += settings.auth_register_window_seconds
    limiter.consume_registration(victim, settings)


def test_client_identity_ignores_untrusted_or_multihop_forwarded_headers() -> None:
    def request(peer: str | None, forwarded: str | None) -> Request:
        headers = [] if forwarded is None else [(b"x-forwarded-for", forwarded.encode())]
        scope: dict[str, Any] = {"type": "http", "headers": headers}
        if peer is not None:
            scope["client"] = (peer, 12345)
        return Request(scope)

    untrusted = Settings(maya_env="test", auth_trust_gateway_x_forwarded_for=False)
    trusted = Settings(maya_env="test", auth_trust_gateway_x_forwarded_for=True)
    assert client_key(request("10.0.0.5", "203.0.113.8"), untrusted) == "ip:10.0.0.5"
    assert client_key(request("10.0.0.5", "203.0.113.8"), trusted) == "ip:203.0.113.8"
    assert client_key(request("10.0.0.5", "203.0.113.8, 10.0.0.1"), trusted) == "ip:10.0.0.5"
    assert client_key(request("2001:db8::1", None), untrusted) == "ip:2001:db8::1"
    assert client_key(request(None, None), untrusted) == "peer:unknown"


def test_production_without_private_catalog_requires_existing_teacher_password(
    tmp_path: Path,
) -> None:
    app, _database, _settings_value = _new_app(tmp_path, catalog=False)
    with pytest.raises(RuntimeError, match="private Teacher credential catalog"):
        with TestClient(app, base_url=PUBLIC_ORIGIN):
            pass


def test_production_bootstrap_preserves_database_password_override(tmp_path: Path) -> None:
    app, database, settings = _new_app(tmp_path)
    database.upgrade_schema()
    with database.session() as session:
        seed_demo_data(session)
        session.add(
            UserCredential(
                user_id=TEACHER_ID,
                username="maya",
                password_hash=PasswordHash.recommended().hash(DATABASE_OVERRIDE_PASSWORD),
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
    with TestClient(app, base_url=PUBLIC_ORIGIN) as client:
        accepted = _post_login(client, "maya", DATABASE_OVERRIDE_PASSWORD)
        assert accepted.status_code == 200, accepted.text
        client.cookies.clear()
        old_catalog_password = _post_login(client, "maya", PUBLIC_TEACHER_PASSWORD)
        assert old_catalog_password.status_code == 401
        assert old_catalog_password.json()["code"] == "password_incorrect"
    with database.session() as session:
        stored = session.get(UserCredential, TEACHER_ID)
        assert stored is not None
        assert PasswordHash.recommended().verify(DATABASE_OVERRIDE_PASSWORD, stored.password_hash)
        assert (
            session.scalar(
                select(CourseMember.user_id).where(
                    CourseMember.course_id == COURSE_ID,
                    CourseMember.user_id == TEACHER_ID,
                    CourseMember.role == "teacher",
                )
            )
            == TEACHER_ID
        )


def test_retry_denial_keeps_prior_authenticated_session_active(tmp_path: Path) -> None:
    app, database, _settings_value = _new_app(
        tmp_path,
        settings_overrides={
            "auth_login_account_failure_limit": 1,
            "auth_login_client_failure_limit": 10,
        },
    )
    with TestClient(app, base_url=PUBLIC_ORIGIN) as client:
        initial = _post_login(client, "maya", PUBLIC_TEACHER_PASSWORD)
        assert initial.status_code == 200
        raw_cookie = client.cookies.get("maya_session")
        assert raw_cookie is not None
        failed = _post_login(client, "not-a-user", "invalid-password")
        assert failed.status_code == 401
        denied = _post_login(client, "not-a-user", "invalid-password")
        assert denied.status_code == 429
        with database.session() as session:
            stored = session.get(SessionRecord, session_hash(raw_cookie))
            assert stored is not None
            assert stored.revoked_at is None
    with database.session() as session:
        assert session.scalar(select(func.count(SessionRecord.id_hash))) == 1
