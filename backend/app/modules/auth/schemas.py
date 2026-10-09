"""Public authentication DTOs."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=128, json_schema_extra={"format": "password"})


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
    avatar: str | None = None
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
    avatar: str | None = None
    role: str


class UpdateCurrentUserRequest(BaseModel):
    avatar: str | None = Field(max_length=64)


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(max_length=128, json_schema_extra={"format": "password"})
    new_password: str = Field(max_length=128, json_schema_extra={"format": "password"})


class RegisterRequest(BaseModel):
    """Public self-registration input for a student account."""

    # Only the upper bounds are enforced here. Length/shape rejection lives in
    # the registration service so the client sees one stable 422 code
    # (``registration_invalid``) instead of a mix of 400 and 422 envelopes.
    username: str = Field(max_length=64)
    password: str = Field(max_length=128, json_schema_extra={"format": "password"})
    group_name: str = Field(max_length=200)
    display_name: str | None = Field(default=None, max_length=200)
    course_id: UUID | None = None


class RegistrationGroup(BaseModel):
    """A group a registering student may join, with no member identities."""

    name: str
    member_count: int = Field(ge=0)


class RegistrationOptions(BaseModel):
    """Server-decided options a registration form may present."""

    course_id: UUID
    course_name: str
    groups: list[RegistrationGroup]


class PasswordResetRequest(BaseModel):
    """Teacher-initiated password reset for one student in their course."""

    course_id: UUID
    user_id: UUID
    # Omit to let the server generate a short, read-aloud-safe password.
    new_password: str | None = Field(
        default=None,
        max_length=128,
        json_schema_extra={"format": "password"},
    )


class PasswordResetResult(BaseModel):
    """The value to hand to the student. Returned once and never stored."""

    user_id: UUID
    username: str
    display_name: str
    password: str = Field(json_schema_extra={"format": "password"})
