"""Stable, provider-neutral avatar catalog DTOs."""

from __future__ import annotations

from pydantic import BaseModel


class AvatarTemplate(BaseModel):
    """A server-owned avatar preset and its editable capability names."""

    id: str
    name: str
    available: bool
    supported_parameters: list[str]
