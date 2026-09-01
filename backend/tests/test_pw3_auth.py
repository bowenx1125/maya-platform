from __future__ import annotations

import logging
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import app.modules.auth.credentials as credential_state
import pytest
from app.core.config import Settings
from app.core.db import Database
from app.core.models import Course, CourseMember, GroupMember, SessionRecord, User
from app.main import create_app
from app.modules.auth.credentials import (
    CATALOG_MAX_BYTES,
    CredentialFileError,
    account_id,
    load_desired_graph,
    parse_accounts_markdown,
    verify_password,
)
from app.modules.auth.models import DemoAccountBinding
from app.modules.auth.service import (
    AccountSyncError,
    bootstrap_demo_accounts,
    create_rotated_session,
    session_hash,
    sync_demo_accounts,
)
from app.seed import seed_demo_data
from fastapi.testclient import TestClient
from sqlalchemy import select

ACCOUNT_TABLE = """# private Demo catalog
| account_key | username | display_name | password | role | group |
| --- | --- | --- | --- | --- | --- |
| maya | maya | Demo Teacher | demo-password | teacher | |
| bowen | bowen | Bowen Student 1 | demo-password | student | group-demo |
| kaikai | kaikai | Kaikai Student 1 | demo-password | student | group-demo |
"""


def _app(tmp_path: Path, *, quick_login: bool = True) -> tuple[Any, Database, Settings, Path]:
    accounts = tmp_path / "accounts.private.md"
    accounts.write_text(ACCOUNT_TABLE, encoding="utf-8")
    accounts.chmod(0o600)
    settings = Settings(
        maya_env="test",
        session_secret="x" * 32,
        demo_mode=True,
        demo_quick_login=quick_login,
        database_url=f"sqlite:///{tmp_path / 'maya.sqlite3'}",
        data_root=tmp_path,
        demo_accounts_file=accounts,
        llm_provider="mock",
        embedding_provider="mock",
        tts_provider="mock",
        voice_provider="mock",
        translation_provider=None,
    )
    database = Database(settings.database_url, settings.data_root)
    database.initialize_schema()
    with database.session() as session:
        seed_demo_data(session)
    sync_demo_accounts(database, settings)
    # The fixture performs seed then account sync explicitly; the app lifespan
    # is skipped here so its Wave 0 seed guard does not reject the intentional
    # catalog subset used by these focused tests.
    return create_app(settings, database, initialize_database=False), database, settings, accounts


def test_private_catalog_parser_is_strict_and_never_echoes_secret() -> None:
    graph = parse_accounts_markdown(ACCOUNT_TABLE)
    assert {account.account_key for account in graph.accounts} == {
        "maya",
        "bowen",
        "kaikai",
    }
    assert account_id("maya") == "08b9de2d-bb75-5c71-a64b-231b48f9eb25"
    malformed = ACCOUNT_TABLE.replace("kaikai", "bowen", 1)
    with pytest.raises(CredentialFileError) as error:
        parse_accounts_markdown(malformed)
    assert "demo-password" not in str(error.value)
    assert "bowen" not in str(error.value)


@pytest.mark.parametrize("password", ["12345", "x" * 4097])
def test_private_catalog_password_length_is_bounded_without_echo(
    password: str,
) -> None:
    malformed = ACCOUNT_TABLE.replace("demo-password", password, 1)
    with pytest.raises(CredentialFileError) as error:
        parse_accounts_markdown(malformed)
    assert str(error.value) == "demo account catalog is malformed"
    assert password not in str(error.value)


def test_private_catalog_accepts_the_frozen_six_character_password() -> None:
    accepted = ACCOUNT_TABLE.replace("demo-password", "123456", 1)
    graph = parse_accounts_markdown(accepted)
    assert graph.accounts[0].password == "123456"


def test_unhandled_auth_request_logs_only_request_id_and_exception_type(
    app_factory: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    app, _database, _settings = app_factory()
    sentinels = (
        "account_key=sentinel-account-key",
        "username=sentinel-username",
        "password=sentinel-password",
        "hash=sentinel-password-hash",
        "group=sentinel-group",
        "path=/absolute/private/accounts.private.md",
        "raw line=| sentinel-account-key | sentinel-username | sentinel-password |",
    )
    secret_message = " ".join(sentinels)

    def unhandled() -> None:
        try:
            raise ValueError(secret_message)
        except ValueError as cause:
            raise RuntimeError(secret_message) from cause

    app.add_api_route("/auth-test-unhandled", unhandled, methods=["GET"])
    target_logger = logging.getLogger("maya.backend")
    target_logger.disabled = False
    target_logger.propagate = True
    caplog.set_level(logging.ERROR, logger="maya.backend")
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/auth-test-unhandled")

    assert response.status_code == 503
    body = response.json()
    assert body["code"] == "provider_unavailable"
    assert body["message"] == "The service is temporarily unavailable."
    assert all(sentinel not in response.text for sentinel in sentinels)
    records = [
        record
        for record in caplog.records
        if record.name == "maya.backend" and "Unhandled request failure" in record.getMessage()
    ]
    assert len(records) == 1
    message = records[0].getMessage()
    assert re.fullmatch(
        r"Unhandled request failure request_id=[0-9a-f-]+ error_type=RuntimeError",
        message,
    )
    assert all(sentinel not in message for sentinel in sentinels)


def test_private_catalog_secure_read_detects_same_size_rewrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "private.md"
    target.write_text(ACCOUNT_TABLE, encoding="utf-8")
    target.chmod(0o600)
    original_read = os.read
    changed = False

    def read_and_rewrite(descriptor: int, size: int) -> bytes:
        nonlocal changed
        content = original_read(descriptor, size)
        if content and not changed:
            changed = True
            replacement = ACCOUNT_TABLE.replace("Demo Teacher", "Demo Scholar", 1)
            assert len(replacement) == len(ACCOUNT_TABLE)
            target.write_text(replacement, encoding="utf-8")
            target.chmod(0o600)
        return content

    monkeypatch.setattr(os, "read", read_and_rewrite)
    settings = Settings(maya_env="test", demo_accounts_file=target)
    with pytest.raises(CredentialFileError) as error:
        load_desired_graph(settings)
    assert str(error.value) == "demo account catalog changed while reading"
    assert error.value.__cause__ is None


def test_legacy_catalog_requires_explicit_switch_and_secure_regular_file(tmp_path: Path) -> None:
    legacy = tmp_path / "demo_users.yaml"
    legacy.write_text("users: []\n", encoding="utf-8")
    legacy.chmod(0o600)
    missing_private = tmp_path / "missing-accounts.private.md"
    settings = Settings(
        maya_env="test",
        demo_accounts_file=missing_private,
        demo_users_file=legacy,
        allow_legacy_demo_users=True,
    )
    assert load_desired_graph(settings).accounts == ()

    disabled = settings.model_copy(update={"allow_legacy_demo_users": False})
    with pytest.raises(CredentialFileError):
        load_desired_graph(disabled)

    legacy.chmod(0o644)
    with pytest.raises(CredentialFileError) as broad:
        load_desired_graph(settings)
    assert broad.value.__cause__ is None
    legacy.chmod(0o600)
    oversized = b"x" * (CATALOG_MAX_BYTES + 1)
    legacy.write_bytes(oversized)
    legacy.chmod(0o600)
    with pytest.raises(CredentialFileError):
        load_desired_graph(settings)

    legacy.unlink()
    legacy.symlink_to(tmp_path / "does-not-exist.yaml")
    with pytest.raises(CredentialFileError):
        load_desired_graph(settings)


def test_private_catalog_rejects_broad_mode_and_symlink_without_echoing_path(
    tmp_path: Path,
) -> None:
    target = tmp_path / "private.md"
    target.write_text(ACCOUNT_TABLE, encoding="utf-8")
    target.chmod(0o644)
    settings = Settings(maya_env="test", demo_accounts_file=target)
    with pytest.raises(CredentialFileError) as broad:
        load_desired_graph(settings)
    assert str(target) not in str(broad.value)

    target.chmod(0o600)
    link = tmp_path / "linked.md"
    link.symlink_to(target)
    linked_settings = Settings(maya_env="test", demo_accounts_file=link)
    with pytest.raises(CredentialFileError) as symlinked:
        load_desired_graph(linked_settings)
    assert str(target) not in str(symlinked.value)


def test_anonymous_catalog_and_quick_login_require_both_demo_flags(
    tmp_path: Path,
) -> None:
    app, database, settings, _accounts = _app(tmp_path)
    with TestClient(app) as client:
        identities = client.get("/api/v1/auth/demo-identities")
        assert identities.status_code == 200
        assert identities.headers.get("set-cookie") is None
        body = identities.json()
        assert {item["display_name"] for item in body} == {
            "Demo Teacher",
            "Bowen Student 1",
            "Kaikai Student 1",
        }
        assert all(set(item) == {"user_id", "display_name", "role"} for item in body)
        assert "account_key" not in identities.text
        assert "demo-password" not in identities.text

        teacher_id = next(item["user_id"] for item in body if item["role"] == "teacher")
        selected = client.post(
            "/api/v1/auth/quick-login",
            json={"user_id": teacher_id},
        )
        assert selected.status_code == 200, selected.text
        assert selected.json()["user"]["id"] == teacher_id
        assert "demo-password" not in selected.text

    disabled_settings = settings.model_copy(update={"demo_quick_login": False})
    disabled_app = create_app(disabled_settings, database, initialize_database=False)
    with TestClient(disabled_app) as disabled:
        assert disabled.get("/api/v1/auth/demo-identities").status_code == 404
        assert (
            disabled.post(
                "/api/v1/auth/quick-login",
                json={"user_id": teacher_id},
            ).status_code
            == 404
        )


def test_sync_rename_remove_readd_preserves_uuid_and_revokes_sessions(
    tmp_path: Path,
) -> None:
    app, database, settings, accounts = _app(tmp_path)
    student_id = account_id("bowen")
    with TestClient(app) as client:
        password_login = client.post(
            "/api/v1/auth/login",
            json={"username": "bowen", "password": "demo-password"},
        )
        assert password_login.status_code == 200
        old_cookie = client.cookies.get("maya_session")
        assert old_cookie

        renamed = ACCOUNT_TABLE.replace(
            "| bowen | bowen | Bowen Student 1 |",
            "| bowen | bowen-renamed | Renamed Bowen |",
        )
        accounts.write_text(renamed, encoding="utf-8")
        accounts.chmod(0o600)
        # A catalog is read once per process; a new Settings/app lifetime
        # models the restart required to apply this file edit.
        renamed_settings = settings.model_copy()
        sync_demo_accounts(database, renamed_settings)

        with database.session() as session:
            user = session.get(User, student_id)
            assert user is not None
            assert user.username == "bowen-renamed"
            assert user.display_name == "Renamed Bowen"
            assert user.status == "active"
            old_session = session.scalar(
                select(SessionRecord).where(SessionRecord.id_hash == session_hash(old_cookie))
            )
            assert old_session is not None and old_session.revoked_at is not None

        renamed_row = (
            "| bowen | bowen-renamed | Renamed Bowen | demo-password | student | group-demo |\n"
        )
        removed = renamed.replace(renamed_row, "")
        accounts.write_text(removed, encoding="utf-8")
        accounts.chmod(0o600)
        removed_settings = settings.model_copy()
        sync_demo_accounts(database, removed_settings)
        with database.session() as session:
            user = session.get(User, student_id)
            assert user is not None and user.status == "inactive"
            assert (
                session.scalar(select(CourseMember).where(CourseMember.user_id == student_id))
                is None
            )
            assert (
                session.scalar(select(GroupMember).where(GroupMember.user_id == student_id)) is None
            )

        accounts.write_text(renamed, encoding="utf-8")
        accounts.chmod(0o600)
        readded_settings = settings.model_copy()
        sync_demo_accounts(database, readded_settings)
        with database.session() as session:
            user = session.get(User, student_id)
            assert user is not None
            assert user.id == student_id
            assert user.status == "active"
            assert session.scalar(select(CourseMember).where(CourseMember.user_id == student_id))
            assert session.scalar(select(GroupMember).where(GroupMember.user_id == student_id))


def test_cross_process_unchanged_and_display_only_catalog_preserve_session(
    tmp_path: Path,
) -> None:
    _app_instance, database, settings, accounts = _app(tmp_path)
    student_id = account_id("bowen")
    with database.session() as session:
        user = session.get(User, student_id)
        assert user is not None
        old_display_name = user.display_name

    token = "cross-process-session-token"
    with database.session() as session:
        user = session.get(User, student_id)
        assert user is not None
        token, _session_row, _csrf = create_rotated_session(session, user, settings)

    # A new Settings/Database pair represents a separate process.  The
    # persisted material fingerprint must preserve an unchanged session.
    restarted = settings.model_copy()
    restarted_database = Database(settings.database_url, settings.resolved_data_root)
    sync_demo_accounts(restarted_database, restarted)
    with restarted_database.session() as session:
        row = session.scalar(
            select(SessionRecord).where(SessionRecord.id_hash == session_hash(token))
        )
        assert row is not None and row.revoked_at is None

    # Display-only changes are not authentication/authorization material and
    # therefore keep the same session while updating the public projection.
    changed = ACCOUNT_TABLE.replace("Bowen Student 1", "Bowen Student One", 1)
    accounts.write_text(changed, encoding="utf-8")
    accounts.chmod(0o600)
    display_settings = settings.model_copy()
    display_database = Database(settings.database_url, settings.resolved_data_root)
    sync_demo_accounts(display_database, display_settings)
    with display_database.session() as session:
        row = session.scalar(
            select(SessionRecord).where(SessionRecord.id_hash == session_hash(token))
        )
        user = session.get(User, student_id)
        assert row is not None and row.revoked_at is None
        assert user is not None and user.display_name == "Bowen Student One"
    assert old_display_name == "Bowen Student 1"


@pytest.mark.parametrize(
    ("label", "replacement"),
    # A "moved to another group" case is deliberately absent: the Demo graph
    # has exactly one group and the parser rejects a student row with an
    # empty group, so no valid catalog can express that change. The invalid
    # target is covered by test_invalid_desired_group_rolls_back_the_complete_graph.
    [
        (
            "password",
            (
                "| bowen | bowen | Bowen Student 1 | demo-password |",
                "| bowen | bowen | Bowen Student 1 | changed-pass |",
            ),
        ),
        (
            "role",
            (
                "| bowen | bowen | Bowen Student 1 | demo-password | student | group-demo |",
                "| bowen | bowen | Bowen Student 1 | demo-password | teacher | |",
            ),
        ),
        (
            "active",
            (
                "| bowen | bowen | Bowen Student 1 | demo-password | student | group-demo |\n",
                "",
            ),
        ),
    ],
)
def test_password_role_group_and_removal_revoke_bound_sessions(
    tmp_path: Path,
    label: str,
    replacement: tuple[str, str],
) -> None:
    _app_instance, database, settings, accounts = _app(tmp_path)
    student_id = account_id("bowen")
    with database.session() as session:
        user = session.get(User, student_id)
        assert user is not None
        raw_token, _row, _csrf = create_rotated_session(session, user, settings)

    accounts.write_text(ACCOUNT_TABLE.replace(*replacement), encoding="utf-8")
    accounts.chmod(0o600)
    restarted = settings.model_copy()
    restarted_database = Database(settings.database_url, settings.resolved_data_root)
    sync_demo_accounts(restarted_database, restarted)
    with restarted_database.session() as session:
        row = session.scalar(
            select(SessionRecord).where(SessionRecord.id_hash == session_hash(raw_token))
        )
        assert row is not None and row.revoked_at is not None, label


def test_same_process_catalog_edit_is_not_hot_reloaded(tmp_path: Path) -> None:
    _app_instance, database, settings, accounts = _app(tmp_path)
    accounts.write_text(
        ACCOUNT_TABLE.replace("bowen | bowen", "bowen | bowen-new"),
        encoding="utf-8",
    )
    accounts.chmod(0o600)
    # Both password verification and an explicit sync in the same process use
    # the startup snapshot rather than rereading the changed file.
    assert verify_password(settings, "bowen", "demo-password") == account_id("bowen")
    assert verify_password(settings, "bowen-new", "demo-password") is None
    sync_demo_accounts(database, settings)
    with database.session() as session:
        user = session.get(User, account_id("bowen"))
        assert user is not None and user.username == "bowen"


def test_nonbinding_user_is_not_disabled_when_catalog_row_is_removed(tmp_path: Path) -> None:
    _app_instance, database, settings, accounts = _app(tmp_path)
    nonbinding_id = "11111111-1111-4111-8111-111111111111"
    with database.session() as session:
        session.add(
            User(
                id=nonbinding_id,
                username="ordinary-user",
                display_name="Ordinary User",
                status="active",
                created_at=datetime.now(UTC),
            )
        )
    accounts.write_text(
        ACCOUNT_TABLE.replace(
            "| bowen | bowen | Kaikai Student 1 | demo-password | student | group-demo |\n",
            "",
        ),
        encoding="utf-8",
    )
    accounts.chmod(0o600)
    restarted = settings.model_copy()
    restarted_database = Database(settings.database_url, settings.resolved_data_root)
    sync_demo_accounts(restarted_database, restarted)
    with restarted_database.session() as session:
        user = session.get(User, nonbinding_id)
        assert user is not None and user.status == "active"


def test_fresh_invalid_bootstrap_rolls_back_seed_and_catalog_graph(tmp_path: Path) -> None:
    accounts = tmp_path / "accounts.private.md"
    accounts.write_text(ACCOUNT_TABLE, encoding="utf-8")
    accounts.chmod(0o600)
    settings = Settings(
        maya_env="test",
        session_secret="x" * 32,
        demo_mode=True,
        demo_accounts_file=accounts,
        database_url=f"sqlite:///{tmp_path / 'fresh.sqlite3'}",
        data_root=tmp_path / "data",
    )
    database = Database(settings.database_url, settings.resolved_data_root)
    database.initialize_schema()
    invalid = parse_accounts_markdown(ACCOUNT_TABLE.replace("group-demo", "missing-group"))
    with pytest.raises(AccountSyncError):
        bootstrap_demo_accounts(database, settings, seed_demo_data, invalid)
    with database.session() as session:
        assert session.scalars(select(Course)).all() == []
        assert session.scalars(select(User)).all() == []
        assert session.scalars(select(CourseMember)).all() == []
        assert session.scalars(select(GroupMember)).all() == []
        assert session.scalars(select(DemoAccountBinding)).all() == []


def test_sync_commit_failure_does_not_publish_catalog_snapshot(tmp_path: Path) -> None:
    accounts = tmp_path / "accounts.private.md"
    accounts.write_text(ACCOUNT_TABLE, encoding="utf-8")
    accounts.chmod(0o600)
    settings = Settings(
        maya_env="test",
        session_secret="x" * 32,
        demo_mode=True,
        demo_accounts_file=accounts,
        database_url=f"sqlite:///{tmp_path / 'commit-failure.sqlite3'}",
        data_root=tmp_path / "data",
    )
    database = Database(settings.database_url, settings.resolved_data_root)
    database.initialize_schema()
    with database.session() as session:
        seed_demo_data(session)

    original_factory = database.session_factory
    failing_session = original_factory()

    def fail_commit() -> None:
        raise RuntimeError("injected commit failure")

    failing_session.commit = fail_commit  # type: ignore[method-assign]
    cast(Any, database).session_factory = lambda: failing_session
    with pytest.raises(AccountSyncError):
        sync_demo_accounts(database, settings)
    database.session_factory = original_factory

    assert id(settings) not in credential_state._PENDING_GRAPHS
    assert id(settings) not in credential_state._CATALOG_SNAPSHOTS
    with database.session() as session:
        # The failed commit did not apply any account projection or binding.
        assert session.scalars(select(DemoAccountBinding)).all() == []
        user = session.get(User, account_id("bowen"))
        assert user is not None and user.status == "active"


def test_invalid_desired_group_rolls_back_the_complete_graph(tmp_path: Path) -> None:
    _app_instance, database, settings, _accounts = _app(tmp_path)
    with database.session() as session:
        before_users = [
            (row.id, row.username, row.display_name, row.status)
            for row in session.scalars(select(User).order_by(User.id)).all()
        ]
        before_courses = [
            (row.course_id, row.user_id, row.role)
            for row in session.scalars(
                select(CourseMember).order_by(CourseMember.course_id, CourseMember.user_id)
            ).all()
        ]
        before_groups = [
            (row.group_id, row.user_id, row.role)
            for row in session.scalars(
                select(GroupMember).order_by(GroupMember.group_id, GroupMember.user_id)
            ).all()
        ]

    invalid = parse_accounts_markdown(ACCOUNT_TABLE.replace("group-demo", "missing-group"))
    with pytest.raises(AccountSyncError):
        sync_demo_accounts(database, settings, invalid)

    with database.session() as session:
        assert before_users == [
            (row.id, row.username, row.display_name, row.status)
            for row in session.scalars(select(User).order_by(User.id)).all()
        ]
        assert before_courses == [
            (row.course_id, row.user_id, row.role)
            for row in session.scalars(
                select(CourseMember).order_by(CourseMember.course_id, CourseMember.user_id)
            ).all()
        ]
        assert before_groups == [
            (row.group_id, row.user_id, row.role)
            for row in session.scalars(
                select(GroupMember).order_by(GroupMember.group_id, GroupMember.user_id)
            ).all()
        ]


def test_lifespan_seeds_once_then_allows_catalog_rename_on_restart(tmp_path: Path) -> None:
    accounts = tmp_path / "accounts.private.md"
    accounts.write_text(ACCOUNT_TABLE, encoding="utf-8")
    accounts.chmod(0o600)
    settings = Settings(
        maya_env="test",
        session_secret="x" * 32,
        demo_mode=True,
        demo_quick_login=True,
        database_url=f"sqlite:///{tmp_path / 'startup.sqlite3'}",
        data_root=tmp_path / "data",
        demo_accounts_file=accounts,
    )
    database = Database(settings.database_url, settings.resolved_data_root)
    with TestClient(create_app(settings, database)) as first:
        identities = first.get("/api/v1/auth/demo-identities")
        assert identities.status_code == 200
        assert len(identities.json()) == 3

    accounts.write_text(
        ACCOUNT_TABLE.replace(
            "| bowen | bowen | Bowen Student 1 |",
            "| bowen | bowen-renamed | Renamed Bowen |",
        ),
        encoding="utf-8",
    )
    accounts.chmod(0o600)
    restarted_settings = settings.model_copy()
    restarted_database = Database(
        restarted_settings.database_url,
        restarted_settings.resolved_data_root,
    )
    with TestClient(create_app(restarted_settings, restarted_database)) as restarted:
        identities = restarted.get("/api/v1/auth/demo-identities")
        assert identities.status_code == 200
        assert "Renamed Bowen" in {row["display_name"] for row in identities.json()}
        login_response = restarted.post(
            "/api/v1/auth/login",
            json={"username": "bowen-renamed", "password": "demo-password"},
        )
        assert login_response.status_code == 200
