"""Teacher Record lists every attempt whatever happened to its Team, chat or Agents.

Production 2026-10-24: 33 activities pointed at soft-deleted Teams and the
teacher's Record was empty while students still saw their own attempts.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.core.models import GroupMember
from app.modules.learning.attempts import start_or_resume_attempt
from app.modules.learning.models import (
    AssessmentActivity,
    AssessmentAttempt,
    LearningBoundaryEvidence,
)
from app.modules.teams.models import CourseTeamPublication, Team, TeamVersion
from app.modules.workspace.models import Conversation
from app.seed import COURSE_ID, TEACHER_ID
from sqlalchemy import event, select, text

from tests.test_mayaform_assessment_attempts import (
    _answer_current,
    _create_formal_conversation,
    _service_actor,
    attempt_env,  # noqa: F401  (fixture)
)
from tests.test_mayaform_learning_evidence import STUDENT_ID, _context, _login

TEACHER_URL = f"/api/v1/learning/courses/{COURSE_ID}/assessment-attempts"
STUDENT_URL = f"/api/v1/learning/courses/{COURSE_ID}/my-assessment-attempts"

_DROP_ATTEMPT_CONVERSATION_FK = (
    "ALTER TABLE assessment_attempts DROP CONSTRAINT fk_assessment_attempt_conversation"
)


def _attempt(database: Any, settings: Any, client: Any) -> dict[str, str]:
    token, _csrf = _login(client, "bowen")
    with database.session() as db:
        conversation_id, team_id, version_id, publication_id, *_rest = _create_formal_conversation(
            db, prompts=("Q1", "Q2")
        )
        actor = _context(db, settings, token)
        started = start_or_resume_attempt(db, actor, conversation_id, client_event_id=uuid4())
        assert started is not None
        _answer_current(db, actor, conversation_id, "kept answer")
        team = db.get(Team, team_id)
        assert team is not None
        return {
            "attempt": str(started.attempt.id),
            "conversation": conversation_id,
            "team": team_id,
            "version": version_id,
            "publication": publication_id,
            "team_name": team.display_name,
        }


def _teacher_row(client: Any, attempt_id: str) -> dict[str, Any]:
    _login(client, "maya")
    listed = client.get(TEACHER_URL)
    assert listed.status_code == 200, listed.text
    rows = [row for row in listed.json() if row["attempt_id"] == attempt_id]
    assert len(rows) == 1, "the teacher's Record lost the attempt"
    return rows[0]


def _student_sees(client: Any, attempt_id: str) -> bool:
    _login(client, "bowen")
    listed = client.get(STUDENT_URL)
    assert listed.status_code == 200, listed.text
    return attempt_id in {row["attempt_id"] for row in listed.json()}


def test_a_soft_deleted_team_keeps_its_records(attempt_env: Any) -> None:  # noqa: F811
    _app, database, settings, client = attempt_env
    made = _attempt(database, settings, client)
    with database.session() as db:
        team = db.get(Team, made["team"])
        assert team is not None
        team.deleted_at = datetime.now(UTC)
        db.commit()
    row = _teacher_row(client, made["attempt"])
    assert row["team_name"] == made["team_name"]
    assert row["questions"][0]["answers"] == ["kept answer"]
    assert _student_sees(client, made["attempt"])


def test_a_hard_deleted_team_keeps_its_records_under_the_stored_name(
    attempt_env: Any,  # noqa: F811
) -> None:
    from app.modules.real_delete import hard_delete_team

    _app, database, settings, client = attempt_env
    made = _attempt(database, settings, client)
    with database.session() as db:
        team = db.get(Team, made["team"])
        assert team is not None
        hard_delete_team(db, team)
        db.commit()
    with database.session() as db:
        attempt = db.get(AssessmentAttempt, made["attempt"])
        assert attempt is not None and attempt.abandonment_reason == "source_deleted"
    row = _teacher_row(client, made["attempt"])
    assert row["team_name"] == made["team_name"]
    assert row["test_name"] == made["team_name"]
    # Cut off mid-attempt: shown as unfinished, not hidden.
    assert (row["status"], row["phase"]) == ("paused", "paused")
    assert row["questions"][0]["answers"] == ["kept answer"]
    assert _student_sees(client, made["attempt"])


def test_a_new_team_version_keeps_the_old_versions_records(attempt_env: Any) -> None:  # noqa: F811
    _app, database, settings, client = attempt_env
    made = _attempt(database, settings, client)
    with database.session() as db:
        publication = db.get(CourseTeamPublication, made["publication"])
        assert publication is not None
        publication.state = "revoked"
        publication.revoked_at = datetime.now(UTC)
        team = db.get(Team, made["team"])
        old = db.get(TeamVersion, made["version"])
        assert team is not None and old is not None
        db.add(
            TeamVersion(
                **{
                    column.key: getattr(old, column.key)
                    for column in TeamVersion.__table__.columns
                    if column.key not in {"id", "version_seq"}
                },
                id=str(uuid4()),
                version_seq=old.version_seq + 1,
            )
        )
        team.current_version_seq = old.version_seq + 1
        db.commit()
    row = _teacher_row(client, made["attempt"])
    assert row["version_label"] == "V1.0"


def test_a_deleted_chat_and_a_deleted_agent_keep_the_records(attempt_env: Any) -> None:  # noqa: F811
    from app.core.models import Agent
    from app.modules.real_delete import hard_delete_agent, hard_delete_conversation
    from app.modules.teams.models import TeamVersionMember

    _app, database, settings, client = attempt_env
    made = _attempt(database, settings, client)
    with database.session() as db:
        conversation = db.get(Conversation, made["conversation"])
        assert conversation is not None
        hard_delete_conversation(db, conversation, settings.resolved_data_root)
        db.commit()
    assert _teacher_row(client, made["attempt"])["conversation_id"] is None
    with database.session() as db:
        leader = db.scalars(
            select(TeamVersionMember).where(
                TeamVersionMember.team_version_id == made["version"],
                TeamVersionMember.is_leader.is_(True),
            )
        ).first()
        assert leader is not None
        agent = db.get(Agent, leader.agent_id)
        assert agent is not None
        hard_delete_agent(db, agent, settings.resolved_data_root)
        db.commit()
    row = _teacher_row(client, made["attempt"])
    assert row["questions"][0]["answers"] == ["kept answer"]
    assert _student_sees(client, made["attempt"])


def test_a_student_who_left_every_group_keeps_the_record(attempt_env: Any) -> None:  # noqa: F811
    _app, database, settings, client = attempt_env
    made = _attempt(database, settings, client)
    with database.session() as db:
        for membership in db.scalars(
            select(GroupMember).where(GroupMember.user_id == STUDENT_ID)
        ).all():
            db.delete(membership)
        db.commit()
    row = _teacher_row(client, made["attempt"])
    assert (row["group_id"], row["group_name"]) == (None, None)


def test_a_teacher_delete_is_real_and_reaches_the_student(attempt_env: Any) -> None:  # noqa: F811
    from app.modules.learning.models import LearningAssessment, LearningRecord

    _app, database, settings, client = attempt_env
    made = _attempt(database, settings, client)
    _token, csrf = _login(client, "maya")
    deleted = client.delete(f"{TEACHER_URL}/{made['attempt']}", headers={"X-CSRF-Token": csrf})
    assert deleted.status_code == 204, deleted.text
    _login(client, "maya")
    assert made["attempt"] not in client.get(TEACHER_URL).text
    assert not _student_sees(client, made["attempt"])
    with database.session() as db:
        assert db.get(AssessmentAttempt, made["attempt"]) is None
        assert (
            db.scalars(
                select(LearningRecord).where(LearningRecord.attempt_id == made["attempt"])
            ).all()
            == []
        )
        assert (
            db.scalars(
                select(LearningAssessment).where(LearningAssessment.attempt_id == made["attempt"])
            ).all()
            == []
        )
        # The chat is independent of Record.
        assert db.get(Conversation, made["conversation"]) is not None


def test_a_teacher_delete_of_an_answered_attempt_does_not_depend_on_fk_order(
    attempt_env: Any,  # noqa: F811
    monkeypatch: Any,
) -> None:
    """Production 2026-10-24 (PostgreSQL): the purge cleared an answered
    question's answer link before deleting the question, and the CHECK that an
    answered question keeps its answer refused it. The order foreign keys come
    back from the catalog differs by database, so both orders must work.
    """

    from app.modules import purge as purge_module

    original = purge_module._catalog

    def reversed_catalog(engine: Any) -> dict[str, list[Any]]:
        return {name: list(reversed(keys)) for name, keys in original(engine).items()}

    _app, database, settings, client = attempt_env
    made = _attempt(database, settings, client)
    monkeypatch.setattr(purge_module, "_catalog", reversed_catalog)
    _token, csrf = _login(client, "maya")
    deleted = client.delete(f"{TEACHER_URL}/{made['attempt']}", headers={"X-CSRF-Token": csrf})
    assert deleted.status_code == 204, deleted.text
    with database.session() as db:
        assert db.get(AssessmentAttempt, made["attempt"]) is None


def test_teacher_delete_with_assessment_revision_boundary_evidence(
    attempt_env: Any,  # noqa: F811
) -> None:
    """Production 2026-10-27: teacher Record delete purged learning_assessments
    first and nulled learning_boundary_evidence.assessment_revision_id. Rows that
    used an assessment revision as their only source then violated
    ck_learning_boundary_evidence_source (both sources NULL) and the DELETE
    returned 500. Evidence that names a deleted assessment revision must go with
    it.
    """

    import hashlib
    import json

    from app.modules.learning.models import (
        LearningAssessment,
        LearningAssessmentRevision,
        LearningBoundary,
        LearningBoundaryRevision,
    )

    _app, database, settings, client = attempt_env
    made = _attempt(database, settings, client)
    evidence_id = str(uuid4())
    with database.session() as db:
        attempt = db.get(AssessmentAttempt, made["attempt"])
        assert attempt is not None
        activity = db.get(AssessmentActivity, attempt.activity_id)
        assert activity is not None
        now = datetime.now(UTC)
        assessment_id = str(uuid4())
        revision_id = str(uuid4())
        content = json.dumps(
            {"overall_feedback": "eval", "questions": [], "strengths": [], "next_steps": []},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        boundary_id = str(uuid4())
        boundary_revision_id = str(uuid4())
        boundary_json = json.dumps(
            {"summary": "boundary"}, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        db.add_all(
            [
                LearningAssessment(
                    id=assessment_id,
                    owner_user_id=attempt.actor_user_id,
                    course_id=activity.course_id,
                    created_conversation_id=made["conversation"],
                    attempt_id=attempt.id,
                    current_revision_seq=1,
                    created_at=now,
                    updated_at=now,
                ),
                LearningAssessmentRevision(
                    id=revision_id,
                    assessment_id=assessment_id,
                    revision_seq=1,
                    previous_revision_id=None,
                    actor_user_id=attempt.actor_user_id,
                    course_id=activity.course_id,
                    conversation_id=made["conversation"],
                    team_id=activity.team_id,
                    team_version_id=activity.team_version_id,
                    origin="published_course_team",
                    chat_visibility="private",
                    activity_id=activity.id,
                    attempt_id=attempt.id,
                    revision_source="model_evaluation",
                    evaluator_team_member_id=activity.evaluator_team_member_id,
                    evaluator_agent_version_id=activity.evaluator_agent_version_id,
                    editor_team_member_id=None,
                    editor_agent_version_id=None,
                    source_model_call_id=str(uuid4()),
                    source_tool_call_id=f"record-delete-{uuid4()}",
                    content_json=content,
                    content_hash=hashlib.sha256(content.encode()).hexdigest(),
                    created_at=now,
                ),
                LearningBoundary(
                    id=boundary_id,
                    attempt_id=attempt.id,
                    activity_id=activity.id,
                    owner_user_id=attempt.actor_user_id,
                    course_id=activity.course_id,
                    conversation_id=made["conversation"],
                    current_revision_seq=1,
                    created_at=now,
                    updated_at=now,
                ),
                LearningBoundaryRevision(
                    id=boundary_revision_id,
                    boundary_id=boundary_id,
                    attempt_id=attempt.id,
                    revision_seq=1,
                    previous_revision_id=None,
                    actor_user_id=attempt.actor_user_id,
                    summarizer_team_member_id=activity.boundary_team_member_id,
                    summarizer_agent_version_id=activity.boundary_agent_version_id,
                    source_model_call_id=str(uuid4()),
                    source_tool_call_id=f"record-delete-boundary-{uuid4()}",
                    content_json=boundary_json,
                    content_hash=hashlib.sha256(boundary_json.encode()).hexdigest(),
                    created_at=now,
                ),
            ]
        )
        db.flush()
        db.add(
            LearningBoundaryEvidence(
                id=evidence_id,
                boundary_revision_id=boundary_revision_id,
                attempt_id=attempt.id,
                learning_record_id=None,
                assessment_revision_id=revision_id,
                created_at=now,
            )
        )
        db.commit()
    _token, csrf = _login(client, "maya")
    deleted = client.delete(f"{TEACHER_URL}/{made['attempt']}", headers={"X-CSRF-Token": csrf})
    assert deleted.status_code == 204, deleted.text
    with database.session() as db:
        assert db.get(AssessmentAttempt, made["attempt"]) is None
        assert db.get(LearningBoundaryEvidence, evidence_id) is None


def test_the_teacher_list_reads_a_fixed_number_of_queries(attempt_env: Any) -> None:  # noqa: F811
    from app.modules.learning.reports import list_course_assessment_attempts

    _app, database, settings, client = attempt_env
    _attempt(database, settings, client)

    def count_queries() -> int:
        seen = [0]

        def tick(*_args: Any) -> None:
            seen[0] += 1

        event.listen(database.engine, "before_cursor_execute", tick)
        try:
            with database.session() as db:
                teacher = _service_actor(db, settings, TEACHER_ID)
                list_course_assessment_attempts(db, teacher, course_id=COURSE_ID)
        finally:
            event.remove(database.engine, "before_cursor_execute", tick)
        return seen[0]

    one = count_queries()
    with database.session() as db:
        for attempt in db.scalars(select(AssessmentAttempt)).all():
            # Finished attempts need no phase lookup, so only the bulk reads remain.
            attempt.status = "completed"
            attempt.completed_at = datetime.now(UTC)
        db.commit()
    for _ in range(3):
        _attempt(database, settings, client)
    with database.session() as db:
        for attempt in db.scalars(select(AssessmentAttempt)).all():
            attempt.status = "completed"
            attempt.completed_at = attempt.completed_at or datetime.now(UTC)
        db.commit()
    four = count_queries()
    assert four <= one + 2, (one, four)


def test_bulk_answer_sheets_match_the_single_sheet(attempt_env: Any) -> None:  # noqa: F811
    from app.modules.learning.reports import answer_sheets, attempt_answer_sheet

    _app, database, settings, client = attempt_env
    made = [_attempt(database, settings, client) for _ in range(2)]
    with database.session() as db:
        attempts = [db.get(AssessmentAttempt, row["attempt"]) for row in made]
        bulk = answer_sheets(db, [attempt for attempt in attempts if attempt is not None])
        for attempt in attempts:
            assert attempt is not None
            assert bulk[attempt.id] == attempt_answer_sheet(db, attempt)


def test_student_record_tolerates_blank_conversation_id(attempt_env: Any) -> None:  # noqa: F811
    """Blank source_conversation_id must coerce to null, not 500 the list."""

    _app, database, settings, client = attempt_env
    made = _attempt(database, settings, client)
    with database.session() as db:
        # Prod can hold "" from older writers; the live FK blocks inserting that
        # here, so drop it for this fixture database only.
        db.execute(text(_DROP_ATTEMPT_CONVERSATION_FK))
        attempt = db.get(AssessmentAttempt, made["attempt"])
        assert attempt is not None
        attempt.source_conversation_id = ""
        db.commit()
    _login(client, "bowen")
    listed = client.get(STUDENT_URL)
    assert listed.status_code == 200, listed.text
    [row] = [item for item in listed.json() if item["attempt_id"] == made["attempt"]]
    assert row["conversation_id"] is None
    assert row["questions"][0]["answers"] == ["kept answer"]


def test_student_record_keeps_attempts_with_orphaned_chat_fk(
    attempt_env: Any,  # noqa: F811
) -> None:
    """Orphan chat FK must not filter the student list empty (false empty)."""

    _app, database, settings, client = attempt_env
    made = _attempt(database, settings, client)
    orphan = str(uuid4())
    with database.session() as db:
        db.execute(text(_DROP_ATTEMPT_CONVERSATION_FK))
        attempt = db.get(AssessmentAttempt, made["attempt"])
        assert attempt is not None
        attempt.source_conversation_id = orphan
        db.commit()
        assert db.get(Conversation, orphan) is None
    assert _student_sees(client, made["attempt"])
    _login(client, "bowen")
    [row] = [
        item for item in client.get(STUDENT_URL).json() if item["attempt_id"] == made["attempt"]
    ]
    assert row["conversation_id"] == orphan


def test_student_record_lists_answers_with_null_question_version(
    attempt_env: Any,  # noqa: F811
) -> None:
    """Null frozen question_version_id must not 500 my-assessment-attempts."""

    from app.modules.learning.models import AssessmentAttemptQuestion

    _app, database, settings, client = attempt_env
    made = _attempt(database, settings, client)
    with database.session() as db:
        rows = db.scalars(
            select(AssessmentAttemptQuestion).where(
                AssessmentAttemptQuestion.attempt_id == made["attempt"]
            )
        ).all()
        assert rows
        for row in rows:
            row.question_version_id = None
        db.commit()
    _login(client, "bowen")
    listed = client.get(STUDENT_URL)
    assert listed.status_code == 200, listed.text
    [row] = [item for item in listed.json() if item["attempt_id"] == made["attempt"]]
    assert row["questions"][0]["answers"] == ["kept answer"]


def test_student_record_skips_one_broken_row_without_500(
    attempt_env: Any,  # noqa: F811
) -> None:
    """A single invalid row is skipped; siblings still return 200."""

    _app, database, settings, client = attempt_env
    first = _attempt(database, settings, client)
    second = _attempt(database, settings, client)
    with database.session() as db:
        db.execute(text(_DROP_ATTEMPT_CONVERSATION_FK))
        broken = db.get(AssessmentAttempt, second["attempt"])
        assert broken is not None
        # Non-blank junk survives blank→None coerce and fails UUID validation.
        broken.source_conversation_id = "not-a-uuid"
        db.commit()
    _login(client, "bowen")
    listed = client.get(STUDENT_URL)
    assert listed.status_code == 200, listed.text
    ids = {row["attempt_id"] for row in listed.json()}
    assert first["attempt"] in ids
    assert second["attempt"] not in ids
