"""Closed provider-neutral M15 REST DTOs."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


TranslationBatchStatus = Literal["pending", "running", "completed", "partial", "failed"]
TranslationItemStatus = Literal["pending", "running", "ready", "failed"]


class TranslationItemSummary(ClosedModel):
    content_type: Literal["turn", "report_revision"]
    content_id: UUID
    source_text_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: TranslationItemStatus
    reused: bool
    safe_error_code: str | None = None


class TranslationBatchDTO(ClosedModel):
    id: UUID
    debate_id: UUID
    input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: TranslationBatchStatus
    target_language: Literal["zh-Hans"]
    quality: Literal["test_representation"]
    total_items: int = Field(ge=0)
    succeeded_items: int = Field(ge=0)
    failed_items: int = Field(ge=0)
    items: list[TranslationItemSummary]
    created_at: datetime
    updated_at: datetime


__all__ = [
    "ClosedModel",
    "TranslationBatchDTO",
    "TranslationBatchStatus",
    "TranslationItemStatus",
    "TranslationItemSummary",
]
