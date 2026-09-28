from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier
from typing import Any
from uuid import uuid4

import pytest
from app.core.db import Database
from app.core.errors import PlatformError
from app.core.models import (
    Agent,
    AgentVersion,
    Course,
    CourseMember,
    KnowledgeDocument,
    KnowledgeSnapshot,
    SnapshotDocument,
    StoredFile,
    TeacherGroupAccess,
    User,
)
from fastapi.testclient import TestClient
from sqlalchemy import text

from tests.conftest import login

COURSE_ID = "b1ae79ed-e4a6-5b02-9abd-3a3ae944284b"
GROUP_ID = "7813f937-902c-5534-bfb2-ad773a43aeda"
MAYA_ID = "08b9de2d-bb75-5c71-a64b-231b48f9eb25"
BOWEN_ID = "60541c78-30f1-55c5-b2aa-207b6a766883"


def _headers(csrf: str, key: str | None = None) -> dict[str, str]:
    result = {"Origin": "http://testserver", "X-CSRF-Token": csrf}
    if key is not None:
        result["Idempotency-Key"] = key
    return result


def _make_agent_version(
    database: Any,
    *,
    owner_id: str,
    name: str,
    visibility: str = "private",
    group_id: str | None = None,
    course_id: str = COURSE_ID,
) -> tuple[str, str]:
    timestamp = datetime.now(UTC)
    agent_id = str(uuid4())
    version_id = str(uuid4())
    with database.session() as db:
        agent = Agent(
            id=agent_id,
            group_id=group_id,
            owner_user_id=owner_id,
            course_id=course_id,
            ownership_scope="group" if group_id else "personal",
            visibility=visibility,
            authorization_epoch=0,
            name=name,
            description="",
            metadata_revision=0,
            status="active",
            current_published_version_id=version_id,
            created_at=timestamp,
            updated_at=timestamp,
        )
        version = AgentVersion(
            id=version_id,
            agent_id=agent_id,
            version_seq=1,
            state="published",
            revision=1,
            agent_md=f"# {name}",
            avatar_config_json="{}",
            authorization_epoch=0,
            draft_visibility=visibility,
            published_visibility=visibility,
            published_at=timestamp,
            created_at=timestamp,
            updated_at=timestamp,
        )
        db.add_all([agent, version])
        db.commit()
    return agent_id, version_id


def _attach_personal_snapshot(database: Any, version_id: str) -> str:
    timestamp = datetime.now(UTC)
    content = "K3 private source fence fixture\n"
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    file_id, document_id, snapshot_id = str(uuid4()), str(uuid4()), str(uuid4())
    snapshot_document_id = str(uuid4())
    with database.session() as db:
        db.add(
            StoredFile(
                id=file_id,
                kind="markdown",
                relative_path=f"teams/{file_id}.md",
                sha256=digest,
                size_bytes=len(content.encode("utf-8")),
                state="active",
                created_at=timestamp,
                updated_at=timestamp,
            )
        )
        db.flush()
        db.add(
            KnowledgeDocument(
                id=document_id,
                group_id=None,
                owner_user_id=MAYA_ID,
                course_id=COURSE_ID,
                ownership_scope="personal",
                visibility="private",
                authorization_epoch=0,
                source_filename="private-source.md",
                stored_file_id=file_id,
                char_count=len(content),
                index_status="ready",
                index_revision=1,
                workspace_state="active",
                content_hash=digest,
                safe_error_code=None,
                created_at=timestamp,
                updated_at=timestamp,
            )
        )
        db.flush()
        db.add(
            KnowledgeSnapshot(
                id=snapshot_id,
                agent_version_id=version_id,
                stored_file_id=file_id,
                content_hash=digest,
                total_char_count=len(content),
                embedding_key="mock-sha256-v1",
                chunking_json="{}",
                created_at=timestamp,
            )
        )
        db.flush()
        db.add(
            SnapshotDocument(
                id=snapshot_document_id,
                snapshot_id=snapshot_id,
                document_id=document_id,
                stored_file_id=file_id,
                source_filename="private-source.md",
                char_count=len(content),
                order_index=0,
                source_authorization_epoch=0,
            )
        )
        version = db.get(AgentVersion, version_id)
        assert version is not None
        version.knowledge_snapshot_id = snapshot_id
        db.commit()
    return document_id


def _team_payload(version_ids: list[str], *, visibility: str = "private") -> dict[str, Any]:
    return {
        "display_name": "Two perspectives",
        "visibility": visibility,
        "members": [
            {"agent_version_id": version_ids[0], "is_leader": True, "position": 0},
            {"agent_version_id": version_ids[1], "is_leader": False, "position": 1},
        ],
        "shared_knowledge_set_ids": [],
    }


def test_personal_teacher_public_team_creates_directory_and_invoke_grants_atomically(
    client: TestClient, database: Any
) -> None:
    _, csrf = login(client, "maya")
    first = _make_agent_version(database, owner_id=MAYA_ID, name="Private Seed A")
    second = _make_agent_version(database, owner_id=MAYA_ID, name="Private Seed B")
    payload = _team_payload([first[1], second[1]], visibility="public")

    created_response = client.post(
        f"/api/v1/courses/{COURSE_ID}/teams",
        headers=_headers(csrf, "k3-create-teacher-public-team-01"),
        json=payload,
    )
    assert created_response.status_code == 201, created_response.text
    created = created_response.json()
    assert created["ownership_scope"] == "personal"
    assert created["current_version_seq"] == 1
    assert created["publication_state"] == "published"
    assert [member["is_leader"] for member in created["members"]].count(True) == 1

    replay = client.post(
        f"/api/v1/courses/{COURSE_ID}/teams",
        headers=_headers(csrf, "k3-create-teacher-public-team-01"),
        json=payload,
    )
    assert replay.status_code == 201, replay.text
    assert replay.json() == created

    with database.session() as db:
        from app.modules.teams.models import (
            CourseTeamPublication,
            TeamMemberInvokeGrant,
            TeamVersion,
        )

        version_id = created["current_version_id"]
        publication = db.query(CourseTeamPublication).filter_by(team_version_id=version_id).one()
        assert publication.state == "published"
        grants = db.query(TeamMemberInvokeGrant).filter_by(publication_id=publication.id).all()
        assert {grant.agent_version_id for grant in grants} == {first[1], second[1]}
        assert {grant.team_version_id for grant in grants} == {version_id}
        assert db.query(TeamVersion).filter_by(team_id=created["id"]).count() == 1
        from app.modules.knowledge.services import can_invoke_version
        from app.modules.teams.service import resolve_chat_entry

        selection = resolve_chat_entry(db, BOWEN_ID, created["id"], require_publication=True)
        assert {member.agent_version_id for member in selection.members} == {first[1], second[1]}
        assert all(member.invoke_grant_id for member in selection.members)
        assert (
            can_invoke_version(
                db, BOWEN_ID, db.get(AgentVersion, first[1]), db.get(Agent, first[0])
            )
            is False
        )
        with pytest.raises(PlatformError) as denied_custom_team:
            resolve_chat_entry(db, BOWEN_ID, created["id"], require_publication=False)
        assert denied_custom_team.value.status_code == 404

    _, student_csrf = login(client, "bowen")
    directory_response = client.get(
        f"/api/v1/courses/{COURSE_ID}/maya-teams",
        headers=_headers(student_csrf),
    )
    assert directory_response.status_code == 200, directory_response.text
    directory = directory_response.json()
    assert len(directory) == 1
    assert directory[0]["id"] == created["id"]
    assert directory[0]["team_version_id"] == created["current_version_id"]
    assert all(
        "agent_id" not in member and "agent_version_id" not in member
        for member in directory[0]["members"]
    )
    assert "shared_knowledge_set_ids" not in directory[0]

    # A name-only edit creates a new immutable version but preserves the
    # authorization epoch and old frozen Chat grant.
    updated_payload = {
        **payload,
        "expected_metadata_revision": 0,
        "display_name": "Two perspectives, revised",
    }
    _, teacher_csrf_again = login(client, "maya")
    updated_response = client.put(
        f"/api/v1/teams/{created['id']}",
        headers=_headers(teacher_csrf_again, "k3-save-teacher-team-version-0001"),
        json=updated_payload,
    )
    assert updated_response.status_code == 200, updated_response.text
    updated = updated_response.json()
    assert updated["current_version_seq"] == 2
    assert updated["publication_state"] == "published"
    assert updated["metadata_revision"] == 1
    with database.session() as db:
        old = (
            db.query(CourseTeamPublication)
            .filter_by(team_version_id=created["current_version_id"])
            .one()
        )
        assert old.state == "retained"
        assert db.query(TeamVersion).filter_by(team_id=created["id"]).count() == 2
        from app.modules.teams.service import assert_current_chat_targets

        assert_current_chat_targets(db, BOWEN_ID, selection)
    directory_after = client.get(
        f"/api/v1/courses/{COURSE_ID}/maya-teams",
        headers=_headers(student_csrf),
    )
    assert directory_after.status_code == 200
    assert len(directory_after.json()) == 1
    assert directory_after.json()[0]["team_version_id"] == updated["current_version_id"]
    assert directory_after.json()[0]["display_name"] == "Two perspectives, revised"

    private_payload = {
        **updated_payload,
        "expected_metadata_revision": 1,
        "visibility": "private",
    }
    made_private = client.put(
        f"/api/v1/teams/{created['id']}",
        headers=_headers(teacher_csrf_again, "k3-team-public-to-private-0001"),
        json=private_payload,
    )
    assert made_private.status_code == 200, made_private.text
    assert made_private.json()["authorization_epoch"] == 1
    with database.session() as db:
        from app.modules.teams.service import assert_current_chat_targets

        with pytest.raises(PlatformError) as revoked_team:
            assert_current_chat_targets(db, BOWEN_ID, selection)
        assert revoked_team.value.status_code == 404
    assert (
        client.get(f"/api/v1/courses/{COURSE_ID}/maya-teams", headers=_headers(student_csrf)).json()
        == []
    )

    stale_update = client.put(
        f"/api/v1/teams/{created['id']}",
        headers=_headers(teacher_csrf_again, "k3-save-stale-team-revision-0001"),
        json=updated_payload,
    )
    assert stale_update.status_code == 409
    assert stale_update.json()["code"] == "stale_revision"


def test_student_public_team_is_not_registered_and_foreign_private_member_is_hidden(
    client: TestClient, database: Any
) -> None:
    _, student_csrf = login(client, "bowen")
    first = _make_agent_version(database, owner_id=BOWEN_ID, name="Student Agent A")
    second = _make_agent_version(database, owner_id=BOWEN_ID, name="Student Agent B")
    public_payload = _team_payload([first[1], second[1]], visibility="public")
    response = client.post(
        f"/api/v1/courses/{COURSE_ID}/teams",
        headers=_headers(student_csrf, "k3-create-student-public-team-01"),
        json=public_payload,
    )
    assert response.status_code == 201, response.text
    assert response.json()["publication_state"] == "unpublished"
    assert response.json()["ownership_scope"] == "personal"
    assert (
        client.get(f"/api/v1/courses/{COURSE_ID}/maya-teams", headers=_headers(student_csrf)).json()
        == []
    )

    foreign_private = _make_agent_version(database, owner_id=MAYA_ID, name="Teacher Private Canary")
    denied = client.post(
        f"/api/v1/courses/{COURSE_ID}/teams",
        headers=_headers(student_csrf, "k3-create-team-with-foreign-private-01"),
        json=_team_payload([foreign_private[1], first[1]]),
    )
    assert denied.status_code == 404

    invalid_leader = _team_payload([first[1], second[1]])
    invalid_leader["members"][0]["is_leader"] = False
    invalid = client.post(
        f"/api/v1/courses/{COURSE_ID}/teams",
        headers=_headers(student_csrf, "k3-create-team-without-leader-01"),
        json=invalid_leader,
    )
    assert invalid.status_code == 400
    assert invalid.json()["code"] == "malformed_request"
    two_leaders = _team_payload([first[1], second[1]])
    two_leaders["members"][1]["is_leader"] = True
    invalid_two_leaders = client.post(
        f"/api/v1/courses/{COURSE_ID}/teams",
        headers=_headers(student_csrf, "k3-create-team-with-two-leaders-01"),
        json=two_leaders,
    )
    assert invalid_two_leaders.status_code == 400


def test_team_scope_deduplicates_agents_and_only_eligible_teacher_team_is_published(
    client: TestClient, database: Any
) -> None:
    _, teacher_csrf = login(client, "maya")
    agent_id, version_one = _make_agent_version(database, owner_id=MAYA_ID, name="Versioned A")
    _other_agent_id, version_b = _make_agent_version(database, owner_id=MAYA_ID, name="Versioned B")
    version_two = str(uuid4())
    timestamp = datetime.now(UTC)
    with database.session() as db:
        db.add(
            AgentVersion(
                id=version_two,
                agent_id=agent_id,
                version_seq=2,
                state="superseded",
                revision=2,
                agent_md="# Versioned A V2",
                avatar_config_json="{}",
                authorization_epoch=0,
                draft_visibility="private",
                published_visibility="private",
                published_at=timestamp,
                created_at=timestamp,
                updated_at=timestamp,
            )
        )
        db.commit()
    duplicate_agent = {
        "display_name": "Duplicate Agent",
        "visibility": "private",
        "members": [
            {"agent_version_id": version_one, "is_leader": True, "position": 0},
            {"agent_version_id": version_two, "is_leader": False, "position": 1},
        ],
        "shared_knowledge_set_ids": [],
    }
    duplicate_response = client.post(
        f"/api/v1/courses/{COURSE_ID}/teams",
        headers=_headers(teacher_csrf, "k3-team-duplicate-agent-two-vers-01"),
        json=duplicate_agent,
    )
    assert duplicate_response.status_code == 422
    assert duplicate_response.json()["code"] == "duplicate_team_agent"

    foreign_course_id = str(uuid4())
    with database.session() as db:
        db.add(
            Course(
                id=foreign_course_id,
                code=f"foreign-{foreign_course_id}",
                name="Foreign course",
                current_audio_debate_id=None,
                created_at=datetime.now(UTC),
            )
        )
        db.add(
            CourseMember(
                course_id=foreign_course_id,
                user_id=MAYA_ID,
                role="teacher",
                created_at=datetime.now(UTC),
            )
        )
        db.commit()
    foreign = _make_agent_version(
        database,
        owner_id=MAYA_ID,
        name="Cross course Agent",
        course_id=foreign_course_id,
    )
    cross_course = client.post(
        f"/api/v1/courses/{COURSE_ID}/teams",
        headers=_headers(teacher_csrf, "k3-team-cross-course-member-0001"),
        json=_team_payload([foreign[1], version_b]),
    )
    assert cross_course.status_code == 404

    private_payload = _team_payload([version_one, version_b], visibility="private")
    private = client.post(
        f"/api/v1/courses/{COURSE_ID}/teams",
        headers=_headers(teacher_csrf, "k3-create-teacher-private-team-01"),
        json=private_payload,
    )
    assert private.status_code == 201, private.text
    assert private.json()["publication_state"] == "unpublished"

    group_first = _make_agent_version(
        database, owner_id=BOWEN_ID, name="Group Member A", visibility="public", group_id=GROUP_ID
    )
    group_second = _make_agent_version(
        database, owner_id=BOWEN_ID, name="Group Member B", visibility="public", group_id=GROUP_ID
    )
    with database.session() as db:
        db.add(
            TeacherGroupAccess(
                group_id=GROUP_ID,
                user_id=MAYA_ID,
                created_at=datetime.now(UTC),
            )
        )
        db.commit()
    _, teacher_csrf = login(client, "maya")
    group_payload = _team_payload([group_first[1], group_second[1]], visibility="public")
    group_payload["group_id"] = GROUP_ID
    group_response = client.post(
        f"/api/v1/courses/{COURSE_ID}/teams",
        headers=_headers(teacher_csrf, "k3-create-entered-group-team-01"),
        json=group_payload,
    )
    assert group_response.status_code == 201, group_response.text
    assert group_response.json()["ownership_scope"] == "group"
    assert group_response.json()["publication_state"] == "unpublished"
    directory = client.get(
        f"/api/v1/courses/{COURSE_ID}/maya-teams", headers=_headers(teacher_csrf)
    )
    assert directory.status_code == 200
    assert directory.json() == []


def test_team_idempotent_replay_rechecks_owner_acl_and_set_revocation_fences_selection(
    client: TestClient, database: Any
) -> None:
    _, csrf = login(client, "maya")
    first = _make_agent_version(database, owner_id=MAYA_ID, name="Revocation A")
    second = _make_agent_version(database, owner_id=MAYA_ID, name="Revocation B")
    created_set = client.post(
        f"/api/v1/courses/{COURSE_ID}/knowledge-sets",
        headers=_headers(csrf, "k3-create-source-set-for-team-01"),
        json={"display_name": "Team only study set"},
    )
    assert created_set.status_code == 201, created_set.text
    set_id = created_set.json()["id"]
    payload = _team_payload([first[1], second[1]], visibility="private")
    payload["shared_knowledge_set_ids"] = [set_id]
    created = client.post(
        f"/api/v1/courses/{COURSE_ID}/teams",
        headers=_headers(csrf, "k3-create-team-shared-set-0001"),
        json=payload,
    )
    assert created.status_code == 201, created.text
    from app.modules.teams.service import resolve_chat_entry

    with database.session() as db:
        before_revoke = resolve_chat_entry(db, MAYA_ID, created.json()["id"])
        assert before_revoke.shared_knowledge_set_ids == (set_id,)

    deleted = client.request(
        "DELETE",
        f"/api/v1/knowledge-sets/{set_id}",
        headers=_headers(csrf, "k3-revoke-team-shared-set-0001"),
        json={"expected_metadata_revision": 0, "expected_content_revision": 0},
    )
    assert deleted.status_code == 200, deleted.text
    with database.session() as db:
        with pytest.raises(PlatformError) as revoked_set:
            resolve_chat_entry(db, MAYA_ID, created.json()["id"])
        assert revoked_set.value.status_code == 404

    with database.session() as db:
        from app.modules.teams.models import Team

        team = db.get(Team, created.json()["id"])
        assert team is not None
        team.deleted_at = datetime.now(UTC)
        db.commit()
    replay = client.post(
        f"/api/v1/courses/{COURSE_ID}/teams",
        headers=_headers(csrf, "k3-create-team-shared-set-0001"),
        json=payload,
    )
    assert replay.status_code == 404


def test_team_metadata_cas_allows_only_one_concurrent_new_version(
    client: TestClient, database: Any
) -> None:
    _, csrf = login(client, "maya")
    first = _make_agent_version(database, owner_id=MAYA_ID, name="CAS Agent A")
    second = _make_agent_version(database, owner_id=MAYA_ID, name="CAS Agent B")
    created = client.post(
        f"/api/v1/courses/{COURSE_ID}/teams",
        headers=_headers(csrf, "k3-create-concurrent-cas-team-01"),
        json=_team_payload([first[1], second[1]]),
    )
    assert created.status_code == 201, created.text
    team_id = created.json()["id"]

    from app.core.errors import PlatformError
    from app.modules.auth.service import AuthContext
    from app.modules.teams.schemas import SaveTeamVersionRequest
    from app.modules.teams.service import save_team_version

    start = Barrier(2)

    def save(name: str) -> str:
        db = database.session_factory()
        try:
            # A detached user identity is sufficient for service-level ACL
            # resolution; the separate SQLite writer locks serialize the CAS.
            user = db.get(User, MAYA_ID)
            assert user is not None
            db.expunge(user)
            context = AuthContext("", None, user, "")  # type: ignore[arg-type]
            db.rollback()
            start.wait(timeout=5)
            db.execute(text("BEGIN IMMEDIATE"))
            request_payload = _team_payload([first[1], second[1]])
            request_payload["expected_metadata_revision"] = 0
            request_payload["display_name"] = name
            request = SaveTeamVersionRequest(**request_payload)
            save_team_version(db, context, team_id, request)
            db.commit()
            return "saved"
        except PlatformError as error:
            db.rollback()
            return error.code
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(save, ["Concurrent Team A", "Concurrent Team B"]))
    assert sorted(outcomes) == ["saved", "stale_revision"]
    with database.session() as db:
        from app.modules.teams.models import Team, TeamVersion

        team = db.get(Team, team_id)
        assert team is not None
        assert team.metadata_revision == 1
        assert team.current_version_seq == 2
        assert db.query(TeamVersion).filter_by(team_id=team_id).count() == 2


def test_selected_team_target_does_not_depend_on_an_unselected_revoked_member(
    client: TestClient, database: Any
) -> None:
    _, csrf = login(client, "maya")
    first = _make_agent_version(database, owner_id=MAYA_ID, name="Selected Member")
    second = _make_agent_version(database, owner_id=MAYA_ID, name="Unselected Member")
    revoked_source_id = _attach_personal_snapshot(database, second[1])
    created = client.post(
        f"/api/v1/courses/{COURSE_ID}/teams",
        headers=_headers(csrf, "k3-create-target-fence-team-0001"),
        json=_team_payload([first[1], second[1]], visibility="public"),
    )
    assert created.status_code == 201, created.text
    members = created.json()["members"]
    selected_id = next(row["id"] for row in members if row["agent_id"] == first[0])
    revoked_id = next(row["id"] for row in members if row["agent_id"] == second[0])
    from app.modules.teams.service import assert_current_chat_targets, resolve_chat_entry

    with database.session() as db:
        selection = resolve_chat_entry(
            db,
            BOWEN_ID,
            created.json()["id"],
            require_publication=True,
            target_binding_ids={selected_id},
        )
    with database.session() as db:
        document = db.get(KnowledgeDocument, revoked_source_id)
        assert document is not None
        document.authorization_epoch += 1
        db.commit()
    with database.session() as db:
        assert_current_chat_targets(db, BOWEN_ID, selection, {selected_id})
        with pytest.raises(PlatformError) as revoked_target:
            resolve_chat_entry(
                db,
                BOWEN_ID,
                created.json()["id"],
                require_publication=True,
                target_binding_ids={revoked_id},
            )
        assert revoked_target.value.status_code == 404


def test_maya_team_grant_rechecks_frozen_raw_source_epoch(
    client: TestClient, database: Any
) -> None:
    _, csrf = login(client, "maya")
    first = _make_agent_version(database, owner_id=MAYA_ID, name="Raw source member")
    second = _make_agent_version(database, owner_id=MAYA_ID, name="No source member")
    document_id = _attach_personal_snapshot(database, first[1])
    created = client.post(
        f"/api/v1/courses/{COURSE_ID}/teams",
        headers=_headers(csrf, "k3-create-raw-source-fenced-team-01"),
        json=_team_payload([first[1], second[1]], visibility="public"),
    )
    assert created.status_code == 201, created.text
    selected_id = next(
        member["id"] for member in created.json()["members"] if member["agent_id"] == first[0]
    )
    from app.modules.teams.service import assert_current_chat_targets, resolve_chat_entry

    with database.session() as db:
        selection = resolve_chat_entry(
            db,
            BOWEN_ID,
            created.json()["id"],
            require_publication=True,
            target_binding_ids={selected_id},
        )
    with database.session() as db:
        document = db.get(KnowledgeDocument, document_id)
        assert document is not None
        document.authorization_epoch += 1
        db.commit()
    with database.session() as db:
        with pytest.raises(PlatformError) as revoked_source:
            assert_current_chat_targets(db, BOWEN_ID, selection, {selected_id})
        assert revoked_source.value.status_code == 404


def test_maya_team_grant_rechecks_shared_set_authorization_epoch(
    client: TestClient, database: Any
) -> None:
    _, csrf = login(client, "maya")
    first = _make_agent_version(database, owner_id=MAYA_ID, name="Shared Set A")
    second = _make_agent_version(database, owner_id=MAYA_ID, name="Shared Set B")
    set_response = client.post(
        f"/api/v1/courses/{COURSE_ID}/knowledge-sets",
        headers=_headers(csrf, "k3-create-epoch-set-for-team-01"),
        json={"display_name": "Shared Set epoch fence"},
    )
    assert set_response.status_code == 201, set_response.text
    set_id = set_response.json()["id"]
    payload = _team_payload([first[1], second[1]], visibility="public")
    payload["shared_knowledge_set_ids"] = [set_id]
    created = client.post(
        f"/api/v1/courses/{COURSE_ID}/teams",
        headers=_headers(csrf, "k3-create-set-epoch-fenced-team-01"),
        json=payload,
    )
    assert created.status_code == 201, created.text
    from app.modules.teams.service import assert_current_chat_targets, resolve_chat_entry

    with database.session() as db:
        selection = resolve_chat_entry(db, BOWEN_ID, created.json()["id"], require_publication=True)
    with database.session() as db:
        from app.modules.knowledge_sets.models import KnowledgeSet

        shared_set = db.get(KnowledgeSet, set_id)
        assert shared_set is not None
        shared_set.authorization_epoch += 1
        db.commit()
    with database.session() as db:
        with pytest.raises(PlatformError) as revoked_set:
            assert_current_chat_targets(db, BOWEN_ID, selection)
        assert revoked_set.value.status_code == 404


def test_publication_failure_rolls_back_team_version_directory_and_grants(
    client: TestClient, database: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    del client
    first = _make_agent_version(database, owner_id=MAYA_ID, name="Atomic Agent A")
    second = _make_agent_version(database, owner_id=MAYA_ID, name="Atomic Agent B")
    from app.modules.auth.service import AuthContext
    from app.modules.teams import service
    from app.modules.teams.models import (
        CourseTeamPublication,
        Team,
        TeamMemberInvokeGrant,
        TeamVersion,
        TeamVersionMember,
    )
    from app.modules.teams.schemas import CreateTeamRequest

    with database.session_factory() as db:
        user = db.get(User, MAYA_ID)
        assert user is not None
        db.expunge(user)
        context = AuthContext("", None, user, "")  # type: ignore[arg-type]

        def fail_after_directory_insert(
            session: Any,
            team: Team,
            version: TeamVersion,
            actor: AuthContext,
            timestamp: datetime,
        ) -> None:
            publication = CourseTeamPublication(
                id=str(uuid4()),
                course_id=team.course_id,
                team_id=team.id,
                team_version_id=version.id,
                publisher_user_id=actor.user.id,
                authorization_epoch=team.authorization_epoch,
                state="published",
                published_at=timestamp,
                revoked_at=None,
            )
            session.add(publication)
            session.flush()
            raise RuntimeError("injected publication fault")

        monkeypatch.setattr(service, "_publish_eligible_team", fail_after_directory_insert)
        with pytest.raises(RuntimeError, match="injected publication fault"):
            service.create_team(
                db,
                context,
                COURSE_ID,
                CreateTeamRequest(**_team_payload([first[1], second[1]], visibility="public")),
            )
        db.rollback()
        assert db.query(Team).count() == 0
        assert db.query(TeamVersion).count() == 0
        assert db.query(TeamVersionMember).count() == 0
        assert db.query(CourseTeamPublication).count() == 0
        assert db.query(TeamMemberInvokeGrant).count() == 0


def test_0040_downgrade_refuses_to_discard_team_history(tmp_path: Path) -> None:
    from alembic import command
    from alembic.config import Config
    from app.core.models import Course, User
    from app.modules.teams.models import Team

    database_path = tmp_path / "k3a-downgrade.sqlite3"
    database_url = f"sqlite:///{database_path}"
    database = Database(database_url)
    database.upgrade_schema()
    timestamp = datetime.now(UTC)
    with database.session() as db:
        db.add(
            User(
                id=MAYA_ID,
                username="k3a-owner",
                display_name="K3A owner",
                status="active",
                created_at=timestamp,
            )
        )
        db.add(
            Course(
                id=COURSE_ID,
                code="k3a-course",
                name="K3A course",
                current_audio_debate_id=None,
                created_at=timestamp,
            )
        )
        db.flush()
        db.add(
            Team(
                id=str(uuid4()),
                owner_user_id=MAYA_ID,
                course_id=COURSE_ID,
                group_id=None,
                ownership_scope="personal",
                display_name="Keep my Team",
                visibility="private",
                metadata_revision=0,
                authorization_epoch=0,
                current_version_seq=1,
                deleted_at=None,
                created_at=timestamp,
                updated_at=timestamp,
            )
        )

    migration_dir = Path(__file__).resolve().parents[1] / "migrations"
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("script_location", str(migration_dir))
    config.set_main_option("sqlalchemy.url", database_url)
    config.attributes["database_url"] = database_url
    with pytest.raises(RuntimeError, match="Team history exists"):
        command.downgrade(config, "0039_knowledge_generation_materialization")
    with database.engine.connect() as connection:
        head = connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one()
        assert head == "0040_teams_publication_grants"
        assert connection.exec_driver_sql("SELECT COUNT(*) FROM teams").scalar_one() == 1
    database.engine.dispose()
