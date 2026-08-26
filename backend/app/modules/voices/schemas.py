"""Provider-neutral M08 API schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

VoiceStatus = Literal[
    "validating",
    "enrolling",
    "preview_ready",
    "ready",
    "deleting",
    "outcome_unknown",
    "failed",
    "deleted",
]


class VoiceProfile(BaseModel):
    id: UUID
    scope: Literal["system", "group"]
    group_id: UUID | None = None
    status: VoiceStatus
    source_filename: str = ""
    safe_error_code: str | None = None
    created_at: datetime


class PlaybackResource(BaseModel):
    playback_url: str = Field(json_schema_extra={"format": "uri-reference"})
    expires_at: datetime


# The descriptive alias keeps route/service code readable while the class name
# remains exactly the frozen OpenAPI component name.
VoiceProfileResponse = VoiceProfile
