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
    char_count: int = Field(ge=1)
    index_status: Literal["pending", "indexing", "ready", "failed"]
    workspace_state: Literal["active", "hidden"]
    safe_error_code: str | None = None
    created_at: datetime


class JobStatus(BaseModel):
    id: UUID
    kind: str
    status: Literal["pending", "running", "completed", "failed", "interrupted"]
    safe_error_code: str | None = None
