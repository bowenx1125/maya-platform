from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base


class RuntimeModelCallStage(Base):
    """Exact Single model calls retain envelopes before any Tool side effect."""

    __tablename__ = "runtime_model_call_stages"

    operation_id: Mapped[str] = mapped_column(
        ForeignKey("provider_operations.id", ondelete="RESTRICT"), primary_key=True
    )
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("agent_conversations.id", ondelete="RESTRICT")
    )
    turn_id: Mapped[str] = mapped_column(
        ForeignKey("agent_conversation_turns.id", ondelete="RESTRICT")
    )
    executor_agent_version_id: Mapped[str] = mapped_column(
        ForeignKey("agent_versions.id", ondelete="RESTRICT")
    )
    ordinal: Mapped[int] = mapped_column()
    dispatch_ordinal: Mapped[int] = mapped_column()
    request_hash: Mapped[str] = mapped_column(String(64))
    request_json: Mapped[str] = mapped_column(Text)
    accepted_response_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    accepted_response_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "turn_id", "executor_agent_version_id", "ordinal", name="uq_runtime_model_stage_ordinal"
        ),
        CheckConstraint("ordinal >= 0", name="ck_runtime_model_stage_ordinal"),
        CheckConstraint("dispatch_ordinal >= 0", name="ck_runtime_model_stage_dispatch_ordinal"),
        CheckConstraint("length(request_hash)=64", name="ck_runtime_model_stage_request_hash"),
        CheckConstraint(
            "(accepted_response_json IS NULL AND accepted_response_hash IS NULL "
            "AND accepted_at IS NULL) OR "
            "(accepted_response_json IS NOT NULL AND accepted_response_hash IS NOT NULL "
            "AND length(accepted_response_hash)=64 AND accepted_at IS NOT NULL)",
            name="ck_runtime_model_stage_accepted_pair",
        ),
    )


class RuntimeToolReceipt(Base):
    __tablename__ = "runtime_tool_receipts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    actor_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("agent_conversations.id", ondelete="RESTRICT")
    )
    turn_id: Mapped[str] = mapped_column(
        ForeignKey("agent_conversation_turns.id", ondelete="RESTRICT")
    )
    model_operation_id: Mapped[str] = mapped_column(
        ForeignKey("provider_operations.id", ondelete="RESTRICT")
    )
    tool_call_id: Mapped[str] = mapped_column(Text)
    tool_name: Mapped[str] = mapped_column(String(80))
    request_hash: Mapped[str] = mapped_column(String(64))
    result_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("model_operation_id", "tool_call_id", name="uq_runtime_tool_call_receipt"),
    )
