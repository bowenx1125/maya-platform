"""Public authentication DTOs."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    username: str
    password: str = Field(json_schema_extra={"format": "password"})


class CourseMembership(BaseModel):
    course_id: UUID
    role: Literal["teacher", "student"]


class GroupMembership(BaseModel):
    group_id: UUID
    role: Literal["leader", "admin", "member"]


class CurrentUser(BaseModel):
    id: UUID
    username: str
    display_name: str
    courses: list[CourseMembership]
    groups: list[GroupMembership]


class AuthSession(BaseModel):
    user: CurrentUser
    csrf_token: str = Field(min_length=32)
    expires_at: datetime


class DemoIdentity(BaseModel):
    user_id: UUID
    display_name: str
    role: Literal["teacher", "student"]


class DemoSwitchRequest(BaseModel):
    user_id: UUID


class DemoQuickLoginRequest(BaseModel):
    """Public selector for an identity from the safe Demo catalog."""

    user_id: UUID


class PublicMember(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    display_name: str
    role: str
