"""M15 translation persistence models.

The Wave 3 migration is owned by the main integration agent.  These models
describe the translation-owned tables so isolated service tests can use
``Base.metadata`` and the migration can import the same vocabulary.  No
relationship is declared to the report module: the exact content FK is
maintained by the additive migration and by the service's scoped queries.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base


class TranslationBatch(Base):
    """One teacher-triggered immutable input manifest and its item links."""

    __tablename__ = "translation_batches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    debate_id: Mapped[str] = mapped_column(String(36), nullable=False)
    course_id: Mapped[str] = mapped_column(String(36), nullable=False)
    requested_by: Mapped[str] = mapped_column(String(36), nullable=False)
    target_language: Mapped[str] = mapped_column(String(16), nullable=False)
    policy_key: Mapped[str] = mapped_column(String(80), nullable=False)
    quality_key: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    manifest_json: Mapped[str] = mapped_column(Text, nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    total_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    succeeded_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["debate_id", "course_id"],
            ["debates.id", "debates.course_id"],
            name="fk_translation_batches_debate_course",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["course_id", "requested_by"],
            ["course_members.course_id", "course_members.user_id"],
            name="fk_translation_batches_requester_course",
            ondelete="RESTRICT",
        ),
        CheckConstraint("target_language = 'zh-Hans'", name="ck_translation_batches_target"),
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'partial', 'failed')",
            name="ck_translation_batches_status",
        ),
        CheckConstraint("length(input_hash) = 64", name="ck_translation_batches_hash_shape"),
        CheckConstraint(
            "total_items >= 0 AND succeeded_items >= 0 AND failed_items >= 0",
            name="ck_translation_batches_counts_nonnegative",
        ),
        CheckConstraint(
            "(status IN ('pending', 'running') AND succeeded_items + failed_items <= total_items) "
            "OR (status = 'completed' AND total_items = succeeded_items AND failed_items = 0) "
            "OR (status = 'failed' AND total_items = failed_items AND succeeded_items = 0) "
            "OR (status = 'partial' AND total_items = succeeded_items + failed_items "
            "AND succeeded_items > 0 AND failed_items > 0)",
            name="ck_translation_batches_terminal_counts",
        ),
        UniqueConstraint("id", "debate_id", name="uq_translation_batches_id_debate"),
        Index(
            "uq_translation_batches_active_fence",
            "debate_id",
            "input_hash",
            "target_language",
            unique=True,
            sqlite_where=status.in_(("pending", "running")),
        ),
        Index("ix_translation_batches_debate_created", "debate_id", "created_at"),
    )


class TranslationEntry(Base):
    """Immutable global derived translation cache entry."""

    __tablename__ = "translation_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    debate_id: Mapped[str] = mapped_column(String(36), nullable=False)
    content_type: Mapped[str] = mapped_column(String(24), nullable=False)
    turn_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    report_revision_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source_text_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    target_language: Mapped[str] = mapped_column(String(16), nullable=False)
    policy_key: Mapped[str] = mapped_column(String(80), nullable=False)
    quality_key: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    translated_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    safe_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    @property
    def source_hash(self) -> str:
        """Compatibility vocabulary used by the internal cache key."""

        return self.source_text_hash

    __table_args__ = (
        ForeignKeyConstraint(
            ["turn_id", "debate_id"],
            ["debate_turns.id", "debate_turns.debate_id"],
            name="fk_translation_entries_turn_debate",
            ondelete="RESTRICT",
        ),
        # The report FK is intentionally kept out of ORM relationships while
        # the M14 model is developed in parallel.  The additive migration
        # creates this exact scoped constraint.
        ForeignKeyConstraint(
            ["report_revision_id", "debate_id"],
            ["civilization_report_revisions.id", "civilization_report_revisions.debate_id"],
            name="fk_translation_entries_report_revision",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "content_type IN ('turn', 'report_revision')",
            name="ck_translation_entries_content_type",
        ),
        CheckConstraint(
            "(content_type = 'turn' AND turn_id IS NOT NULL AND report_revision_id IS NULL) OR "
            "(content_type = 'report_revision' AND turn_id IS NULL "
            "AND report_revision_id IS NOT NULL)",
            name="ck_translation_entries_content_shape",
        ),
        CheckConstraint("target_language = 'zh-Hans'", name="ck_translation_entries_target"),
        CheckConstraint(
            "status IN ('pending', 'running', 'ready', 'failed')",
            name="ck_translation_entries_status",
        ),
        CheckConstraint(
            "status = 'ready' AND translated_text IS NOT NULL "
            "AND length(trim(translated_text)) > 0 AND safe_error_code IS NULL "
            "OR status = 'failed' AND translated_text IS NULL AND safe_error_code IS NOT NULL "
            "OR status IN ('pending', 'running') AND translated_text IS NULL "
            "AND safe_error_code IS NULL",
            name="ck_translation_entries_text_shape",
        ),
        UniqueConstraint("id", "debate_id", name="uq_translation_entries_id_debate"),
        Index(
            "uq_translation_entries_turn_ready_cache",
            "turn_id",
            "source_text_hash",
            "target_language",
            "policy_key",
            "quality_key",
            unique=True,
            sqlite_where=(status == "ready") & turn_id.is_not(None),
        ),
        Index(
            "uq_translation_entries_turn_active_cache",
            "turn_id",
            "source_text_hash",
            "target_language",
            "policy_key",
            "quality_key",
            unique=True,
            sqlite_where=status.in_(("pending", "running")) & turn_id.is_not(None),
        ),
        Index(
            "uq_translation_entries_report_ready_cache",
            "report_revision_id",
            "source_text_hash",
            "target_language",
            "policy_key",
            "quality_key",
            unique=True,
            sqlite_where=(status == "ready") & report_revision_id.is_not(None),
        ),
        Index(
            "uq_translation_entries_report_active_cache",
            "report_revision_id",
            "source_text_hash",
            "target_language",
            "policy_key",
            "quality_key",
            unique=True,
            sqlite_where=status.in_(("pending", "running")) & report_revision_id.is_not(None),
        ),
        Index("ix_translation_entries_debate", "debate_id"),
    )


class TranslationBatchItem(Base):
    """A batch's ordered relation to a cache entry."""

    __tablename__ = "translation_batch_items"

    batch_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    entry_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    debate_id: Mapped[str] = mapped_column(String(36), nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    reused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    safe_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["batch_id", "debate_id"],
            ["translation_batches.id", "translation_batches.debate_id"],
            name="fk_translation_batch_items_batch_debate",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["entry_id", "debate_id"],
            ["translation_entries.id", "translation_entries.debate_id"],
            name="fk_translation_batch_items_entry_debate",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("batch_id", "entry_id", name="uq_translation_batch_items_entry"),
        UniqueConstraint("batch_id", "order_index", name="uq_translation_batch_items_order"),
        CheckConstraint("order_index >= 0", name="ck_translation_batch_items_order"),
        CheckConstraint(
            "status IN ('pending', 'running', 'ready', 'failed')",
            name="ck_translation_batch_items_status",
        ),
        Index("ix_translation_batch_items_batch", "batch_id", "order_index"),
    )


__all__ = ["TranslationBatch", "TranslationBatchItem", "TranslationEntry"]
