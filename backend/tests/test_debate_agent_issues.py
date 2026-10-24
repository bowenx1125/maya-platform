"""A refused Debate create names every Agent problem (owner request 2026-10-24)."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.core.models import Agent, AgentVersion
from app.modules.agents.readiness import agent_md_is_standard
from app.modules.debates.models import Debate
from sqlalchemy import func, select

from tests import test_wave2_setup as debate_fixtures
from tests.conftest import login
from tests.test_wave2_setup import COURSE_ID, GROUP_DEMO_ID, _insert_published_agent, headers

debate_app = debate_fixtures.debate_app


def _create(client: Any, csrf: str, agent_ids: list[str]) -> Any:
    return client.post(
        f"/api/v1/courses/{COURSE_ID}/debates",
        headers=headers(csrf, **{"Idempotency-Key": f"agent-issues-{uuid4()}"}),
        json={
            "topic": "How should people learn together?",
            "participants": [
                {"agent_id": agent_id, "stance_mode": "open"} for agent_id in agent_ids
            ],
            "round_count": 4,
            "rule_set_id": "ordered_multi_expert_mutual_learning_v1",
        },
    )


def test_agent_md_rule_is_a_heading_and_text() -> None:
    assert agent_md_is_standard("# 朱熹\n\n格物致知。")
    assert not agent_md_is_standard("格物致知。")
    assert not agent_md_is_standard("# 朱熹\n## 只有标题")
    assert not agent_md_is_standard("")


def test_every_agent_problem_is_listed_with_its_agent(debate_app: Any) -> None:
    _app, database, client = debate_app
    no_rag, no_rag_version, _ = _insert_published_agent(
        database, group_id=GROUP_DEMO_ID, name="朱熹"
    )
    bad_md, bad_md_version, _ = _insert_published_agent(
        database, group_id=GROUP_DEMO_ID, name="王阳明"
    )
    unpublished, _, _ = _insert_published_agent(database, group_id=GROUP_DEMO_ID, name="陆九渊")
    with database.session() as db:
        version = db.get(AgentVersion, no_rag_version)
        assert version is not None
        version.knowledge_snapshot_id = None
        broken = db.get(AgentVersion, bad_md_version)
        assert broken is not None
        broken.agent_md = "只有正文，没有标题"
        draft_only = db.get(Agent, unpublished)
        assert draft_only is not None
        draft_only.current_published_version_id = None
    _, csrf = login(client)
    response = _create(client, csrf, [no_rag, bad_md, unpublished])
    assert response.status_code == 422, response.text
    body = response.json()
    assert body["code"] == "debate_agents_not_ready"
    issues = {(item["agent_id"], item["issue"]) for item in body["details"]["issues"]}
    assert issues == {
        (no_rag, "rag_missing"),
        (bad_md, "agent_md_invalid"),
        (unpublished, "agent_not_published"),
    }
    named = {item["agent_id"]: item for item in body["details"]["issues"]}
    assert named[no_rag]["agent_name"] == "朱熹"
    assert "朱熹" in named[no_rag]["message"]
    with database.session() as db:
        assert db.scalar(select(func.count()).select_from(Debate)) == 0


def test_voice_none_alone_never_refuses_a_debate(debate_app: Any) -> None:
    _app, database, client = debate_app
    first, _, _ = _insert_published_agent(database, group_id=GROUP_DEMO_ID, name="A")
    second, _, _ = _insert_published_agent(database, group_id=GROUP_DEMO_ID, name="B")
    _, csrf = login(client)
    created = _create(client, csrf, [first, second])
    assert created.status_code == 201, created.text


def _issues(response: Any) -> list[dict[str, Any]]:
    assert response.status_code == 422, response.text
    body = response.json()
    assert body["code"] == "debate_agents_not_ready"
    return list(body["details"]["issues"])


def test_a_missing_or_foreign_agent_is_one_named_issue(debate_app: Any) -> None:
    _app, database, client = debate_app
    real, _, _ = _insert_published_agent(database, group_id=GROUP_DEMO_ID, name="A")
    missing = str(uuid4())
    _, csrf = login(client)
    issues = _issues(_create(client, csrf, [real, missing]))
    assert issues == [
        {
            "agent_id": missing,
            # Missing and out-of-course read the same, so nothing is disclosed.
            "agent_name": "",
            "issue": "agent_not_found",
            "blocking": True,
            "message": "Agent “” is no longer available in this course.",
        }
    ]


def test_a_concurrent_change_names_the_agent(debate_app: Any, monkeypatch: Any) -> None:
    from app.core.errors import validation_failure
    from app.modules.debates.setup import service

    _app, database, client = debate_app
    first, _, _ = _insert_published_agent(database, group_id=GROUP_DEMO_ID, name="朱熹")
    second, _, _ = _insert_published_agent(database, group_id=GROUP_DEMO_ID, name="王阳明")

    def changed(*_args: Any, **kwargs: Any) -> None:
        if kwargs["agent"].id == second:
            raise validation_failure("changed", code="agent_not_current")

    monkeypatch.setattr(service, "_fence_resolved_agent_chain", changed)
    _, csrf = login(client)
    [issue] = _issues(_create(client, csrf, [first, second]))
    assert (issue["agent_id"], issue["agent_name"], issue["issue"]) == (
        second,
        "王阳明",
        "agent_not_current",
    )
    with database.session() as db:
        assert db.scalar(select(func.count()).select_from(Debate)) == 0


def test_a_race_past_the_first_check_still_names_the_agent(
    debate_app: Any, monkeypatch: Any
) -> None:
    from app.modules.debates.setup import service

    _app, database, client = debate_app
    first, _, _ = _insert_published_agent(database, group_id=GROUP_DEMO_ID, name="A")
    second, second_version, _ = _insert_published_agent(
        database, group_id=GROUP_DEMO_ID, name="陆九渊"
    )
    with database.session() as db:
        version = db.get(AgentVersion, second_version)
        assert version is not None
        version.knowledge_snapshot_id = None
    # The RAG went away between the readiness check and the participant row.
    monkeypatch.setattr(service, "_assert_participants_ready", lambda *_a, **_k: None)
    _, csrf = login(client)
    [issue] = _issues(_create(client, csrf, [first, second]))
    assert (issue["agent_id"], issue["agent_name"], issue["issue"]) == (
        second,
        "陆九渊",
        "rag_missing",
    )


def test_the_agent_and_the_debate_form_read_the_same_readiness(debate_app: Any) -> None:
    _app, database, client = debate_app
    agent_id, version_id, _ = _insert_published_agent(database, group_id=GROUP_DEMO_ID, name="A")
    with database.session() as db:
        version = db.get(AgentVersion, version_id)
        assert version is not None
        version.agent_md = "no heading"
        version.voice_profile_id = None
    _, _csrf = login(client)
    candidates = client.get(f"/api/v1/courses/{COURSE_ID}/published-agents")
    assert candidates.status_code == 200, candidates.text
    [listed] = [item for item in candidates.json() if item["agent"]["id"] == agent_id]
    kinds = {(item["issue"], item["blocking"]) for item in listed["readiness_issues"]}
    assert kinds == {("agent_md_invalid", True), ("voice_missing", False)}
    detail = client.get(f"/api/v1/agents/{agent_id}")
    assert detail.status_code == 200, detail.text
    assert {item["issue"] for item in detail.json()["readiness_issues"]} == {
        "agent_md_invalid",
        "voice_missing",
    }


def test_an_agent_failing_every_hint_still_saves_and_publishes(debate_app: Any) -> None:
    """No RAG, Voice None, non-standard AGENT.md, retired Avatar: hints only."""

    _app, database, client = debate_app
    _, csrf = login(client, "bowen")
    created = client.post(
        f"/api/v1/groups/{GROUP_DEMO_ID}/agents",
        headers=headers(csrf, **{"Idempotency-Key": f"agent-issues-{uuid4()}"}),
        json={"name": "Soft Agent", "description": "", "visibility": "public"},
    )
    assert created.status_code == 201, created.text
    agent_id = created.json()["id"]
    version_id = created.json()["versions"][0]["id"]
    saved = client.patch(
        f"/api/v1/agent-versions/{version_id}",
        headers=headers(csrf),
        json={"expected_revision": 0, "agent_md": "just a sentence, no heading"},
    )
    assert saved.status_code == 200, saved.text
    with database.session() as db:
        version = db.get(AgentVersion, version_id)
        assert version is not None
        version.avatar_config_json = '{"template_id": "retired-template"}'
    published = client.post(
        f"/api/v1/agent-versions/{version_id}/publish",
        headers=headers(csrf, **{"Idempotency-Key": f"agent-issues-{uuid4()}"}),
        json={"expected_revision": saved.json()["revision"]},
    )
    assert published.status_code == 200, published.text
    assert published.json()["state"] == "published"
    detail = client.get(f"/api/v1/agents/{agent_id}")
    assert {item["issue"] for item in detail.json()["readiness_issues"]} == {
        "rag_missing",
        "agent_md_invalid",
        "avatar_missing",
        "voice_missing",
    }
    # A Debate still refuses it, naming every blocking reason.
    other, _, _ = _insert_published_agent(database, group_id=GROUP_DEMO_ID, name="Other")
    _, teacher_csrf = login(client)
    issues = _issues(_create(client, teacher_csrf, [agent_id, other]))
    assert {item["issue"] for item in issues} == {
        "rag_missing",
        "agent_md_invalid",
        "avatar_missing",
    }


def test_a_malformed_debate_names_each_field(debate_app: Any) -> None:
    _app, database, client = debate_app
    first, _, _ = _insert_published_agent(database, group_id=GROUP_DEMO_ID, name="A")
    second, _, _ = _insert_published_agent(database, group_id=GROUP_DEMO_ID, name="B")
    _, csrf = login(client)

    def post(body: dict[str, Any]) -> list[tuple[str, str]]:
        response = client.post(
            f"/api/v1/courses/{COURSE_ID}/debates",
            headers=headers(csrf, **{"Idempotency-Key": f"agent-issues-{uuid4()}"}),
            json={
                "topic": "How should people learn together?",
                "participants": [
                    {"agent_id": first, "stance_mode": "open"},
                    {"agent_id": second, "stance_mode": "open"},
                ],
                "round_count": 4,
                "rule_set_id": "ordered_multi_expert_mutual_learning_v1",
                **body,
            },
        )
        assert response.status_code == 400, response.text
        assert response.json()["code"] == "malformed_request"
        return [(item["field"], item["type"]) for item in response.json()["details"]["errors"]]

    assert post({"topic": "   "}) == [("topic", "topic_blank")]
    assert post(
        {
            "participants": [
                {"agent_id": first, "stance_mode": "open"},
                {"agent_id": first, "stance_mode": "open"},
            ]
        }
    ) == [("participants", "participants_duplicate")]
    assert post(
        {
            "participants": [
                {"agent_id": first, "stance_mode": "open"},
                {"agent_id": second, "stance_mode": "assigned"},
            ]
        }
    ) == [("participants.1", "assigned_stance_missing")]
