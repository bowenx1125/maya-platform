"""A republished assessment Team reopens on its current version.

Owner report (2026-10-18): a teacher republished an assessment Team while a
student was mid-test. Reopening the Team returned the old unfinished Chat,
whose publication was now revoked, and every send there was 404 forever.
Finding the unfinished test now skips a Chat that can no longer be sent to,
so the student gets a new Chat on the current version. The unfinished
attempt on the revoked version is kept (the teacher's Record shows it).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.modules.demo_baseline.service import ensure_demo_baseline
from app.modules.learning.attempts import start_or_resume_attempt
from app.modules.learning.models import AssessmentAttempt
from app.modules.teams.models import (
    CourseTeamPublication,
    Team,
    TeamVersionMember,
    TeamVersionSet,
)
from app.modules.teams.schemas import SaveTeamVersionRequest, TeamMemberInput
from app.modules.teams.service import save_team_version
from app.modules.workspace import team_runtime as runtime
from app.modules.workspace.models import Conversation, ConversationTurn
from app.modules.workspace.schemas import MayaTeamChatEntry, TeamRouting
from app.modules.workspace.team_conversation import create_team_conversation
from app.seed import TEACHER_ID
from fastapi.testclient import TestClient
from sqlalchemy import select

from tests.test_mayaform_assessment_attempts import (
    STUDENT_ID,
    _create_formal_conversation,
    _service_actor,
)


def _republish(db: Any, settings: Any, conversation: Conversation) -> str:
    """The teacher saves a new version of the published Team.

    An edit that changes authorization revokes the old publication; the old
    publication is revoked here directly so the test does not depend on
    which edit that is.
    """

    teacher = _service_actor(db, settings, TEACHER_ID)
    team = db.get(Team, conversation.team_id)
    assert team is not None
    members = db.scalars(
        select(TeamVersionMember)
        .where(TeamVersionMember.team_version_id == conversation.team_version_id)
        .order_by(TeamVersionMember.position)
    ).all()
    set_ids = db.scalars(
        select(TeamVersionSet.knowledge_set_id).where(
            TeamVersionSet.team_version_id == conversation.team_version_id
        )
    ).all()
    save_team_version(
        db,
        teacher,
        team.id,
        SaveTeamVersionRequest(
            display_name=team.display_name,
            visibility=team.visibility,
            expected_metadata_revision=team.metadata_revision,
            members=[
                TeamMemberInput(
                    agent_version_id=member.agent_version_id,
                    is_leader=member.is_leader,
                    position=member.position,
                )
                for member in members
            ],
            shared_knowledge_set_ids=list(set_ids),
        ),
    )
    old = db.get(CourseTeamPublication, conversation.publication_id)
    assert old is not None
    old.state = "revoked"
    old.revoked_at = datetime.now(UTC)
    current = db.scalar(
        select(CourseTeamPublication).where(
            CourseTeamPublication.team_id == team.id,
            CourseTeamPublication.state == "published",
        )
    )
    assert current is not None and current.id != old.id
    db.flush()
    return current.id


def test_reopening_a_republished_team_mid_test_gives_a_chat_that_sends(
    client: TestClient, database: Any, app_bundle: Any, monkeypatch: Any
) -> None:
    del client
    _app, _database, settings = app_bundle
    monkeypatch.setattr(
        runtime, "invoke_mock_member", lambda request: runtime.MemberReply("Answer")
    )
    with database.session() as db:
        ensure_demo_baseline(db, settings.resolved_data_root)
        old_chat_id, team_id, *_rest = _create_formal_conversation(db, prompts=("甲题", "乙题"))
        db.commit()
        actor = _service_actor(db, settings, STUDENT_ID)
        started = start_or_resume_attempt(db, actor, old_chat_id, client_event_id=uuid4())
        assert started is not None
        old_attempt_id = str(started.attempt.id)
        db.commit()

        old_chat = db.get(Conversation, old_chat_id)
        assert old_chat is not None
        new_publication_id = _republish(db, settings, old_chat)
        db.commit()

    with database.session() as db:
        reopened = create_team_conversation(
            db, actor, MayaTeamChatEntry(kind="maya_team", team_id=team_id)
        )
        db.commit()
        reopened_id, reopened_publication = reopened.id, reopened.publication_id
    assert reopened_id != old_chat_id
    assert reopened_publication == new_publication_id

    with database.session() as db:
        chat = db.get(Conversation, reopened_id)
        assert chat is not None
        claim = runtime.claim_team_turn(
            db,
            settings,
            conversation_id=reopened_id,
            actor_id=actor.user.id,
            request_id=str(uuid4()),
            expected_revision=chat.revision,
            message="你好",
            routing=TeamRouting(mode="all"),
            actor_context=actor,
        )
    runtime.execute_team_turn(database.session_factory, claim)
    with database.session() as db:
        turn = db.get(ConversationTurn, claim.turn_id)
        assert turn is not None and turn.state == "ready", (turn.state, turn.safe_error_code)
        # The unfinished attempt on the revoked version is kept, not deleted.
        old_attempt = db.get(AssessmentAttempt, old_attempt_id)
        assert old_attempt is not None and old_attempt.status in {"in_progress", "paused"}
        assert db.get(Conversation, old_chat_id) is not None

    # Starting the test again on the current version follows the owner rule
    # for a new Chat (2026-10-13): a new test begins and the unfinished one on
    # the revoked version is given up, never deleted.
    with database.session() as db:
        chat = db.get(Conversation, reopened_id)
        assert chat is not None
        formal = runtime.claim_team_turn(
            db,
            settings,
            conversation_id=reopened_id,
            actor_id=actor.user.id,
            request_id=str(uuid4()),
            expected_revision=chat.revision,
            message="正式测评",
            routing=TeamRouting(mode="all"),
            actor_context=actor,
        )
    runtime.execute_team_turn(database.session_factory, formal)
    with database.session() as db:
        turn = db.get(ConversationTurn, formal.turn_id)
        assert turn is not None and turn.state == "ready", (turn.state, turn.safe_error_code)
        attempts = {
            attempt.source_conversation_id: attempt
            for attempt in db.scalars(
                select(AssessmentAttempt).where(AssessmentAttempt.actor_user_id == STUDENT_ID)
            )
        }
        assert attempts[reopened_id].status == "in_progress"
        old = attempts[old_chat_id]
        assert old.id == old_attempt_id
        assert (old.status, old.abandonment_reason) == ("abandoned", "user_redo")
