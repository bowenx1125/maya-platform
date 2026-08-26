"""Read-only organization DTOs."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field


class Member(BaseModel):
    user_id: UUID
    display_name: str
    role: str


class Course(BaseModel):
    id: UUID
    code: str
    name: str
    current_audio_debate_id: UUID | None = None


class CourseDetail(Course):
    # The frozen allOf contract leaves members optional, while the route still
    # always supplies it in current responses.
    members: list[Member] = Field(default_factory=list)


class Group(BaseModel):
    id: UUID
    course_id: UUID
    name: str


class GroupDetail(Group):
    members: list[Member] = Field(default_factory=list)
