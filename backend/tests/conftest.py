from __future__ import annotations

from collections.abc import Callable, Iterator
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
                "user_id": "98644172-6bbb-5383-8198-3b78dcd5b9ab",
                "username": "teacher-demo",
                "password_hash": password_hash,
            },
            {
                "user_id": "bad7de3c-0409-5d50-9ad7-bbb641d1f6a7",
                "username": "student-bowen-1",
                "password_hash": password_hash,
            },
            {
                "user_id": "7ff99250-0829-5864-8040-b3133510e7da",
                "username": "student-bowen-2",
                "password_hash": password_hash,
            },
            {
                "user_id": "4d2445fe-7c7b-55ff-8c4c-778ab5098c1d",
                "username": "student-bowen-3",
                "password_hash": password_hash,
            },
            {
                "user_id": "0c12d01a-5acf-5430-bc4d-731af768ff46",
                "username": "student-kaikai-1",
                "password_hash": password_hash,
            },
            {
                "user_id": "d4465e7b-7b76-5ac1-8f6e-5ce6a6da737d",
                "username": "student-kaikai-2",
                "password_hash": password_hash,
            },
            {
                "user_id": "fc2604c6-c760-53e5-b69b-c3a1ef471ea8",
                "username": "student-kaikai-3",
                "password_hash": password_hash,
            },
        ]
    }
    credential_file = tmp_path / "demo_users.yaml"
    credential_file.write_text(yaml.safe_dump(credentials), encoding="utf-8")
    credential_file.chmod(0o600)

    def factory(*, demo_mode: bool = True) -> tuple[FastAPI, Database, Settings]:
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
            translation_provider=None,
        )
        database = Database(settings.database_url, settings.data_root)
        return create_app(settings, database), database, settings

    return factory


@pytest.fixture
def client(app_factory: Callable[..., tuple[FastAPI, Database, Settings]]) -> Iterator[TestClient]:
    app, _database, _settings = app_factory()
    with TestClient(app) as test_client:
        yield test_client


def login(client: TestClient, username: str = "teacher-demo") -> tuple[dict[str, Any], str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": "demo-password"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    return payload, payload["csrf_token"]
