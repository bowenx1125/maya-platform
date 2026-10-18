"""A Team whose Guide declares no assessment gets no assessment content at all.

Owner report (2026-10-18): a private, non-assessment Team member answered
"你是谁" with an invented "[Turn 1: identity probe — this turn is outside the
assessment protocol ...]" header. The prompt for that ordinary Team chat
carried test/attempt/score/ledger wording and thirteen assessment Tools, and
the model imitated it. The fix removes all of it for such Teams.
"""

from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

import pytest
from app.core.models import AgentVersion
from app.modules.auth.service import get_auth_context
from app.modules.runtime_tools.builtin import (
    ASSESSMENT_TOOL_NAMES,
    NON_ASSESSMENT_TOOL_NAMES,
    runtime_registry,
)
from app.modules.workspace import team_runtime as runtime
from app.modules.workspace.formal_assessment import declares_assessment
from app.modules.workspace.models import Conversation
from fastapi.testclient import TestClient

from tests.conftest import login, post_message
from tests.test_mayaform_team_conversations import (
    COURSE_ID,
    MAYA_ID,
    _create,
    _headers,
    _make_agent_version,
)

# Any of these in an ordinary Team prompt is assessment protocol leaking in.
ASSESSMENT_WORDS = re.compile(
    r"assess|\btests?\b|attempt|score|rubric|ledger|\bformal\b|boundary|正式测评|测评|"
    r"read_memory|read_session|evaluator|summarizer|question",
    re.IGNORECASE,
)
INFORMAL_RULESET = (
    "# Team Ruleset\n\n## Informal\n- The Leader always replies first.\n"
    "- Others reply only when relevant; an empty reply is fine.\n"
)
FORMAL_RULESET = (
    "# Team Ruleset\n\n## Formal assessment\nanswer_recorder: A\nquestion_guide: B\n"
    "scorer: A\nsummarizer: C\nstudent_round_order: A, B\n"
)


def test_declares_assessment_needs_a_formal_section_or_recipe() -> None:
    assert declares_assessment("# Guide\n\n" + FORMAL_RULESET)
    assert declares_assessment("# Guide\nMAYA-ASSESSMENT-RECIPE: mayaform.diagnostic.v1\n")
    assert not declares_assessment("# Guide\n\n" + INFORMAL_RULESET)
    assert not declares_assessment("# Guide\n\nJust chat.")
    # A heading outside # Team Ruleset is ordinary prose, not a declaration.
    assert not declares_assessment("# Guide\n\n## Formal assessment\nscorer: A\n")


def test_every_runtime_tool_is_classified_for_assessment() -> None:
    names = set(runtime_registry())
    assert not ASSESSMENT_TOOL_NAMES & NON_ASSESSMENT_TOOL_NAMES
    assert names == ASSESSMENT_TOOL_NAMES | NON_ASSESSMENT_TOOL_NAMES


@pytest.mark.parametrize("viewer_is_teacher", [False, True])
@pytest.mark.parametrize("is_leader", [False, True])
@pytest.mark.parametrize("ruleset", [None, INFORMAL_RULESET])
def test_ordinary_team_prompt_has_no_assessment_wording(
    viewer_is_teacher: bool, is_leader: bool, ruleset: str | None
) -> None:
    body = runtime.extract_team_ruleset(f"# Guide\n\n{ruleset}") if ruleset else None
    for mentioned in (False, True):
        system = runtime._member_system(
            "# Reader\n\nRead the chat log.",
            "{}",
            team_ruleset=body,
            speaker_name="读心师",
            is_leader=is_leader,
            viewer_is_teacher=viewer_is_teacher,
            mentioned=mentioned,
            attempt_closed=True,
            assessment_capable=False,
        )
        assert ASSESSMENT_WORDS.search(system) is None, ASSESSMENT_WORDS.search(system)
        assert "You are 读心师." in system
        assert "<team_reply_protocol>" in system
        assert "does not treat that member as failed" in system
        assert ("You must reply" in system) is mentioned
        assert ("<team_informal>" in system) is (ruleset is not None)
        assert "write_agent_memory" in system


def test_assessment_team_prompt_is_unchanged_by_default() -> None:
    body = runtime.extract_team_ruleset("# Guide\n\n" + FORMAL_RULESET)
    leader = runtime._member_system(
        "# Guide", "{}", team_ruleset=body, speaker_name="B", is_leader=True
    )
    assert "saying 正式测评" in leader
    assert "Formal assessment does not change ordinary chat" in leader
    # A live attempt or executor keeps the assessment protocol even if flagged.
    active = runtime._member_system(
        "# Guide", "{}", assessment_active=True, speaker_name="B", assessment_capable=False
    )
    assert "<active_assessment_action_protocol>" in active


def _team_chat(
    client: TestClient, database: Any, leader_md: str, *, as_student: bool
) -> tuple[dict[str, Any], str]:
    _, csrf = login(client, "maya")
    versions = [
        _make_agent_version(
            database, owner_id=MAYA_ID, name=f"Member {index}", visibility="public"
        )[1]
        for index in range(2)
    ]
    with database.session() as db:
        leader = db.get(AgentVersion, versions[0])
        assert leader is not None
        leader.agent_md = leader_md
    created = client.post(
        f"/api/v1/courses/{COURSE_ID}/teams",
        headers=_headers(csrf, f"no-assess-team-{uuid4()}"),
        json={
            "display_name": "Ordinary Team",
            "visibility": "public",
            "members": [
                {"agent_version_id": version_id, "position": index, "is_leader": index == 0}
                for index, version_id in enumerate(versions)
            ],
        },
    )
    assert created.status_code == 201, created.text
    if as_student:
        _, csrf = login(client, "bowen")
        return _create(client, csrf, {"kind": "maya_team", "team_id": created.json()["id"]}), csrf
    return _create(client, csrf, {"kind": "team", "team_id": created.json()["id"]}), csrf


def _send(
    client: TestClient, session: dict[str, Any], csrf: str, monkeypatch: Any
) -> tuple[list[runtime.MemberRequest], str]:
    seen: list[runtime.MemberRequest] = []

    def reply(request: runtime.MemberRequest) -> runtime.MemberReply:
        seen.append(request)
        return runtime.MemberReply(f"Reply {request.speaker_name}")

    monkeypatch.setattr(runtime, "invoke_mock_member", reply)
    response = post_message(
        client,
        f"/api/v1/conversations/{session['id']}/messages",
        headers=_headers(csrf),
        json={
            "request_id": str(uuid4()),
            "expected_revision": session["revision"],
            "message": "你是谁，介绍你自己",
            "routing": {"mode": "all", "participant_ids": []},
        },
    )
    assert response.status_code == 200, response.text
    turn = [item for item in response.json()["turns"] if item["user_text"]][-1]
    return seen, turn["id"]


@pytest.mark.parametrize("as_student", [False, True])
def test_ordinary_team_turn_gets_no_assessment_prompt_or_tools(
    app_bundle: Any, client: TestClient, database: Any, monkeypatch: Any, as_student: bool
) -> None:
    app, _, settings = app_bundle
    session, csrf = _team_chat(
        client,
        database,
        "# Leader\n\nGive the big picture.\n\n" + INFORMAL_RULESET,
        as_student=as_student,
    )
    seen, turn_id = _send(client, session, csrf, monkeypatch)
    assert seen
    for request in seen:
        assert ASSESSMENT_WORDS.search(request.system_message) is None, request.speaker_name
    with database.session() as db:
        row = db.get(Conversation, session["id"])
        assert row is not None and not runtime.team_assessment_capable(db, row)
        actor = get_auth_context(db, settings, client.cookies.get("maya_session"))
        assert actor is not None
    claim = runtime.TeamClaim(turn_id, "unused", False, settings, actor)
    names = {
        function.name
        for function in runtime._runtime_tools(
            database.session_factory,
            claim,
            conversation_id=session["id"],
            participant_id=seen[0].participant_id,
            turn_id=turn_id,
        )
    }
    assert names, "ordinary Team tools such as account memory stay available"
    assert not names & ASSESSMENT_TOOL_NAMES
    assert "write_agent_memory" in names


def test_assessment_team_keeps_its_protocol_and_tools(
    app_bundle: Any, client: TestClient, database: Any, monkeypatch: Any
) -> None:
    _, _, settings = app_bundle
    session, csrf = _team_chat(
        client,
        database,
        "# Leader\n\n# Team Ruleset\n\n## Formal assessment\nanswer_recorder: Member 1\n"
        "question_guide: Member 0\nscorer: Member 1\nsummarizer: Member 1\n"
        "student_round_order: Member 1, Member 0\n",
        as_student=False,
    )
    seen, turn_id = _send(client, session, csrf, monkeypatch)
    assert any("Formal assessment" in request.system_message for request in seen)
    with database.session() as db:
        row = db.get(Conversation, session["id"])
        assert row is not None and runtime.team_assessment_capable(db, row)
        actor = get_auth_context(db, settings, client.cookies.get("maya_session"))
    claim = runtime.TeamClaim(turn_id, "unused", False, settings, actor)
    names = {
        function.name
        for function in runtime._runtime_tools(
            database.session_factory,
            claim,
            conversation_id=session["id"],
            participant_id=seen[0].participant_id,
            turn_id=turn_id,
        )
    }
    assert "read_course_statistics" in names
