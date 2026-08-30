"""Bounded in-process scheduler for Mock insight and Maya report Jobs."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import Job

from .models import (
    BarrageInsightSnapshot,
    CivilizationReportCurrentSuccess,
    CivilizationReportRevision,
)
from .service import process_insight_job, process_report_job


class ReportTaskManager:
    """Run at most one serial insight/report chain for each Debate."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        event_publisher: Callable[[str, str, dict[str, Any]], bool],
    ) -> None:
        self.session_factory = session_factory
        self.event_publisher = event_publisher
        self._loop: asyncio.AbstractEventLoop | None = None
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._closed = False

    def bind_running_loop(self) -> None:
        self._loop = asyncio.get_running_loop()

    def wake(self, debate_id: str) -> None:
        loop = self._loop
        if self._closed or loop is None or loop.is_closed():
            return
        loop.call_soon_threadsafe(self._schedule, debate_id)

    def _schedule(self, debate_id: str) -> None:
        current = self._tasks.get(debate_id)
        if current is not None and not current.done():
            return
        task = asyncio.create_task(self._run(debate_id), name=f"maya-report-{debate_id}")
        self._tasks[debate_id] = task
        task.add_done_callback(lambda _task: self._tasks.pop(debate_id, None))

    async def _run(self, debate_id: str) -> None:
        await asyncio.to_thread(self._run_chain, debate_id)

    def _next_job(self, debate_id: str) -> tuple[str, str] | None:
        with self.session_factory() as db:
            job = db.scalar(
                select(Job)
                .where(
                    Job.debate_id == debate_id,
                    Job.state == "pending",
                    Job.operation.in_(("barrage_insight.generate", "report.generate")),
                )
                .order_by(Job.created_at, Job.id)
            )
            if job is None:
                return None
            if job.operation == "barrage_insight.generate" and job.insight_snapshot_id:
                return job.operation, job.insight_snapshot_id
            if job.operation == "report.generate" and job.report_revision_id:
                return job.operation, job.report_revision_id
            return None

    def _run_chain(self, debate_id: str) -> None:
        while True:
            pending = self._next_job(debate_id)
            if pending is None:
                return
            operation, owner_id = pending
            if operation == "barrage_insight.generate":
                self._run_insight(debate_id, owner_id)
            else:
                self._run_report(debate_id, owner_id)

    def _run_insight(self, debate_id: str, snapshot_id: str) -> None:
        with self.session_factory() as db:
            snapshot = db.get(BarrageInsightSnapshot, snapshot_id)
            if snapshot is None or snapshot.status != "generating":
                return
            revision = snapshot.revision_no
        self.event_publisher(
            debate_id,
            "barrage_insight.started",
            {"revision": revision, "status": "generating"},
        )
        with self.session_factory() as db:
            snapshot = process_insight_job(db, snapshot_id)
            db.commit()
            status = snapshot.status
            payload = {
                "revision": snapshot.revision_no,
                "status": status,
                "included_count": snapshot.included_count,
                "filtered_count": snapshot.filtered_count,
            }
            if status == "ready":
                payload["snapshot_id"] = snapshot.id
            else:
                payload["safe_error_code"] = snapshot.safe_error_code or "insight_generation_failed"
        event_type = "barrage_insight.completed" if status == "ready" else "barrage_insight.failed"
        self.event_publisher(debate_id, event_type, payload)

    def _run_report(self, debate_id: str, revision_id: str) -> None:
        with self.session_factory() as db:
            revision = db.get(CivilizationReportRevision, revision_id)
            if revision is None or revision.status != "generating":
                return
        self.event_publisher(
            debate_id,
            "report.started",
            {"revision_id": revision_id, "status": "generating"},
        )
        with self.session_factory() as db:
            revision = process_report_job(db, revision_id)
            db.commit()
            pointer = db.scalar(
                select(CivilizationReportCurrentSuccess).where(
                    CivilizationReportCurrentSuccess.report_id == revision.report_id
                )
            )
            status = revision.status
            if status == "ready":
                payload: dict[str, Any] = {
                    "revision_id": revision.id,
                    "revision_no": revision.revision_no,
                    "status": "ready",
                    "current_success_revision_id": revision.id,
                    "latest_attempt_status": "ready",
                    "word_count": revision.word_count,
                }
                event_type = "report.completed"
            else:
                payload = {
                    "revision_id": revision.id,
                    "revision_no": revision.revision_no,
                    "status": "failed",
                    "current_success_revision_id": pointer.revision_id if pointer else None,
                    "latest_attempt_status": "failed",
                    "safe_error_code": revision.safe_error_code or "report_generation_failed",
                }
                event_type = "report.failed"
        self.event_publisher(debate_id, event_type, payload)

    def schedule_pending(self) -> None:
        with self.session_factory() as db:
            debate_ids = tuple(
                db.scalars(
                    select(Job.debate_id)
                    .where(
                        Job.state == "pending",
                        Job.debate_id.is_not(None),
                        Job.operation.in_(("barrage_insight.generate", "report.generate")),
                    )
                    .distinct()
                ).all()
            )
        for debate_id in debate_ids:
            if debate_id:
                self.wake(debate_id)

    async def close(self) -> None:
        self._closed = True
        tasks = tuple(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()


__all__ = ["ReportTaskManager"]
