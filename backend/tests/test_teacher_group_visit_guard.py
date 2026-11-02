"""Who may enter a group, how long that visit lives, and what it must not do.

Entering is a temporary membership of the teacher who teaches the group's
course. It is not a student roster row, it expires, and a second enter
refreshes the same row.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from alembic import command
from app.core.db import ALEMBIC_HEAD, MIGRATION_BASELINE
from app.core.models import (
    Course,
    CourseMember,
    Group,
    GroupMember,
    TeacherGroupAccess,
    User,
)
from app.modules.org.teacher_visit import purge_expired_teacher_visits
from fastapi.testclient import TestClient
from sqlalchemy import func, inspect, select, text

from tests.conftest import login
from tests.postgres_db import named_url
from tests.test_mayaform_teams import (
    BOWEN_ID,
    COURSE_ID,
    MAYA_ID,
    _headers,
    _make_agent_version,
)
from tests.test_teacher_group_visit import DEMO_GROUP_ID, _membership
from tests.test_teacher_observer import _group_with_private_work

JADE_ID = "89857c76-2d84-5ecf-b680-990815b98680"
KAIKAI_ID = "bc170f51-45fb-5296-a36d-a2edc8f8d315"
ORIGIN = {"Origin": "http://testserver"}


def test_only_an_active_teacher_of_the_owning_course_can_enter(
    client: TestClient, database: Any
) -> None:
    foreign_course = str(uuid4())
    foreign_group = str(uuid4())
    now = datetime.now(UTC)
    with database.session() as db:
        db.add(
            Course(
                id=foreign_course,
                code=f"other-{foreign_course[:8]}",
                name="Other course",
                current_audio_debate_id=None,
                created_at=now,
            )
        )
        db.add(
            Group(
                id=foreign_group,
                course_id=foreign_course,
                name="Other group",
                created_at=now,
            )
        )
        jade = db.get(CourseMember, {"course_id": COURSE_ID, "user_id": JADE_ID})
        assert jade is not None
        db.delete(jade)
        jade_group = db.get(GroupMember, {"group_id": DEMO_GROUP_ID, "user_id": JADE_ID})
        if jade_group is not None:
            db.delete(jade_group)
        db.add(
            CourseMember(
                course_id=foreign_course,
                user_id=JADE_ID,
                role="teacher",
                created_at=now,
            )
        )
        colleague = db.get(CourseMember, {"course_id": COURSE_ID, "user_id": KAIKAI_ID})
        assert colleague is not None
        colleague.role = "teacher"
        db.commit()

    # The same course's other teacher may enter. A teacher of another course,
    # a student, a missing group, and a request with no credentials may not.
    # Login is per request: the client keeps only the latest session cookie.
    _, maya_csrf = login(client, "maya")
    assert client.post(_membership(), headers=_headers(maya_csrf)).status_code == 200
    _, kaikai_csrf = login(client, "kaikai")
    assert client.post(_membership(), headers=_headers(kaikai_csrf)).status_code == 200
    _, jade_csrf = login(client, "jade")
    assert client.post(_membership(), headers=_headers(jade_csrf)).status_code == 404
    _, maya_csrf = login(client, "maya")
    assert client.post(_membership(foreign_group), headers=_headers(maya_csrf)).status_code == 404
    _, bowen_csrf = login(client, "bowen")
    assert client.post(_membership(), headers=_headers(bowen_csrf)).status_code == 403
    _, maya_csrf = login(client, "maya")
    assert client.post(_membership(str(uuid4())), headers=_headers(maya_csrf)).status_code == 404
    assert TestClient(client.app).post(_membership()).status_code == 401
    assert client.post(_membership(), headers=ORIGIN).status_code == 403

    with database.session() as db:
        teacher = db.get(User, MAYA_ID)
        assert teacher is not None
        teacher.status = "inactive"
        db.commit()
    assert client.post(_membership(), headers=_headers(maya_csrf)).status_code == 401


def test_entering_twice_refreshes_one_row_and_leaving_deletes_it(
    client: TestClient, database: Any
) -> None:
    _, csrf = login(client, "maya")
    headers = {**ORIGIN, "X-CSRF-Token": csrf}
    assert client.post(_membership(), headers=headers).status_code == 200
    with database.session() as db:
        row = db.get(TeacherGroupAccess, {"group_id": DEMO_GROUP_ID, "user_id": MAYA_ID})
        assert row is not None
        row.expires_at = datetime.now(UTC) + timedelta(minutes=1)
        db.commit()
    assert client.post(_membership(), headers=headers).status_code == 200
    with database.session() as db:
        rows = db.scalars(
            select(TeacherGroupAccess).where(
                TeacherGroupAccess.group_id == DEMO_GROUP_ID,
                TeacherGroupAccess.user_id == MAYA_ID,
            )
        ).all()
        assert len(rows) == 1
        assert rows[0].expires_at > datetime.now(UTC) + timedelta(hours=1)
        assert db.get(GroupMember, {"group_id": DEMO_GROUP_ID, "user_id": MAYA_ID}) is None
    assert client.delete(_membership(), headers=headers).status_code == 204
    with database.session() as db:
        assert db.get(TeacherGroupAccess, {"group_id": DEMO_GROUP_ID, "user_id": MAYA_ID}) is None
    assert client.delete(_membership(), headers=headers).status_code == 204


def test_students_do_not_see_the_temporary_member(client: TestClient, database: Any) -> None:
    with database.session() as db:
        before = db.scalar(
            select(func.count())
            .select_from(GroupMember)
            .where(GroupMember.group_id == DEMO_GROUP_ID)
        )
    _, csrf = login(client, "maya")
    assert client.post(_membership(), headers={**ORIGIN, "X-CSRF-Token": csrf}).status_code == 200
    with database.session() as db:
        after = db.scalar(
            select(func.count())
            .select_from(GroupMember)
            .where(GroupMember.group_id == DEMO_GROUP_ID)
        )
    assert before == after

    login(client, "bowen")
    detail = client.get(f"/api/v1/groups/{DEMO_GROUP_ID}").json()
    assert MAYA_ID not in {member["user_id"] for member in detail["members"]}
    login(client, "maya")
    overview = client.get(f"/api/v1/groups/{DEMO_GROUP_ID}/overview").json()
    assert MAYA_ID not in {member["user_id"] for member in overview["members"]}
    with database.session() as db:
        roster = db.scalar(
            select(func.count())
            .select_from(GroupMember)
            .where(GroupMember.group_id == DEMO_GROUP_ID, GroupMember.user_id == MAYA_ID)
        )
        assert roster == 0


def test_a_visit_edits_only_this_groups_studyform_and_public_brainform(
    client: TestClient, database: Any
) -> None:
    work = _group_with_private_work(client, database)
    other_group = str(uuid4())
    now = datetime.now(UTC)
    with database.session() as db:
        db.add(
            Group(
                id=other_group,
                course_id=COURSE_ID,
                name=f"Elsewhere {other_group[:8]}",
                created_at=now,
            )
        )
        db.commit()
    other_agent, _version = _make_agent_version(
        database,
        owner_id=BOWEN_ID,
        name="Elsewhere voice",
        visibility="private",
        group_id=other_group,
    )
    _, csrf = login(client, "maya")
    headers = {**ORIGIN, "X-CSRF-Token": csrf}
    assert client.post(_membership(work["group"]), headers=headers).status_code == 200

    renamed = client.patch(
        f"/api/v1/agents/{work['agent']}",
        headers=headers,
        json={"name": "Reviewed", "expected_metadata_revision": 0},
    )
    assert renamed.status_code == 200, renamed.text
    removed = client.delete(
        f"/api/v1/agents/{work['agent']}",
        headers=_headers(csrf, f"visit-no-delete-{uuid4()}"),
    )
    assert removed.status_code in {403, 404}, removed.text
    elsewhere = client.patch(
        f"/api/v1/agents/{other_agent}",
        headers=headers,
        json={"name": "Not this group", "expected_metadata_revision": 0},
    )
    assert elsewhere.status_code in {403, 404}, elsewhere.text
    assert client.delete(f"/api/v1/groups/{work['group']}", headers=headers).status_code == 405
    # There is no member-management route for a visit to call.
    assert client.post(f"/api/v1/groups/{work['group']}/members", headers=headers).status_code in {
        404,
        405,
    }

    private = client.post(
        f"/api/v1/knowledge-documents/{work['document']}:rename",
        headers=_headers(csrf, f"visit-private-rename-{uuid4()}"),
        json={"expected_filename": "private-notes.md", "filename": "opened-notes.md"},
    )
    assert private.status_code == 404, private.text


def test_expired_visit_cannot_edit_and_the_sweep_removes_it(
    client: TestClient, database: Any
) -> None:
    work = _group_with_private_work(client, database)
    _, csrf = login(client, "maya")
    headers = {**ORIGIN, "X-CSRF-Token": csrf}
    assert client.post(_membership(work["group"]), headers=headers).status_code == 200
    with database.session() as db:
        from app.core.models import KnowledgeDocument

        document = db.get(KnowledgeDocument, work["document"])
        assert document is not None
        document.visibility = "public"
        db.commit()
    opened = client.post(
        f"/api/v1/knowledge-documents/{work['document']}:rename",
        headers=_headers(csrf, f"visit-public-rename-{uuid4()}"),
        json={"expected_filename": "private-notes.md", "filename": "class-notes.md"},
    )
    assert opened.status_code == 200, opened.text
    assert opened.json()["source_filename"] == "class-notes.md"

    with database.session() as db:
        row = db.get(TeacherGroupAccess, {"group_id": work["group"], "user_id": MAYA_ID})
        assert row is not None
        row.expires_at = datetime.now(UTC) - timedelta(minutes=5)
        db.commit()
    stale = client.patch(
        f"/api/v1/agents/{work['agent']}",
        headers=headers,
        json={"name": "After expiry", "expected_metadata_revision": 0},
    )
    assert stale.status_code in {403, 404}, stale.text
    with database.session() as db:
        removed = purge_expired_teacher_visits(db)
        db.flush()
        assert removed == 1
        left = db.scalar(
            select(func.count())
            .select_from(TeacherGroupAccess)
            .where(
                TeacherGroupAccess.group_id == work["group"],
                TeacherGroupAccess.user_id == MAYA_ID,
            )
        )
        assert left == 0


def test_visit_expiry_migration_keeps_rows_and_downgrades(tmp_path: Any) -> None:
    from app.core.db import Database

    database = Database(named_url(f"{tmp_path / 'visit-expiry'}"))
    database.upgrade_schema()
    now = datetime.now(UTC)
    user_id, course_id, group_id = str(uuid4()), str(uuid4()), str(uuid4())
    with database.session() as db:
        db.add(
            User(
                id=user_id,
                username=f"visit-{user_id[:8]}",
                display_name="Visit",
                status="active",
                created_at=now,
            )
        )
        db.add(
            Course(
                id=course_id,
                code=f"visit-{course_id[:8]}",
                name="Visit course",
                current_audio_debate_id=None,
                created_at=now,
            )
        )
        db.add(Group(id=group_id, course_id=course_id, name="Visit group", created_at=now))
        db.flush()
        db.add(
            TeacherGroupAccess(
                group_id=group_id,
                user_id=user_id,
                created_at=now - timedelta(hours=3),
                expires_at=now + timedelta(hours=1),
            )
        )
        db.commit()
    with database.engine.begin() as connection:
        connection.execute(text("DROP INDEX IF EXISTS ix_teacher_group_access_expires_at"))
        connection.execute(text("ALTER TABLE teacher_group_access DROP COLUMN expires_at"))
        # The models already include chat_type. Replaying from 0080 runs 0081,
        # which adds that column, so the stamped copy has to look like 0080.
        connection.execute(
            text(
                "ALTER TABLE agent_conversations "
                "DROP CONSTRAINT IF EXISTS ck_conversations_chat_type"
            )
        )
        connection.execute(text("ALTER TABLE agent_conversations DROP COLUMN IF EXISTS chat_type"))
        connection.execute(
            text("UPDATE alembic_version SET version_num = :version"),
            {"version": MIGRATION_BASELINE},
        )
    database.upgrade_schema()
    with database.engine.connect() as connection:
        version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert version == ALEMBIC_HEAD
        stored = connection.execute(
            text(
                "SELECT expires_at FROM teacher_group_access "
                "WHERE group_id = :group_id AND user_id = :user_id"
            ),
            {"group_id": group_id, "user_id": user_id},
        ).one()
        expires_at = stored[0]
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        # The backfill measures from created_at, so a three-hour-old visit is
        # already past the two-hour window and the row is still present.
        assert expires_at <= datetime.now(UTC)
        columns = {
            column["name"] for column in inspect(connection).get_columns("teacher_group_access")
        }
        assert "expires_at" in columns
    config = database._alembic_config()
    command.downgrade(config, MIGRATION_BASELINE)  # type: ignore[arg-type]
    with database.engine.connect() as connection:
        columns = {
            column["name"] for column in inspect(connection).get_columns("teacher_group_access")
        }
        assert "expires_at" not in columns
        kept = connection.execute(
            text(
                "SELECT user_id FROM teacher_group_access "
                "WHERE group_id = :group_id AND user_id = :user_id"
            ),
            {"group_id": group_id, "user_id": user_id},
        ).scalar_one()
        assert kept == user_id
    command.upgrade(config, "head")  # type: ignore[arg-type]
    with database.engine.connect() as connection:
        assert (
            connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            == ALEMBIC_HEAD
        )
        assert (
            connection.execute(
                text("SELECT count(*) FROM teacher_group_access WHERE user_id = :user_id"),
                {"user_id": user_id},
            ).scalar_one()
            == 1
        )
    database.dispose()
