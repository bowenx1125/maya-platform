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
