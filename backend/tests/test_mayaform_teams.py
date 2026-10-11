from __future__ import annotations

import hashlib
import json
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
    FileReference,
    Group,
    GroupMember,
    KnowledgeDocument,
    KnowledgeSnapshot,
    SnapshotDocument,
    StoredFile,
    TeacherGroupAccess,
    User,
)
from app.modules.teams.models import TeamVersionMember
from fastapi.testclient import TestClient
from sqlalchemy import select, text

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
    file_id, frozen_file_id, snapshot_file_id = str(uuid4()), str(uuid4()), str(uuid4())
    document_id, snapshot_id = str(uuid4()), str(uuid4())
    snapshot_document_id = str(uuid4())
    snapshot_bytes = b"combined snapshot fixture\n"
    snapshot_hash = hashlib.sha256(snapshot_bytes).hexdigest()
    with database.session() as db:
        db.add_all(
            [
                StoredFile(
                    id=file_id,
                    kind="markdown",
                    relative_path=f"teams/{file_id}.md",
                    sha256=digest,
                    size_bytes=len(content.encode("utf-8")),
                    state="active",
                    created_at=timestamp,
                    updated_at=timestamp,
                ),
                StoredFile(
                    id=frozen_file_id,
                    kind="snapshot_source",
                    relative_path=f"snapshots/{snapshot_id}/documents/{snapshot_document_id}.md",
                    sha256=digest,
                    size_bytes=len(content.encode("utf-8")),
                    state="active",
                    created_at=timestamp,
                    updated_at=timestamp,
                ),
                StoredFile(
                    id=snapshot_file_id,
                    kind="snapshot_rag",
                    relative_path=f"snapshots/{snapshot_id}/rag.md",
                    sha256=snapshot_hash,
                    size_bytes=len(snapshot_bytes),
                    state="active",
                    created_at=timestamp,
                    updated_at=timestamp,
                ),
            ]
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
                stored_file_id=snapshot_file_id,
                content_hash=snapshot_hash,
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
                stored_file_id=frozen_file_id,
                source_filename="private-source.md",
                char_count=len(content),
                order_index=0,
                source_authorization_epoch=0,
            )
        )
        db.add(
            FileReference(
                id=str(uuid4()),
                stored_file_id=snapshot_file_id,
                owner_type="knowledge_snapshot",
                owner_id=snapshot_id,
                purpose="rag",
                created_at=timestamp,
            )
        )
        db.add(
            FileReference(
                id=str(uuid4()),
                stored_file_id=frozen_file_id,
                owner_type="snapshot_document",
                owner_id=snapshot_document_id,
                purpose="source",
                created_at=timestamp,
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
        readable = resolve_chat_entry(db, BOWEN_ID, created["id"], require_publication=False)
        assert readable.publication_id == publication.id

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
    assert made_private.status_code == 409, made_private.text
    assert made_private.json()["code"] == "team_visibility_locked"
    assert (
        len(
            client.get(
                f"/api/v1/courses/{COURSE_ID}/maya-teams", headers=_headers(student_csrf)
            ).json()
        )
        == 1
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
    from app.modules.knowledge.source_versions import retain_current_source_version

    with database.session() as db:
        document = db.get(KnowledgeDocument, document_id)
        assert document is not None
        original_content_hash = document.content_hash
        member = db.scalar(
            select(TeamVersionMember).where(
                TeamVersionMember.team_version_id == selection.team_version_id,
                TeamVersionMember.agent_version_id == first[1],
            )
        )
        assert member is not None
        current_fences = json.loads(member.raw_source_fences_json)
        assert isinstance(current_fences, list) and len(current_fences) == 1
        retain_current_source_version(db, document)
        content = "A newer current revision leaves the published Agent snapshot frozen.\n"
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        timestamp = datetime.now(UTC)
        new_file_id = str(uuid4())
        db.add(
            StoredFile(
                id=new_file_id,
                kind="markdown",
                relative_path=f"teams/{new_file_id}.md",
                sha256=digest,
                size_bytes=len(content.encode("utf-8")),
                state="active",
                created_at=timestamp,
                updated_at=timestamp,
            )
        )
        db.flush()
        document.stored_file_id = new_file_id
        document.char_count = len(content)
        document.content_version_seq += 1
        document.index_status = "ready"
        document.index_revision += 1
        document.content_hash = digest
        document.updated_at = timestamp
        db.flush()
        db.expire(document, ["stored_file"])
        retain_current_source_version(db, document)
        legacy_fences = [
            {
                "document_id": fence["document_id"],
                "stored_file_id": fence["stored_file_id"],
                "content_hash": original_content_hash,
                "file_sha256": fence["file_sha256"],
                "authorization_epoch": fence["authorization_epoch"],
            }
            for fence in current_fences
        ]
        member.raw_source_fences_json = json.dumps(legacy_fences, separators=(",", ":"))
        db.commit()
    with database.session() as db:
        assert_current_chat_targets(db, BOWEN_ID, selection, {selected_id})
    with database.session() as db:
        member = db.scalar(
            select(TeamVersionMember).where(
                TeamVersionMember.team_version_id == selection.team_version_id,
                TeamVersionMember.agent_version_id == first[1],
            )
        )
        assert member is not None
        foreign_file_id = str(uuid4())
        timestamp = datetime.now(UTC)
        db.add(
            StoredFile(
                id=foreign_file_id,
                kind="snapshot_source",
                relative_path=f"snapshots/foreign/{foreign_file_id}.md",
                sha256=legacy_fences[0]["file_sha256"],
                size_bytes=1,
                state="active",
                created_at=timestamp,
                updated_at=timestamp,
            )
        )
        member.raw_source_fences_json = json.dumps(
            [{**legacy_fences[0], "stored_file_id": foreign_file_id}], separators=(",", ":")
        )
        db.commit()
    with database.session() as db:
        with pytest.raises(PlatformError) as foreign_legacy_file:
            assert_current_chat_targets(db, BOWEN_ID, selection, {selected_id})
        assert foreign_legacy_file.value.status_code == 404
    with database.session() as db:
        member = db.scalar(
            select(TeamVersionMember).where(
                TeamVersionMember.team_version_id == selection.team_version_id,
                TeamVersionMember.agent_version_id == first[1],
            )
        )
        document = db.get(KnowledgeDocument, document_id)
        assert member is not None and document is not None
        member.raw_source_fences_json = json.dumps(legacy_fences, separators=(",", ":"))
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


@pytest.mark.parametrize(
    "mutation,expected_status",
    [
        ("content_only", 201),
        ("legacy_content_only", 201),
        ("authorization_epoch_changed", 404),
        ("source_withdrawn", 404),
        ("source_course_mismatch", 404),
        ("wrong_snapshot", 404),
        ("frozen_file_deleted", 404),
        ("frozen_file_rebound", 404),
    ],
)
def test_team_creation_preserves_owned_published_snapshot_after_source_content_revision(
    client: TestClient, database: Database, mutation: str, expected_status: int
) -> None:
    """A content-only edit must not invalidate an owned immutable snapshot."""

    from app.modules.knowledge.source_versions import retain_current_source_version
    from app.modules.knowledge_sets.models import KnowledgeDocumentVersion
    from sqlalchemy import select

    seeded = [
        _make_agent_version(database, owner_id=MAYA_ID, name=f"Snapshot Member {index}")
        for index in range(4)
    ]
    versions = [version_id for _agent_id, version_id in seeded]
    document_id = _attach_personal_snapshot(database, versions[0])
    with database.session() as db:
        document = db.get(KnowledgeDocument, document_id)
        assert document is not None
        old_file_id = document.stored_file_id
        version = db.get(AgentVersion, versions[0])
        assert version is not None and version.knowledge_snapshot_id is not None
        snapshot = db.get(KnowledgeSnapshot, version.knowledge_snapshot_id)
        assert snapshot is not None
        frozen_source = db.scalar(
            select(SnapshotDocument).where(
                SnapshotDocument.snapshot_id == version.knowledge_snapshot_id,
                SnapshotDocument.document_id == document_id,
            )
        )
        assert frozen_source is not None and frozen_source.stored_file_id != old_file_id
        frozen_file = db.get(StoredFile, frozen_source.stored_file_id)
        assert frozen_file is not None
        old_epoch = document.authorization_epoch
        if mutation != "legacy_content_only":
            retain_current_source_version(db, document)
        old_file = db.get(StoredFile, old_file_id)
        assert old_file is not None
        old_content_hash = document.content_hash
        old_file_sha = old_file.sha256
        timestamp = datetime.now(UTC)
        revised_content = "Maya's current source revision, with unchanged access rights.\n"
        revised_sha = hashlib.sha256(revised_content.encode("utf-8")).hexdigest()
        revised_file_id = str(uuid4())
        db.add(
            StoredFile(
                id=revised_file_id,
                kind="markdown",
                relative_path=f"teams/{revised_file_id}.md",
                sha256=revised_sha,
                size_bytes=len(revised_content.encode("utf-8")),
                state="active",
                created_at=timestamp,
                updated_at=timestamp,
            )
        )
        db.flush()
        document.stored_file_id = revised_file_id
        document.char_count = len(revised_content)
        document.content_version_seq += 1
        document.index_status = "ready"
        document.index_revision += 1
        document.content_hash = revised_sha
        if mutation == "authorization_epoch_changed":
            document.authorization_epoch += 1
        elif mutation == "source_withdrawn":
            document.workspace_state = "hidden"
        elif mutation == "source_course_mismatch":
            foreign_course_id = str(uuid4())
            db.add(
                Course(
                    id=foreign_course_id,
                    code=f"other-{uuid4()}",
                    name="Other course",
                    created_at=timestamp,
                )
            )
            db.flush()
            db.add(
                CourseMember(
                    course_id=foreign_course_id,
                    user_id=MAYA_ID,
                    role="teacher",
                    created_at=timestamp,
                )
            )
            document.course_id = foreign_course_id
        elif mutation == "wrong_snapshot":
            snapshot.agent_version_id = versions[1]
        document.updated_at = timestamp
        assert document.authorization_epoch == old_epoch + int(
            mutation == "authorization_epoch_changed"
        )
        db.flush()
        db.expire(document, ["stored_file"])
        retain_current_source_version(db, document)
        if mutation == "frozen_file_deleted":
            frozen_file.state = "deleted"
        elif mutation == "frozen_file_rebound":
            foreign_file_id = str(uuid4())
            db.add(
                StoredFile(
                    id=foreign_file_id,
                    kind="snapshot_source",
                    relative_path=f"snapshots/foreign/{foreign_file_id}.md",
                    sha256=old_file_sha,
                    size_bytes=old_file.size_bytes,
                    state="active",
                    created_at=timestamp,
                    updated_at=timestamp,
                )
            )
            db.flush()
            frozen_source.stored_file_id = foreign_file_id
        old_version = db.scalar(
            select(KnowledgeDocumentVersion).where(
                KnowledgeDocumentVersion.document_id == document_id,
                KnowledgeDocumentVersion.stored_file_id == old_file_id,
                KnowledgeDocumentVersion.content_hash == old_content_hash,
                KnowledgeDocumentVersion.file_sha256 == old_file_sha,
            )
        )
        if mutation == "legacy_content_only":
            assert old_version is None
        else:
            assert old_version is not None and old_version.authorization_epoch == old_epoch
        assert frozen_source.stored_file_id != document.stored_file_id

    _, csrf = login(client, "maya")
    response = client.post(
        f"/api/v1/courses/{COURSE_ID}/teams",
        headers=_headers(csrf, f"historical-snapshot-team-{uuid4()}"),
        json={
            **_team_payload(versions, visibility="private"),
            "members": [
                {
                    "agent_version_id": version_id,
                    "is_leader": index == 0,
                    "position": index,
                }
                for index, version_id in enumerate(versions)
            ],
        },
    )
    assert response.status_code == expected_status, response.text
    if expected_status == 201:
        assert len(response.json()["members"]) == 4
        from app.modules.teams.models import Team, TeamVersion
        from app.modules.teams.service import assert_current_chat_targets, resolve_chat_entry

        with database.session() as db:
            team = db.get(Team, response.json()["id"])
            assert team is not None
            team_version = db.scalar(
                select(TeamVersion).where(
                    TeamVersion.team_id == team.id,
                    TeamVersion.version_seq == team.current_version_seq,
                )
            )
            assert team_version is not None
            team_member = db.scalar(
                select(TeamVersionMember).where(
                    TeamVersionMember.team_version_id == team_version.id,
                    TeamVersionMember.agent_version_id == versions[0],
                )
            )
            assert team_member is not None
            persisted_fences = json.loads(team_member.raw_source_fences_json)
            agent_version = db.get(AgentVersion, versions[0])
            assert agent_version is not None and agent_version.knowledge_snapshot_id is not None
            snapshot_documents = db.scalars(
                select(SnapshotDocument).where(
                    SnapshotDocument.snapshot_id == agent_version.knowledge_snapshot_id
                )
            ).all()
            assert len(persisted_fences) == len(snapshot_documents)
            assert len({fence["snapshot_document_id"] for fence in persisted_fences}) == len(
                persisted_fences
            )
            assert {fence["snapshot_document_id"] for fence in persisted_fences} == {
                row.id for row in snapshot_documents
            }
            selection = resolve_chat_entry(db, MAYA_ID, response.json()["id"])
            assert_current_chat_targets(db, MAYA_ID, selection)


def test_team_member_without_knowledge_snapshot_keeps_an_empty_source_fence(
    client: TestClient, database: Database
) -> None:
    first = _make_agent_version(database, owner_id=MAYA_ID, name="No RAG member")
    second = _make_agent_version(database, owner_id=MAYA_ID, name="Also no RAG")
    _, csrf = login(client, "maya")
    response = client.post(
        f"/api/v1/courses/{COURSE_ID}/teams",
        headers=_headers(csrf, f"no-rag-team-{uuid4()}"),
        json=_team_payload([first[1], second[1]], visibility="private"),
    )
    assert response.status_code == 201, response.text

    from app.modules.teams.models import Team, TeamVersion
    from app.modules.teams.service import assert_current_chat_targets, resolve_chat_entry

    with database.session() as db:
        team = db.get(Team, response.json()["id"])
        assert team is not None
        team_version = db.scalar(
            select(TeamVersion).where(
                TeamVersion.team_id == team.id,
                TeamVersion.version_seq == team.current_version_seq,
            )
        )
        assert team_version is not None
        member = db.scalar(
            select(TeamVersionMember).where(
                TeamVersionMember.team_version_id == team_version.id,
                TeamVersionMember.agent_version_id == first[1],
            )
        )
        assert member is not None and member.raw_source_fences_json == "[]"
        selection = resolve_chat_entry(db, MAYA_ID, team.id)
        assert_current_chat_targets(db, MAYA_ID, selection)


@pytest.mark.parametrize(
    "mutation",
    [
        "empty",
        "duplicate",
        "foreign_snapshot",
        "foreign_document",
        "foreign_file",
        "legacy_duplicate",
    ],
)
def test_team_send_rejects_incomplete_or_foreign_snapshot_source_fences(
    mutation: str, client: TestClient, database: Database
) -> None:
    seeded = [
        _make_agent_version(database, owner_id=MAYA_ID, name=f"Fence member {index}")
        for index in range(2)
    ]
    versions = [version_id for _agent_id, version_id in seeded]
    source_ids = [_attach_personal_snapshot(database, version_id) for version_id in versions]
    _, csrf = login(client, "maya")
    response = client.post(
        f"/api/v1/courses/{COURSE_ID}/teams",
        headers=_headers(csrf, f"malformed-source-fence-team-{uuid4()}"),
        json=_team_payload(versions, visibility="private"),
    )
    assert response.status_code == 201, response.text

    from app.modules.teams.service import assert_current_chat_targets, resolve_chat_entry

    selected_id = next(
        member["id"]
        for member in response.json()["members"]
        if member["agent_version_id"] == versions[0]
    )
    with database.session() as db:
        selection = resolve_chat_entry(db, MAYA_ID, response.json()["id"])
        member = db.scalar(
            select(TeamVersionMember).where(
                TeamVersionMember.team_version_id == selection.team_version_id,
                TeamVersionMember.agent_version_id == versions[0],
            )
        )
        assert member is not None
        fences = json.loads(member.raw_source_fences_json)
        assert isinstance(fences, list) and len(fences) == 1
        if mutation == "empty":
            fences = []
        elif mutation == "duplicate":
            fences = [*fences, *fences]
        elif mutation == "foreign_snapshot":
            foreign_version = db.get(AgentVersion, versions[1])
            assert foreign_version is not None
            fences[0]["snapshot_id"] = foreign_version.knowledge_snapshot_id
        elif mutation == "foreign_document":
            fences[0]["document_id"] = source_ids[1]
        elif mutation == "foreign_file":
            foreign_version = db.get(AgentVersion, versions[1])
            assert foreign_version is not None and foreign_version.knowledge_snapshot_id is not None
            foreign_source = db.scalar(
                select(SnapshotDocument).where(
                    SnapshotDocument.snapshot_id == foreign_version.knowledge_snapshot_id
                )
            )
            assert foreign_source is not None
            fences[0]["stored_file_id"] = foreign_source.stored_file_id
        else:
            legacy_fence = {
                key: fences[0][key]
                for key in ("document_id", "stored_file_id", "file_sha256", "authorization_epoch")
            }
            document = db.get(KnowledgeDocument, source_ids[0])
            assert document is not None
            legacy_fence["content_hash"] = document.content_hash
            fences = [legacy_fence, legacy_fence]
        member.raw_source_fences_json = json.dumps(fences, separators=(",", ":"))
        db.commit()

    with database.session() as db:
        with pytest.raises(PlatformError) as incomplete_fence:
            assert_current_chat_targets(db, MAYA_ID, selection, {selected_id})
        assert incomplete_fence.value.status_code == 404


def test_team_llm_send_rechecks_persisted_source_fences_after_reservation(
    client: TestClient, app_bundle: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from unittest.mock import Mock

    from agno.models.message import Message
    from app.core.models import ProviderOperation
    from app.modules.provider_disclosure.team_standing import (
        confirm_team_standing_grant,
        prepare_team_standing_grant,
    )
    from app.modules.workspace import team_runtime
    from app.modules.workspace.chat_team_provider import dispatch_team_model
    from app.modules.workspace.chat_team_sdk import TeamDispatchError
    from app.modules.workspace.models import (
        Conversation,
        ConversationParticipant,
        ConversationTurn,
        TeamTurnResult,
    )
    from app.providers.control_repository import ProviderRepository
    from app.providers.llm_adapter import DashScopeLLMConfig
    from httpx import Response

    from tests.test_team_provider_disclosure import _prepared
    from tests.test_wave4_provider_preflight import _digest, _policy

    _app, database, settings = app_bundle
    result_id, _manifest, _document_id, _set_id = _prepared(client, database, settings)
    settings.llm_provider = "dashscope"
    settings.dashscope_api_key = "synthetic-key"
    settings.dashscope_workspace_id = "synthetic-workspace"
    settings.dashscope_region = "cn-beijing"
    policy = _policy(
        policy_id="team-source-fence-after-reservation",
        endpoint=DashScopeLLMConfig(
            api_key="synthetic-key",
            workspace_id="synthetic-workspace",
            region="cn-beijing",
            model_key=settings.llm_model,
            policy_hash=_digest("pending-source-fence-policy"),
        ).resolved_endpoint,
    )
    settings.llm_provider_policy_hash = policy.policy_hash
    ProviderRepository(database).save_policy_snapshot(policy)

    with database.session() as db:
        result = db.get(TeamTurnResult, result_id)
        assert result is not None
        conversation = db.get(Conversation, result.conversation_id)
        turn = db.get(ConversationTurn, result.turn_id)
        participant = db.get(ConversationParticipant, result.participant_id)
        assert conversation is not None and turn is not None and participant is not None
        plan = prepare_team_standing_grant(
            db,
            MAYA_ID,
            team_version_id=conversation.team_version_id,
            policy_hash=policy.policy_hash,
            provider_operation="llm_agent_chat",
        )
        confirm_team_standing_grant(
            db,
            MAYA_ID,
            team_version_id=conversation.team_version_id,
            policy_hash=policy.policy_hash,
            provider_operation="llm_agent_chat",
            expected_resource_hash=plan.resource_hash,
            expected_team_epoch=plan.team_epoch,
            expected_publication_epoch=plan.publication_epoch,
        )
        turn_id = turn.id
        participant_id = participant.id
        team_member_id = participant.team_member_id
        claim_token = turn.claim_token
        binding_ids = {team_member_id}
    assert claim_token is not None
    request = team_runtime._start_member(
        database.session_factory, turn_id, claim_token, result_id, settings=settings
    )
    assert request is not None

    original_transition = ProviderRepository.transition
    transition_seen: list[str] = []

    def transition(self: Any, operation_id: str, **kwargs: Any) -> Any:
        if kwargs.get("expected") == "reserved" and kwargs.get("state") == "sending":
            transition_seen.append(operation_id)
            with database.session() as db:
                participant = db.get(ConversationParticipant, participant_id)
                assert participant is not None
                member = db.get(TeamVersionMember, participant.team_member_id)
                assert member is not None
                member.raw_source_fences_json = "[]"
                db.commit()
        return original_transition(self, operation_id, **kwargs)

    monkeypatch.setattr(ProviderRepository, "transition", transition)
    transport = Mock(
        return_value=Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "Synthetic reply"},
                        "finish_reason": "stop",
                    }
                ]
            },
        )
    )
    monkeypatch.setattr(
        "app.modules.workspace.chat_team_provider.HttpxLLMTransport.post_bytes", transport
    )
    with database.session() as db:
        with pytest.raises(TeamDispatchError, match="team_context_changed"):
            dispatch_team_model(
                db,
                settings,
                request,
                [Message(role="user", content="synthetic current user")],
                [],
                None,
                ordinal=0,
                selected_binding_ids=binding_ids,
                actor_context=None,
            )

    assert len(transition_seen) == 1
    assert transport.call_count == 0
    with database.session() as db:
        operation = db.get(ProviderOperation, transition_seen[0])
        assert operation is not None
        member = db.get(TeamVersionMember, team_member_id)
        assert operation.state == "not_sent"
        assert operation.charged_request_count == 0
        assert member is not None and member.raw_source_fences_json == "[]"


def test_owner_soft_deletes_a_maya_team_and_replays_the_same_key(
    client: TestClient, database: Any
) -> None:
    _, csrf = login(client, "maya")
    first = _make_agent_version(database, owner_id=MAYA_ID, name="Delete Seed A")
    second = _make_agent_version(database, owner_id=MAYA_ID, name="Delete Seed B")
    created = client.post(
        f"/api/v1/courses/{COURSE_ID}/teams",
        headers=_headers(csrf, "k3-delete-team-create-01"),
        json=_team_payload([first[1], second[1]], visibility="public"),
    )
    assert created.status_code == 201, created.text
    team_id = created.json()["id"]

    _, student_csrf = login(client, "bowen")
    denied = client.delete(
        f"/api/v1/teams/{team_id}",
        headers=_headers(student_csrf, "k3-delete-team-bowen-01"),
    )
    assert denied.status_code == 404

    _, csrf = login(client, "maya")
    deleted = client.delete(
        f"/api/v1/teams/{team_id}",
        headers=_headers(csrf, "k3-delete-team-01"),
    )
    assert deleted.status_code == 204, deleted.text
    replay = client.delete(
        f"/api/v1/teams/{team_id}",
        headers=_headers(csrf, "k3-delete-team-01"),
    )
    assert replay.status_code == 204
    listed = client.get(f"/api/v1/courses/{COURSE_ID}/teams", headers=_headers(csrf))
    assert listed.status_code == 200
    assert all(item["id"] != team_id for item in listed.json())
    directory = client.get(f"/api/v1/courses/{COURSE_ID}/maya-teams", headers=_headers(csrf))
    assert directory.status_code == 200
    assert all(item["id"] != team_id for item in directory.json())
    assert client.get(f"/api/v1/teams/{team_id}", headers=_headers(csrf)).status_code == 404


def test_student_public_team_is_read_only_for_the_same_group_and_teachers(
    client: TestClient, database: Any
) -> None:
    group_id = str(uuid4())
    with database.session() as db:
        db.add(
            Group(
                id=group_id,
                course_id=COURSE_ID,
                name=f"Circle {group_id[:8]}",
                created_at=datetime.now(UTC),
            )
        )
        db.add(
            GroupMember(
                group_id=group_id,
                user_id=BOWEN_ID,
                role="member",
                created_at=datetime.now(UTC),
            )
        )
        db.commit()
    _, bowen_csrf = login(client, "bowen")
    first = _make_agent_version(
        database,
        owner_id=BOWEN_ID,
        name="Group voice A",
        visibility="public",
        group_id=group_id,
    )
    second = _make_agent_version(
        database,
        owner_id=BOWEN_ID,
        name="Group voice B",
        visibility="public",
        group_id=group_id,
    )
    created_set = client.post(
        f"/api/v1/courses/{COURSE_ID}/knowledge-sets",
        headers=_headers(bowen_csrf, f"student-team-set-{uuid4()}"),
        json={"display_name": "Shared circle notes"},
    )
    assert created_set.status_code == 201, created_set.text
    set_id = created_set.json()["id"]
    payload = _team_payload([first[1], second[1]], visibility="public")
    payload["group_id"] = group_id
    payload["shared_knowledge_set_ids"] = [set_id]
    created = client.post(
        f"/api/v1/courses/{COURSE_ID}/teams",
        headers=_headers(bowen_csrf, f"student-public-team-{uuid4()}"),
        json=payload,
    )
    assert created.status_code == 201, created.text
    body = created.json()
    team_id = body["id"]
    assert body["can_edit"] is True
    assert body["publication_state"] == "unpublished"
    assert body["shared_knowledge_sets"] == [{"id": set_id, "display_name": "Shared circle notes"}]
    assert [member["display_name"] for member in body["members"]] == [
        "Group voice A",
        "Group voice B",
    ]

    _, outsider_csrf = login(client, "kaikai")
    assert (
        client.get(f"/api/v1/teams/{team_id}", headers=_headers(outsider_csrf)).status_code == 404
    )
    outsider_list = client.get(
        f"/api/v1/courses/{COURSE_ID}/teams", headers=_headers(outsider_csrf)
    )
    assert outsider_list.status_code == 200
    assert all(item["id"] != team_id for item in outsider_list.json())

    _, teacher_csrf = login(client, "maya")
    teacher = client.get(f"/api/v1/teams/{team_id}", headers=_headers(teacher_csrf))
    assert teacher.status_code == 200, teacher.text
    assert teacher.json()["can_edit"] is False
    assert teacher.json()["shared_knowledge_sets"][0]["display_name"] == "Shared circle notes"

    with database.session() as db:
        db.add(
            GroupMember(
                group_id=group_id,
                user_id="bc170f51-45fb-5296-a36d-a2edc8f8d315",
                role="member",
                created_at=datetime.now(UTC),
            )
        )
        db.commit()
    _, classmate_csrf = login(client, "kaikai")
    classmate = client.get(f"/api/v1/teams/{team_id}", headers=_headers(classmate_csrf))
    assert classmate.status_code == 200, classmate.text
    assert classmate.json()["can_edit"] is False
    assert classmate.json()["members"][0]["is_leader"] is True

    _, bowen_csrf = login(client, "bowen")
    locked = client.put(
        f"/api/v1/teams/{team_id}",
        headers=_headers(bowen_csrf, f"student-team-lock-{uuid4()}"),
        json={
            "display_name": body["display_name"],
            "visibility": "private",
            "members": payload["members"],
            "shared_knowledge_set_ids": [set_id],
            "expected_metadata_revision": body["metadata_revision"],
        },
    )
    assert locked.status_code == 409, locked.text
    assert locked.json()["code"] == "team_visibility_locked"
