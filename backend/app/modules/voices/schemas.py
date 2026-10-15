"""Provider-neutral M08 API schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from unicodedata import category
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints, field_validator

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
    scope: Literal["system", "group", "personal"]
    group_id: UUID | None = None
    status: VoiceStatus
    source_filename: str = ""
    safe_error_code: str | None = None
    created_at: datetime
    # Only the creator may rename, preview, confirm or delete; groupmates may
    # select a ready voice.
    can_manage: bool = True


class RenameVoiceProfileRequest(BaseModel):
    source_filename: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
    ]

    @field_validator("source_filename")
    @classmethod
    def safe_filename(cls, value: str) -> str:
        if value in {".", ".."} or any(char in "/\\" or category(char) == "Cc" for char in value):
            raise ValueError("Use a filename without path separators or control characters.")
        return value


class PlaybackResource(BaseModel):
    playback_url: str = Field(json_schema_extra={"format": "uri-reference"})
    expires_at: datetime


# The descriptive alias keeps route/service code readable while the class name
# remains exactly the frozen OpenAPI component name.
VoiceProfileResponse = VoiceProfile


SystemVoiceSegmentId = Literal["mandarin", "cantonese", "mixed", "numbers", "all"]


class SystemVoicePreviewRequest(BaseModel):
    segment_id: SystemVoiceSegmentId


class SystemVoiceScriptResponse(BaseModel):
    segment_id: Literal["mandarin", "cantonese", "mixed", "numbers"]
    voice: str
    language: str
    text: str
    expected_reading: str


class SystemVoicePreviewResponse(BaseModel):
    request_id: str
    segment_id: Literal["mandarin", "cantonese", "mixed", "numbers"]
    voice: str
    language: str
    text: str
    expected_reading: str
    playback_url: str = Field(json_schema_extra={"format": "uri-reference"})
    expires_at: datetime
    provider_request_id: str | None = None
    deduplicated: bool = False
