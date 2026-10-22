from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from app.core.errors import PlatformError
from app.core.models import ProviderOperation
from app.modules.demo_baseline.service import ensure_demo_baseline
from app.modules.learning.attempts import (
    _boundary_completion_event_id,
    _boundary_completion_request_hash,
    _event,
    start_or_resume_attempt,
)
from app.modules.learning.models import (
    AssessmentActivity,
    AssessmentAttempt,
    LearningBoundary,
    LearningBoundaryRevision,
)
from app.modules.runtime_tools.models import RuntimeToolReceipt
from app.modules.workspace import chat
from app.modules.workspace.models import (
    Conversation,
    ConversationParticipant,
    ConversationTurn,
    TeamProviderCall,
)
from app.modules.workspace.team_conversation import team_session_view
from sqlalchemy import event, select

from tests.test_assessment_reply_text import _result
from tests.test_mayaform_assessment_attempts import (
    _accepted_tool_identity,
    _begin_pending_executor_turn,
    _create_formal_conversation,
    _finish_executor_turn,
)
from tests.test_mayaform_teams import BOWEN_ID, COURSE_ID, _make_agent_version
from tests.test_team_provider_stage import _dispatch
from tests.test_wave3_agent_metadata import _context


def _turns(db: Any, conversation_id: str, count: int) -> list[ConversationTurn]:
    timestamp = datetime.now(UTC) - timedelta(minutes=1)
    rows = [
        ConversationTurn(
            id=str(uuid4()),
            conversation_id=conversation_id,
            position=position,
            user_text=f"Synthetic question {position}",
            assistant_text=f"Synthetic reply {position}",
            sources_json="[]",
            mode="mock",
            state="ready",
            created_at=timestamp + timedelta(milliseconds=position),
        )
        for position in range(count)
    ]
    db.add_all(rows)
    db.flush()
    return rows


def _conversation(database: Any) -> str:
    _agent_id, version_id = _make_agent_version(
        database, owner_id=BOWEN_ID, name="History query regression"
    )
    conversation_id = str(uuid4())
    with database.session() as db:
        db.add(
            Conversation(
                id=conversation_id,
                user_id=BOWEN_ID,
                course_id=COURSE_ID,
                agent_version_id=version_id,
                created_at=datetime.now(UTC),
            )
        )
        db.commit()
    return conversation_id


def _receipt(
    db: Any, conversation_id: str, turn_id: str, value: str, *, actor_id: str = BOWEN_ID
) -> None:
    operation_id = str(uuid4())
    now = datetime.now(UTC)
    db.add(
        ProviderOperation(
            id=operation_id,
            scope_id=conversation_id,
            provider_operation="chat",
            logical_item_id=operation_id,
            attempt_no=1,
            request_hash="a" * 64,
            max_tokens=0,
            max_cost_cny=0,
            policy_hash="b" * 64,
            export_manifest_hash="c" * 64,
            state="not_sent",
            created_at=now,
            updated_at=now,
        )
    )
    db.flush()
    db.add(
        RuntimeToolReceipt(
            id=str(uuid4()),
            actor_user_id=actor_id,
            conversation_id=conversation_id,
            turn_id=turn_id,
            model_operation_id=operation_id,
            tool_call_id=str(uuid4()),
            tool_name="assessment_action",
            request_hash="d" * 64,
            result_json=value,
            created_at=now,
        )
    )
    db.flush()


@pytest.mark.parametrize("count", [1, 20, 100])
def test_history_assessment_reads_do_not_grow_per_turn(
    client: Any, database: Any, count: int
) -> None:
    conversation_id = _conversation(database)
    with database.session() as db:
        row = db.get(Conversation, conversation_id)
        turns = _turns(db, conversation_id, count)
        db.commit()
        # Read both implementations from the same persisted data, excluding fixture queries.
        row = db.get(Conversation, conversation_id)
        turns = list(
            db.scalars(
                select(ConversationTurn)
                .where(ConversationTurn.conversation_id == conversation_id)
                .order_by(ConversationTurn.position, ConversationTurn.id)
            )
        )
        statements: list[str] = []

        def count_selects(_conn: Any, _cursor: Any, statement: str, *_args: Any) -> None:
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)

        event.listen(db.get_bind(), "before_cursor_execute", count_selects)
        try:
            original = {
                turn.id: chat._assessment_result_for_turn(db, row.id, turn.id, row.user_id)
                for turn in turns
            }
            original_count = len(statements)
            statements.clear()
            actual = chat._assessment_results_for_history(db, row, turns)
            batched_count = len(statements)
        finally:
            event.remove(db.get_bind(), "before_cursor_execute", count_selects)
        assert actual == original == {turn.id: None for turn in turns}
        assert batched_count <= original_count
        assert batched_count <= 5


def test_history_keeps_latest_valid_receipt_and_actor_scope(client: Any, database: Any) -> None:
    from app.seed import KAIKAI_ID

    conversation_id = _conversation(database)
    with database.session() as db:
        row = db.get(Conversation, conversation_id)
        turns = _turns(db, conversation_id, 3)
        first = _result("assessment.started", "transitioned")
        newest = _result("assessment.progress", "read")
        old_receipt = json.dumps({"ok": True, "result": first.model_dump(mode="json")})
        new_receipt = json.dumps({"ok": True, "result": newest.model_dump(mode="json")})
        _receipt(db, row.id, turns[0].id, old_receipt)
        _receipt(db, row.id, turns[0].id, new_receipt)
        _receipt(db, row.id, turns[0].id, "{malformed")
        _receipt(db, row.id, turns[0].id, '{"ok":false}')
        _receipt(db, row.id, turns[1].id, old_receipt, actor_id=KAIKAI_ID)
        original = {
            turn.id: chat._assessment_result_for_turn(db, row.id, turn.id, row.user_id)
            for turn in turns
        }
        actual = chat._assessment_results_for_history(db, row, turns)
        assert actual == original
        assert actual[turns[0].id] == newest
        assert actual[turns[1].id] is None
        assert actual[turns[2].id] is None


@pytest.mark.parametrize("status", ["paused", "completed", "abandoned"])
def test_history_refreshes_only_latest_lifecycle(
    client: Any, database: Any, app_bundle: Any, status: str
) -> None:
    actor = _context(database, BOWEN_ID)
    with database.session() as db:
        ensure_demo_baseline(db, app_bundle[2].resolved_data_root)
        conversation_id, *_ = _create_formal_conversation(db)
        started = start_or_resume_attempt(db, actor, conversation_id, client_event_id=uuid4())
        assert started is not None
        turns = _turns(db, conversation_id, 3)
        old_receipt = _result("assessment.started", "transitioned")
        _receipt(
            db,
            conversation_id,
            turns[0].id,
            json.dumps({"ok": True, "result": old_receipt.model_dump(mode="json")}),
        )
        attempt = db.get(AssessmentAttempt, str(started.attempt.id))
        attempt.status = status
        attempt.updated_at = datetime.now(UTC)
        attempt.completed_at = attempt.updated_at if status == "completed" else None
        attempt.abandoned_at = attempt.updated_at if status == "abandoned" else None
        db.flush()
        row = db.get(Conversation, conversation_id)
        original = {
            turn.id: chat._assessment_result_for_turn(db, row.id, turn.id, row.user_id)
            for turn in turns
        }
        actual = chat._assessment_results_for_history(db, row, turns)
        assert actual == original
        assert actual[turns[0].id] == old_receipt
        assert actual[turns[1].id] is None
        assert actual[turns[-1].id].response_key == f"assessment.{status}"


def test_team_history_uses_only_its_own_projection(
    client: Any, database: Any, app_bundle: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    actor = _context(database, BOWEN_ID)
    with database.session() as db:
        ensure_demo_baseline(db, app_bundle[2].resolved_data_root)
        conversation_id, *_ = _create_formal_conversation(db)
        _turns(db, conversation_id, 3)
        row = db.get(Conversation, conversation_id)
        expected = team_session_view(db, row, actor, [])

        def unexpected_single_agent_projection(*_args: Any, **_kwargs: Any) -> None:
            pytest.fail("Team history must not build discarded single-Agent projections")

        monkeypatch.setattr(chat, "_assessment_result_for_turn", unexpected_single_agent_projection)
        monkeypatch.setattr(
            chat, "_assessment_results_for_history", unexpected_single_agent_projection
        )
        assert chat.session_view(db, row, actor) == expected


def test_other_account_cannot_read_history_or_owner_assessments(
    client: Any, database: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.seed import KAIKAI_ID

    actor = _context(database, KAIKAI_ID)
    conversation_id = _conversation(database)
    with database.session() as db:
        row = db.get(Conversation, conversation_id)
        row.chat_visibility = "public"
        turns = _turns(db, row.id, 2)
        saved = _result("assessment.progress", "read")
        _receipt(
            db,
            row.id,
            turns[0].id,
            json.dumps({"ok": True, "result": saved.model_dump(mode="json")}),
        )

        def reject_private_reads(*_args: Any, **_kwargs: Any) -> None:
            pytest.fail("Public transcript must not load private assessment projections")

        monkeypatch.setattr(chat, "_assessment_results_for_history", reject_private_reads)
        with pytest.raises(PlatformError) as denied:
            chat.session_view(db, row, actor)
        assert denied.value.code == "not_found"


@pytest.mark.parametrize("boundary_position", [0, 1], ids=["historical", "latest"])
@pytest.mark.parametrize("foreign_actor", [False, True], ids=["owner", "foreign-actor"])
def test_history_preserves_completed_boundary_precedence_and_actor_scope(
    client: Any, database: Any, app_bundle: Any, boundary_position: int, foreign_actor: bool
) -> None:
    from app.seed import KAIKAI_ID

    _database, _repository, template_operation_id = _dispatch(client, app_bundle)
    actor = _context(database, BOWEN_ID)
    with database.session() as db:
        ensure_demo_baseline(db, app_bundle[2].resolved_data_root)
        conversation_id, *_ = _create_formal_conversation(db)
        started = start_or_resume_attempt(db, actor, conversation_id, client_event_id=uuid4())
        assert started is not None
        attempt = db.get(AssessmentAttempt, str(started.attempt.id))
        activity = db.get(AssessmentActivity, attempt.activity_id)
        participant = db.scalar(
            select(ConversationParticipant).where(
                ConversationParticipant.conversation_id == conversation_id,
                ConversationParticipant.team_member_id == activity.boundary_team_member_id,
            )
        )
        template_stage_id = db.scalar(
            select(TeamProviderCall.id).where(
                TeamProviderCall.operation_id == template_operation_id
            )
        )
        execution = _begin_pending_executor_turn(
            db,
            conversation_id=conversation_id,
            participant_id=participant.id,
            position=boundary_position,
        )
        identity = _accepted_tool_identity(
            db,
            template_stage_id=template_stage_id,
            conversation_id=conversation_id,
            participant_id=participant.id,
            position=boundary_position,
            tool_name="update_learning_boundary",
            execution=execution,
        )
        call = db.get(TeamProviderCall, identity.model_call_id)
        _finish_executor_turn(db, (identity.turn_id, call.result_id))
        other_turn = _turns(db, conversation_id, 1)[0]
        other_turn.position = 1 - boundary_position
        now = datetime.now(UTC)
        attempt.status = "completed"
        attempt.completed_at = now
        attempt.updated_at = now
        boundary = LearningBoundary(
            id=str(uuid4()),
            attempt_id=attempt.id,
            activity_id=activity.id,
            owner_user_id=BOWEN_ID,
            course_id=COURSE_ID,
            conversation_id=conversation_id,
            current_revision_seq=1,
            created_at=now,
            updated_at=now,
        )
        db.add(boundary)
        db.flush()
        boundary_content = json.dumps(
            {
                "summary": "Synthetic completed Boundary",
                "strengths": [],
                "areas_to_explore": [],
                "next_step": "Compare the next answer.",
            }
        )
        revision = LearningBoundaryRevision(
            id=str(uuid4()),
            boundary_id=boundary.id,
            attempt_id=attempt.id,
            revision_seq=1,
            actor_user_id=BOWEN_ID,
            summarizer_team_member_id=activity.boundary_team_member_id,
            summarizer_agent_version_id=activity.boundary_agent_version_id,
            source_model_call_id=call.id,
            source_tool_call_id=identity.tool_call_id,
            content_json=boundary_content,
            content_hash=hashlib.sha256(boundary_content.encode()).hexdigest(),
            created_at=now,
        )
        db.add(revision)
        db.flush()
        db.add(
            _event(
                attempt=attempt,
                actor_user_id=BOWEN_ID,
                client_event_id=_boundary_completion_event_id(
                    attempt, model_call_id=call.id, tool_call_id=identity.tool_call_id
                ),
                event_kind="complete",
                classification=None,
                request_hash=_boundary_completion_request_hash(
                    attempt, revision, model_call_id=call.id, tool_call_id=identity.tool_call_id
                ),
            )
        )
        db.add(
            RuntimeToolReceipt(
                id=str(uuid4()),
                actor_user_id=KAIKAI_ID if foreign_actor else BOWEN_ID,
                conversation_id=conversation_id,
                turn_id=identity.turn_id,
                model_operation_id=call.operation_id,
                tool_call_id=identity.tool_call_id,
                tool_name="update_learning_boundary",
                request_hash="f" * 64,
                result_json='{"ok":true,"result":{"saved":true}}',
                created_at=now,
            )
        )
        db.flush()
        historical = _result("assessment.started", "transitioned")
        _receipt(
            db,
            conversation_id,
            identity.turn_id,
            json.dumps({"ok": True, "result": historical.model_dump(mode="json")}),
        )
        # A newer paused attempt must not overwrite the exact older Boundary's
        # completion, even when that Boundary belongs to the latest Chat turn.
        restarted = start_or_resume_attempt(db, actor, conversation_id, client_event_id=uuid4())
        assert restarted is not None and restarted.attempt.id != started.attempt.id
        current_attempt = db.get(AssessmentAttempt, str(restarted.attempt.id))
        current_attempt.status = "paused"
        current_attempt.updated_at = datetime.now(UTC)
        db.flush()
        row = db.get(Conversation, conversation_id)
        turns = list(
            db.scalars(
                select(ConversationTurn)
                .where(ConversationTurn.conversation_id == conversation_id)
                .order_by(ConversationTurn.position, ConversationTurn.id)
            )
        )
        original = {
            turn.id: chat._assessment_result_for_turn(db, row.id, turn.id, row.user_id)
            for turn in turns
        }
        actual = chat._assessment_results_for_history(db, row, turns)
        assert actual == original
        projected = actual[identity.turn_id]
        assert projected is not None
        if not foreign_actor:
            assert projected.response_key == "assessment.completed"
            assert projected.context.attempt.id == started.attempt.id
        elif boundary_position == 0:
            assert projected == historical
        else:
            assert projected.response_key == "assessment.paused"
            assert projected.context.attempt.id == restarted.attempt.id
        if boundary_position == 0:
            latest = actual[turns[-1].id]
            assert latest.response_key == "assessment.paused"
            assert latest.context.attempt.id == restarted.attempt.id
