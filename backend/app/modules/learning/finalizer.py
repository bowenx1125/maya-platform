"""Score and summarize a formal assessment after its last answer.

The scorer and summarizer used to run only when a later Team turn happened to
route to them, so an attempt whose student said nothing more stayed
in_progress forever. The server now asks each executor itself, through the
same Team turn path and its authorization, ledgers and idempotency.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import PlatformError
from app.core.models import SessionRecord, User
from app.modules.auth.service import AuthContext
from app.modules.workspace.models import Conversation, ConversationParticipant

from .models import AssessmentActivity, AssessmentAttempt

LOGGER = logging.getLogger("maya.assessment")

Purpose = Literal["assessment_evaluate", "boundary_summarize"]
# One evaluation and one summary per round; anything more means a step failed.
MAX_STEPS = 4


def _in_progress_attempt(db: Session, row: Conversation) -> AssessmentAttempt | None:
    return db.scalar(
        select(AssessmentAttempt).where(
            AssessmentAttempt.source_conversation_id == row.id,
            AssessmentAttempt.actor_user_id == row.user_id,
            AssessmentAttempt.status == "in_progress",
        )
    )


def _next_purpose(db: Session, attempt: AssessmentAttempt) -> Purpose | None:
    """The executor this attempt waits for, or None while questions remain."""

    from .execution import (
        _assessment_for_attempt,
        _current_attempt_question_rows,
        _evaluation_covers_questions,
        attempt_has_final_evidence,
    )

    rows = _current_attempt_question_rows(db, attempt)
    if not rows or any(row.status != "resolved" or row.presented_at is None for row in rows):
        return None
    evaluation = _assessment_for_attempt(db, attempt)
    if evaluation is None or not _evaluation_covers_questions(evaluation[1], rows):
        return "assessment_evaluate"
    if not attempt_has_final_evidence(db, attempt):
        return "boundary_summarize"
    return None


def drive_assessment(
    factory: Callable[[], Session], settings: Settings, conversation_id: str
) -> None:
    from app.modules.workspace.team_runtime import (
        claim_assessment_executor_turn,
        execute_team_turn,
    )

    from .execution import _activity_executor

    attempted: set[tuple[str, int, Purpose]] = set()
    retried: set[tuple[str, int, Purpose]] = set()
    for _step in range(MAX_STEPS):
        with factory() as db:
            row = db.get(Conversation, conversation_id)
            if row is None or row.entry_kind == "agent" or row.withdrawn_at is not None:
                return
            attempt = _in_progress_attempt(db, row)
            user = db.get(User, row.user_id)
            if attempt is None or user is None or user.status != "active":
                return
            purpose = _next_purpose(db, attempt)
            if purpose is None:
                return
            # The same step on the same attempt revision means the executor did
            # not save. Scoring is one attempt. A missed summary gets one server
            # retry; a second miss is recorded for the teacher and stays off
            # the student chat.
            key = (attempt.id, attempt.revision, purpose)
            if key in attempted:
                if purpose != "boundary_summarize" or key in retried:
                    LOGGER.warning(
                        "Assessment step did not save attempt_id=%s purpose=%s",
                        attempt.id,
                        purpose,
                    )
                    return
                retried.add(key)
            else:
                attempted.add(key)
            activity = db.get(AssessmentActivity, attempt.activity_id)
            if activity is None:
                return
            member_id, agent_version_id = _activity_executor(db, activity, purpose)
            participant = db.scalar(
                select(ConversationParticipant).where(
                    ConversationParticipant.conversation_id == row.id,
                    ConversationParticipant.team_member_id == member_id,
                    ConversationParticipant.agent_version_id == agent_version_id,
                )
            )
            if participant is None:
                return
            # The student owns the attempt; the run acts as them through their
            # newest live sign-in, which every Tool call re-checks. Signed out,
            # the attempt waits and resumes on their next message.
            sign_in = db.scalar(
                select(SessionRecord)
                .where(
                    SessionRecord.user_id == user.id,
                    SessionRecord.revoked_at.is_(None),
                    SessionRecord.expires_at > datetime.now(UTC),
                )
                .order_by(SessionRecord.created_at.desc())
                .limit(1)
            )
            if sign_in is None:
                return
            # The claim commits, which would expire these rows; the run reads
            # them later from other sessions, so keep their loaded values.
            db.expunge(sign_in)
            db.expunge(user)
            actor = AuthContext("", sign_in, user, "")
            claim = claim_assessment_executor_turn(
                db,
                settings,
                conversation_id=row.id,
                participant_id=participant.id,
                actor_context=actor,
            )
            if claim is None:
                return
        execute_team_turn(factory, claim)


class AssessmentFinalizer:
    """Run at most one finishing chain per conversation, off the request."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        settings: Callable[[], Settings],
    ) -> None:
        self._factory = session_factory
        self._settings = settings
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="maya-assessment")
        self._lock = threading.Lock()
        self._running: set[str] = set()
        self._rewake: set[str] = set()
        self._closed = False

    def wake(self, conversation_id: str) -> None:
        # Mock members never call a Tool, so an executor turn could only fail.
        if self._settings().llm_provider != "dashscope":
            return
        with self._lock:
            if self._closed:
                return
            if conversation_id in self._running:
                self._rewake.add(conversation_id)
                return
            self._running.add(conversation_id)
        self._executor.submit(self._run, conversation_id)

    def _run(self, conversation_id: str) -> None:
        try:
            drive_assessment(self._factory, self._settings(), conversation_id)
        except PlatformError as error:
            LOGGER.warning(
                "Assessment finishing stopped conversation_id=%s code=%s",
                conversation_id,
                error.code,
            )
        except Exception:
            LOGGER.exception("Assessment finishing failed conversation_id=%s", conversation_id)
        finally:
            with self._lock:
                self._running.discard(conversation_id)
                again = conversation_id in self._rewake and not self._closed
                self._rewake.discard(conversation_id)
            if again:
                self.wake(conversation_id)

    def recover(self) -> None:
        """Resume attempts left waiting for an executor when the server stopped."""

        with self._factory() as db:
            rows = db.execute(
                select(Conversation.id, AssessmentAttempt)
                .join(
                    AssessmentAttempt, AssessmentAttempt.source_conversation_id == Conversation.id
                )
                .where(
                    AssessmentAttempt.status == "in_progress",
                    Conversation.active_request_id.is_(None),
                    Conversation.withdrawn_at.is_(None),
                )
            ).all()
            waiting = [
                conversation_id
                for conversation_id, attempt in rows
                if _next_purpose(db, attempt) is not None
            ]
        for conversation_id in waiting:
            self.wake(conversation_id)

    def close(self) -> None:
        with self._lock:
            self._closed = True
        self._executor.shutdown(wait=False, cancel_futures=True)
