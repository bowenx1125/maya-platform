"""Profile and chooser share a course and preserve Bowen's saved group grants."""

import runpy
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from app.core.errors import PlatformError
from app.core.identity import group_name_key
from app.core.models import CourseMember, Group, GroupMember, SessionRecord, User
from app.modules.auth.credentials import account_id, parse_accounts_markdown
from app.modules.auth.identity_choice import student_landing_group
from app.modules.auth.models import DemoAccountBinding
from app.modules.auth.profile import resolve_student_group
from app.modules.auth.service import session_hash, sync_demo_accounts
from app.modules.org.classes import SECOND_CLASS_GROUP_ID, SECOND_CLASS_ID, change_class
from app.seed import BOWEN_ID, COURSE_ID, GROUP_DEMO_ID
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from tests.test_bowen_identity_choice import challenge, choose
from tests.test_pw3_auth import _app

GROUP_NAMES = ("5", "Group 4", "Group4", "sxsc123——", ".")


@pytest.fixture
def profile_classes(tmp_path):
    app, database, settings, catalog = _app(tmp_path)
    catalog.write_text(
        catalog.read_text()
        + "| bowen1 | bowen1 | Bowen Student 2 | demo-password | student | group-demo |\n"
    )
    sync_demo_accounts(database, settings, parse_accounts_markdown(catalog.read_text()))
    with database.session() as db:
        now = datetime.now(UTC)
        for course_id in (COURSE_ID, SECOND_CLASS_ID):
            for name in GROUP_NAMES:
                db.add(Group(id=str(uuid4()), course_id=course_id, name=name, created_at=now))
        bowen1 = db.get(User, account_id("bowen1"))
        change_class(db, bowen1, SECOND_CLASS_ID)
        db.get(DemoAccountBinding, "bowen").selected_group_id = GROUP_DEMO_ID
    with TestClient(app) as client:
        yield client, database, settings


def _headers(response):
    return {"Origin": "http://testserver", "X-CSRF-Token": response.json()["csrf_token"]}


def _group(db, course_id, name):
    return db.scalars(
        select(Group).where(Group.course_id == course_id, Group.name_key == group_name_key(name))
    ).one()


def test_profile_class_change_updates_session_and_all_maya1002_group_names(profile_classes):
    client, database, _ = profile_classes
    entered = choose(client, challenge(client)["choice_token"], "student", SECOND_CLASS_ID)
    assert entered.status_code == 200, entered.text
    headers = _headers(entered)
    switched = client.patch("/api/v1/auth/me", headers=headers, json={"course_id": COURSE_ID})
    assert switched.status_code == 200, switched.text
    assert switched.json()["user"]["courses"][0]["course_id"] == COURSE_ID
    with database.session() as db:
        assert db.get(GroupMember, (GROUP_DEMO_ID, BOWEN_ID)) is not None
        bowen1_before = db.get(GroupMember, (SECOND_CLASS_GROUP_ID, account_id("bowen1")))
        assert bowen1_before is not None
        other_memberships = set(
            db.scalars(
                select(GroupMember.group_id)
                .join(Group, Group.id == GroupMember.group_id)
                .where(Group.course_id == SECOND_CLASS_ID, GroupMember.user_id == BOWEN_ID)
            )
        )
        group_count = db.scalar(select(func.count()).select_from(Group))
    for name in GROUP_NAMES:
        options = client.get("/api/v1/auth/registration-options").json()
        offered = next(row for row in options["classes"] if row["course_id"] == COURSE_ID)
        assert name in {row["name"] for row in offered["groups"]}
        response = client.patch("/api/v1/auth/me", headers=headers, json={"group_name": name})
        assert response.status_code == 200, response.text
        with database.session() as db:
            expected = _group(db, COURSE_ID, name)
            assert response.json()["user"]["groups"][0]["group_id"] == expected.id
            assert db.get(GroupMember, (expected.id, BOWEN_ID)) is not None
            assert (
                set(
                    db.scalars(
                        select(GroupMember.group_id)
                        .join(Group, Group.id == GroupMember.group_id)
                        .where(Group.course_id == SECOND_CLASS_ID, GroupMember.user_id == BOWEN_ID)
                    )
                )
                == other_memberships
            )
            assert db.get(GroupMember, (SECOND_CLASS_GROUP_ID, account_id("bowen1"))) is not None
            assert db.get(DemoAccountBinding, "bowen").selected_group_id == expected.id
            assert db.scalar(select(func.count()).select_from(Group)) == group_count
    with database.session() as db:
        assert (
            db.get(SessionRecord, session_hash(client.cookies.get("maya_session"))).active_course_id
            == COURSE_ID
        )


def test_bowen_profile_reentry_and_chooser_keep_both_classes_and_saved_group(profile_classes):
    client, database, settings = profile_classes
    entered = choose(client, challenge(client)["choice_token"], "student", SECOND_CLASS_ID)
    headers = _headers(entered)
    moved = client.patch("/api/v1/auth/me", headers=headers, json={"group_name": "5"})
    assert moved.status_code == 200, moved.text
    with database.session() as db:
        chosen_id = _group(db, SECOND_CLASS_ID, "5").id
    for course_id in (COURSE_ID, SECOND_CLASS_ID, SECOND_CLASS_ID):
        switched = client.patch("/api/v1/auth/me", headers=headers, json={"course_id": course_id})
        assert switched.status_code == 200, switched.text
        assert switched.json()["user"]["id"] == BOWEN_ID
        assert switched.json()["user"]["courses"][0]["course_id"] == course_id
        assert len(switched.json()["user"]["courses"]) == 2
    sync_demo_accounts(database, settings)
    with database.session() as db:
        assert db.get(DemoAccountBinding, "bowen").selected_group_id == chosen_id
        assert db.get(DemoAccountBinding, "bowen1").selected_group_id == SECOND_CLASS_GROUP_ID
        assert db.get(GroupMember, (GROUP_DEMO_ID, BOWEN_ID)) is not None
    reentered = choose(client, challenge(client)["choice_token"], "student", SECOND_CLASS_ID)
    assert reentered.status_code == 200, reentered.text
    assert reentered.json()["user"]["groups"][0]["group_id"] == chosen_id
    assert client.get("/api/v1/auth/me").json()["user"]["groups"][0]["group_id"] == chosen_id


@pytest.mark.parametrize("renamed", [False, True])
def test_landing_uses_saved_membership_then_nondefault_ids_and_never_other_account(
    profile_classes, renamed
):
    client, database, _ = profile_classes
    with database.session() as db:
        bowen = db.get(User, BOWEN_ID)
        if renamed:
            db.get(Group, GROUP_DEMO_ID).name = "No Group"
            db.get(Group, SECOND_CLASS_GROUP_ID).name = "No Group"
        db.flush()
        # Production's two accounts remain separate; bowen1's Students grant
        # cannot become bowen's Maya1001 landing membership.
        assert student_landing_group(db, bowen, SECOND_CLASS_ID) is None
        assert student_landing_group(db, bowen, COURSE_ID).id == GROUP_DEMO_ID
        chosen = _group(db, COURSE_ID, "5")
        db.add(
            GroupMember(
                group_id=chosen.id, user_id=BOWEN_ID, role="member", created_at=datetime.now(UTC)
            )
        )
        db.get(DemoAccountBinding, "bowen").selected_group_id = None
        db.flush()
        assert student_landing_group(db, bowen, COURSE_ID).id == chosen.id
        db.get(DemoAccountBinding, "bowen").selected_group_id = GROUP_DEMO_ID
        db.flush()
        assert student_landing_group(db, bowen, COURSE_ID).id == GROUP_DEMO_ID
    entered = choose(client, challenge(client)["choice_token"], "student", COURSE_ID)
    assert entered.status_code == 200, entered.text
    assert entered.json()["user"]["groups"][0]["group_id"] == GROUP_DEMO_ID


def test_revoked_saved_group_is_not_restored_by_chooser_profile_or_catalog(profile_classes):
    client, database, settings = profile_classes
    with database.session() as db:
        db.delete(db.get(GroupMember, (GROUP_DEMO_ID, BOWEN_ID)))
    for _ in range(2):
        entered = choose(client, challenge(client)["choice_token"], "student", COURSE_ID)
        assert entered.status_code == 200, entered.text
        changed = client.patch(
            "/api/v1/auth/me", headers=_headers(entered), json={"course_id": COURSE_ID}
        )
        assert changed.status_code == 200, changed.text
        sync_demo_accounts(database, settings)
        assert changed.json()["user"]["groups"] == []
        with database.session() as db:
            assert student_landing_group(db, db.get(User, BOWEN_ID), COURSE_ID) is None
            assert db.get(GroupMember, (GROUP_DEMO_ID, BOWEN_ID)) is None


def test_readonly_resolver_rejects_ambiguous_missing_and_foreign_course(profile_classes):
    _, database, _ = profile_classes
    with database.session() as db:
        bowen = db.get(User, BOWEN_ID)
        db.add(
            CourseMember(
                course_id=SECOND_CLASS_ID,
                user_id=BOWEN_ID,
                role="student",
                created_at=datetime.now(UTC),
            )
        )
        db.flush()
        for course_id in (COURSE_ID, SECOND_CLASS_ID):
            for name in GROUP_NAMES:
                assert (
                    resolve_student_group(db, bowen, name, course_id=course_id).id
                    == _group(db, course_id, name).id
                )
        for name, course_id in (
            ("5", None),
            ("missing", COURSE_ID),
            ("5", str(uuid4())),
            (" ", COURSE_ID),
        ):
            with pytest.raises(PlatformError) as refused:
                resolve_student_group(db, bowen, name, course_id=course_id)
            assert refused.value.code == "group_not_found"
        assert (
            resolve_student_group(db, bowen, "  ＧＲＯＵＰ   4 ", course_id=COURSE_ID).id
            == _group(db, COURSE_ID, "Group 4").id
        )
        assert not db.new and not db.dirty and not db.deleted


def test_production_verification_script_is_readonly_and_rolled_back(
    profile_classes, monkeypatch, capsys
):
    _, database, settings = profile_classes
    from app.core import config

    monkeypatch.setattr(config, "get_settings", lambda: settings)
    script = Path(__file__).resolve().parents[2] / "scripts" / "verify_profile_groups.py"
    runpy.run_path(str(script), run_name="__main__")
    output = capsys.readouterr().out
    assert "PASS Maya1002 switch validation: 5 ->" in output
    assert "saved_choice=True" in output
    assert "ROLLBACK; read-only verification ended" in output
    with database.session() as db:
        assert db.scalar(select(func.count()).select_from(SessionRecord)) == 0
        assert db.get(GroupMember, (GROUP_DEMO_ID, BOWEN_ID)) is not None
        assert db.get(GroupMember, (_group(db, COURSE_ID, "5").id, BOWEN_ID)) is None
        assert db.get(DemoAccountBinding, "bowen").selected_group_id == GROUP_DEMO_ID
