"""Closed, provider-neutral DTOs for classroom interaction."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VoteAggregate(ClosedModel):
    participant_id: UUID
    count: int = Field(ge=0)
    percentage: float = Field(ge=0, le=100)


class BarrageMessage(ClosedModel):
    id: UUID
    nickname: str
    raw_text: str
    sequence: int = Field(ge=1)
    submitted_at: datetime


class TeacherInteractionClosed(ClosedModel):
    status: Literal["closed"]
    public_url: None
    votes: list[VoteAggregate]
    barrages: list[BarrageMessage]


class TeacherInteractionOpen(ClosedModel):
    status: Literal["open"]
    public_url: str
    votes: list[VoteAggregate]
    barrages: list[BarrageMessage]


class TeacherInteractionFinalized(ClosedModel):
    status: Literal["finalized"]
    public_url: None
    votes: list[VoteAggregate]
    barrages: list[BarrageMessage]


TeacherInteraction = Annotated[
    TeacherInteractionClosed | TeacherInteractionOpen | TeacherInteractionFinalized,
    Field(discriminator="status"),
]


class PublicInteractionParticipant(ClosedModel):
    participant_id: UUID
    slot: Literal["A", "B", "C", "D", "E"]
    name: str


class PublicInteractionForm(ClosedModel):
    topic: str
    participants: list[PublicInteractionParticipant]


class VoteRequest(ClosedModel):
    participant_id: UUID
    client_submission_id: UUID


class BarrageRequest(ClosedModel):
    nickname: str = Field(min_length=1)
    raw_text: str = Field(min_length=1)
    client_submission_id: UUID


class VoteSubmitted(ClosedModel):
    vote_submitted: Literal[True]


class BarrageSubmitted(ClosedModel):
    barrage_submitted: Literal[True]


__all__ = [
    "BarrageMessage",
    "BarrageRequest",
    "BarrageSubmitted",
    "PublicInteractionForm",
    "PublicInteractionParticipant",
    "TeacherInteraction",
    "TeacherInteractionClosed",
    "TeacherInteractionFinalized",
    "TeacherInteractionOpen",
    "VoteAggregate",
    "VoteRequest",
    "VoteSubmitted",
]
