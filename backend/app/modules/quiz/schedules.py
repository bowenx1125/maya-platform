"""One-shot taking schedules; row locks make every replica safe to sweep."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from . import service
from .models import ClassroomQuiz

LOGGER = logging.getLogger("maya.quiz.schedule")
SWEEP_SECONDS = 10.0


def sweep_due_quiz_schedules(
    session_factory: Callable[[], Session], now: datetime | None = None
) -> int:
    now = now if now is not None else service._now()
    with session_factory() as db:
        quiz_ids = db.scalars(
            select(ClassroomQuiz.id).where(
                or_(ClassroomQuiz.scheduled_start_at <= now, ClassroomQuiz.scheduled_end_at <= now)
            )
        ).all()
    applied = 0
    for quiz_id in quiz_ids:
        try:
            with session_factory() as db:
                applied += int(service.apply_due_schedules(db, quiz_id, now))
        except Exception as exc:
            LOGGER.warning(
                "quiz_schedule_apply_failed quiz_id=%s error_type=%s", quiz_id, type(exc).__name__
            )
    return applied


class QuizScheduleSweeper:
    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self.session_factory = session_factory
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(
                target=self._loop, name="maya-quiz-schedules", daemon=True
            )
            self._thread.start()

    def _loop(self) -> None:
        while not self._stop.wait(SWEEP_SECONDS):
            try:
                sweep_due_quiz_schedules(self.session_factory)
            except Exception as exc:
                LOGGER.warning("quiz_schedule_sweep_failed error_type=%s", type(exc).__name__)

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
