"""A teacher deletes a self-registered account: the person and their private
work and grades are physically removed."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.core.models import CourseMember, GroupMember, SessionRecord, User
from app.modules.auth.models import UserCredential
from app.modules.workspace.models import Conversation
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from tests.conftest import login
from tests.test_auth_self_registration import register

COURSE_ID = "b1ae79ed-e4a6-5b02-9abd-3a3ae944284b"
TEACHER_ID = "08b9de2d-bb75-5c71-a64b-231b48f9eb25"
HEADERS = {"Origin": "http://testserver"}


def _delete(client: TestClient, csrf: str, user_id: str) -> Any:
    return client.delete(
        f"/api/v1/courses/{COURSE_ID}/members/{user_id}",
        headers={**HEADERS, "X-CSRF-Token": csrf},
    )


def test_deleting_an_account_removes_the_person_and_their_private_work(
    app_factory: Any,
) -> None:
    app, database, _settings = app_factory()
    with TestClient(app) as student:
        created = register(student, username="leaving-student", password="abcde")
        assert created.status_code == 201, created.text
        user_id = str(created.json()["user"]["id"])
        csrf = created.json()["csrf_token"]
        group_id = created.json()["user"]["groups"][0]["group_id"]
        agent = student.post(
            f"/api/v1/groups/{group_id}/agents",
            headers={**HEADERS, "X-CSRF-Token": csrf, "Idempotency-Key": str(uuid4())},
            json={"name": "My private helper"},
        )
        assert agent.status_code == 201, agent.text
        agent_id = agent.json()["id"]
    with TestClient(app) as teacher:
        _, teacher_csrf = login(teacher)
        assert _delete(teacher, teacher_csrf, user_id).status_code == 204
        roster = teacher.get(f"/api/v1/courses/{COURSE_ID}/roster").json()
        assert all(entry["user_id"] != user_id for entry in roster["entries"])
        # A second delete finds nobody.
        assert _delete(teacher, teacher_csrf, user_id).status_code == 404
    with database.session() as db:
        from app.core.models import Agent

        assert db.get(Agent, agent_id) is None
        assert db.get(User, user_id) is None
        for model, column in (
            (SessionRecord, SessionRecord.user_id),
            (UserCredential, UserCredential.user_id),
            (CourseMember, CourseMember.user_id),
            (GroupMember, GroupMember.user_id),
            (Conversation, Conversation.user_id),
        ):
            count = db.scalar(select(func.count()).select_from(model).where(column == user_id))
            assert count == 0, model.__name__
    # The account cannot sign in, and its username is free again.
    with TestClient(app) as again:
        refused = again.post(
            "/api/v1/auth/login",
            json={"username": "leaving-student", "password": "abcde"},
        )
        assert refused.status_code in {401, 403}
        reused = register(again, username="leaving-student", password="abcde")
        assert reused.status_code == 201, reused.text
        assert reused.json()["user"]["id"] != user_id


def test_a_teacher_cannot_delete_themselves_or_a_catalog_account(client: TestClient) -> None:
    _, csrf = login(client)
    assert _delete(client, csrf, TEACHER_ID).status_code == 409
    roster = client.get(f"/api/v1/courses/{COURSE_ID}/roster").json()
    catalog = next(entry for entry in roster["entries"] if entry["username"] == "bowen")
    refused = _delete(client, csrf, catalog["user_id"])
    assert refused.status_code == 409
    assert refused.json()["code"] == "account_read_only"


def test_a_student_cannot_delete_accounts(app_factory: Any) -> None:
    app, _database, _settings = app_factory()
    with TestClient(app) as student:
        created = register(student, username="curious-student", password="abcde")
        csrf = created.json()["csrf_token"]
        assert _delete(student, csrf, TEACHER_ID).status_code in {403, 404}


def test_hard_delete_removes_public_work_and_grades_only_for_target(app_factory: Any) -> None:
    from datetime import UTC, datetime

    from app.core.models import Agent
    from app.modules.learning.models import LearningAssessment, LearningRecord
    from app.modules.quiz.models import ClassroomQuiz, ClassroomQuizAttempt, ClassroomQuizExemption
    from app.modules.teams.models import Team, TeamVersion

    from tests.test_mayaform_teams import _make_agent_version

    app, database, _ = app_factory()
    users = []
    with TestClient(app) as client:
        for name in ["erased-student", "remaining-student"]:
            response = register(client, username=name, password="abcde")
            assert response.status_code == 201, response.text
            user = response.json()["user"]
            users.append((user["id"], user["groups"][0]["group_id"]))
        agents = [
            _make_agent_version(
                database,
                owner_id=user_id,
                name=f"Shared work {index}",
                group_id=group_id,
                visibility="public",
            )[0]
            for index, (user_id, group_id) in enumerate(users)
        ]
        now = datetime.now(UTC)
        grades = []
        answers = []
        quiz_attempts = []
        quiz_exemptions = []
        quiz_id = str(uuid4())
        team_id, version_id = str(uuid4()), str(uuid4())
        with database.session() as db:
            db.add(
                ClassroomQuiz(
                    id=quiz_id,
                    course_id=COURSE_ID,
                    title="Deletion check",
                    created_by_user_id=TEACHER_ID,
                    created_at=now,
                    updated_at=now,
                )
            )
            db.add(
                Team(
                    id=team_id,
                    owner_user_id=users[1][0],
                    course_id=COURSE_ID,
                    group_id=users[1][1],
                    ownership_scope="group",
                    display_name="Other student's team",
                    visibility="public",
                    current_version_seq=1,
                    created_at=now,
                    updated_at=now,
                )
            )
            db.flush()
            db.add(
                TeamVersion(
                    id=version_id,
                    team_id=team_id,
                    version_seq=1,
                    display_name="Other student's team",
                    visibility="public",
                    authorization_epoch=0,
                    created_by_user_id=users[0][0],
                    created_at=now,
                )
            )
            for user_id, _ in users:
                grade_id, answer_id = str(uuid4()), str(uuid4())
                quiz_attempt_id = str(uuid4())
                grades.append(grade_id)
                answers.append(answer_id)
                quiz_attempts.append(quiz_attempt_id)
                exemption_id = str(uuid4())
                quiz_exemptions.append(exemption_id)
                db.add(
                    ClassroomQuizExemption(
                        id=exemption_id,
                        quiz_id=quiz_id,
                        course_id=COURSE_ID,
                        student_user_id=user_id,
                        taking_epoch=1,
                        deadline_at=now,
                        created_by_user_id=users[0][0],
                        created_at=now,
                        updated_at=now,
                    )
                )
                db.add(
                    ClassroomQuizAttempt(
                        id=quiz_attempt_id,
                        quiz_id=quiz_id,
                        course_id=COURSE_ID,
                        actor_user_id=user_id,
                        content_revision=1,
                        document_snapshot_json="{}",
                        answers_json="{}",
                        submitted_at=now,
                    )
                )
                db.add(
                    LearningAssessment(
                        id=grade_id,
                        owner_user_id=user_id,
                        course_id=COURSE_ID,
                        current_revision_seq=1,
                        created_at=now,
                        updated_at=now,
                    )
                )
                db.add(
                    LearningRecord(
                        id=answer_id,
                        actor_user_id=user_id,
                        course_id=COURSE_ID,
                        origin="single_agent",
                        chat_visibility="private",
                        record_kind="answer",
                        client_event_id=str(uuid4()),
                        payload_json='{"answer":"test answer"}',
                        payload_hash="0" * 64,
                        created_at=now,
                    )
                )
            db.commit()
        _, csrf = login(client)
        response = _delete(client, csrf, users[0][0])
        assert response.status_code == 204, response.text
        with database.session() as db:
            assert db.get(User, users[0][0]) is None
            assert db.get(Agent, agents[0]) is None
            assert db.get(LearningAssessment, grades[0]) is None
            assert db.get(LearningRecord, answers[0]) is None
            assert db.get(ClassroomQuizAttempt, quiz_attempts[0]) is None
            assert db.get(ClassroomQuizExemption, quiz_exemptions[0]) is None
            assert db.get(User, users[1][0]) is not None
            assert db.get(Agent, agents[1]) is not None
            assert db.get(LearningAssessment, grades[1]) is not None
            assert db.get(LearningRecord, answers[1]) is not None
            assert db.get(ClassroomQuiz, quiz_id) is not None
            assert db.get(ClassroomQuizAttempt, quiz_attempts[1]) is not None
            exemption = db.get(ClassroomQuizExemption, quiz_exemptions[1])
            assert exemption is not None
            assert exemption.created_by_user_id is None
            assert db.get(Team, team_id) is not None
            assert db.get(TeamVersion, version_id).created_by_user_id is None


def test_unruled_reference_rolls_back_the_entire_account_delete(app_factory: Any) -> None:
    from app.core.models import Agent
    from app.modules.purge import reset_catalog_cache
    from sqlalchemy import text

    from tests.test_mayaform_teams import _make_agent_version

    app, database, _ = app_factory()
    with TestClient(app) as client:
        response = register(client, username="protected-student", password="abcde")
        user_id = response.json()["user"]["id"]
        group_id = response.json()["user"]["groups"][0]["group_id"]
        agent_id, _ = _make_agent_version(
            database, owner_id=user_id, name="Must survive rollback", group_id=group_id
        )
        with database.session() as db:
            db.execute(
                text(
                    "CREATE TABLE account_delete_probe (id integer PRIMARY KEY, "
                    "user_id varchar(36) REFERENCES users(id))"
                )
            )
            db.execute(
                text("INSERT INTO account_delete_probe VALUES (1, :user_id)"), {"user_id": user_id}
            )
            db.commit()
        reset_catalog_cache()
        _, csrf = login(client)
        response = _delete(client, csrf, user_id)
        assert response.status_code == 409, response.text
        assert response.json()["code"] == "account_delete_blocked"
        with database.session() as db:
            assert db.get(User, user_id).username == "protected-student"
            assert db.get(Agent, agent_id) is not None
            assert db.get(UserCredential, user_id) is not None
        reset_catalog_cache()
