from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier
from typing import Any
from uuid import uuid4

import pytest
from alembic import command
from app.core.errors import PlatformError
from app.core.models import Agent, AgentVersion
from app.modules.auth.service import AuthContext, get_auth_context
from app.modules.demo_baseline.service import (
    BASELINE_VERSION_ID,
    BASELINE_VERSION_IDS,
    ensure_demo_baseline,
)
from app.modules.learning.models import (
    LearningAssessment,
    LearningAssessmentMutation,
    LearningAssessmentRevision,
    LearningRecord,
)
from app.modules.learning.schemas import (
    AnswerRecordRequest,
    CreateAssessmentRequest,
    EditAssessmentRequest,
    HintRecordRequest,
    LearningEvidenceRequest,
    SkipRecordRequest,
)
from app.modules.learning.service import (
    create_assessment,
    edit_assessment,
    read_assessment,
    read_learning_records,
    record_learning_event,
)
from app.modules.teams.models import CourseTeamPublication, Team, TeamVersion, TeamVersionMember
from app.modules.teams.service import _capture_raw_source_fences
from app.modules.workspace.models import Conversation
from app.seed import COURSE_ID, TEACHER_ID
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from sqlalchemy.engine import Engine

from tests.conftest import login
from tests.test_mayaform_team_conversations import _config, _fingerprint, _seed_0040

STUDENT_ID = "60541c78-30f1-55c5-b2aa-207b6a766883"
OTHER_STUDENT_ID = "bc170f51-45fb-5296-a36d-a2edc8f8d315"


@pytest.fixture
def learning_env(app_bundle: Any, client: TestClient) -> tuple[Any, Any, Any, TestClient]:
    app, database, settings = app_bundle
    client.headers["Origin"] = "http://testserver"
    with database.session() as db:
        ensure_demo_baseline(db, settings.resolved_data_root)
    return app, database, settings, client


def _login(client: TestClient, username: str) -> tuple[str, str]:
    _session, csrf = login(client, username)
    token = client.cookies.get("maya_session")
    assert token
    return token, csrf


def _start_chat(client: TestClient, csrf: str) -> str:
    response = client.post(
        "/api/v1/conversations",
        headers={"X-CSRF-Token": csrf},
        json={"entry": {"kind": "agent", "version_id": BASELINE_VERSION_ID}},
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _context(db: Any, settings: Any, raw_token: str) -> AuthContext:
    context = get_auth_context(db, settings, raw_token)
    assert context is not None
    return context


def _team_conversation(
    db: Any,
    *,
    actor_user_id: str,
    team_owner_id: str,
    origin: str,
    visibility: str,
) -> tuple[str, str, str | None]:
    versions = db.scalars(
        select(AgentVersion)
        .join(Agent, Agent.id == AgentVersion.agent_id)
        .where(
            Agent.course_id == COURSE_ID,
            AgentVersion.state == "published",
            AgentVersion.id.in_(BASELINE_VERSION_IDS),
        )
        .order_by(AgentVersion.version_seq, AgentVersion.id)
        .limit(2)
    ).all()
    assert len(versions) == 2
    now = datetime.now(UTC)
    team_id, version_id = str(uuid4()), str(uuid4())
    team_name = f"{origin} provenance fixture"
    team = Team(
        id=team_id,
        owner_user_id=team_owner_id,
        course_id=COURSE_ID,
        group_id=None,
        ownership_scope="personal",
        display_name=team_name,
        visibility="public",
        metadata_revision=0,
        authorization_epoch=0,
        current_version_seq=1,
        deleted_at=None,
        created_at=now,
        updated_at=now,
    )
    version = TeamVersion(
        id=version_id,
        team_id=team_id,
        version_seq=1,
        display_name=team_name,
        visibility="public",
        authorization_epoch=0,
        created_by_user_id=team_owner_id,
        created_at=now,
    )
    db.add_all([team, version])
    db.flush()
    for position, agent_version in enumerate(versions):
        agent = db.get(Agent, agent_version.agent_id)
        assert agent is not None
        db.add(
            TeamVersionMember(
                id=str(uuid4()),
                team_version_id=version_id,
                agent_id=agent.id,
                agent_version_id=agent_version.id,
                position=position,
                is_leader=position == 0,
                display_name=agent.name,
                avatar_config_json=agent_version.avatar_config_json,
                own_knowledge_set_snapshots_json="[]",
                raw_source_fences_json=json.dumps(
                    _capture_raw_source_fences(db, agent_version, COURSE_ID),
                    ensure_ascii=True,
                    separators=(",", ":"),
                ),
                created_at=now,
            )
        )
    db.flush()

    publication_id: str | None = None
    entry_kind = "team"
    publication_epoch: int | None = None
    if origin == "published_course_team":
        entry_kind = "maya_team"
        publication_id = str(uuid4())
        publication_epoch = 0
        db.add(
            CourseTeamPublication(
                id=publication_id,
                course_id=COURSE_ID,
                team_id=team_id,
                team_version_id=version_id,
                publisher_user_id=team_owner_id,
                authorization_epoch=0,
                state="published",
                published_at=now,
                revoked_at=None,
            )
        )
        db.flush()

    conversation_id = str(uuid4())
    db.add(
        Conversation(
            id=conversation_id,
            user_id=actor_user_id,
            course_id=COURSE_ID,
            agent_version_id=None,
            snapshot_id=None,
            agent_name_snapshot="",
            agent_authorization_epoch=0,
            entry_kind=entry_kind,
            chat_visibility=visibility,
            origin=origin,
            team_id=team_id,
            team_version_id=version_id,
            team_owner_user_id=team_owner_id,
            team_name_snapshot=team_name,
            team_authorization_epoch=0,
            publication_id=publication_id,
            publication_epoch=publication_epoch,
            revision=0,
            active_request_id=None,
            created_at=now,
        )
    )
    db.flush()
    return conversation_id, team_id, version_id


def test_answers_hints_skips_and_evidence_append_once_and_survive_chat_delete(
    learning_env: Any,
) -> None:
    _app, database, settings, client = learning_env
    raw_token, csrf = _login(client, "bowen")
    conversation_id = _start_chat(client, csrf)
    # A Chat stored before every Chat became private keeps its legacy label.
    with database.session() as db:
        legacy = db.get(Conversation, conversation_id)
        assert legacy is not None
        legacy.chat_visibility = "public"
    answer_event_id = uuid4()
    first_answer = AnswerRecordRequest(
        kind="answer",
        client_event_id=answer_event_id,
        answer_text="A first, incorrect attempt.",
    )

    with database.session() as db:
        actor = _context(db, settings, raw_token)
        saved_first = record_learning_event(db, actor, conversation_id, first_answer)
        replayed_first = record_learning_event(db, actor, conversation_id, first_answer)
        assert replayed_first.id == saved_first.id
        with pytest.raises(PlatformError) as changed_replay:
            record_learning_event(
                db,
                actor,
                conversation_id,
                AnswerRecordRequest(
                    kind="answer",
                    client_event_id=answer_event_id,
                    answer_text="A changed answer cannot reuse that request key.",
                ),
            )
        assert changed_replay.value.code == "idempotency_conflict"

        record_learning_event(
            db,
            actor,
            conversation_id,
            HintRecordRequest(
                kind="hint",
                client_event_id=uuid4(),
                hint_ref="hint-1",
            ),
        )
        record_learning_event(
            db,
            actor,
            conversation_id,
            AnswerRecordRequest(
                kind="answer",
                client_event_id=uuid4(),
                answer_text="A corrected attempt after the hint.",
            ),
        )
        record_learning_event(
            db,
            actor,
            conversation_id,
            SkipRecordRequest(kind="skip", client_event_id=uuid4()),
        )
        record_learning_event(
            db,
            actor,
            conversation_id,
            LearningEvidenceRequest(
                kind="evidence",
                client_event_id=uuid4(),
                evidence_kind="reflection",
                payload={"text": "I changed my reasoning after the hint."},
            ),
        )
        rows = read_learning_records(db, actor, conversation_id)
        assert [row.kind for row in rows] == ["answer", "hint", "answer", "skip", "evidence"]
        assert rows[0].payload["answer_text"] == "A first, incorrect attempt."
        assert rows[2].payload["answer_text"] == "A corrected attempt after the hint."
        assert str(rows[0].provenance.actor_user_id) == actor.user.id
        assert str(rows[0].provenance.course_id) == COURSE_ID
        assert rows[0].provenance.origin == "single_agent"
        assert rows[0].provenance.chat_visibility == "public"
        assert rows[0].provenance.activity_id is None

    # A legacy Public Chat stays a single_agent fact; it is not rewritten into
    # published-course evidence merely because its chat_visibility is public.
    withdrawn = client.delete(
        f"/api/v1/conversations/{conversation_id}",
        headers={"X-CSRF-Token": csrf},
    )
    assert withdrawn.status_code == 204, withdrawn.text
    assert client.get(f"/api/v1/conversations/{conversation_id}").status_code == 404
    with database.session() as db:
        conversation = db.get(Conversation, conversation_id)
        assert conversation is not None and conversation.withdrawn_at is not None
        assert (
            db.scalar(
                select(func.count(LearningRecord.id)).where(
                    LearningRecord.conversation_id == conversation_id
                )
            )
            == 5
        )
        with pytest.raises(PlatformError) as withdrawn_records:
            read_learning_records(db, _context(db, settings, raw_token), conversation_id)
        assert withdrawn_records.value.code == "not_found"


def test_assessment_revision_chain_cas_replay_and_private_acl(
    learning_env: Any,
) -> None:
    _app, database, settings, client = learning_env
    student_token, student_csrf = _login(client, "bowen")
    student_conversation = _start_chat(client, student_csrf)
    with database.session() as db:
        student = _context(db, settings, student_token)
    other_token, other_csrf = _login(client, "kaikai")
    other_conversation = _start_chat(client, other_csrf)
    with database.session() as db:
        other_student = _context(db, settings, other_token)
    teacher_token, teacher_csrf = _login(client, "maya")
    teacher_conversation = _start_chat(client, teacher_csrf)
    with database.session() as db:
        teacher = _context(db, settings, teacher_token)
    create = CreateAssessmentRequest(
        client_event_id=uuid4(),
        content={"summary": "First judgement", "status": "partial"},
    )

    with database.session() as db:
        created = create_assessment(db, student, student_conversation, create)
        replay = create_assessment(db, student, student_conversation, create)
        assert replay == created
        assessment_id = created.assessment_id
        assert created.revision.revision_seq == 1
        assert created.revision.provenance.origin == "single_agent"

        updated_request = EditAssessmentRequest(
            client_event_id=uuid4(),
            expected_revision=1,
            content={"summary": "Corrected judgement", "status": "supported"},
        )
        updated = edit_assessment(db, student, student_conversation, assessment_id, updated_request)
        assert updated.revision.revision_seq == 2
        assert updated.revision.previous_revision_id == created.revision.id
        assert (
            edit_assessment(db, student, student_conversation, assessment_id, updated_request)
            == updated
        )

        with pytest.raises(PlatformError) as cross_operation_reuse:
            edit_assessment(
                db,
                student,
                student_conversation,
                assessment_id,
                EditAssessmentRequest(
                    client_event_id=create.client_event_id,
                    expected_revision=2,
                    content={"summary": "Reused create event id"},
                ),
            )
        assert cross_operation_reuse.value.code == "idempotency_conflict"

        with pytest.raises(PlatformError) as stale:
            edit_assessment(
                db,
                student,
                student_conversation,
                assessment_id,
                EditAssessmentRequest(
                    client_event_id=uuid4(),
                    expected_revision=1,
                    content={"summary": "A concurrent stale edit"},
                ),
            )
        assert stale.value.code == "stale_revision"

        history = read_assessment(db, student, student_conversation, assessment_id)
        assert history.current_revision_seq == 2
        assert [revision.revision_seq for revision in history.revisions] == [1, 2]
        assert [revision.content["summary"] for revision in history.revisions] == [
            "First judgement",
            "Corrected judgement",
        ]
        assert (
            db.scalar(
                select(func.count(LearningAssessmentRevision.id)).where(
                    LearningAssessmentRevision.assessment_id == str(assessment_id)
                )
            )
            == 2
        )
        assert (
            db.scalar(
                select(func.count(LearningAssessmentMutation.id)).where(
                    LearningAssessmentMutation.assessment_id == str(assessment_id)
                )
            )
            == 2
        )

        for actor, own_conversation in (
            (other_student, other_conversation),
            (teacher, teacher_conversation),
        ):
            with pytest.raises(PlatformError) as denied:
                read_assessment(db, actor, own_conversation, assessment_id)
            assert denied.value.code == "not_found"
            with pytest.raises(PlatformError) as edit_denied:
                edit_assessment(
                    db,
                    actor,
                    own_conversation,
                    assessment_id,
                    EditAssessmentRequest(
                        client_event_id=uuid4(),
                        expected_revision=2,
                        content={"summary": "Must remain private"},
                    ),
                )
            assert edit_denied.value.code == "not_found"

        # Teacher's Public Tool still supports their own resource; this service
        # does not grant cross-student access from the Teacher role.
        teacher_assessment = create_assessment(
            db,
            teacher,
            teacher_conversation,
            CreateAssessmentRequest(client_event_id=uuid4(), content={"summary": "Teacher-owned"}),
        )
        assert (
            read_assessment(
                db, teacher, teacher_conversation, teacher_assessment.assessment_id
            ).current.content["summary"]
            == "Teacher-owned"
        )


def test_team_provenance_is_copied_from_conversation_without_public_chat_promotion(
    learning_env: Any,
) -> None:
    _app, database, settings, client = learning_env
    raw_token, _csrf = _login(client, "bowen")
    with database.session() as db:
        custom_conversation, custom_team_id, custom_version_id = _team_conversation(
            db,
            actor_user_id=STUDENT_ID,
            team_owner_id=STUDENT_ID,
            origin="custom_team",
            visibility="public",
        )
        maya_conversation, maya_team_id, maya_version_id = _team_conversation(
            db,
            actor_user_id=STUDENT_ID,
            team_owner_id=TEACHER_ID,
            origin="published_course_team",
            visibility="public",
        )
        actor = _context(db, settings, raw_token)
        custom = record_learning_event(
            db,
            actor,
            custom_conversation,
            LearningEvidenceRequest(
                kind="evidence",
                client_event_id=uuid4(),
                evidence_kind="reasoning",
                payload={"statement": "Student Custom Team evidence."},
            ),
        )
        published = record_learning_event(
            db,
            actor,
            maya_conversation,
            LearningEvidenceRequest(
                kind="evidence",
                client_event_id=uuid4(),
                evidence_kind="reasoning",
                payload={"statement": "Published Team evidence."},
            ),
        )

        assert custom.provenance.origin == "custom_team"
        assert str(custom.provenance.team_id) == custom_team_id
        assert str(custom.provenance.team_version_id) == custom_version_id
        assert custom.provenance.activity_id is None
        assert published.provenance.origin == "published_course_team"
        assert str(published.provenance.team_id) == maya_team_id
        assert str(published.provenance.team_version_id) == maya_version_id
        assert published.provenance.chat_visibility == "public"
        assert published.provenance.activity_id is None
        assert (
            db.scalar(
                select(func.count(LearningRecord.id)).where(
                    LearningRecord.origin == "single_agent",
                    LearningRecord.chat_visibility == "public",
                    LearningRecord.activity_id.is_not(None),
                )
            )
            == 0
        )


def test_concurrent_assessment_cas_allows_only_one_revision_winner(learning_env: Any) -> None:
    _app, database, settings, client = learning_env
    raw_token, csrf = _login(client, "bowen")
    conversation_id = _start_chat(client, csrf)
    with database.session() as db:
        actor = _context(db, settings, raw_token)
        created = create_assessment(
            db,
            actor,
            conversation_id,
            CreateAssessmentRequest(client_event_id=uuid4(), content={"summary": "Version 1"}),
        )
    assessment_id = created.assessment_id
    barrier = Barrier(2)

    def attempt_edit(summary: str) -> str:
        with database.session() as db:
            actor = _context(db, settings, raw_token)
            request = EditAssessmentRequest(
                client_event_id=uuid4(),
                expected_revision=1,
                content={"summary": summary},
            )
            barrier.wait(timeout=5)
            try:
                edit_assessment(db, actor, conversation_id, assessment_id, request)
                return "saved"
            except PlatformError as error:
                if error.code != "stale_revision":
                    raise
                return "stale"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(attempt_edit, ("Candidate A", "Candidate B")))

    assert sorted(outcomes) == ["saved", "stale"]
    with database.session() as db:
        head = db.get(LearningAssessment, str(assessment_id))
        assert head is not None and head.current_revision_seq == 2
        revisions = db.scalars(
            select(LearningAssessmentRevision)
            .where(LearningAssessmentRevision.assessment_id == str(assessment_id))
            .order_by(LearningAssessmentRevision.revision_seq)
        ).all()
        assert len(revisions) == 2
        assert revisions[1].content_json in {
            '{"summary":"Candidate A"}',
            '{"summary":"Candidate B"}',
        }


def _migrated_learning_database(path: Path) -> None:
    _seed_0040(path)
    command.upgrade(_config(path), "0043_learning_evidence")


def test_0045_upgrade_preserves_populated_learning_rows_and_foreign_keys(
    tmp_path: Path,
) -> None:
    path = tmp_path / "learning-populated-0045.sqlite3"
    _migrated_learning_database(path)
    record_id, assessment_id, revision_id = str(uuid4()), str(uuid4()), str(uuid4())
    with sqlite3.connect(path) as db:
        actor, course, conversation = db.execute(
            "SELECT user_id,course_id,id FROM agent_conversations LIMIT 1"
        ).fetchone()
        db.execute("PRAGMA foreign_keys=ON")
        db.execute(
            "INSERT INTO learning_records (id,actor_user_id,course_id,conversation_id,"
            "team_id,team_version_id,origin,chat_visibility,activity_id,record_kind,"
            "client_event_id,payload_json,payload_hash,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                record_id,
                actor,
                course,
                conversation,
                None,
                None,
                "single_agent",
                "private",
                None,
                "answer",
                str(uuid4()),
                '{"answer_text":"retained before attempts migration"}',
                "a" * 64,
                "2026-09-29 00:00:00",
            ),
        )
        db.execute(
            "INSERT INTO learning_assessments "
            "(id,owner_user_id,course_id,created_conversation_id,current_revision_seq,"
            "created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
            (
                assessment_id,
                actor,
                course,
                conversation,
                1,
                "2026-09-29 00:00:00",
                "2026-09-29 00:00:00",
            ),
        )
        db.execute(
            "INSERT INTO learning_assessment_revisions "
            "(id,assessment_id,revision_seq,previous_revision_id,actor_user_id,course_id,"
            "conversation_id,team_id,team_version_id,origin,chat_visibility,activity_id,"
            "content_json,content_hash,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                revision_id,
                assessment_id,
                1,
                None,
                actor,
                course,
                conversation,
                None,
                None,
                "single_agent",
                "private",
                None,
                '{"summary":"retained before attempts migration"}',
                "b" * 64,
                "2026-09-29 00:00:00",
            ),
        )
    command.upgrade(_config(path), "0045_assessment_attempts")
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "0045_assessment_attempts",
        )
        assert db.execute(
            "SELECT payload_json,attempt_id FROM learning_records WHERE id=?", (record_id,)
        ).fetchone() == ('{"answer_text":"retained before attempts migration"}', None)
        assert db.execute(
            "SELECT content_json,revision_source,attempt_id FROM learning_assessment_revisions "
            "WHERE id=?",
            (revision_id,),
        ).fetchone() == (
            '{"summary":"retained before attempts migration"}',
            "user_authored",
            None,
        )
        assert db.execute(
            "SELECT attempt_id FROM learning_assessments WHERE id=?", (assessment_id,)
        ).fetchone() == (None,)
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_0043_downgrade_refuses_saved_raw_evidence_without_changing_database(
    tmp_path: Path,
) -> None:
    path = tmp_path / "learning-populated.sqlite3"
    _migrated_learning_database(path)
    with sqlite3.connect(path) as db:
        actor, course, conversation = db.execute(
            "SELECT user_id,course_id,id FROM agent_conversations LIMIT 1"
        ).fetchone()
        db.execute("PRAGMA foreign_keys=ON")
        db.execute(
            "INSERT INTO learning_records (id,actor_user_id,course_id,conversation_id,"
            "team_id,team_version_id,origin,chat_visibility,activity_id,record_kind,"
            "client_event_id,payload_json,payload_hash,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                str(uuid4()),
                actor,
                course,
                conversation,
                None,
                None,
                "single_agent",
                "private",
                None,
                "answer",
                str(uuid4()),
                '{"answer_text":"preserved"}',
                "a" * 64,
                "2026-09-28 00:00:00",
            ),
        )
    before = _fingerprint(path)
    with pytest.raises(RuntimeError, match="Cannot downgrade saved learning evidence"):
        command.downgrade(_config(path), "0042_team_turn_results")
    assert _fingerprint(path) == before
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "0043_learning_evidence",
        )
        assert db.execute("SELECT count(*) FROM learning_records").fetchone() == (1,)
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_0043_empty_downgrade_head_failure_rolls_back_schema(
    tmp_path: Path,
) -> None:
    path = tmp_path / "learning-head-fault.sqlite3"
    _migrated_learning_database(path)
    before = _fingerprint(path)
    fired = False

    def fail(
        _connection: Any,
        _cursor: Any,
        statement: str,
        _parameters: Any,
        _context: Any,
        _many: bool,
    ) -> None:
        nonlocal fired
        if "UPDATE alembic_version" in statement:
            fired = True
            raise RuntimeError("0043 injected downgrade head failure")

    event.listen(Engine, "before_cursor_execute", fail)
    try:
        with pytest.raises(RuntimeError, match="0043 injected downgrade head failure"):
            command.downgrade(_config(path), "0042_team_turn_results")
    finally:
        event.remove(Engine, "before_cursor_execute", fail)
    assert fired and _fingerprint(path) == before
    command.downgrade(_config(path), "0042_team_turn_results")
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "0042_team_turn_results",
        )
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
