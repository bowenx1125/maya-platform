from __future__ import annotations

from typing import Any

import pytest
from app.modules.avatars.catalog import (
    AVATAR_TEMPLATE_IDS,
    DEFAULT_AVATAR_CONFIG,
    AvatarConfigValidationError,
    avatar_catalog_entries,
    compatible_asset_count,
    default_config_for,
    is_supported_template,
    validate_avatar_config,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.conftest import login


def _with_avatar_route(
    app_factory: Any,
) -> tuple[FastAPI, TestClient]:
    app, _database, _settings = app_factory()
    return app, TestClient(app)


def test_catalog_has_stable_allowlist_and_one_shared_compatible_asset() -> None:
    entries = avatar_catalog_entries()
    assert tuple(entry.id for entry in entries) == AVATAR_TEMPLATE_IDS
    assert [entry.available for entry in entries] == [True, True, True]
    assert compatible_asset_count() == 1
    assert len({"/avatars/female_1.glb" for _entry in entries}) == 1

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
            == [
                "template_id",
                "material_theme",
                "eye_color",
                "default_expression",
                "expression_strength",
                "motion_style",
            ]
            for item in payload
        )
    del app
