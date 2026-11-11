"""Teacher roster removals prune only empty, unreferenced, non-default groups."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Event
from typing import Any
from uuid import uuid4

import pytest
from app.core.db import registered_metadata
from app.core.errors import PlatformError
from app.core.locks import xact_lock
from app.core.models import Agent, Course, Group, GroupMember, TeacherGroupAccess, User
from app.modules.auth import profile
from app.modules.auth.models import DemoAccountBinding
from app.modules.auth.registration import attach_to_group
from app.modules.knowledge_sets.models import KnowledgeSet
from app.modules.org import groups, names
from app.modules.org.classes import SECOND_CLASS_GROUP_ID
from app.modules.org.groups import IGNORED_GROUP_REFERENCES, prune_empty_groups
from app.modules.org.roster import delete_member, move_to_group
from app.modules.quiz.models import ClassroomQuiz
from app.modules.teams.models import Team
from app.seed import BOWEN_ID, GROUP_DEMO_ID, seed_uuid
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from tests.conftest import login
from tests.test_account_delete import COURSE_ID, HEADERS, TEACHER_ID, _delete
from tests.test_auth_self_registration import register
from tests.test_course_roster import _update


def _register(client: TestClient, **kwargs: Any) -> tuple[str, str]:
    response = register(client, **kwargs)
    assert response.status_code == 201, response.text
    user = response.json()["user"]
    return user["id"], user["groups"][0]["group_id"]


def _assert_listed(client: TestClient, group_id: str, *, listed: bool) -> None:
    response = client.get(f"/api/v1/courses/{COURSE_ID}/groups")
    assert response.status_code == 200, response.text
    assert (group_id in {row["id"] for row in response.json()}) is listed
    options = client.get("/api/v1/auth/registration-options")
    assert options.status_code == 200, options.text
    course = next(row for row in options.json()["classes"] if row["course_id"] == COURSE_ID)
    assert ("Team Aurora" in {row["name"] for row in course["groups"]}) is listed
    assert ("Team Aurora" in {row["name"] for row in options.json()["groups"]}) is listed


@pytest.mark.parametrize("member_count", [1, 2])
def test_sequential_teacher_deletes_prune_only_after_last_member(
    client: TestClient, database: Any, member_count: int
) -> None:
    users = [_register(client, username=f"leaver-{index}") for index in range(member_count)]
    group_id = users[0][1]
    _, csrf = login(client)
    headers = {**HEADERS, "X-CSRF-Token": csrf}
    assert client.post(f"/api/v1/groups/{group_id}/membership", headers=headers).status_code == 200
    for index, (user_id, _) in enumerate(users):
        response = _delete(client, csrf, user_id)
        assert response.status_code == 204, response.text
        remains = index < member_count - 1
        _assert_listed(client, group_id, listed=remains)
        with database.session() as db:
            assert (db.get(Group, group_id) is not None) is remains
    with database.session() as db:
        assert db.get(TeacherGroupAccess, (group_id, TEACHER_ID)) is None


@pytest.mark.parametrize("member_count,same_group", [(1, False), (2, False), (1, True)])
def test_teacher_moves_prune_only_the_empty_group_left_behind(
    client: TestClient, database: Any, member_count: int, same_group: bool
) -> None:
    user_id, group_id = _register(client)
    if member_count == 2:
        _register(client, username="staying-student")
    _, csrf = login(client)
    target = "Team Aurora" if same_group else "Destination"
    response = _update(client, csrf, user_id, group_name=target)
    assert response.status_code == 200, response.text
    remains = same_group or member_count == 2
    _assert_listed(client, group_id, listed=remains)
    with database.session() as db:
        assert (db.get(Group, group_id) is not None) is remains
        assert db.get(GroupMember, (response.json()["groups"][0]["id"], user_id)) is not None


@pytest.mark.parametrize(
    "reference", ["agent", "team_tombstone", "knowledge_set_tombstone", "quiz"]
)
@pytest.mark.parametrize("removal", ["move", "delete"])
def test_referenced_empty_groups_and_their_work_survive(
    client: TestClient, database: Any, reference: str, removal: str
) -> None:
    user_id, group_id = _register(client)
    owner_id = user_id if removal == "move" else TEACHER_ID
    now = datetime.now(UTC)
    row_id = str(uuid4())
    if reference == "agent":
        from tests.test_mayaform_teams import _make_agent_version

        row_id, _ = _make_agent_version(
            database, owner_id=owner_id, name="Retained work", group_id=group_id
        )
        model = Agent
    elif reference == "quiz":
        model = ClassroomQuiz
        with database.session() as db:
            db.add(
                ClassroomQuiz(
                    id=row_id,
                    course_id=COURSE_ID,
                    group_id=group_id,
                    title="Group audience",
                    created_by_user_id=TEACHER_ID,
                    created_at=now,
                    updated_at=now,
                )
            )
    else:
        model = Team if reference == "team_tombstone" else KnowledgeSet
        extra = {"current_version_seq": 1} if model is Team else {}
        with database.session() as db:
            db.add(
                model(
                    id=row_id,
                    owner_user_id=owner_id,
                    course_id=COURSE_ID,
                    group_id=group_id,
                    ownership_scope="group",
                    display_name="Retained tombstone",
                    visibility="private",
                    deleted_at=now,
                    created_at=now,
                    updated_at=now,
                    **extra,
                )
            )
    _, csrf = login(client)
    if removal == "move":
        response = _update(client, csrf, user_id, group_name="Destination")
        assert response.status_code == 200, response.text
    else:
        response = _delete(client, csrf, user_id)
        assert response.status_code == 204, response.text
    _assert_listed(client, group_id, listed=True)
    with database.session() as db:
        assert (
            db.scalar(select(GroupMember.user_id).where(GroupMember.group_id == group_id)) is None
        )
        assert db.get(model, row_id).group_id == group_id
        assert db.get(Group, group_id) is not None


def test_default_groups_survive_and_created_class_remains_joinable(
    client: TestClient, database: Any
) -> None:
    _, csrf = login(client)
    response = client.post(
        "/api/v1/courses",
        json={"name": "Cleanup class"},
        headers={**HEADERS, "X-CSRF-Token": csrf},
    )
    assert response.status_code == 201, response.text
    course_id = response.json()["id"]
    group_id = seed_uuid(f"class-students-{course_id}")
    user_id, joined = _register(client, course_id=course_id, group_name="Students")
    assert joined == group_id
    _, csrf = login(client)
    response = client.delete(
        f"/api/v1/courses/{course_id}/members/{user_id}",
        headers={**HEADERS, "X-CSRF-Token": csrf},
    )
    assert response.status_code == 204, response.text
    with database.session() as db:
        db.execute(delete(GroupMember).where(GroupMember.group_id == GROUP_DEMO_ID))
        prune_empty_groups(db, COURSE_ID, [GROUP_DEMO_ID])
        second = db.get(Group, SECOND_CLASS_GROUP_ID)
        prune_empty_groups(db, second.course_id, [SECOND_CLASS_GROUP_ID])
        for protected in [GROUP_DEMO_ID, SECOND_CLASS_GROUP_ID, group_id]:
            assert db.get(Group, protected) is not None
    options = client.get("/api/v1/auth/registration-options").json()
    course = next(row for row in options["classes"] if row["course_id"] == course_id)
    assert course["groups"] == [{"name": "Students", "member_count": 0}]


def test_default_fallback_is_protected(client: TestClient, database: Any) -> None:
    course_id, group_id = str(uuid4()), str(uuid4())
    now = datetime.now(UTC)
    with database.session() as db:
        db.add(Course(id=course_id, code=f"class-{uuid4().hex}", name="Fallback", created_at=now))
        db.flush()
        db.add(Group(id=group_id, course_id=course_id, name="Fallback group", created_at=now))
        db.flush()
        prune_empty_groups(db, course_id, [group_id, group_id])
        assert db.get(Group, group_id) is not None


def test_catalog_delete_never_prunes(client: TestClient, database: Any) -> None:
    _, csrf = login(client)
    roster = client.get(f"/api/v1/courses/{COURSE_ID}/roster").json()["entries"]
    bowen = next(row for row in roster if row["username"] == "bowen")
    before = client.get(f"/api/v1/courses/{COURSE_ID}/groups").json()
    response = _delete(client, csrf, bowen["user_id"])
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "account_read_only"
    assert client.get(f"/api/v1/courses/{COURSE_ID}/groups").json() == before
    with database.session() as db:
        assert db.get(Group, GROUP_DEMO_ID) is not None


def test_student_self_move_keeps_the_empty_source_group(client: TestClient, database: Any) -> None:
    _, group_id = _register(client)
    _register(client, username="destination-student", group_name="Destination")
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "new-student", "password": "correct-horse-1"},
    )
    assert response.status_code == 200, response.text
    response = client.patch(
        "/api/v1/auth/me",
        json={"group_name": "Destination"},
        headers={**HEADERS, "X-CSRF-Token": response.json()["csrf_token"]},
    )
    assert response.status_code == 200, response.text
    with database.session() as db:
        assert db.get(Group, group_id) is not None
        assert (
            db.scalar(select(GroupMember.user_id).where(GroupMember.group_id == group_id)) is None
        )


def test_group_pruning_rolls_back_with_account_deletion(client: TestClient, database: Any) -> None:
    user_id, group_id = _register(client)
    with pytest.raises(RuntimeError, match="abort outer transaction"), database.session() as db:
        group = db.get(Group, group_id)
        assert len(group.memberships) == 1
        delete_member(
            db,
            course_id=COURSE_ID,
            actor=db.get(User, TEACHER_ID),
            user_id=user_id,
            data_root=None,
        )
        assert db.get(Group, group_id) is None
        raise RuntimeError("abort outer transaction")
    with database.session() as db:
        assert db.get(Group, group_id) is not None
        assert db.get(User, user_id) is not None
        assert db.get(GroupMember, (group_id, user_id)) is not None


def test_group_reference_inventory() -> None:
    referrers = {
        table.name
        for table in registered_metadata().tables.values()
        for fk in table.foreign_key_constraints
        if fk.referred_table.name == "groups"
    }
    assert IGNORED_GROUP_REFERENCES == {
        "group_members",
        "teacher_group_access",
        "demo_account_bindings",
    }
    assert referrers - IGNORED_GROUP_REFERENCES == {
        "agents",
        "knowledge_documents",
        "knowledge_sets",
        "teams",
        "voice_previews",
        "classroom_quizzes",
        "provider_export_manifests",
        "debate_participants",
        "voice_profiles",
    }
    assert IGNORED_GROUP_REFERENCES <= referrers


@pytest.mark.parametrize("join_path", ["registration", "move", "self_move"])
@pytest.mark.parametrize("prune_first", [True, False])
def test_named_joins_and_pruning_serialize(
    client: TestClient,
    database: Any,
    monkeypatch: pytest.MonkeyPatch,
    join_path: str,
    prune_first: bool,
) -> None:
    leaver_id, group_id = _register(client)
    if join_path == "self_move":
        joiner_id = BOWEN_ID
    else:
        joiner_id, _ = _register(client, username="joiner", group_name="Destination")
    with database.session() as db:
        db.execute(delete(GroupMember).where(GroupMember.user_id == leaver_id))
        if join_path == "self_move":
            binding = db.scalar(
                select(DemoAccountBinding).where(DemoAccountBinding.user_id == joiner_id)
            )
            selected_group_id_before = binding.selected_group_id
            group_ids_before = set(
                db.scalars(select(GroupMember.group_id).where(GroupMember.user_id == joiner_id))
            )
    waiting = Event()

    def observed_lock(db: Any, name: str) -> None:
        waiting.set()
        xact_lock(db, name)

    def join(db: Any) -> str:
        user = db.get(User, joiner_id)
        if join_path == "registration":
            group = attach_to_group(db, db.get(Course, COURSE_ID), user, "Team Aurora")
            db.flush()
            return group.id
        if join_path == "self_move":
            profile.change_group(db, user, "Team Aurora")
        else:
            move_to_group(db, COURSE_ID, user, "Team Aurora")
        return db.scalar(select(Group.id).where(Group.name == "Team Aurora"))

    def worker() -> str | None:
        with database.session() as db:
            if prune_first:
                return join(db)
            prune_empty_groups(db, COURSE_ID, [group_id])
            return None

    with ThreadPoolExecutor(max_workers=1) as pool:
        with database.session() as db:
            if prune_first:
                prune_empty_groups(db, COURSE_ID, [group_id])
                module = profile if join_path == "self_move" else names
                monkeypatch.setattr(module, "xact_lock", observed_lock)
            else:
                assert join(db) == group_id
                monkeypatch.setattr(groups, "xact_lock", observed_lock)
            future = pool.submit(worker)
            assert waiting.wait(5), "concurrent operation did not reach the transaction lock"
            assert not future.done()
        if prune_first and join_path == "self_move":
            with pytest.raises(PlatformError) as error:
                future.result(timeout=10)
            assert error.value.code == "group_not_found"
            with database.session() as db:
                assert db.get(Group, group_id) is None
                assert db.scalar(select(Group.id).where(Group.name == "Team Aurora")) is None
                binding = db.scalar(
                    select(DemoAccountBinding).where(DemoAccountBinding.user_id == joiner_id)
                )
                assert binding.selected_group_id == selected_group_id_before
                assert (
                    set(
                        db.scalars(
                            select(GroupMember.group_id).where(GroupMember.user_id == joiner_id)
                        )
                    )
                    == group_ids_before
                )
            return
        resolved = future.result(timeout=10) if prune_first else group_id
        if not prune_first:
            future.result(timeout=10)
    with database.session() as db:
        assert db.get(GroupMember, (resolved, joiner_id)) is not None
        assert db.get(Group, resolved) is not None
        if join_path == "self_move":
            binding = db.scalar(
                select(DemoAccountBinding).where(DemoAccountBinding.user_id == joiner_id)
            )
            assert binding.selected_group_id == resolved
        if prune_first:
            assert resolved != group_id
            assert db.get(Group, group_id) is None
