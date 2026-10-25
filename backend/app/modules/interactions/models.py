"""Wave 3 M13 persistence models.

These declarations are imported by the composition root before isolated
``create_all`` tests or Alembic metadata inspection.  The authoritative
deployment migration remains owned by the main window; this module only
defines the exact scoped table shape consumed by the interaction service.
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
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base


class ClassroomInteractionWindow(Base):
    __tablename__ = "classroom_interaction_windows"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    debate_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    course_id: Mapped[str] = mapped_column(String(36), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="closed")
    token_nonce: Mapped[bytes | None] = mapped_column(LargeBinary(32), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Last sequence handed to a barrage. Writers increment it in one statement
    # instead of reading MAX(sequence), which collides under Postgres.
    barrage_sequence: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    opened_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finalized_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    frozen_barrage_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    frozen_barrage_input_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    frozen_vote_totals_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    frozen_vote_input_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    frozen_barrage_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    frozen_vote_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["debate_id", "course_id"],
            ["debates.id", "debates.course_id"],
            name="fk_interaction_windows_debate_course",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["course_id", "opened_by"],
            ["course_members.course_id", "course_members.user_id"],
            name="fk_interaction_windows_opened_by_teacher",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["course_id", "finalized_by"],
            ["course_members.course_id", "course_members.user_id"],
            name="fk_interaction_windows_finalized_by_teacher",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("id", "debate_id", name="uq_interaction_windows_id_debate"),
        CheckConstraint(
            "status IN ('closed', 'open', 'finalized')",
            name="ck_interaction_windows_status",
        ),
        CheckConstraint("revision >= 0", name="ck_interaction_windows_revision"),
        CheckConstraint(
            "token_nonce IS NULL OR length(token_nonce) = 32",
            name="ck_interaction_windows_nonce_shape",
        ),
        CheckConstraint(
            "status <> 'closed' OR (token_nonce IS NULL AND opened_by IS NULL "
            "AND opened_at IS NULL "
            "AND finalized_by IS NULL AND finalized_at IS NULL AND frozen_barrage_ids_json IS NULL "
            "AND frozen_barrage_input_hash IS NULL AND frozen_vote_totals_json IS NULL "
            "AND frozen_vote_input_hash IS NULL AND frozen_barrage_count IS NULL "
            "AND frozen_vote_count IS NULL)",
            name="ck_interaction_windows_closed_shape",
        ),
        CheckConstraint(
            "status <> 'open' OR (token_nonce IS NOT NULL AND opened_by IS NOT NULL "
            "AND opened_at IS NOT NULL "
            "AND finalized_by IS NULL AND finalized_at IS NULL AND frozen_barrage_ids_json IS NULL "
            "AND frozen_barrage_input_hash IS NULL AND frozen_vote_totals_json IS NULL "
            "AND frozen_vote_input_hash IS NULL AND frozen_barrage_count IS NULL "
            "AND frozen_vote_count IS NULL)",
            name="ck_interaction_windows_open_shape",
        ),
        CheckConstraint(
            "status <> 'finalized' OR (token_nonce IS NOT NULL AND opened_by IS NOT NULL "
            "AND opened_at IS NOT NULL AND finalized_by IS NOT NULL "
            "AND finalized_at IS NOT NULL AND frozen_barrage_ids_json IS NOT NULL "
            "AND frozen_barrage_input_hash IS NOT NULL AND frozen_vote_totals_json IS NOT NULL "
            "AND frozen_vote_input_hash IS NOT NULL AND frozen_barrage_count IS NOT NULL "
            "AND frozen_vote_count IS NOT NULL)",
            name="ck_interaction_windows_finalized_shape",
        ),
        CheckConstraint(
            "frozen_barrage_count IS NULL OR frozen_barrage_count >= 0",
            name="ck_interaction_windows_barrage_count",
        ),
        CheckConstraint(
            "frozen_vote_count IS NULL OR frozen_vote_count >= 0",
            name="ck_interaction_windows_vote_count",
        ),
        Index("ix_interaction_windows_course_status", "course_id", "status"),
        Index("uq_interaction_windows_nonce", "token_nonce", unique=True),
    )


class Vote(Base):
    __tablename__ = "votes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    window_id: Mapped[str] = mapped_column(String(36), nullable=False)
    debate_id: Mapped[str] = mapped_column(String(36), nullable=False)
    participant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    client_submission_id: Mapped[str] = mapped_column(String(36), nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Server hash of window + audience id (0074): one vote per person.
    voter_key: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["window_id", "debate_id"],
            ["classroom_interaction_windows.id", "classroom_interaction_windows.debate_id"],
            name="fk_votes_window_debate",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["participant_id", "debate_id"],
            ["debate_participants.id", "debate_participants.debate_id"],
            name="fk_votes_participant_debate",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("window_id", "client_submission_id", name="uq_votes_window_submission"),
        Index("ix_votes_window_participant", "window_id", "participant_id"),
        Index(
            "uq_votes_window_voter",
            "window_id",
            "voter_key",
            unique=True,
            postgresql_where=text("voter_key IS NOT NULL"),
        ),
    )


class BarrageMessage(Base):
    __tablename__ = "barrage_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    window_id: Mapped[str] = mapped_column(String(36), nullable=False)
    debate_id: Mapped[str] = mapped_column(String(36), nullable=False)
    turn_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("debate_turns.id", ondelete="RESTRICT"), nullable=True
    )
    nickname: Mapped[str] = mapped_column(Text, nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    client_submission_id: Mapped[str] = mapped_column(String(36), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Server hash of window + audience id (0074): the per-person cooldown.
    voter_key: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["window_id", "debate_id"],
            ["classroom_interaction_windows.id", "classroom_interaction_windows.debate_id"],
            name="fk_barrage_messages_window_debate",
            ondelete="CASCADE",
        ),
        UniqueConstraint("id", "window_id", "debate_id", name="uq_barrage_messages_scoped_id"),
        UniqueConstraint(
            "window_id", "client_submission_id", name="uq_barrage_messages_window_submission"
        ),
        UniqueConstraint("window_id", "sequence", name="uq_barrage_messages_window_sequence"),
        CheckConstraint("length(trim(nickname)) > 0", name="ck_barrage_messages_nickname_nonblank"),
        CheckConstraint("length(trim(raw_text)) > 0", name="ck_barrage_messages_text_nonblank"),
        Index("ix_barrage_messages_window_sequence", "window_id", "sequence"),
        Index("ix_barrage_messages_window_voter", "window_id", "voter_key", "submitted_at"),
    )


class InteractionFinalVoteCount(Base):
    __tablename__ = "interaction_final_vote_counts"

    window_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    debate_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    participant_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["window_id", "debate_id"],
            ["classroom_interaction_windows.id", "classroom_interaction_windows.debate_id"],
            name="fk_final_votes_window_debate",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["participant_id", "debate_id"],
            ["debate_participants.id", "debate_participants.debate_id"],
            name="fk_final_votes_participant_debate",
            ondelete="RESTRICT",
        ),
        CheckConstraint("count >= 0", name="ck_final_votes_count"),
        UniqueConstraint("window_id", "participant_id", name="uq_final_votes_window_participant"),
    )


class InteractionFinalBarrage(Base):
    __tablename__ = "interaction_final_barrages"

    window_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    debate_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    barrage_message_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["window_id", "debate_id"],
            ["classroom_interaction_windows.id", "classroom_interaction_windows.debate_id"],
            name="fk_final_barrages_window_debate",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["barrage_message_id", "window_id", "debate_id"],
            ["barrage_messages.id", "barrage_messages.window_id", "barrage_messages.debate_id"],
            name="fk_final_barrages_message_scope",
            ondelete="RESTRICT",
        ),
        CheckConstraint("sequence >= 1", name="ck_final_barrages_sequence"),
        UniqueConstraint(
            "window_id", "barrage_message_id", name="uq_final_barrages_window_message"
        ),
        UniqueConstraint("window_id", "sequence", name="uq_final_barrages_window_sequence"),
    )


__all__ = [
    "BarrageMessage",
    "ClassroomInteractionWindow",
    "InteractionFinalBarrage",
    "InteractionFinalVoteCount",
    "Vote",
]
