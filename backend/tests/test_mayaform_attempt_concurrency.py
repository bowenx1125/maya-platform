from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier, Lock
from typing import Any
from uuid import UUID, uuid4

import pytest
from app.core.models import CourseMember, ProviderOperation, User
from app.modules.auth.service import create_rotated_session, get_auth_context
from app.modules.demo_baseline.service import ensure_demo_baseline
from app.modules.knowledge_sets.schemas import SaveKnowledgeMarkdownRequest
from app.modules.knowledge_sets.service import save_brainform_markdown
from app.modules.learning.attempts import (
    _attempt_question_rows,
    apply_assessment_decision,
    get_assessment_runtime_context,
    mark_attempt_question_presented,
    read_attempt_answers,
    start_or_resume_attempt,
)
from app.modules.learning.execution import attempt_has_final_evidence
from app.modules.learning.models import (
    AssessmentActivity,
    AssessmentActivityQuestion,
    AssessmentAttempt,
    AssessmentAttemptEvent,
    LearningRecord,
)
from app.modules.learning.schemas import AssessmentRuntimeDecision
from app.modules.workspace.models import (
    Conversation,
    ConversationParticipant,
    ConversationParticipantSet,
    ConversationSharedSet,
    ConversationTurn,
    TeamTurnResult,
)
from app.modules.workspace.team_runtime import _begin as begin_sqlite_writer
from app.seed import COURSE_ID, TEACHER_ID
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from tests.test_mayaform_assessment_attempts import (
    STUDENT_ID,
    _answer_decision,
    _copy_conversation,
    _create_formal_conversation,
)
from tests.test_mayaform_knowledge_attempt_invalidation import (
    _add_markdown_head,
    _bind_set_to_leader_agent,
    _markdown,
    _seed_prior_final_evidence,
)


def _actor(db: Any, settings: Any, token: str) -> Any:
    actor = get_auth_context(db, settings, token)
    assert actor is not None
    return actor


def _decision(event_id: UUID, question_version_id: UUID, answer: str) -> AssessmentRuntimeDecision:
    return _answer_decision(event_id, question_version_id, answer)


def _clone_formal_conversation(
    db: Any,
    source_id: str,
    *,
    actor_user_id: str,
) -> str:
    clone_id = _copy_conversation(
        db,
        source_id,
        actor_user_id=actor_user_id,
        visibility="private",
    )
    source_participants = db.scalars(
        select(ConversationParticipant)
        .where(ConversationParticipant.conversation_id == source_id)
        .order_by(ConversationParticipant.position)
    ).all()
    participant_ids: dict[str, str] = {}
    for participant in source_participants:
        participant_id = str(uuid4())
        participant_ids[participant.id] = participant_id
        db.add(
            ConversationParticipant(
                id=participant_id,
                conversation_id=clone_id,
                team_version_id=participant.team_version_id,
                team_member_id=participant.team_member_id,
                agent_id=participant.agent_id,
                agent_version_id=participant.agent_version_id,
                snapshot_id=participant.snapshot_id,
                agent_authorization_epoch=participant.agent_authorization_epoch,
                position=participant.position,
                is_leader=participant.is_leader,
                display_name=participant.display_name,
                avatar_config_json=participant.avatar_config_json,
                invoke_grant_id=participant.invoke_grant_id,
            )
        )
    db.flush()
    for source_participant_id, clone_participant_id in participant_ids.items():
        bindings = db.scalars(
            select(ConversationParticipantSet).where(
                ConversationParticipantSet.participant_id == source_participant_id
            )
        ).all()
        for binding in bindings:
            db.add(
                ConversationParticipantSet(
                    participant_id=clone_participant_id,
                    knowledge_set_id=binding.knowledge_set_id,
                    position=binding.position,
                )
            )
    shared_sets = db.scalars(
        select(ConversationSharedSet).where(ConversationSharedSet.conversation_id == source_id)
    ).all()
    for binding in shared_sets:
        db.add(
            ConversationSharedSet(
                conversation_id=clone_id,
                knowledge_set_id=binding.knowledge_set_id,
                position=binding.position,
            )
        )
    db.flush()
    return clone_id


@pytest.fixture
def concurrency_env(app_bundle: Any, client: TestClient) -> tuple[Any, Any, Any, TestClient]:
    app, database, settings = app_bundle
    client.headers["Origin"] = "http://testserver"
    with database.session() as db:
        ensure_demo_baseline(db, settings.resolved_data_root)
    return app, database, settings, client


def test_twenty_independent_students_submit_during_knowledge_update_and_recover(
    concurrency_env: Any,
    app_factory: Any,
) -> None:
    app, database, settings, _primary_client = concurrency_env
    student_ids = [str(uuid4()) for _ in range(20)]
    now = datetime.now(UTC)
    tokens: dict[str, str] = {}
    csrf_tokens: dict[str, str] = {}
    conversations: dict[str, str] = {}

    with database.session() as db:
        for index, user_id in enumerate(student_ids):
            user = User(
                id=user_id,
                username=f"attempt-concurrency-{index}-{user_id[:8]}",
                display_name=f"Concurrency learner {index}",
                avatar=None,
                status="active",
                created_at=now,
            )
            db.add(user)
            db.add(
                CourseMember(
                    course_id=COURSE_ID,
                    user_id=user_id,
                    role="student",
                    created_at=now,
                )
            )
        db.flush()
        raw_teacher_token, _teacher_session, teacher_csrf = create_rotated_session(
            db, db.get(User, TEACHER_ID), settings
        )
        tokens[TEACHER_ID] = raw_teacher_token
        csrf_tokens[TEACHER_ID] = teacher_csrf
        for user_id in student_ids:
            user = db.get(User, user_id)
            assert user is not None
            token, _session, csrf = create_rotated_session(db, user, settings)
            tokens[user_id] = token
            csrf_tokens[user_id] = csrf

        (
            source_conversation_id,
            _team_id,
            _team_version_id,
            _publication_id,
            knowledge_set_id,
            question_pairs,
        ) = _create_formal_conversation(
            db,
            actor_user_id=student_ids[0],
            visibility="private",
        )
        _bind_set_to_leader_agent(db, source_conversation_id, knowledge_set_id)
        _add_markdown_head(
            db,
            set_id=knowledge_set_id,
            markdown=_markdown("Original question"),
            question_version_ids=[version_id for _asset_id, version_id in question_pairs],
        )
        conversations[student_ids[0]] = source_conversation_id
        for user_id in student_ids[1:]:
            conversations[user_id] = _clone_formal_conversation(
                db,
                source_conversation_id,
                actor_user_id=user_id,
            )

    # Every account has a distinct persisted cookie and client jar. Each GET
    # proves that cookie resolves only to the owning learner's private Chat.
    clients: dict[str, TestClient] = {}
    for user_id in student_ids:
        learner_client = TestClient(app)
        learner_client.cookies.set("maya_session", tokens[user_id])
        clients[user_id] = learner_client
        response = learner_client.get(f"/api/v1/conversations/{conversations[user_id]}")
        assert response.status_code == 200, response.text
        assert response.json()["id"] == conversations[user_id]
    cross_chat_read = clients[student_ids[0]].get(
        f"/api/v1/conversations/{conversations[student_ids[1]]}"
    )
    assert cross_chat_read.status_code == 404

    attempt_ids: dict[str, str] = {}
    first_question_version_id: str | None = None
    completed_attempt_id: str | None = None
    completed_revision: int | None = None
    completed_question_ids: tuple[str, ...] = ()

    # Create one terminal historical attempt, then a live attempt for that same
    # learner. A canonical update must leave the terminal generation untouched.
    with database.session() as db:
        actor = _actor(db, settings, tokens[student_ids[0]])
        historical = start_or_resume_attempt(
            db,
            actor,
            conversations[student_ids[0]],
            client_event_id=uuid4(),
        )
        assert historical is not None
        historical_row = db.get(AssessmentAttempt, str(historical.attempt.id))
        assert historical_row is not None
        historical_row.status = "completed"
        historical_row.completed_at = now
        historical_row.revision += 1
        historical_row.updated_at = now
        completed_attempt_id = historical_row.id
        completed_revision = historical_row.revision
        completed_question_ids = tuple(
            row.id for row in _attempt_question_rows(db, historical_row.id)
        )

    for user_id in student_ids:
        with database.session() as db:
            actor = _actor(db, settings, tokens[user_id])
            started = start_or_resume_attempt(
                db,
                actor,
                conversations[user_id],
                client_event_id=uuid4(),
            )
            assert started is not None and started.current_question is not None
            if first_question_version_id is None:
                first_question_version_id = str(started.current_question.question_version_id)
            assert str(started.current_question.question_version_id) == first_question_version_id
            attempt_ids[user_id] = str(started.attempt.id)
            mark_attempt_question_presented(
                db,
                actor,
                conversations[user_id],
                question_version_id=started.current_question.question_version_id,
            )

    assert first_question_version_id is not None
    shared_event_id = uuid4()
    action_specs = [
        (index, shared_event_id if index in {0, 1} else uuid4(), f"answer-{index}")
        for index in range(len(student_ids))
    ]
    duplicate_action = action_specs[0]
    concurrent_actions = action_specs + [duplicate_action]
    start_barrier = Barrier(len(concurrent_actions))
    session_ids: set[int] = set()
    session_lock = Lock()

    def submit_first_question(spec: tuple[int, UUID, str]) -> str:
        index, event_id, answer = spec
        user_id = student_ids[index]
        start_barrier.wait(timeout=20)
        with database.session() as db:
            with session_lock:
                session_ids.add(id(db))
            actor = _actor(db, settings, tokens[user_id])
            begin_sqlite_writer(db)
            result = apply_assessment_decision(
                db,
                actor,
                conversations[user_id],
                user_message=f"My answer is {answer}.",
                decision=_decision(
                    event_id,
                    UUID(first_question_version_id),
                    answer,
                ),
            )
            assert result is not None
            return result.disposition

    with ThreadPoolExecutor(max_workers=len(concurrent_actions)) as pool:
        first_results = list(pool.map(submit_first_question, concurrent_actions))
    assert len(session_ids) == len(concurrent_actions)
    assert all(result in {"recorded", "transitioned"} for result in first_results)

    with database.engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA journal_mode").scalar_one().casefold() == "wal"
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
        assert connection.exec_driver_sql("PRAGMA busy_timeout").scalar_one() >= 5_000

    with database.session() as db:
        answers = db.scalars(
            select(LearningRecord)
            .where(
                LearningRecord.attempt_id.in_(list(attempt_ids.values())),
                LearningRecord.record_kind == "answer",
            )
            .order_by(LearningRecord.created_at, LearningRecord.id)
        ).all()
        assert len(answers) == 20
        by_user = {row.actor_user_id: row for row in answers}
        assert set(by_user) == set(student_ids)
        assert all(by_user[user_id].attempt_id == attempt_ids[user_id] for user_id in student_ids)
        assert all(
            by_user[user_id].conversation_id == conversations[user_id] for user_id in student_ids
        )
        same_uuid_events = db.scalars(
            select(AssessmentAttemptEvent).where(
                AssessmentAttemptEvent.activity_id
                == db.get(AssessmentAttempt, attempt_ids[student_ids[0]]).activity_id,
                AssessmentAttemptEvent.client_event_id == str(shared_event_id),
                AssessmentAttemptEvent.event_kind == "answer",
            )
        ).all()
        assert {event.actor_user_id for event in same_uuid_events} == {
            student_ids[0],
            student_ids[1],
        }
        assert len(same_uuid_events) == 2
        first_actor_duplicate = [
            event for event in same_uuid_events if event.actor_user_id == student_ids[0]
        ]
        assert len(first_actor_duplicate) == 1
        assert first_actor_duplicate[0].learning_record_id == by_user[student_ids[0]].id
        first_activity = db.get(
            AssessmentActivity,
            str(db.get(AssessmentAttempt, attempt_ids[student_ids[0]]).activity_id),
        )
        assert first_activity is not None and first_activity.question_selection_revision == 1
        second_question_version_id = str(question_pairs[1][1])
        actor_zero = _actor(db, settings, tokens[student_ids[0]])
        second_context = get_assessment_runtime_context(
            db, actor_zero, conversations[student_ids[0]]
        )
        assert second_context is not None and second_context.current_question is not None
        assert (
            str(second_context.current_question.question_version_id) == second_question_version_id
        )
        mark_attempt_question_presented(
            db,
            actor_zero,
            conversations[student_ids[0]],
            question_version_id=second_context.current_question.question_version_id,
        )
        old_activity_questions = db.scalars(
            select(AssessmentActivityQuestion).where(
                AssessmentActivityQuestion.activity_id == first_activity.id,
                AssessmentActivityQuestion.selection_revision == 1,
            )
        ).all()
        assert len(old_activity_questions) == 2
        provider_count_before_update = db.scalar(select(func.count(ProviderOperation.id))) or 0
        historical_row = db.get(AssessmentAttempt, completed_attempt_id)
        assert historical_row is not None

    race_barrier = Barrier(2)

    def race_student_answer() -> str:
        race_barrier.wait(timeout=10)
        with database.session() as db:
            actor = _actor(db, settings, tokens[student_ids[0]])
            begin_sqlite_writer(db)
            result = apply_assessment_decision(
                db,
                actor,
                conversations[student_ids[0]],
                user_message="My answer is old-second-answer for the second Question.",
                decision=_decision(
                    uuid4(),
                    UUID(second_question_version_id),
                    "old-second-answer",
                ),
            )
            if result is None:
                return "removed"
            return result.disposition

    def race_teacher_save() -> None:
        race_barrier.wait(timeout=10)
        with database.session() as db:
            teacher = _actor(db, settings, tokens[TEACHER_ID])
            save_brainform_markdown(
                db,
                teacher,
                knowledge_set_id,
                SaveKnowledgeMarkdownRequest(
                    expected_version_seq=1,
                    markdown=_markdown("Updated question"),
                ),
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        answer_future = pool.submit(race_student_answer)
        save_future = pool.submit(race_teacher_save)
        raced_answer_disposition = answer_future.result(timeout=20)
        save_future.result(timeout=20)
    assert raced_answer_disposition in {"recorded", "redirected", "removed"}

    with database.session() as db:
        activity = db.get(AssessmentActivity, first_activity.id)
        assert activity is not None and activity.question_selection_revision == 2
        for user_id in student_ids:
            assert db.get(AssessmentAttempt, attempt_ids[user_id]) is None
            assert (
                read_attempt_answers(
                    db,
                    _actor(db, settings, tokens[user_id]),
                    conversations[user_id],
                )
                == []
            )
            conversation = db.get(Conversation, conversations[user_id])
            assert conversation is not None and conversation.active_request_id is None
            assert (
                db.scalar(
                    select(func.count(ConversationTurn.id)).where(
                        ConversationTurn.conversation_id == conversation.id,
                        ConversationTurn.state.in_(("pending", "paused")),
                    )
                )
                == 0
            )
            assert (
                db.scalar(
                    select(func.count(TeamTurnResult.id))
                    .join(ConversationTurn, ConversationTurn.id == TeamTurnResult.turn_id)
                    .where(
                        TeamTurnResult.conversation_id == conversation.id,
                        TeamTurnResult.state.in_(("pending", "running")),
                    )
                )
                == 0
            )
            notice = db.scalar(
                select(ConversationTurn).where(
                    ConversationTurn.conversation_id == conversation.id,
                    ConversationTurn.user_text == "",
                )
            )
            assert notice is not None and notice.state == "ready"
        historical_row = db.get(AssessmentAttempt, completed_attempt_id)
        assert historical_row is not None
        assert historical_row.status == "completed"
        assert historical_row.question_selection_revision == 1
        assert historical_row.revision == completed_revision
        assert tuple(row.id for row in _attempt_question_rows(db, historical_row.id)) == (
            completed_question_ids
        )
        assert (db.scalar(select(func.count(ProviderOperation.id))) or 0) == (
            provider_count_before_update
        )
        old_revision = db.get(Conversation, conversations[student_ids[0]]).revision - 1

    stale_response = clients[student_ids[0]].post(
        f"/api/v1/conversations/{conversations[student_ids[0]]}/messages",
        headers={
            "Origin": "http://testserver",
            "X-CSRF-Token": csrf_tokens[student_ids[0]],
            "Idempotency-Key": f"stale-after-knowledge-update-{uuid4()}",
        },
        json={
            "request_id": str(uuid4()),
            "expected_revision": old_revision,
            "message": "An answer to the old question sent before seeing the notice.",
        },
    )
    assert stale_response.status_code == 409, stale_response.text
    with database.session() as db:
        assert (db.scalar(select(func.count(ProviderOperation.id))) or 0) == (
            provider_count_before_update
        )
        current_attempt = db.get(AssessmentAttempt, attempt_ids[student_ids[0]])
        assert current_attempt is None
        assert (
            read_attempt_answers(
                db,
                _actor(db, settings, tokens[student_ids[0]]),
                conversations[student_ids[0]],
            )
            == []
        )

    # Rebuild the application and its SQLAlchemy engine over the same SQLite
    # file. The durable notice and current Question survive, and the learner
    # can continue with one new answer using their own persisted cookie.
    restarted_app, restarted_database, restarted_settings = app_factory()
    with TestClient(restarted_app) as restarted_client:
        restarted_client.cookies.set("maya_session", tokens[student_ids[0]])
        restored = restarted_client.get(f"/api/v1/conversations/{conversations[student_ids[0]]}")
        assert restored.status_code == 200, restored.text
        assert "老师已更改当前回合的 Knowledge，请重新答题。" in restored.text
        with restarted_database.session() as db:
            begin_sqlite_writer(db)
            actor = _actor(db, restarted_settings, tokens[student_ids[0]])
            restarted = start_or_resume_attempt(
                db,
                actor,
                conversations[student_ids[0]],
                client_event_id=uuid4(),
            )
            assert restarted is not None
            context = get_assessment_runtime_context(
                db,
                actor,
                conversations[student_ids[0]],
            )
            assert context is not None and context.current_question is not None
            assert context.current_question.prompt == "Updated question one"
            shown = mark_attempt_question_presented(
                db,
                actor,
                conversations[student_ids[0]],
                question_version_id=context.current_question.question_version_id,
            )
            assert shown.current_question is not None
            resumed_answer = apply_assessment_decision(
                db,
                actor,
                conversations[student_ids[0]],
                user_message="My new-after-restart answer follows the saved notice.",
                decision=_decision(
                    uuid4(),
                    shown.current_question.question_version_id,
                    "new-after-restart",
                ),
            )
            assert resumed_answer is not None and resumed_answer.disposition == "recorded"

    for learner_client in clients.values():
        learner_client.close()


def test_completion_and_canonical_update_race_has_one_durable_winner(
    concurrency_env: Any,
) -> None:
    _app, database, settings, _client = concurrency_env
    with database.session() as db:
        student_token, _student_session, _student_csrf = create_rotated_session(
            db, db.get(User, STUDENT_ID), settings
        )
        teacher_token, _teacher_session, _teacher_csrf = create_rotated_session(
            db, db.get(User, TEACHER_ID), settings
        )
        (
            conversation_id,
            _team_id,
            _team_version_id,
            _publication_id,
            knowledge_set_id,
            question_pairs,
        ) = _create_formal_conversation(db, visibility="private")
        _bind_set_to_leader_agent(db, conversation_id, knowledge_set_id)
        _add_markdown_head(
            db,
            set_id=knowledge_set_id,
            markdown=_markdown("Question"),
            question_version_ids=[version_id for _asset_id, version_id in question_pairs],
        )
        learner = _actor(db, settings, student_token)
        started = start_or_resume_attempt(db, learner, conversation_id, client_event_id=uuid4())
        assert started is not None and started.current_question is not None
        current = started.current_question
        for answer in ("first-race-answer", "second-race-answer"):
            shown = mark_attempt_question_presented(
                db,
                learner,
                conversation_id,
                question_version_id=current.question_version_id,
            )
            assert shown.current_question is not None
            result = apply_assessment_decision(
                db,
                learner,
                conversation_id,
                user_message=f"My answer is {answer}.",
                decision=_decision(uuid4(), shown.current_question.question_version_id, answer),
            )
            assert result is not None and result.disposition == "recorded"
            if result.context.current_question is None:
                break
            current = result.context.current_question
        attempt = db.get(AssessmentAttempt, str(started.attempt.id))
        activity = db.get(AssessmentActivity, str(started.attempt.activity_id))
        conversation = db.get(Conversation, conversation_id)
        assert attempt is not None and activity is not None and conversation is not None
        assert len(read_attempt_answers(db, learner, conversation_id)) == 2
        _seed_prior_final_evidence(
            db,
            attempt=attempt,
            activity=activity,
            conversation=conversation,
        )
        provider_count_before = db.scalar(select(func.count(ProviderOperation.id))) or 0

    race_barrier = Barrier(2)

    def complete_attempt() -> str:
        race_barrier.wait(timeout=10)
        with database.session() as db:
            begin_sqlite_writer(db)
            learner = _actor(db, settings, student_token)
            result = apply_assessment_decision(
                db,
                learner,
                conversation_id,
                user_message="Complete the current assessment.",
                decision=AssessmentRuntimeDecision(
                    client_event_id=uuid4(),
                    classification="complete_request",
                ),
            )
            if result is None:
                return None
            return result.disposition

    def save_new_knowledge() -> None:
        race_barrier.wait(timeout=10)
        with database.session() as db:
            teacher = _actor(db, settings, teacher_token)
            save_brainform_markdown(
                db,
                teacher,
                knowledge_set_id,
                SaveKnowledgeMarkdownRequest(
                    expected_version_seq=1,
                    markdown=_markdown("Updated question"),
                ),
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        complete_future = pool.submit(complete_attempt)
        save_future = pool.submit(save_new_knowledge)
        completion_disposition = complete_future.result(timeout=20)
        save_future.result(timeout=20)
    assert completion_disposition in {"transitioned", "redirected", None}

    with database.session() as db:
        attempt = db.get(AssessmentAttempt, str(started.attempt.id))
        activity = db.get(AssessmentActivity, str(started.attempt.activity_id))
        conversation = db.get(Conversation, conversation_id)
        assert activity is not None and conversation is not None
        if attempt is not None and attempt.status == "completed":
            assert attempt.completed_at is not None
            assert attempt.question_selection_revision == 1
            assert attempt_has_final_evidence(db, attempt)
            assert _attempt_question_rows(db, attempt.id)[-1].status == "resolved"
            assert (
                db.scalar(
                    select(func.count(ConversationTurn.id)).where(
                        ConversationTurn.conversation_id == conversation_id,
                        ConversationTurn.user_text == "",
                    )
                )
                == 0
            )
        elif attempt is not None:
            raise AssertionError(f"unfinished attempt remained {attempt.status}")
        else:
            assert (
                db.scalar(
                    select(func.count(ConversationTurn.id)).where(
                        ConversationTurn.conversation_id == conversation_id,
                        ConversationTurn.user_text == "",
                        ConversationTurn.state == "ready",
                    )
                )
                == 1
            )
        assert (db.scalar(select(func.count(ProviderOperation.id))) or 0) == provider_count_before
