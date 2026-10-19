"""Bounded in-process scheduler for Mock insight and Maya report Jobs."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import Job

from .models import (
    BarrageInsightSnapshot,
    CivilizationReport,
    CivilizationReportCurrentSuccess,
    CivilizationReportRevision,
)
from .service import (
    RealReportRuntime,
    ReportAdmissionDeferred,
    fail_report_waiting_for_insight,
    process_insight_job,
    process_report_job,
)

LOGGER = logging.getLogger(__name__)


class ReportTaskManager:
    """Run at most one serial insight/report chain for each Debate."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        event_publisher: Callable[[str, str, dict[str, Any]], bool],
        *,
        real_runtime: RealReportRuntime | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.event_publisher = event_publisher
        self.real_runtime = real_runtime
        self._loop: asyncio.AbstractEventLoop | None = None
        self._tasks: dict[str, asyncio.Task[None]] = {}
        # A wake that arrives while a chain is draining must not be dropped.
        self._rewake: set[str] = set()
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
            # The running chain may already be past its last _next_job read, so
            # it cannot be relied on to notice this new Job. Remember the wake
            # and re-schedule when it finishes: otherwise a report requested in
            # that window sat pending forever and Regenerate looked broken for
            # no reason a teacher could see.
            self._rewake.add(debate_id)
            return
        task = asyncio.create_task(self._run(debate_id), name=f"maya-report-{debate_id}")
        self._tasks[debate_id] = task
        task.add_done_callback(lambda _task: self._finished(debate_id))

    def _finished(self, debate_id: str) -> None:
        self._tasks.pop(debate_id, None)
        if self._closed:
            self._rewake.discard(debate_id)
            return
        if debate_id in self._rewake:
            self._rewake.discard(debate_id)
            self._schedule(debate_id)

    async def _run(self, debate_id: str) -> None:
        work = asyncio.create_task(asyncio.to_thread(self._run_chain, debate_id))
        try:
            await asyncio.shield(work)
        except asyncio.CancelledError:
            try:
                await work
            except Exception:
                pass
            raise

    async def request_cancel_debate(self, debate_id: str) -> None:
        """Stop future work after Destroy without holding its HTTP response."""
        self._rewake.discard(debate_id)
        task = self._tasks.get(debate_id)
        if task is not None and not task.done():
            task.cancel()

    async def cancel_debate(self, debate_id: str) -> None:
        self._rewake.discard(debate_id)
        task = self._tasks.get(debate_id)
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

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
            try:
                if operation == "barrage_insight.generate":
                    self._run_insight(debate_id, owner_id)
                else:
                    self._run_report(debate_id, owner_id)
            except ReportAdmissionDeferred as exc:
                # The server is shedding load: the Job is pending again and
                # nothing was sent. Slower, never stuck: look again later.
                LOGGER.info(
                    "Report for debate %s deferred under pressure retry_after_s=%s",
                    debate_id,
                    exc.retry_after_seconds,
                )
                self._retry_later(debate_id, exc.retry_after_seconds)
                return
            except Exception as exc:
                # An unexpected failure used to escape into the asyncio task
                # and die there as "Task exception was never retrieved". The
                # Job stayed ``running`` and the revision ``generating``
                # forever, so the panel showed a spinner nothing would ever
                # resolve and Regenerate only added another stuck revision.
                # A failure has to be recorded where the teacher can see it and
                # act on it; the loop stops so a broken job cannot spin.
                LOGGER.error(
                    "Report chain failed for debate %s error_type=%s",
                    debate_id,
                    type(exc).__name__,
                )
                if isinstance(exc, ValidationError):
                    LOGGER.error(
                        "Report input validation failed for debate %s fields=%s",
                        debate_id,
                        [
                            {"field": ".".join(map(str, error["loc"])), "type": error["type"]}
                            for error in exc.errors(include_input=False, include_url=False)
                        ],
                    )
                self._fail_stuck_job(debate_id, operation, owner_id)
                return

    def _retry_later(self, debate_id: str, delay_seconds: float) -> None:
        loop = self._loop
        if self._closed or loop is None or loop.is_closed():
            return
        delay = min(30.0, max(2.0, float(delay_seconds)))
        loop.call_soon_threadsafe(
            lambda: None if self._closed else loop.call_later(delay, self._schedule, debate_id)
        )

    def _fail_stuck_job(self, debate_id: str, operation: str, owner_id: str) -> None:
        """Record an unexpected failure so the teacher can retry it."""

        payload: dict[str, Any]
        try:
            with self.session_factory() as db:
                job = db.scalar(
                    select(Job).where(
                        Job.debate_id == debate_id,
                        Job.operation == operation,
                        (
                            Job.report_revision_id == owner_id
                            if operation == "report.generate"
                            else Job.insight_snapshot_id == owner_id
                        ),
                    )
                )
                if job is not None:
                    job.state = "failed"
                    job.safe_error_code = "report_generation_failed"
                revision = None
                snapshot = None
                if operation == "report.generate":
                    revision = db.get(CivilizationReportRevision, owner_id)
                    if revision is not None and revision.status == "generating":
                        revision.status = "failed"
                        revision.safe_error_code = "report_generation_failed"
                        report = db.get(CivilizationReport, revision.report_id)
                        if report is not None:
                            report.generation_status = "failed"
                            report.latest_attempt_status = "failed"
                else:
                    snapshot = db.get(BarrageInsightSnapshot, owner_id)
                    if snapshot is not None and snapshot.status == "generating":
                        snapshot.status = "failed"
                        snapshot.safe_error_code = "insight_generation_failed"
                        fail_report_waiting_for_insight(db, snapshot.id)
                if operation == "report.generate":
                    pointer = (
                        db.scalar(
                            select(CivilizationReportCurrentSuccess).where(
                                CivilizationReportCurrentSuccess.report_id == revision.report_id
                            )
                        )
                        if revision is not None
                        else None
                    )
                    event_type = "report.failed"
                    payload = {
                        "revision_id": owner_id,
                        "revision_no": revision.revision_no if revision is not None else 1,
                        "status": "failed",
                        "current_success_revision_id": (pointer.revision_id if pointer else None),
                        "latest_attempt_status": "failed",
                        "safe_error_code": "report_generation_failed",
                    }
                else:
                    event_type = "barrage_insight.failed"
                    payload = {
                        "revision": snapshot.revision_no if snapshot is not None else 1,
                        "status": "failed",
                        "safe_error_code": "insight_generation_failed",
                    }
                db.commit()
        except Exception:
            LOGGER.exception("Could not record the failure of a stuck report job")
            return
        self.event_publisher(debate_id, event_type, payload)

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
            revision = process_report_job(db, revision_id, runtime=self.real_runtime)
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
            elif status == "generating":
                # Parked awaiting a provider confirmation. This used to publish
                # a "report.pending" event, which is not a registered type, so
                # the whole chain died with "unsupported playback event type"
                # and left the Job running forever. The revision row already
                # carries this state and the panel reads it.
                LOGGER.info(
                    "Report revision %s is waiting for a provider confirmation",
                    revision.id,
                )
                return
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
