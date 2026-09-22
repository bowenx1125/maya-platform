from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base


class Conversation(Base):
    __tablename__ = "agent_conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    agent_version_id: Mapped[str] = mapped_column(
        ForeignKey("agent_versions.id", ondelete="RESTRICT")
    )
    snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_snapshots.id", ondelete="RESTRICT")
    )
    revision: Mapped[int] = mapped_column(Integer, default=0)
    active_request_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (CheckConstraint("revision >= 0"),)


class ConversationTurn(Base):
    __tablename__ = "agent_conversation_turns"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("agent_conversations.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    user_text: Mapped[str] = mapped_column(Text)
    assistant_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    sources_json: Mapped[str] = mapped_column(Text, default="[]")
    mode: Mapped[str] = mapped_column(String(8))
    state: Mapped[str] = mapped_column(String(24), default="pending")
    safe_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("mode IN ('real', 'mock')"),
        CheckConstraint("state IN ('pending', 'ready', 'failed', 'acceptance_unknown')"),
    )


class ProviderPreferences(Base):
    # Provider credentials are installation-wide, not readable course content.
    __tablename__ = "provider_preferences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    modes_json: Mapped[str] = mapped_column(Text, default="{}")
    encrypted_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    checks_json: Mapped[str] = mapped_column(Text, default="{}")
    __table_args__ = (CheckConstraint("id = 1 AND revision >= 0"),)


class LivePresence(Base):
    __tablename__ = "classroom_live_presence"

    course_id: Mapped[str] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), primary_key=True
    )
    debate_id: Mapped[str] = mapped_column(ForeignKey("debates.id", ondelete="CASCADE"))
    session_hash: Mapped[str] = mapped_column(String(64))
    lease_id: Mapped[str] = mapped_column(String(36))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
