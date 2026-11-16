from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from app.core.models import Agent, AgentVersion
from app.modules.avatars.catalog import (
    AVATAR_TEMPLATE_IDS,
    DEFAULT_AVATAR_CONFIG,
    AvatarConfigValidationError,
    avatar_asset_url,
    avatar_catalog_entries,
    compatible_asset_count,
    default_config_for,
    is_supported_template,
    registered_avatar_assets,
    validate_avatar_config,
)
from app.modules.knowledge.services import _avatar
from app.modules.workspace.chat import agent_view
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.conftest import login


def _with_avatar_route(
    app_factory: Any,
) -> tuple[FastAPI, TestClient]:
    app, _database, _settings = app_factory()
    return app, TestClient(app)


def test_catalog_registers_local_glb_assets() -> None:
    entries = avatar_catalog_entries()
    assets = registered_avatar_assets()
    assert tuple(entry.id for entry in entries) == AVATAR_TEMPLATE_IDS
    assert [entry.available for entry in entries] == [True, True, True, True]
    assert assets == (
        "/avatars/female_1.glb",
        "/avatars/elder-scholar.glb",
        "/avatars/noble-scholar.glb",
        "/avatars/Maya-Egg.glb",
    )
    assert compatible_asset_count() == 4
    assert [avatar_asset_url(entry.id) for entry in entries] == list(assets)
    assert all("material_theme" in entry.supported_parameters for entry in entries[:3])
    assert entries[3].supported_parameters == ["template_id"]
    asset_root = Path(__file__).resolve().parents[2] / "frontend" / "public"
    for asset_url in assets:
        assert (asset_root / asset_url.lstrip("/")).is_file()

    # A caller receives a fresh list and cannot mutate the server-owned order.
    entries[0].supported_parameters.append("unexpected")
    assert "unexpected" not in avatar_catalog_entries()[0].supported_parameters


def test_each_preset_has_distinct_defaults_and_legacy_config_remains_valid() -> None:
    defaults = [default_config_for(template_id) for template_id in AVATAR_TEMPLATE_IDS]
    assert [config.template_id for config in defaults] == list(AVATAR_TEMPLATE_IDS)
    assert [config.material_theme for config in defaults] == [
        "demo",
        "warm_sand",
        "civic_olive",
        "demo",
    ]
    assert len({config.material_theme for config in defaults}) == 3
    assert validate_avatar_config(DEFAULT_AVATAR_CONFIG) == DEFAULT_AVATAR_CONFIG
    assert is_supported_template("wave1-default-head")
    assert not is_supported_template("unknown-template")


@pytest.mark.parametrize(
    "field,value",
    [
        ("template_id", "unknown-template"),
        ("unexpected", "value"),
        ("material_theme", "purple"),
        ("eye_color", "violet"),
        ("default_expression", "surprised"),
        ("expression_strength", "extreme"),
        ("motion_style", "dance"),
    ],
)
def test_catalog_rejects_unknown_template_or_parameter(field: str, value: str) -> None:
    config = DEFAULT_AVATAR_CONFIG.model_dump()
    config[field] = value
    with pytest.raises(AvatarConfigValidationError) as caught:
        validate_avatar_config(config)
    assert caught.value.code == "avatar_missing"
    assert caught.value.field == field


def test_avatar_catalog_route_is_authenticated_and_stable(app_factory: Any) -> None:
    app, client = _with_avatar_route(app_factory)
    with client:
        unauthenticated = client.get("/api/v1/avatar-templates")
        assert unauthenticated.status_code == 401

        _session, _csrf = login(client)
        response = client.get("/api/v1/avatar-templates")
        assert response.status_code == 200, response.text
        payload = response.json()
        assert [item["id"] for item in payload] == list(AVATAR_TEMPLATE_IDS)
        assert all(item["available"] is True for item in payload)
        assert all(
            item["supported_parameters"]
            == (
                ["template_id"]
                if item["id"] == "egg"
                else [
                    "template_id",
                    "material_theme",
                    "eye_color",
                    "default_expression",
                    "expression_strength",
                    "motion_style",
                ]
            )
            for item in payload
        )
    del app


def test_student_chat_and_teacher_preview_read_identical_avatar_fields() -> None:
    stored = {
        "template_id": "maya-civic-observer",
        "material_theme": "cool_slate",
        "eye_color": "green",
        "default_expression": "serious_angry",
        "expression_strength": "high",
        "motion_style": "active",
    }
    raw = json.dumps(stored)
    version = AgentVersion(
        id=str(uuid4()),
        agent_id=str(uuid4()),
        version_seq=2,
        avatar_config_json=raw,
    )
    agent = Agent(id=version.agent_id, name="Observer", visibility="private", deleted_at=None)
    chat_fields = agent_view(version, agent, str(uuid4())).avatar_config.model_dump()
    teacher_fields = _avatar(raw).model_dump()
    assert chat_fields == teacher_fields == stored


def test_update_agent_draft_avatar_survives_reread(client: TestClient) -> None:
    _user, csrf = login(client, "bowen")
    created = client.post(
        "/api/v1/groups/7813f937-902c-5534-bfb2-ad773a43aeda/agents",
        headers={
            "Origin": "http://testserver",
            "X-CSRF-Token": csrf,
            "Idempotency-Key": "avatar-appearance-create",
        },
        json={"name": "Appearance Guide", "description": "Avatar draft."},
    )
    assert created.status_code == 201, created.text
    version_id = created.json()["versions"][0]["id"]
    avatar = {
        **created.json()["versions"][0]["avatar_config"],
        "template_id": "maya-warm-scholar",
        "material_theme": "cool_slate",
        "eye_color": "blue",
    }
    saved = client.patch(
        f"/api/v1/agent-versions/{version_id}",
        headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
        json={"expected_revision": 0, "avatar_config": avatar},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["avatar_config"] == avatar
    reread = client.get(f"/api/v1/agent-versions/{version_id}")
    assert reread.status_code == 200, reread.text
    assert reread.json()["avatar_config"] == avatar
