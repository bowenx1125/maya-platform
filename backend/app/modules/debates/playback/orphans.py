"""Reclaim Debate/report jobs whose backend died while a peer kept serving.

Used instead of the full startup recovery when another backend replica is
alive (see ``app.core.replica``): only the given job ids are touched, with
the same outcomes the full recovery gives them.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import bindparam, text

from app.modules.reports.service import recover_report_jobs

REPORT_OPERATIONS = ("barrage_insight.generate", "report.generate")


def recover_orphan_debate_jobs(db: Any, job_ids: Iterable[str]) -> int:
    ids = tuple(sorted(set(job_ids)))
    if not ids:
        return 0
    now = datetime.now(UTC)
    rows = (
        db.execute(
            text(
                "SELECT j.id, j.debate_id, j.turn_id, j.operation, "
                "COALESCE(ps.status,'') AS playback_status, COALESCE(d.status,'') AS debate_status "
                "FROM jobs AS j LEFT JOIN debates AS d ON d.id=j.debate_id "
                "LEFT JOIN playback_states AS ps ON ps.debate_id=j.debate_id "
                "WHERE j.id IN :ids AND j.state='running'"
            ).bindparams(bindparam("ids", expanding=True)),
            {"ids": ids},
        )
        .mappings()
        .all()
    )
    report_ids = [str(r["id"]) for r in rows if r["operation"] in REPORT_OPERATIONS]
    count = recover_report_jobs(db, only_job_ids=report_ids) if report_ids else 0
    for row in rows:
        if row["operation"] in REPORT_OPERATIONS or not row["turn_id"]:
            continue
        paused = row["playback_status"] == "paused" and row["debate_status"] == "running"
        params = {"job": row["id"], "turn": row["turn_id"], "debate": row["debate_id"], "now": now}
        if paused:
            # An explicit Pause survives: the turn is prepared again on Continue.
            db.execute(
                text(
                    "UPDATE jobs SET state='pending', claim_token=NULL, safe_error_code=NULL, "
                    "updated_at=:now WHERE id=:job"
                ),
                params,
            )
            db.execute(
                text(
                    "UPDATE debate_turns SET generation_status='pending', "
                    "preparation_stage='generation', safe_error_code=NULL, updated_at=:now "
                    "WHERE id=:turn AND generation_status IN ('pending','running')"
                ),
                params,
            )
        else:
            db.execute(
                text(
                    "UPDATE debate_turns SET generation_status='failed', "
                    "preparation_stage='failed', safe_error_code='process_restarted', "
                    "updated_at=:now WHERE id=:turn AND generation_status IN ('pending','running')"
                ),
                params,
            )
            db.execute(
                text(
                    "UPDATE jobs SET state='interrupted', safe_error_code='process_restarted', "
                    "updated_at=:now WHERE id=:job"
                ),
                params,
            )
            db.execute(
                text(
                    "UPDATE debates SET status='failed', updated_at=:now "
                    "WHERE id=:debate AND status='running'"
                ),
                params,
            )
            db.execute(
                text(
                    "UPDATE playback_states SET status='stopped', cursor_ms=0, "
                    "control_version=control_version+1, controller_epoch=NULL, "
                    "controller_owner_connection=NULL, server_started_at=NULL, "
                    "updated_at=:now WHERE debate_id=:debate"
                ),
                params,
            )
        count += 1
    return count


__all__ = ["recover_orphan_debate_jobs"]
