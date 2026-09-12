from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml
from app.core.config import Settings
from app.core.db import Database
from app.main import create_app
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pwdlib import PasswordHash


@pytest.fixture
def app_factory(tmp_path: Path) -> Callable[..., tuple[FastAPI, Database, Settings]]:
    # One fixture lifetime represents one unchanged private catalog across
    # multiple app/process instances.  Re-hashing the same password for every
    # factory call would create a new Argon2 salt and falsely look like a
    # material credential change, revoking otherwise valid sessions.
    password_hash = PasswordHash.recommended().hash("demo-password")
    credentials = {
        "users": [
            {
                "user_id": "08b9de2d-bb75-5c71-a64b-231b48f9eb25",
                "username": "maya",
                "password_hash": password_hash,
            },
            {
                "user_id": "60541c78-30f1-55c5-b2aa-207b6a766883",
                "username": "bowen",
                "password_hash": password_hash,
            },
            {
                "user_id": "bc170f51-45fb-5296-a36d-a2edc8f8d315",
                "username": "kaikai",
                "password_hash": password_hash,
            },
            {
                "user_id": "89857c76-2d84-5ecf-b680-990815b98680",
                "username": "jade",
                "password_hash": password_hash,
            },
        ]
    }
    credential_file = tmp_path / "demo_users.yaml"
    credential_file.write_text(yaml.safe_dump(credentials), encoding="utf-8")
    credential_file.chmod(0o600)

    def factory(
        *,
        demo_mode: bool = True,
    ) -> tuple[FastAPI, Database, Settings]:
        settings = Settings(
            maya_env="test",
            session_secret="x" * 32,
            demo_mode=demo_mode,
            demo_quick_login=False,
            allow_legacy_demo_users=True,
            database_url=f"sqlite:///{tmp_path / 'maya.sqlite3'}",
            data_root=tmp_path,
            # Keep the legacy fixture explicit and independent of any
            # developer .env file or repository-local private catalog.
            demo_accounts_file=tmp_path / "missing-accounts.private.md",
            demo_users_file=credential_file,
            llm_provider="mock",
            embedding_provider="mock",
            tts_provider="mock",
            voice_provider="mock",
        )
        database = Database(settings.database_url, settings.data_root)
        return create_app(settings, database), database, settings

    return factory


@pytest.fixture
def app_bundle(
    app_factory: Callable[..., tuple[FastAPI, Database, Settings]],
) -> tuple[FastAPI, Database, Settings]:
    """One app/database pair shared by ``client`` and ``database``."""

    return app_factory()


@pytest.fixture
def client(app_bundle: tuple[FastAPI, Database, Settings]) -> Iterator[TestClient]:
    app, _database, _settings = app_bundle
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def database(app_bundle: tuple[FastAPI, Database, Settings]) -> Database:
    """The database behind ``client``, for tests that must seed extra rows."""

    return app_bundle[1]


def login(client: TestClient, username: str = "maya") -> tuple[dict[str, Any], str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": "demo-password"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    return payload, payload["csrf_token"]


# The product graph has exactly one Demo group, so a group the caller is not a
# member of cannot be reached through the seed. Access-control tests create one
# directly; it is never seeded, exported or shipped.
FOREIGN_GROUP_ID = "1f1b3c2e-0f4d-4a5b-9c6d-7e8f90a1b2c3"


def make_foreign_group(database: Any, course_id: str, name: str = "Foreign Group") -> str:
    """Insert a group in the same course that no seeded user belongs to."""

    from app.core.models import Group

    with database.session() as session:
        if session.get(Group, FOREIGN_GROUP_ID) is None:
            session.add(
                Group(
                    id=FOREIGN_GROUP_ID,
                    course_id=course_id,
                    name=name,
                    created_at=datetime.now(UTC),
                )
            )
            session.commit()
    return FOREIGN_GROUP_ID
