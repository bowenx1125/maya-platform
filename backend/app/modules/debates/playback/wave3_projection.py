"""Authoritative summary-only Wave 3 WebSocket snapshot projection."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import invalid_state
from app.modules.debates.models import DebateParticipant
from app.modules.interactions.models import (
    BarrageMessage,
    ClassroomInteractionWindow,
    InteractionFinalBarrage,
    InteractionFinalVoteCount,
    Vote,
)
from app.modules.reports.models import (
    BarrageInsightSnapshot,
    CivilizationReport,
    CivilizationReportCurrentSuccess,
    CivilizationReportRevision,
)


def wave3_snapshot_projection(db: Session, debate_id: str) -> dict[str, Any]:
    window = db.scalar(
        select(ClassroomInteractionWindow).where(
            ClassroomInteractionWindow.debate_id == debate_id
        )
    )
    if window is None:
        raise invalid_state("The classroom interaction window is unavailable.")
    participants = list(
        db.scalars(
            select(DebateParticipant)
            .where(DebateParticipant.debate_id == debate_id)
            .order_by(DebateParticipant.order_index, DebateParticipant.id)
        ).all()
    )
    if window.status == "finalized":
        counts = {
            row.participant_id: int(row.count)
            for row in db.scalars(
                select(InteractionFinalVoteCount).where(
                    InteractionFinalVoteCount.window_id == window.id,
                    InteractionFinalVoteCount.debate_id == debate_id,
                )
            ).all()
        }
        barrage_count = int(
            db.scalar(
                select(func.count(InteractionFinalBarrage.barrage_message_id)).where(
                    InteractionFinalBarrage.window_id == window.id,
                    InteractionFinalBarrage.debate_id == debate_id,
                )
            )
            or 0
        )
        if (
            set(counts) != {row.id for row in participants}
            or barrage_count != window.frozen_barrage_count
            or sum(counts.values()) != window.frozen_vote_count
        ):
            raise invalid_state("The finalized interaction summary is inconsistent.")
    else:
        counts = {row.id: 0 for row in participants}
        for participant_id, count in db.execute(
            select(Vote.participant_id, func.count(Vote.id))
            .where(Vote.window_id == window.id)
            .group_by(Vote.participant_id)
        ).all():
            if participant_id in counts:
                counts[str(participant_id)] = int(count)
        barrage_count = int(
            db.scalar(
                select(func.count(BarrageMessage.id)).where(BarrageMessage.window_id == window.id)
            )
            or 0
        )
    total_votes = sum(counts.values())
    vote_rows = [
        {
            "participant_id": participant.id,
            "count": counts[participant.id],
            "percentage": (
                round(counts[participant.id] * 1000 / total_votes) / 10 if total_votes else 0
            ),
        }
        for participant in participants
    ]

    insight = db.scalar(
        select(BarrageInsightSnapshot)
        .where(BarrageInsightSnapshot.debate_id == debate_id)
        .order_by(BarrageInsightSnapshot.revision_no.desc(), BarrageInsightSnapshot.id.desc())
    )
    insight_status = insight.status if insight is not None else "not_started"
    insight_summary = {
        "status": insight_status,
        "included_count": int(insight.included_count if insight is not None else 0),
        "filtered_count": int(insight.filtered_count if insight is not None else 0),
        "snapshot_id": insight.id if insight is not None else None,
        "revision": insight.revision_no if insight is not None else None,
    }

    report = db.scalar(
        select(CivilizationReport).where(CivilizationReport.debate_id == debate_id)
    )
    active_revision = db.scalar(
        select(CivilizationReportRevision).where(
            CivilizationReportRevision.debate_id == debate_id,
            CivilizationReportRevision.status == "generating",
        )
    )
    pointer = (
        db.scalar(
            select(CivilizationReportCurrentSuccess).where(
                CivilizationReportCurrentSuccess.report_id == report.id
            )
        )
        if report is not None
        else None
    )
    current_revision = (
        db.get(CivilizationReportRevision, pointer.revision_id) if pointer is not None else None
    )
    generation_status = report.generation_status if report is not None else "not_started"
    latest_status = report.latest_attempt_status if report is not None else "not_started"
    return {
        "interaction_status": window.status,
        "insight_status": insight_status,
        "report_status": generation_status,
        "interaction": {
            "status": window.status,
            "votes": vote_rows,
            "barrage_count": barrage_count,
            "total_votes": total_votes,
        },
        "report": {
            "generation_status": generation_status,
            "latest_attempt_status": latest_status,
            "insight": insight_summary,
            "active_revision_id": active_revision.id if active_revision is not None else None,
            "current_success_revision_id": (
                current_revision.id if current_revision is not None else None
            ),
            "current_success_word_count": (
                current_revision.word_count if current_revision is not None else None
            ),
        },
    }


__all__ = ["wave3_snapshot_projection"]
