from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from app.modules.demo_baseline.service import ensure_demo_baseline
from app.modules.learning.attempts import (
    apply_assessment_decision,
    mark_attempt_question_presented,
    read_attempt_answers,
    start_or_resume_attempt,
)
from app.modules.learning.schemas import AssessmentRuntimeDecision
from app.modules.runtime_tools.builtin import EmptyArguments, runtime_registry
from app.modules.runtime_tools.registry import ToolCallIdentity, exposed_tools
from app.modules.workspace.models import Conversation
from fastapi.testclient import TestClient

from tests.test_mayaform_assessment_attempts import _create_formal_conversation
from tests.test_mayaform_learning_evidence import _context, _login


def test_actual_registry_mounts_learning_tools_and_serializes_formal_reads(
    client: TestClient, app_bundle: Any
) -> None:
    _app, database, settings = app_bundle
    client.headers["Origin"] = "http://testserver"
    with database.session() as db:
        ensure_demo_baseline(db, settings.resolved_data_root)
    token, _csrf = _login(client, "bowen")
    with database.session() as db:
        conversation_id, *_ = _create_formal_conversation(db, visibility="private")
        actor = _context(db, settings, token)
        started = start_or_resume_attempt(db, actor, conversation_id, client_event_id=uuid4())
        assert started is not None and started.current_question is not None
        presented = mark_attempt_question_presented(
            db,
            actor,
            conversation_id,
            question_version_id=started.current_question.question_version_id,
        )
        assert presented.current_question is not None
        answer_text = "the original saved answer"
        answer_message = f"My answer is {answer_text}."
        answered = apply_assessment_decision(
            db,
            actor,
            conversation_id,
            user_message=answer_message,
            decision=AssessmentRuntimeDecision(
                client_event_id=uuid4(),
                classification="answer_only",
                answer_span=answer_text,
                question_version_id=presented.current_question.question_version_id,
            ),
        )
        assert answered is not None and answered.response_key == "assessment.answer_recorded"
        internal_answers = read_attempt_answers(db, actor, conversation_id)
        assert len(internal_answers) == 1 and internal_answers[0].answer_text == answer_text
        assert "question_ordinal" in internal_answers[0].model_dump(mode="json")
        registry = runtime_registry()
        mounted = {spec.name for spec in exposed_tools(db, actor, conversation_id, registry)}
        assert {
            "assessment_action",
            "read_session",
            "read_memory",
            "read_learning_attempt",
            "read_assessment",
            "edit_assessment",
            "read_learning_boundary",
            "update_learning_boundary",
        } <= mounted
        teacher_only = {
            "list_course_assessments",
            "read_course_statistics",
            "read_student_test_transcripts",
            "create_course_report",
            "list_course_reports",
            "read_student_answers",
        }
        assert teacher_only <= registry.keys()
        # A student never gets the teacher's reads, including test transcripts.
        assert not teacher_only & mounted
        row = db.get(Conversation, conversation_id)
        assert row is not None
        identity = ToolCallIdentity(
            conversation_id, str(uuid4()), str(uuid4()), str(uuid4()), "read"
        )
        for name in ("read_session", "read_memory"):
            result = registry[name].handler(db, actor, row, EmptyArguments(), "read", identity)
            decoded = json.loads(json.dumps(result))
            records = decoded["assessment"] if name == "read_session" else decoded
            assert set(records) == {"source", "progress", "submitted_records"}
            assert records["source"] == "saved_assessment_attempt"
            assert records["submitted_records"] == [
                {
                    "answer_text": answer_text,
                    "created_at": internal_answers[0].created_at.isoformat().replace("+00:00", "Z"),
                }
            ]
            assert set(records["submitted_records"][0]) == {"answer_text", "created_at"}
            submitted = json.dumps(records["submitted_records"], ensure_ascii=False).casefold()
            encoded = json.dumps(decoded, ensure_ascii=False)
            for forbidden in ("question_ordinal", "question_version_id"):
                assert forbidden not in submitted
            for forbidden in ("score", "rubric", "reference answer"):
                assert forbidden.casefold() not in encoded.casefold()
