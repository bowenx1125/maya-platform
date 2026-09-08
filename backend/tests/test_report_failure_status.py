from app.core.models import Job
from app.modules.reports.models import CivilizationReport, CivilizationReportRevision
from app.modules.reports.service import (
    get_current_report,
    process_insight_job,
    process_report_job,
    reconcile_orphaned_report_statuses,
    recover_report_jobs,
)
from app.modules.reports.task_manager import ReportTaskManager
from fastapi.testclient import TestClient
from sqlalchemy import select

from tests.test_wave3_reports import TEACHER_ID, _finalize_interaction


def test_unexpected_report_failure_updates_authoritative_poll_status(app_factory):
    app, database, settings = app_factory()
    settings.classroom_public_base_url = "http://192.168.1.25:8080"
    with TestClient(app):
        debate_id, snapshot_id = _finalize_interaction(database, settings)
        with database.session() as db:
            process_insight_job(db, snapshot_id)
            revision = db.scalar(
                select(CivilizationReportRevision).where(
                    CivilizationReportRevision.debate_id == debate_id,
                )
            )
            assert revision is not None
            revision_id = revision.id
            db.commit()
        events = []
        manager = ReportTaskManager(database.session_factory, lambda *args: events.append(args))
        manager._fail_stuck_job(debate_id, "report.generate", revision_id)
        with database.session() as db:
            report = get_current_report(db, actor_user_id=TEACHER_ID, debate_id=debate_id)
            assert report.generation_status == "failed"
            assert report.latest_attempt_status == "failed"
            assert report.active_revision_id is None
            job = db.scalar(select(Job).where(Job.report_revision_id == revision_id))
            assert job is not None and job.state == "failed"
        assert events[-1][1] == "report.failed"


def test_startup_repairs_old_spinner_without_retrying_generation(app_factory):
    app, database, settings = app_factory()
    settings.classroom_public_base_url = "http://192.168.1.25:8080"
    with TestClient(app):
        debate_id, snapshot_id = _finalize_interaction(database, settings)
        with database.session() as db:
            process_insight_job(db, snapshot_id)
            revision = db.scalar(
                select(CivilizationReportRevision).where(
                    CivilizationReportRevision.debate_id == debate_id,
                )
            )
            assert revision is not None
            revision.status = "failed"
            revision.safe_error_code = "report_generation_failed"
            job = db.scalar(select(Job).where(Job.report_revision_id == revision.id))
            assert job is not None
            job.state = "failed"
            job.safe_error_code = "report_generation_failed"
            db.commit()
        with database.session() as db:
            assert recover_report_jobs(db) == 1
            report = get_current_report(db, actor_user_id=TEACHER_ID, debate_id=debate_id)
            assert report.generation_status == "failed"
            assert report.active_revision_id is None
            assert reconcile_orphaned_report_statuses(db) == 0


def test_reconciliation_preserves_active_work_and_existing_success(app_factory):
    app, database, settings = app_factory()
    settings.classroom_public_base_url = "http://192.168.1.25:8080"
    with TestClient(app):
        debate_id, snapshot_id = _finalize_interaction(database, settings)
        with database.session() as db:
            process_insight_job(db, snapshot_id)
            assert reconcile_orphaned_report_statuses(db) == 0
            revision = db.scalar(
                select(CivilizationReportRevision).where(
                    CivilizationReportRevision.debate_id == debate_id,
                )
            )
            assert revision is not None and revision.status == "generating"
            process_report_job(db, revision.id)
            report_row = db.scalar(
                select(CivilizationReport).where(
                    CivilizationReport.debate_id == debate_id,
                )
            )
            assert report_row is not None
            report_row.generation_status = "generating"
            report_row.latest_attempt_status = "generating"
            db.flush()
            assert reconcile_orphaned_report_statuses(db) == 1
            report = get_current_report(db, actor_user_id=TEACHER_ID, debate_id=debate_id)
            assert report.generation_status == "ready"
            assert report.latest_attempt_status == "ready"
            assert report.current_success_revision is not None
            assert reconcile_orphaned_report_statuses(db) == 0


def test_generating_and_failed_report_revisions_do_not_emit_removed_translation_field():
    from datetime import UTC, datetime
    from types import SimpleNamespace
    from uuid import uuid4

    from app.modules.reports.service import _revision_dto

    for status in ("generating", "failed"):
        revision = SimpleNamespace(
            id=str(uuid4()),
            revision_no=1,
            status=status,
            created_at=datetime.now(UTC),
            safe_error_code="report_generation_failed" if status == "failed" else None,
        )
        result = _revision_dto(None, revision)
        assert result.status == status
        assert "translated_markdown" not in result.model_dump()
