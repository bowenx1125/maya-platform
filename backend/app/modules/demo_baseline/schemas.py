"""Closed browser-safe Demo baseline and composition DTOs."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DemoSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


DemoComponentMode = Literal["real", "mock"]


class DemoComponent(DemoSchema):
    key: Literal["embedding", "llm", "tts", "voice", "translation", "report"]
    label: str = Field(min_length=1)
    mode: DemoComponentMode


class DemoComposition(DemoSchema):
    """Only the modes and display labels the browser needs to show."""

    components: tuple[DemoComponent, ...]


class DemoBaseline(DemoSchema):
    agent_id: UUID
    version_id: UUID
    snapshot_id: UUID
    group_id: UUID
    system_baseline: Literal[True] = True
    immutable: Literal[True] = True
    usable: bool


class DemoRuntimeStatus(DemoSchema):
    baseline: DemoBaseline
    composition: DemoComposition
    dirty_agents: int = Field(ge=0)
    dirty_debates: int = Field(ge=0)
    dirty_interactions: int = Field(ge=0)
