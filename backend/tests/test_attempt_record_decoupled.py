"""Owner rules (2026-10-20): Chat window and Record are decoupled.

1. Deleting a Chat keeps the attempt and its per-question answers in Record.
2. A student may complete the same assessment Team many times.
3. At most one unfinished attempt per student and Team; a new start asks
   continue (reopen it) or restart (delete it, keep completed ones).
4. A resumed attempt keeps its answers and tells the prompt it was resumed.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from app.core.db import Database
from app.core.errors import PlatformError
from app.modules.auth.service import get_auth_context
from app.modules.learning.attempts import (
    RESUME_CHOICE_PROMPT,
    is_resumed_attempt,
    resume_choice,
)
from app.modules.learning.models import AssessmentAttempt, AssessmentAttemptQuestion
from app.modules.learning.reports import list_my_assessment_attempts
from app.modules.workspace.models import Conversation
from app.modules.workspace.team_runtime import (
    RESUMED_ATTEMPT_NOTE,
    _attempt_was_resumed,
    _begin_formal_attempt_on_explicit_start,
)
from fastapi.testclient import TestClient
from sqlalchemy import select

from tests.test_workspace_reentry import (  # noqa: F401
    _create_attempt,
    _login,
    _post_maya_team,
    reentry_env,
)


def _delete_chat(client: TestClient, csrf: str, conversation_id: str) -> None:
    response = client.delete(
        f"/api/v1/conversations/{conversation_id}",
        headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
    )
    assert response.status_code == 204, response.text


def _unfinished(db: Any, actor_user_id: str, team_id: str) -> list[AssessmentAttempt]:
    return list(
        db.scalars(
            select(AssessmentAttempt).where(
                AssessmentAttempt.actor_user_id == actor_user_id,
                AssessmentAttempt.team_id == team_id,
                AssessmentAttempt.status.in_(("in_progress", "paused")),
            )
        )
    )


def _setup(env: tuple[Database, Any, TestClient]) -> dict[str, Any]:
    database, settings, client = env
    user_id, token, csrf = _login(client, "bowen")
    source_id, team_id, attempt_id, _rev = _create_attempt(
        database,
        settings,
        actor_user_id=user_id,
        actor_token=token,
        visibility="private",
        status="in_progress",
    )
    _delete_chat(client, csrf, source_id)
    created = _post_maya_team(client, csrf, team_id)
    assert created.status_code == 200, created.text
    new_id = created.json()["id"]
    assert new_id != source_id
    return {
        "database": database,
        "settings": settings,
        "user_id": user_id,
        "token": token,
        "source_id": source_id,
        "team_id": team_id,
        "attempt_id": attempt_id,
        "new_id": new_id,
    }


def _start(db: Any, ctx: dict[str, Any], message: str) -> None:
    actor = get_auth_context(db, ctx["settings"], ctx["token"])
    row = db.get(Conversation, ctx["new_id"])
    _begin_formal_attempt_on_explicit_start(db, row, actor, message, str(uuid4()))


def test_choice_phrases() -> None:
    assert resume_choice("继续") == "continue"
    assert resume_choice(" 接着上次 ") == "continue"
    assert resume_choice("重新做") == "restart"
    assert resume_choice("重做。") == "restart"
    assert resume_choice("我继续想想这道题") is None


def test_rule1_deleted_chat_keeps_attempt_and_record(reentry_env: Any) -> None:  # noqa: F811
    ctx = _setup(reentry_env)
    with ctx["database"].session() as db:
        attempt = db.get(AssessmentAttempt, ctx["attempt_id"])
        assert attempt is not None and attempt.status == "in_progress"
        assert db.scalars(
            select(AssessmentAttemptQuestion).where(
                AssessmentAttemptQuestion.attempt_id == attempt.id
            )
        ).first()
        actor = get_auth_context(db, ctx["settings"], ctx["token"])
        course_id = db.get(Conversation, ctx["source_id"]).course_id
        listed = list_my_assessment_attempts(db, actor, course_id=course_id)
        assert ctx["attempt_id"] in str(listed)


def test_rule3_start_asks_when_unfinished_attempt_exists(reentry_env: Any) -> None:  # noqa: F811
    ctx = _setup(reentry_env)
    with ctx["database"].session() as db:
        with pytest.raises(PlatformError) as raised:
            _start(db, ctx, "正式测评")
        assert raised.value.code == "assessment_resume_choice_required"
        assert raised.value.message == RESUME_CHOICE_PROMPT
        assert [a.id for a in _unfinished(db, ctx["user_id"], ctx["team_id"])] == [
            ctx["attempt_id"]
        ]


def test_rule3_continue_reopens_attempt_with_answers(reentry_env: Any) -> None:  # noqa: F811
    ctx = _setup(reentry_env)
    with ctx["database"].session() as db:
        before = {
            row.id
            for row in db.scalars(
                select(AssessmentAttemptQuestion).where(
                    AssessmentAttemptQuestion.attempt_id == ctx["attempt_id"]
                )
            )
        }
        with pytest.raises(PlatformError) as raised:
            _start(db, ctx, "继续")
        assert raised.value.code == "assessment_resume_original_conversation"
        assert raised.value.details["conversation_id"] == ctx["source_id"]
    with ctx["database"].session() as db:
        source = db.get(Conversation, ctx["source_id"])
        assert source is not None and source.withdrawn_at is None
        unfinished = _unfinished(db, ctx["user_id"], ctx["team_id"])
        assert [a.id for a in unfinished] == [ctx["attempt_id"]]
        after = {
            row.id
            for row in db.scalars(
                select(AssessmentAttemptQuestion).where(
                    AssessmentAttemptQuestion.attempt_id == ctx["attempt_id"]
                )
            )
        }
        assert after == before
        # Rule 4: the resumed attempt keeps its answers and edit path; the
        # prompt is only told it was resumed.
        assert is_resumed_attempt(db, ctx["attempt_id"])
        assert _attempt_was_resumed(db, source)
        assert "Do not re-ask answered questions" in RESUMED_ATTEMPT_NOTE


def test_rule3_restart_deletes_unfinished_and_starts_fresh(reentry_env: Any) -> None:  # noqa: F811
    ctx = _setup(reentry_env)
    with ctx["database"].session() as db:
        _start(db, ctx, "重新做")
        db.commit()
    with ctx["database"].session() as db:
        assert db.get(AssessmentAttempt, ctx["attempt_id"]) is None
        assert not db.scalars(
            select(AssessmentAttemptQuestion).where(
                AssessmentAttemptQuestion.attempt_id == ctx["attempt_id"]
            )
        ).first()
        unfinished = _unfinished(db, ctx["user_id"], ctx["team_id"])
        assert len(unfinished) == 1
        assert unfinished[0].source_conversation_id == ctx["new_id"]
        assert not is_resumed_attempt(db, unfinished[0].id)


def test_rule2_completed_attempts_accumulate_and_restart_keeps_them(reentry_env: Any) -> None:  # noqa: F811
    database, settings, client = reentry_env
    user_id, token, csrf = _login(client, "bowen")
    source_id, team_id, first_id, _rev = _create_attempt(
        database,
        settings,
        actor_user_id=user_id,
        actor_token=token,
        visibility="private",
        status="completed",
    )
    _delete_chat(client, csrf, source_id)
    completed_ids = {first_id}
    for _ in range(2):
        created = _post_maya_team(client, csrf, team_id)
        assert created.status_code == 200, created.text
        with database.session() as db:
            actor = get_auth_context(db, settings, token)
            row = db.get(Conversation, created.json()["id"])
            # No unfinished attempt: no question, a new attempt starts.
            _begin_formal_attempt_on_explicit_start(db, row, actor, "正式测评", str(uuid4()))
            fresh = _unfinished(db, user_id, team_id)
            assert len(fresh) == 1
            fresh[0].status = "completed"
            fresh[0].completed_at = datetime.now(UTC)
            completed_ids.add(fresh[0].id)
            db.commit()
        _delete_chat(client, csrf, created.json()["id"])
    with database.session() as db:
        done = db.scalars(
            select(AssessmentAttempt.id).where(
                AssessmentAttempt.actor_user_id == user_id,
                AssessmentAttempt.team_id == team_id,
                AssessmentAttempt.status == "completed",
            )
        ).all()
        assert set(done) == completed_ids and len(done) == 3


def test_rule3_tool_start_asks_instead_of_silently_abandoning(
    reentry_env: Any,  # noqa: F811
) -> None:
    from app.modules.learning.attempts import apply_assessment_decision
    from app.modules.learning.schemas import AssessmentRuntimeDecision

    ctx = _setup(reentry_env)
    with ctx["database"].session() as db:
        actor = get_auth_context(db, ctx["settings"], ctx["token"])
        with pytest.raises(PlatformError) as raised:
            apply_assessment_decision(
                db,
                actor,
                ctx["new_id"],
                user_message="开始吧",
                decision=AssessmentRuntimeDecision(
                    client_event_id=uuid4(), classification="start_request"
                ),
            )
        assert raised.value.code == "assessment_resume_choice_required"
        db.rollback()
    with ctx["database"].session() as db:
        attempt = db.get(AssessmentAttempt, ctx["attempt_id"])
        assert attempt is not None and attempt.status == "in_progress"
        assert len(_unfinished(db, ctx["user_id"], ctx["team_id"])) == 1
