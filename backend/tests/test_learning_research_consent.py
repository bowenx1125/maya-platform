"""Optional learning-data research consent at password login."""

from __future__ import annotations

from typing import Any

from app.modules.auth.models import UserLearningResearchConsent
from app.modules.auth.research_consent import CONSENT_COPY_VERSION
from fastapi.testclient import TestClient
from sqlalchemy import func, select


def test_login_research_consent_default_false_writes_nothing(
    app_bundle: tuple[Any, Any, Any],
) -> None:
    app, database, _settings = app_bundle
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/auth/login",
            json={"username": "maya", "password": "demo-password"},
        )
        assert response.status_code == 200, response.text
        user_id = response.json()["user"]["id"]
    with database.session() as db:
        assert db.get(UserLearningResearchConsent, user_id) is None


def test_login_research_consent_true_then_untick_revokes(
    app_bundle: tuple[Any, Any, Any],
) -> None:
    app, database, _settings = app_bundle
    with TestClient(app) as client:
        accepted = client.post(
            "/api/v1/auth/login",
            json={
                "username": "maya",
                "password": "demo-password",
                "research_consent": True,
            },
        )
        assert accepted.status_code == 200, accepted.text
        user_id = accepted.json()["user"]["id"]
        with database.session() as db:
            row = db.get(UserLearningResearchConsent, user_id)
            assert row is not None
            assert row.consented is True
            assert row.consent_copy_version == CONSENT_COPY_VERSION

        revoked = client.post(
            "/api/v1/auth/login",
            json={
                "username": "maya",
                "password": "demo-password",
                "research_consent": False,
            },
        )
        assert revoked.status_code == 200, revoked.text
        with database.session() as db:
            row = db.get(UserLearningResearchConsent, user_id)
            assert row is not None
            assert row.consented is False
            assert row.consent_copy_version == CONSENT_COPY_VERSION


def test_failed_login_does_not_write_research_consent(
    app_bundle: tuple[Any, Any, Any],
) -> None:
    app, database, _settings = app_bundle
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/auth/login",
            json={
                "username": "maya",
                "password": "wrong-password",
                "research_consent": True,
            },
        )
        assert response.status_code == 401
    with database.session() as db:
        count = db.scalar(select(func.count()).select_from(UserLearningResearchConsent))
        assert count == 0
