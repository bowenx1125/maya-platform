from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from app.core.errors import PlatformError
from app.core.models import ProviderOperation
from app.modules.demo_baseline.service import ensure_demo_baseline
from app.modules.knowledge_sets.models import (
    AgentKnowledgeSet,
    KnowledgeSet,
    KnowledgeSetMarkdownVersion,
)
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
from app.modules.learning.execution import (
    _scope_answers,
    attempt_has_final_evidence,
    read_own_formal_attempt,
    write_formal_assessment,
)
from app.modules.learning.models import (
    AssessmentActivity,
    AssessmentAttempt,
    AssessmentAttemptEvent,
    LearningAssessment,
    LearningAssessmentRevision,
    LearningBoundary,
    LearningBoundaryEvidence,
    LearningBoundaryRevision,
    LearningRecord,
)
from app.modules.workspace.models import (
    Conversation,
    ConversationParticipant,
    ConversationTurn,
    TeamProviderCall,
    TeamTurnResult,
)
from app.modules.workspace.team_runtime import _current_run, team_history
from app.seed import TEACHER_ID
from sqlalchemy import func, select

from tests.test_mayaform_assessment_attempts import (
    STUDENT_ID,
    _accepted_tool_identity,
    _answer_decision,
    _begin_pending_executor_turn,
    _create_formal_conversation,
    _service_actor,
)
from tests.test_mayaform_learning_evidence import _login
from tests.test_team_provider_stage import _dispatch


@pytest.fixture
def attempt_env(app_bundle: Any, client: Any) -> tuple[Any, Any, Any, Any]:
    app, database, settings = app_bundle
    client.headers["Origin"] = "http://testserver"
    with database.session() as db:
        ensure_demo_baseline(db, settings.resolved_data_root)
    return app, database, settings, client


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _markdown(prompt_prefix: str) -> str:
    return (
        "# Current Knowledge\n\n"
        "## Questions\n\n"
        "### Question 1\n\n"
        f"{prompt_prefix} one\n\n"
        "#### Rubric\n\n"
        "- **Reasoning** (2): Explain the connection.\n\n"
        "Total: 2 points\n\n"
        "#### Reference answer\n\n"
        "Private teacher answer one.\n\n"
        "### Question 2\n\n"
        f"{prompt_prefix} two\n\n"
        "#### Rubric\n\n"
        "- **Reasoning** (2): Explain the result.\n\n"
        "Total: 2 points\n\n"
        "#### Reference answer\n\n"
        "Private teacher answer two.\n"
    )


def _add_markdown_head(
    db: Any,
    *,
    set_id: str,
    markdown: str,
    question_version_ids: list[str],
) -> None:
    set_row = db.get(KnowledgeSet, set_id)
    assert set_row is not None
    set_row.current_markdown_version_seq = 1
    set_row.content_revision += 1
    db.add(
        KnowledgeSetMarkdownVersion(
            id=str(uuid4()),
            knowledge_set_id=set_id,
            version_seq=1,
            markdown=markdown,
            student_projection_markdown="# Current Knowledge\n\nPublic student notes.\n",
            asset_version_ids_json=json.dumps(
                question_version_ids, ensure_ascii=False, separators=(",", ":")
            ),
            content_hash=_digest(markdown),
            origin="manual",
            generation_run_id=None,
            generation_intent_seq=None,
            source_manifest_hash=None,
            created_by_user_id=TEACHER_ID,
            generator_agent_version_id=None,
            created_at=datetime.now(UTC),
        )
    )
    db.flush()


def _bind_set_to_leader_agent(db: Any, conversation_id: str, set_id: str) -> None:
    leader = db.scalar(
        select(ConversationParticipant).where(
            ConversationParticipant.conversation_id == conversation_id,
            ConversationParticipant.is_leader.is_(True),
        )
    )
    assert leader is not None
    db.add(
        AgentKnowledgeSet(
            agent_id=leader.agent_id,
            knowledge_set_id=set_id,
            order_index=0,
            created_by_user_id=TEACHER_ID,
            created_at=datetime.now(UTC),
        )
    )
    db.flush()


def _seed_prior_final_evidence(
    db: Any,
    *,
    attempt: AssessmentAttempt,
    activity: AssessmentActivity,
    conversation: Conversation,
) -> tuple[set[str], str]:
    effective, evidence_ids = _scope_answers(db, attempt, _attempt_question_rows(db, attempt.id))
    assert effective and evidence_ids
    assessment_id = str(uuid4())
    assessment = LearningAssessment(
        id=assessment_id,
        owner_user_id=attempt.actor_user_id,
        course_id=activity.course_id,
        created_conversation_id=conversation.id,
        attempt_id=attempt.id,
        current_revision_seq=1,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    content_json = json.dumps(
        {"overall_feedback": "Old generation evaluation", "questions": []},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    assessment_revision_id = str(uuid4())
    assessment_revision = LearningAssessmentRevision(
        id=assessment_revision_id,
        assessment_id=assessment_id,
        revision_seq=1,
        previous_revision_id=None,
        actor_user_id=attempt.actor_user_id,
        course_id=activity.course_id,
        conversation_id=conversation.id,
        team_id=activity.team_id,
        team_version_id=activity.team_version_id,
        origin="published_course_team",
        chat_visibility=conversation.chat_visibility,
        activity_id=activity.id,
        attempt_id=attempt.id,
        revision_source="model_evaluation",
        evaluator_team_member_id=activity.evaluator_team_member_id,
        evaluator_agent_version_id=activity.evaluator_agent_version_id,
        editor_team_member_id=None,
        editor_agent_version_id=None,
        source_model_call_id=str(uuid4()),
        source_tool_call_id=f"stale-assessment-{uuid4()}",
        content_json=content_json,
        content_hash=_digest(content_json),
        created_at=datetime.now(UTC),
    )
    boundary_id = str(uuid4())
    boundary = LearningBoundary(
        id=boundary_id,
        attempt_id=attempt.id,
        activity_id=activity.id,
        owner_user_id=attempt.actor_user_id,
        course_id=activity.course_id,
        conversation_id=conversation.id,
        current_revision_seq=1,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    boundary_revision_id = str(uuid4())
    boundary_json = json.dumps(
        {
            "summary": "Old generation boundary",
            "strengths": [],
            "areas_to_explore": [],
            "next_step": "Retry.",
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    boundary_revision = LearningBoundaryRevision(
        id=boundary_revision_id,
        boundary_id=boundary_id,
        attempt_id=attempt.id,
        revision_seq=1,
        previous_revision_id=None,
        actor_user_id=attempt.actor_user_id,
        summarizer_team_member_id=activity.boundary_team_member_id,
        summarizer_agent_version_id=activity.boundary_agent_version_id,
        source_model_call_id=str(uuid4()),
        source_tool_call_id=f"stale-boundary-{uuid4()}",
        content_json=boundary_json,
        content_hash=_digest(boundary_json),
        created_at=datetime.now(UTC),
    )
    db.add_all([assessment, assessment_revision, boundary, boundary_revision])
    db.flush()
    for record_id in evidence_ids:
        db.add(
            LearningBoundaryEvidence(
                id=str(uuid4()),
                boundary_revision_id=boundary_revision_id,
                attempt_id=attempt.id,
                learning_record_id=record_id,
                assessment_revision_id=None,
                created_at=datetime.now(UTC),
            )
        )
    db.add(
        LearningBoundaryEvidence(
            id=str(uuid4()),
            boundary_revision_id=boundary_revision_id,
            attempt_id=attempt.id,
            learning_record_id=None,
            assessment_revision_id=assessment_revision_id,
            created_at=datetime.now(UTC),
        )
    )
    db.flush()
    assert attempt_has_final_evidence(db, attempt)
    return set(evidence_ids), boundary_revision_id


def test_teacher_canonical_save_invalidates_current_evidence_and_fences_old_team_run(
    attempt_env: Any,
    app_bundle: Any,
) -> None:
    _app, database, _settings, client = attempt_env
    _template_database, _repository, template_operation_id = _dispatch(client, app_bundle)
    with database.session() as db:
        template_stage = db.scalar(
            select(TeamProviderCall).where(TeamProviderCall.operation_id == template_operation_id)
        )
        assert template_stage is not None
        template_stage_id = template_stage.id
    with database.session() as db:
        (
            conversation_id,
            _team_id,
            _team_version_id,
            _publication_id,
            set_id,
            questions,
        ) = _create_formal_conversation(db, visibility="public")
        _bind_set_to_leader_agent(db, conversation_id, set_id)
        _add_markdown_head(
            db,
            set_id=set_id,
            markdown=_markdown("Question"),
            question_version_ids=[version_id for _asset_id, version_id in questions],
        )
        learner = _service_actor(db, _settings, STUDENT_ID)
        started = start_or_resume_attempt(db, learner, conversation_id, client_event_id=uuid4())
        assert started is not None and started.current_question is not None
        activity = db.get(AssessmentActivity, str(started.attempt.activity_id))
        assert activity is not None
        evaluator = db.scalar(
            select(ConversationParticipant).where(
                ConversationParticipant.conversation_id == conversation_id,
                ConversationParticipant.team_member_id == activity.evaluator_team_member_id,
            )
        )
        assert evaluator is not None
        evaluator_execution = _begin_pending_executor_turn(
            db,
            conversation_id=conversation_id,
            participant_id=evaluator.id,
            position=0,
        )
        evaluator_turn = db.get(ConversationTurn, evaluator_execution[0])
        assert evaluator_turn is not None
        evaluator_turn.routing_json = json.dumps(
            {"mode": "selected", "participant_ids": [evaluator.id]},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        evaluator_turn.request_hash = _digest("accepted pending evaluator request")
        evaluator_turn.claim_token = str(uuid4())
        stale_evaluator_identity = _accepted_tool_identity(
            db,
            template_stage_id=template_stage_id,
            conversation_id=conversation_id,
            participant_id=evaluator.id,
            position=0,
            tool_name="edit_assessment",
            execution=evaluator_execution,
        )
        old_question_version_id = started.current_question.question_version_id
        mark_attempt_question_presented(
            db,
            learner,
            conversation_id,
            question_version_id=old_question_version_id,
        )
        first = apply_assessment_decision(
            db,
            learner,
            conversation_id,
            user_message="OLD_ANSWER_ONE",
            decision=_answer_decision(uuid4(), old_question_version_id, "OLD_ANSWER_ONE"),
        )
        assert first is not None and first.context.current_question is not None
        old_second_version_id = first.context.current_question.question_version_id
        mark_attempt_question_presented(
            db,
            learner,
            conversation_id,
            question_version_id=old_second_version_id,
        )
        second = apply_assessment_decision(
            db,
            learner,
            conversation_id,
            user_message="OLD_ANSWER_TWO",
            decision=_answer_decision(uuid4(), old_second_version_id, "OLD_ANSWER_TWO"),
        )
        assert second is not None and second.context.progress.resolved_count == 2
        attempt = db.get(AssessmentAttempt, str(started.attempt.id))
        activity = db.get(AssessmentActivity, str(started.attempt.activity_id))
        conversation = db.get(Conversation, conversation_id)
        assert attempt is not None and activity is not None and conversation is not None
        old_answer_ids, old_boundary_revision_id = _seed_prior_final_evidence(
            db,
            attempt=attempt,
            activity=activity,
            conversation=conversation,
        )
        leader = db.scalar(
            select(ConversationParticipant).where(
                ConversationParticipant.conversation_id == conversation_id,
                ConversationParticipant.is_leader.is_(True),
            )
        )
        assert leader is not None
        old_chat_turn_id, old_claim_token = str(uuid4()), str(uuid4())
        now = datetime.now(UTC)
        old_history_turn = ConversationTurn(
            id=str(uuid4()),
            conversation_id=conversation_id,
            position=1,
            user_text="OLD_ANSWER_ONE OLD_ANSWER_TWO",
            assistant_text=None,
            sources_json="[]",
            mode="mock",
            state="ready",
            safe_error_code=None,
            routing_json=None,
            request_hash=None,
            claim_token=None,
            created_at=now,
        )
        db.add(old_history_turn)
        db.flush()
        db.add(
            TeamTurnResult(
                id=str(uuid4()),
                turn_id=old_history_turn.id,
                conversation_id=conversation_id,
                participant_id=leader.id,
                ordinal=0,
                state="ready",
                assistant_text="Please continue.",
                sources_json="[]",
                safe_error_code=None,
                created_at=now,
                completed_at=now,
            )
        )
        old_chat_turn = ConversationTurn(
            id=old_chat_turn_id,
            conversation_id=conversation_id,
            position=2,
            user_text="Continue with stale Knowledge.",
            assistant_text=None,
            sources_json="[]",
            mode="mock",
            state="pending",
            safe_error_code=None,
            routing_json=json.dumps({"mode": "auto", "participant_ids": []}),
            request_hash=_digest("old pending chat turn"),
            claim_token=old_claim_token,
            created_at=now,
        )
        db.add(old_chat_turn)
        db.flush()
        db.add(
            TeamTurnResult(
                id=str(uuid4()),
                turn_id=old_chat_turn_id,
                conversation_id=conversation_id,
                participant_id=leader.id,
                ordinal=0,
                state="running",
                assistant_text=None,
                sources_json="[]",
                safe_error_code=None,
                created_at=now,
                completed_at=None,
            )
        )
        conversation.active_request_id = old_chat_turn_id
        conversation.revision = 2
        db.flush()
        assert attempt_has_final_evidence(db, attempt)

    with database.session() as db:
        teacher = _service_actor(db, _settings, TEACHER_ID)
    with database.session() as db:
        save_brainform_markdown(
            db,
            teacher,
            set_id,
            SaveKnowledgeMarkdownRequest(
                expected_version_seq=1,
                markdown=_markdown("Updated question"),
            ),
        )

    with database.session() as db:
        attempt = db.get(AssessmentAttempt, str(started.attempt.id))
        activity = db.get(AssessmentActivity, str(started.attempt.activity_id))
        conversation = db.get(Conversation, conversation_id)
        assert attempt is not None and activity is not None and conversation is not None
        assert attempt.status == "in_progress"
        assert attempt.question_selection_revision == 2
        current_questions = _attempt_question_rows(db, attempt.id)
        assert len(current_questions) == 2
        assert all(question.status == "not_presented" for question in current_questions)
        assert all(question.question_version_id is None for question in current_questions)
        assert all(question.activity_question_id for question in current_questions)
        context = get_assessment_runtime_context(db, learner, conversation_id)
        assert context is not None and context.current_question is not None
        assert context.current_question.prompt == "Updated question one"
        assert context.current_question.question_version_id != old_question_version_id
        assert read_attempt_answers(db, learner, conversation_id) == []
        projection = read_own_formal_attempt(
            db,
            learner,
            conversation_id,
            attempt_id=attempt.id,
        )
        assert projection["answers"] == []
        assert not attempt_has_final_evidence(db, attempt)
        current_question_ids = {question.id for question in current_questions}
        old_answer_events = db.scalars(
            select(AssessmentAttemptEvent).where(
                AssessmentAttemptEvent.learning_record_id.in_(old_answer_ids)
            )
        ).all()
        assert old_answer_events
        assert all(event.question_id not in current_question_ids for event in old_answer_events)
        old_evidence = db.scalars(
            select(LearningBoundaryEvidence).where(
                LearningBoundaryEvidence.boundary_revision_id == old_boundary_revision_id
            )
        ).all()
        assert old_answer_ids.issubset(
            {row.learning_record_id for row in old_evidence if row.learning_record_id}
        )
        saved_answer_count = db.scalar(
            select(func.count(LearningRecord.id)).where(
                LearningRecord.attempt_id == attempt.id,
                LearningRecord.record_kind == "answer",
            )
        )
        rejected_old_answer = apply_assessment_decision(
            db,
            learner,
            conversation_id,
            user_message="An answer to the old Question.",
            decision=_answer_decision(
                uuid4(), UUID(str(old_question_version_id)), "old Question answer"
            ),
        )
        assert rejected_old_answer is not None
        assert rejected_old_answer.disposition == "redirected"
        assert (
            db.scalar(
                select(func.count(LearningRecord.id)).where(
                    LearningRecord.attempt_id == attempt.id,
                    LearningRecord.record_kind == "answer",
                )
            )
            == saved_answer_count
        )

        stale_turn = db.get(ConversationTurn, old_chat_turn_id)
        assert stale_turn is not None and stale_turn.state == "failed"
        assert stale_turn.claim_token != old_claim_token
        assert conversation.active_request_id is None
        assert _current_run(db, old_chat_turn_id, old_claim_token) is None
        stale_evaluator_turn = db.get(ConversationTurn, evaluator_execution[0])
        stale_evaluator_result = db.get(TeamTurnResult, evaluator_execution[1])
        assert stale_evaluator_turn is not None and stale_evaluator_turn.state == "failed"
        assert stale_evaluator_result is not None and stale_evaluator_result.state == "failed"
        revisions_before_stale_write = db.scalar(
            select(func.count(LearningAssessmentRevision.id)).where(
                LearningAssessmentRevision.attempt_id == str(started.attempt.id)
            )
        )
        with pytest.raises(PlatformError) as stale_evaluator_write:
            write_formal_assessment(
                db,
                learner,
                stale_evaluator_identity,
                {
                    "overall_feedback": "A stale evaluator cannot save this result.",
                    "questions": [
                        {"question_ordinal": 0, "feedback": "Must be fenced."},
                        {"question_ordinal": 1, "feedback": "Must be fenced."},
                    ],
                },
            )
        assert stale_evaluator_write.value.code == "assessment_execution_unverified"
        assert (
            db.scalar(
                select(func.count(LearningAssessmentRevision.id)).where(
                    LearningAssessmentRevision.attempt_id == str(started.attempt.id)
                )
            )
            == revisions_before_stale_write
        )
        assert not any(
            "OLD_ANSWER" in item["content"] for item in team_history(db, conversation_id, 4)
        )
        assert any(
            "老师已更改当前回合的 Knowledge" in item["content"]
            for item in team_history(db, conversation_id, 4)
        )
        assert (
            db.scalar(
                select(func.count(ConversationTurn.id)).where(
                    ConversationTurn.conversation_id == conversation_id,
                    ConversationTurn.user_text == "",
                )
            )
            == 1
        )

    _, csrf = _login(client, "bowen")
    with database.session() as db:
        before_provider_operations = db.scalar(select(func.count(ProviderOperation.id)))
        before_answers = db.scalar(
            select(func.count(LearningRecord.id)).where(
                LearningRecord.attempt_id == str(started.attempt.id),
                LearningRecord.record_kind == "answer",
            )
        )
        current_revision = db.get(Conversation, conversation_id).revision
    stale_send = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers={"X-CSRF-Token": csrf, "Idempotency-Key": f"old-selection-{uuid4()}"},
        json={
            "request_id": str(uuid4()),
            "expected_revision": current_revision - 1,
            "message": "OLD_ANSWER before seeing the new Question",
        },
    )
    assert stale_send.status_code == 409, stale_send.text
    with database.session() as db:
        assert db.scalar(select(func.count(ProviderOperation.id))) == before_provider_operations
        assert (
            db.scalar(
                select(func.count(LearningRecord.id)).where(
                    LearningRecord.attempt_id == str(started.attempt.id),
                    LearningRecord.record_kind == "answer",
                )
            )
            == before_answers
        )
    response = client.get(f"/api/v1/conversations/{conversation_id}")
    assert response.status_code == 200, response.text
    assert "老师已更改当前回合的 Knowledge，请重新答题。" in response.text
    with database.session() as db:
        context = get_assessment_runtime_context(db, learner, conversation_id)
        assert context is not None and context.current_question is not None
        assert context.current_question.prompt == "Updated question one"
        presented = mark_attempt_question_presented(
            db,
            learner,
            conversation_id,
            question_version_id=context.current_question.question_version_id,
        )
        assert presented.current_question is not None
        accepted_new_answer = apply_assessment_decision(
            db,
            learner,
            conversation_id,
            user_message="NEW_ANSWER_ONE",
            decision=_answer_decision(
                uuid4(), context.current_question.question_version_id, "NEW_ANSWER_ONE"
            ),
        )
        assert accepted_new_answer is not None
        assert accepted_new_answer.disposition == "recorded"


def test_empty_current_question_selection_keeps_paused_attempt_open(
    attempt_env: Any,
) -> None:
    _app, database, settings, _client = attempt_env
    with database.session() as db:
        conversation_id, _team_id, _version_id, _publication_id, set_id, questions = (
            _create_formal_conversation(db, visibility="private")
        )
        _bind_set_to_leader_agent(db, conversation_id, set_id)
        _add_markdown_head(
            db,
            set_id=set_id,
            markdown=_markdown("Question"),
            question_version_ids=[version_id for _asset_id, version_id in questions],
        )
        student = _service_actor(db, settings, STUDENT_ID)
        started = start_or_resume_attempt(db, student, conversation_id, client_event_id=uuid4())
        assert started is not None
        attempt = db.get(AssessmentAttempt, str(started.attempt.id))
        assert attempt is not None
        attempt.status = "paused"

    with database.session() as db:
        teacher = _service_actor(db, settings, TEACHER_ID)
    with database.session() as db:
        save_brainform_markdown(
            db,
            teacher,
            set_id,
            SaveKnowledgeMarkdownRequest(
                expected_version_seq=1, markdown="# Notes only\n\nNew public notes.\n"
            ),
        )

    with database.session() as db:
        attempt = db.get(AssessmentAttempt, str(started.attempt.id))
        assert attempt is not None
        assert attempt.status == "paused"
        assert attempt.question_selection_revision == 2
        assert _attempt_question_rows(db, attempt.id) == []
        context = get_assessment_runtime_context(db, student, conversation_id)
        assert context is not None
        assert context.current_question is None
        assert context.progress.question_count == 0
        notice = db.scalar(
            select(ConversationTurn).where(
                ConversationTurn.conversation_id == conversation_id,
                ConversationTurn.user_text == "",
            )
        )
        assert notice is not None
        assert notice.state == "ready"
        result = db.scalar(select(TeamTurnResult).where(TeamTurnResult.turn_id == notice.id))
        assert result is not None and result.assistant_text is not None
        assert "老师已更改当前回合的 Knowledge，请重新答题。" in result.assistant_text
        assert "当前没有可作答题，请等待老师补充后再继续。" in result.assistant_text


def test_failed_notice_write_rolls_back_canonical_head_and_attempt_reset(
    attempt_env: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _app, database, settings, _client = attempt_env
    with database.session() as db:
        conversation_id, _team_id, _version_id, _publication_id, set_id, questions = (
            _create_formal_conversation(db, visibility="public")
        )
        _bind_set_to_leader_agent(db, conversation_id, set_id)
        _add_markdown_head(
            db,
            set_id=set_id,
            markdown=_markdown("Question"),
            question_version_ids=[version_id for _asset_id, version_id in questions],
        )
        student = _service_actor(db, settings, STUDENT_ID)
        started = start_or_resume_attempt(db, student, conversation_id, client_event_id=uuid4())
        assert started is not None
        start_revision = started.attempt.revision
    with database.session() as db:
        teacher = _service_actor(db, settings, TEACHER_ID)

    def fail_notice(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("synthetic notice failure")

    monkeypatch.setattr(
        "app.modules.workspace.team_runtime.persist_assessment_knowledge_update_notice",
        fail_notice,
    )
    with pytest.raises(RuntimeError, match="synthetic notice failure"):
        with database.session() as db:
            save_brainform_markdown(
                db,
                teacher,
                set_id,
                SaveKnowledgeMarkdownRequest(
                    expected_version_seq=1,
                    markdown=_markdown("Updated question"),
                ),
            )
    with database.session() as db:
        set_row = db.get(KnowledgeSet, set_id)
        attempt = db.get(AssessmentAttempt, str(started.attempt.id))
        assert set_row is not None and set_row.current_markdown_version_seq == 1
        assert attempt is not None
        assert attempt.question_selection_revision == 1
        assert attempt.revision == start_revision
        assert len(_attempt_question_rows(db, attempt.id)) == 2
        assert (
            db.scalar(
                select(func.count(ConversationTurn.id)).where(
                    ConversationTurn.conversation_id == conversation_id,
                    ConversationTurn.user_text == "",
                )
            )
            == 0
        )
