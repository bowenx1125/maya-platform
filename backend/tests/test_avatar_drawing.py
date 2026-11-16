"""Editable drawing persistence, bounded input and avatar-only publication."""

from __future__ import annotations

import copy
from typing import Any

import pytest
from app.core.models import Agent, KnowledgeChunk, KnowledgeSnapshot
from app.modules.agents.schemas import AvatarDrawing
from app.modules.avatars import default_config_for
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select

from tests.conftest import login
from tests.test_agent_preview import published_version
from tests.test_wave2_setup import GROUP_DEMO_ID, headers


def drawing() -> dict[str, Any]:
    return {
        "version": 1,
        "mouth": {"x": 0.5, "y": 0.435},
        "strokes": [
            {
                "id": "first",
                "color": "#8C4B9E",
                "width": 0.02,
                "opacity": 1,
                "points": [{"x": 0.4, "y": 0.3}, {"x": 0.6, "y": 0.5}],
                "erasures": [{"width": 0.03, "points": [{"x": 0.5, "y": 0.4}]}],
            }
        ],
    }


def config() -> dict[str, Any]:
    return default_config_for("egg").model_dump() | {"drawing": drawing()}


@pytest.mark.parametrize(
    "field,value",
    [
        ("color", "red"),
        ("color", "#fff"),
        ("width", -0.01),
        ("opacity", 2),
        ("id", "../bad"),
        ("points", [{"x": 1.01, "y": 0.5}]),
        ("points", [{"x": "0.5", "y": 0.5}]),
        ("points", [{"x": float("nan"), "y": 0.5}]),
        ("points", [{"x": 0.5, "y": 0.5}] * 4097),
    ],
)
def test_rejects_invalid_stroke(field: str, value: Any) -> None:
    value_drawing = drawing()
    value_drawing["strokes"][0][field] = value
    with pytest.raises(ValidationError):
        AvatarDrawing.model_validate(value_drawing)


@pytest.mark.parametrize(
    "kind", ["strokes", "points", "bytes", "duplicate", "mouth", "extra", "masks"]
)
def test_drawing_caps(kind: str) -> None:
    value = drawing()
    stroke = value["strokes"][0]
    if kind == "strokes":
        value["strokes"] = [dict(stroke, id=str(i)) for i in range(257)]
    elif kind in {"points", "bytes"}:
        # Bytes use long finite decimal coordinates without crossing the point cap.
        point = (
            {"x": 0.12345678901234567, "y": 0.8765432109876543}
            if kind == "bytes"
            else {"x": 0.5, "y": 0.5}
        )
        value["strokes"] = [
            dict(
                stroke, id=str(i), points=[point] * (3000 if kind == "bytes" else 4000), erasures=[]
            )
            for i in range(6)
        ]
    elif kind == "duplicate":
        value["strokes"].append(copy.deepcopy(stroke))
    elif kind == "mouth":
        value["mouth"]["x"] = 0.9
    elif kind == "masks":
        value["strokes"] = [
            dict(stroke, id=str(i), erasures=stroke["erasures"] * 256) for i in range(9)
        ]
    else:
        value["secret"] = "unsupported"
    with pytest.raises(ValidationError):
        AvatarDrawing.model_validate(value)


def test_create_carries_drawing_and_draft_save_is_noop_or_revision(client: TestClient) -> None:
    _, csrf = login(client, "bowen")
    result = client.post(
        f"/api/v1/groups/{GROUP_DEMO_ID}/agents",
        headers=headers(csrf, **{"Idempotency-Key": "drawing-create-with-config"}),
        json={"name": "Drawing create", "avatar_config": config()},
    )
    assert result.status_code == 201, result.text
    version = result.json()["versions"][0]
    assert version["avatar_config"] == config()
    body = {
        "expected_revision": version["revision"],
        "expected_published_version_id": None,
        "avatar_config": config(),
    }
    path = f"/api/v1/agent-versions/{version['id']}/avatar"
    result = client.put(
        path, headers=headers(csrf, **{"Idempotency-Key": "drawing-nochange-draft"}), json=body
    )
    assert result.status_code == 200, result.text
    assert result.json()["revision"] == version["revision"]
    body["avatar_config"]["drawing"]["mouth"]["x"] = 0.55
    result = client.put(
        path, headers=headers(csrf, **{"Idempotency-Key": "drawing-changed-draft"}), json=body
    )
    assert result.status_code == 200, result.text
    assert result.json()["revision"] == version["revision"] + 1
    assert result.json()["version_label"] == version["version_label"]
    stale = client.put(
        path, headers=headers(csrf, **{"Idempotency-Key": "drawing-stale-draft"}), json=body
    )
    assert stale.status_code == 409


def test_published_save_is_immediate_immutable_idempotent_and_conflict_safe(
    app_factory: Any,
) -> None:
    app, database, _ = app_factory()
    with TestClient(app) as client:
        _, csrf = login(client, "bowen")
        vid = published_version(database)
        old = client.get(f"/api/v1/agent-versions/{vid}").json()
        with database.session() as db:
            source = db.get(KnowledgeSnapshot, old["knowledge_snapshot_id"])
            assert source
            identity = (source.content_hash, source.embedding_key, source.embedding_policy_version)
            chunks = [
                (c.chunk_text, c.embedding_blob)
                for c in db.scalars(
                    select(KnowledgeChunk).where(KnowledgeChunk.snapshot_id == source.id)
                ).all()
            ]
        path = f"/api/v1/agent-versions/{vid}/avatar"
        body = {
            "expected_revision": old["revision"],
            "expected_published_version_id": vid,
            "avatar_config": config(),
        }
        request_headers = headers(csrf, **{"Idempotency-Key": "drawing-published-immediate"})
        result = client.put(path, headers=request_headers, json=body)
        assert result.status_code == 200, result.text
        saved = result.json()
        assert saved["state"] == "published" and saved["id"] != vid
        assert saved["agent_md"] == old["agent_md"]
        assert saved["voice_profile_id"] == old["voice_profile_id"]
        assert saved["avatar_config"] == config()
        assert (
            client.get(f"/api/v1/agents/{saved['agent_id']}").json()["current_published_version_id"]
            == saved["id"]
        )
        assert (
            client.get(f"/api/v1/agent-versions/{vid}").json()["avatar_config"]
            == old["avatar_config"]
        )
        replay = client.put(path, headers=request_headers, json=body)
        assert replay.status_code == 200 and replay.json() == saved
        stale = client.put(
            path,
            headers=headers(csrf, **{"Idempotency-Key": "drawing-conflicting-base"}),
            json=body,
        )
        assert stale.status_code == 409
        body.update(expected_revision=saved["revision"], expected_published_version_id=saved["id"])
        nochange = client.put(
            f"/api/v1/agent-versions/{saved['id']}/avatar",
            headers=headers(csrf, **{"Idempotency-Key": "drawing-published-nochange"}),
            json=body,
        )
        assert nochange.status_code == 200, nochange.text
        assert (
            nochange.json()["id"] == saved["id"]
            and nochange.json()["revision"] == saved["revision"]
        )
        with database.session() as db:
            source = db.get(KnowledgeSnapshot, saved["knowledge_snapshot_id"])
            assert source and source.agent_version_id == saved["id"]
            assert (
                source.content_hash,
                source.embedding_key,
                source.embedding_policy_version,
            ) == identity
            assert [
                (c.chunk_text, c.embedding_blob)
                for c in db.scalars(
                    select(KnowledgeChunk).where(KnowledgeChunk.snapshot_id == source.id)
                ).all()
            ] == chunks
        # Readability alone must never grant an unrelated student edit access.
        with database.session() as db:
            agent = db.get(Agent, saved["agent_id"])
            assert agent is not None
            agent.visibility = "private"
        _, other_csrf = login(client, "maya")
        denied = client.put(
            path,
            headers=headers(other_csrf, **{"Idempotency-Key": "drawing-other-cannot-save"}),
            json=body,
        )
        assert denied.status_code == 404


@pytest.mark.parametrize(
    "case,username,status",
    [
        ("owner", "bowen", 200),
        ("other_private", "kaikai", 404),
        ("teacher", "maya", 200),
        ("groupmate", "kaikai", 200),
        ("outside_group", "kaikai", 404),
        ("other_course", "maya", 404),
    ],
)
def test_avatar_editor_permissions(app_factory: Any, case: str, username: str, status: int) -> None:
    from datetime import UTC, datetime

    from app.core.models import AgentVersion, CourseMember, GroupMember

    from tests.test_agent_preview_snapshot import BOWEN, KAIKAI
    from tests.test_wave2_setup import COURSE_ID

    app, database, _ = app_factory()
    with TestClient(app) as client:
        vid = published_version(database)
        _, csrf = login(client, username)
        with database.session() as db:
            version = db.get(AgentVersion, vid)
            agent = db.get(Agent, version.agent_id)
            if case in {"owner", "other_private"}:
                agent.visibility = "private"
                version.published_visibility = "private"
                agent.owner_user_id = BOWEN
            elif case == "groupmate":
                db.merge(
                    GroupMember(
                        group_id=GROUP_DEMO_ID,
                        user_id=KAIKAI,
                        role="member",
                        created_at=datetime.now(UTC),
                    )
                )
            elif case == "outside_group":
                member = db.get(GroupMember, (GROUP_DEMO_ID, KAIKAI))
                if member is not None:
                    db.delete(member)
            elif case == "other_course":
                member = db.get(CourseMember, (COURSE_ID, "08b9de2d-bb75-5c71-a64b-231b48f9eb25"))
                assert member is not None
                db.delete(member)
            revision = version.revision
        result = client.put(
            f"/api/v1/agent-versions/{vid}/avatar",
            headers=headers(csrf, **{"Idempotency-Key": "drawing-permissions-" + case}),
            json={
                "expected_revision": revision,
                "expected_published_version_id": vid,
                "avatar_config": config(),
            },
        )
        assert result.status_code == status, result.text


def test_smallest_continuous_brush_width_is_valid() -> None:
    value = drawing()
    value["strokes"][0]["width"] = 1 / 1024
    assert AvatarDrawing.model_validate(value).strokes[0].width == 1 / 1024


def test_published_save_rejects_a_separate_draft_without_partial_changes(app_factory: Any) -> None:
    app, database, _ = app_factory()
    with TestClient(app) as client:
        _, csrf = login(client, "bowen")
        vid = published_version(database)
        version = client.get(f"/api/v1/agent-versions/{vid}").json()
        draft = client.post(
            f"/api/v1/agents/{version['agent_id']}/versions",
            headers=headers(csrf, **{"Idempotency-Key": "drawing-separate-draft"}),
        )
        assert draft.status_code == 201, draft.text
        for target in (version, draft.json()):
            response = client.put(
                f"/api/v1/agent-versions/{target['id']}/avatar",
                headers=headers(
                    csrf, **{"Idempotency-Key": "drawing-block-open-draft-" + target["id"]}
                ),
                json={
                    "expected_revision": target["revision"],
                    "expected_published_version_id": vid,
                    "avatar_config": config(),
                },
            )
            assert response.status_code == 409, response.text
            reread = client.get(f"/api/v1/agent-versions/{target['id']}").json()
            assert reread["avatar_config"] == target["avatar_config"]
            assert reread["revision"] == target["revision"]
        assert (
            client.get(f"/api/v1/agents/{version['agent_id']}").json()[
                "current_published_version_id"
            ]
            == vid
        )
