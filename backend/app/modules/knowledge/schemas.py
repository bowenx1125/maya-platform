"""Provider-neutral knowledge API DTOs."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class KnowledgeDocument(BaseModel):
    id: UUID
    group_id: UUID
    source_filename: str
    source_owner_role: Literal["student", "teacher"]
    char_count: int = Field(ge=1)
    content_hash: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    index_revision: int = Field(ge=0)
    index_status: Literal["pending", "indexing", "ready", "failed"]
    workspace_state: Literal["active", "hidden"]
    safe_error_code: str | None = None
    created_at: datetime


class JobStatus(BaseModel):
    id: UUID
    kind: str
    status: Literal["pending", "running", "completed", "failed", "interrupted"]
    safe_error_code: str | None = None
