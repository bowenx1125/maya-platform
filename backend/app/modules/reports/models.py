"""SQLAlchemy persistence models for the M14 derived report domain.

The 0007 migration is owned by the main agent.  These declarations mirror
that additive schema so isolated tests can use ``Base.metadata.create_all``
and the application can import one canonical ORM shape.  Raw interaction
tables are referenced by scoped foreign keys but are deliberately not modeled
here; M13 owns those records and their anonymous boundary.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.models import Base


class BarrageInsightSnapshot(Base):
    __tablename__ = "barrage_insight_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    window_id: Mapped[str] = mapped_column(String(36), nullable=False)
    debate_id: Mapped[str] = mapped_column(String(36), nullable=False)
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    policy_key: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    included_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    filtered_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    safe_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    items: Mapped[list[BarrageInsightItem]] = relationship(
        back_populates="snapshot",
        cascade="all, delete-orphan",
        order_by="BarrageInsightItem.order_index",
    )
    assignments: Mapped[list[BarrageInsightAssignment]] = relationship(
        back_populates="snapshot",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["window_id", "debate_id"],
            ["classroom_interaction_windows.id", "classroom_interaction_windows.debate_id"],
            name="fk_barrage_insight_snapshots_window_debate",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["debate_id"],
            ["debates.id"],
            name="fk_barrage_insight_snapshots_debate",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "id",
            "window_id",
            "debate_id",
            name="uq_barrage_insight_snapshots_id_window_debate",
        ),
        UniqueConstraint(
            "id",
            "debate_id",
            name="uq_barrage_insight_snapshots_id_debate",
        ),
        UniqueConstraint(
            "debate_id",
            "revision_no",
            name="uq_barrage_insight_snapshots_debate_revision",
        ),
        CheckConstraint(
            "status IN ('generating', 'ready', 'failed')",
            name="ck_barrage_insight_snapshots_status",
        ),
        CheckConstraint(
            "attempt >= 1 AND attempt <= 2", name="ck_barrage_insight_snapshots_attempt"
        ),
        CheckConstraint("included_count >= 0", name="ck_barrage_insight_snapshots_included_count"),
        CheckConstraint("filtered_count >= 0", name="ck_barrage_insight_snapshots_filtered_count"),
        CheckConstraint(
            "length(input_hash) = 64 AND input_hash NOT GLOB '*[^0-9a-f]*'",
            name="ck_barrage_insight_snapshots_input_hash",
        ),
        CheckConstraint(
            "status != 'generating' OR (included_count = 0 AND filtered_count = 0 "
            "AND safe_error_code IS NULL)",
            name="ck_barrage_insight_snapshots_generating_shape",
        ),
        CheckConstraint(
            "status != 'ready' OR safe_error_code IS NULL",
            name="ck_barrage_insight_snapshots_ready_error",
        ),
        CheckConstraint(
            "status != 'failed' OR (included_count = 0 AND filtered_count = 0 "
            "AND safe_error_code IS NOT NULL)",
            name="ck_barrage_insight_snapshots_failed_error",
        ),
        Index(
            "ix_barrage_insight_snapshots_active",
            "debate_id",
            unique=True,
            sqlite_where=(status == "generating"),
        ),
        Index("ix_barrage_insight_snapshots_debate", "debate_id", "revision_no"),
    )


class BarrageInsightItem(Base):
    __tablename__ = "barrage_insight_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(String(36), nullable=False)
    window_id: Mapped[str] = mapped_column(String(36), nullable=False)
    debate_id: Mapped[str] = mapped_column(String(36), nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[str] = mapped_column(String(16), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)

    snapshot: Mapped[BarrageInsightSnapshot] = relationship(back_populates="items")

    __table_args__ = (
        ForeignKeyConstraint(
            ["snapshot_id", "window_id", "debate_id"],
            [
                "barrage_insight_snapshots.id",
                "barrage_insight_snapshots.window_id",
                "barrage_insight_snapshots.debate_id",
            ],
            name="fk_barrage_insight_items_snapshot_scope",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "id",
            "snapshot_id",
            "window_id",
            "debate_id",
            name="uq_barrage_insight_items_id_snapshot_scope",
        ),
        UniqueConstraint(
            "snapshot_id",
            "order_index",
            name="uq_barrage_insight_items_snapshot_order",
        ),
        CheckConstraint("order_index >= 0", name="ck_barrage_insight_items_order"),
        CheckConstraint(
            "category IN ('support', 'challenge', 'question')",
            name="ck_barrage_insight_items_category",
        ),
        CheckConstraint("length(trim(summary)) > 0", name="ck_barrage_insight_items_summary"),
        Index("ix_barrage_insight_items_snapshot", "snapshot_id", "order_index"),
    )


class BarrageInsightAssignment(Base):
    """One and only one disposition for every frozen BarrageMessage."""

    __tablename__ = "barrage_insight_assignments"

    snapshot_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    window_id: Mapped[str] = mapped_column(String(36), nullable=False)
    debate_id: Mapped[str] = mapped_column(String(36), nullable=False)
    barrage_message_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    disposition: Mapped[str] = mapped_column(String(16), nullable=False)
    item_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    filter_reason: Mapped[str | None] = mapped_column(String(120), nullable=True)

    snapshot: Mapped[BarrageInsightSnapshot] = relationship(back_populates="assignments")

    __table_args__ = (
        ForeignKeyConstraint(
            ["snapshot_id", "window_id", "debate_id"],
            [
                "barrage_insight_snapshots.id",
                "barrage_insight_snapshots.window_id",
                "barrage_insight_snapshots.debate_id",
            ],
            name="fk_barrage_insight_assignments_snapshot_scope",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["barrage_message_id", "window_id", "debate_id"],
            [
                "barrage_messages.id",
                "barrage_messages.window_id",
                "barrage_messages.debate_id",
            ],
            name="fk_barrage_insight_assignments_barrage_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["item_id", "snapshot_id", "window_id", "debate_id"],
            [
                "barrage_insight_items.id",
                "barrage_insight_items.snapshot_id",
                "barrage_insight_items.window_id",
                "barrage_insight_items.debate_id",
            ],
            name="fk_barrage_insight_assignments_item_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "snapshot_id",
            "barrage_message_id",
            name="uq_barrage_insight_assignments_snapshot_message",
        ),
        CheckConstraint(
            "disposition IN ('included', 'filtered')",
            name="ck_barrage_insight_assignments_disposition",
        ),
        CheckConstraint(
            "(disposition = 'included' AND item_id IS NOT NULL AND filter_reason IS NULL) OR "
            "(disposition = 'filtered' AND item_id IS NULL AND "
            "filter_reason LIKE 'mock_barrage_insight_v1:%')",
            name="ck_barrage_insight_assignments_shape",
        ),
        Index("ix_barrage_insight_assignments_snapshot", "snapshot_id"),
    )


class CivilizationReport(Base):
    __tablename__ = "civilization_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    debate_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("debates.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    generation_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="not_started"
    )
    latest_attempt_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="not_started"
    )
    policy_key: Mapped[str] = mapped_column(
        String(80), nullable=False, default="mock_maya_report_v1"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    revisions: Mapped[list[CivilizationReportRevision]] = relationship(
        back_populates="report",
        cascade="all, delete-orphan",
        order_by="CivilizationReportRevision.revision_no",
    )
    current_success: Mapped[CivilizationReportCurrentSuccess | None] = relationship(
        back_populates="report",
        uselist=False,
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint(
            "generation_status IN ('not_started', 'generating', 'ready', 'failed')",
            name="ck_civilization_reports_generation_status",
        ),
        CheckConstraint(
            "latest_attempt_status IN ('not_started', 'generating', 'ready', 'failed')",
            name="ck_civilization_reports_latest_status",
        ),
        UniqueConstraint("id", "debate_id", name="uq_civilization_reports_id_debate"),
        Index("ix_civilization_reports_debate", "debate_id", unique=True),
    )


class CivilizationReportRevision(Base):
    __tablename__ = "civilization_report_revisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    report_id: Mapped[str] = mapped_column(String(36), nullable=False)
    debate_id: Mapped[str] = mapped_column(String(36), nullable=False)
    insight_snapshot_id: Mapped[str] = mapped_column(String(36), nullable=False)
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    input_manifest_json: Mapped[str] = mapped_column(Text, nullable=False)
    input_manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    english_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    safe_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    trigger: Mapped[str] = mapped_column(String(32), nullable=False, default="automatic")
    requested_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    report: Mapped[CivilizationReport] = relationship(back_populates="revisions")

    __table_args__ = (
        ForeignKeyConstraint(
            ["report_id", "debate_id"],
            ["civilization_reports.id", "civilization_reports.debate_id"],
            name="fk_civilization_report_revisions_report_debate",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["insight_snapshot_id", "debate_id"],
            ["barrage_insight_snapshots.id", "barrage_insight_snapshots.debate_id"],
            name="fk_civilization_report_revisions_insight_debate",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "id", "report_id", "debate_id", name="uq_civilization_report_revisions_id_scope"
        ),
        # The current-success pointer references the exact ready status in
        # the same child-column order; SQLite requires this parent key to be
        # explicitly unique before it will accept the composite FK.
        UniqueConstraint(
            "id",
            "report_id",
            "debate_id",
            "status",
            name="uq_civilization_report_revisions_id_scope_status",
        ),
        UniqueConstraint("id", "debate_id", name="uq_civilization_report_revisions_id_debate"),
        UniqueConstraint(
            "report_id", "revision_no", name="uq_civilization_report_revisions_report_revision"
        ),
        CheckConstraint(
            "status IN ('generating', 'ready', 'failed')",
            name="ck_civilization_report_revisions_status",
        ),
        CheckConstraint(
            "attempt >= 1 AND attempt <= 2", name="ck_civilization_report_revisions_attempt"
        ),
        CheckConstraint(
            "status != 'ready' OR (english_markdown IS NOT NULL AND word_count IS NOT NULL "
            "AND word_count >= 0 AND safe_error_code IS NULL)",
            name="ck_civilization_report_revisions_ready_shape",
        ),
        CheckConstraint(
            "status != 'failed' OR (english_markdown IS NULL AND word_count IS NULL "
            "AND safe_error_code IS NOT NULL)",
            name="ck_civilization_report_revisions_failed_shape",
        ),
        CheckConstraint(
            "status != 'generating' OR (english_markdown IS NULL AND word_count IS NULL "
            "AND safe_error_code IS NULL)",
            name="ck_civilization_report_revisions_generating_shape",
        ),
        CheckConstraint(
            "length(input_manifest_hash) = 64 AND input_manifest_hash NOT GLOB '*[^0-9a-f]*'",
            name="ck_civilization_report_revisions_input_hash",
        ),
        Index(
            "ix_civilization_report_revisions_active",
            "debate_id",
            unique=True,
            sqlite_where=(status == "generating"),
        ),
        Index("ix_civilization_report_revisions_debate", "debate_id", "revision_no"),
    )


class CivilizationReportCurrentSuccess(Base):
    __tablename__ = "civilization_report_current_success"

    report_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    revision_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    debate_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    revision_status: Mapped[str] = mapped_column(String(16), nullable=False, default="ready")

    report: Mapped[CivilizationReport] = relationship(back_populates="current_success")

    __table_args__ = (
        ForeignKeyConstraint(
            ["revision_id", "report_id", "debate_id", "revision_status"],
            [
                "civilization_report_revisions.id",
                "civilization_report_revisions.report_id",
                "civilization_report_revisions.debate_id",
                "civilization_report_revisions.status",
            ],
            name="fk_civilization_report_current_success_ready_revision",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["report_id", "debate_id"],
            ["civilization_reports.id", "civilization_reports.debate_id"],
            name="fk_civilization_report_current_success_report_debate",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "revision_status = 'ready'", name="ck_civilization_report_current_success_ready"
        ),
        UniqueConstraint(
            "revision_id",
            "report_id",
            "debate_id",
            "revision_status",
            name="uq_civilization_report_current_success_scope",
        ),
    )


__all__ = [
    "BarrageInsightAssignment",
    "BarrageInsightItem",
    "BarrageInsightSnapshot",
    "CivilizationReport",
    "CivilizationReportCurrentSuccess",
    "CivilizationReportRevision",
]
