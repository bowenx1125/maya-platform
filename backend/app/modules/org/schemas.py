"""Organization DTOs.

The course and group projections are read-only.  The roster adds the one
teacher-facing write surface: it carries the account facts an edit depends
on, including which source provisions the account and therefore whether an
edit would survive the next restart.
"""

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


class GroupRef(BaseModel):
    id: UUID
    name: str


class RosterEntry(BaseModel):
    """One course member as the teacher's account management view sees it."""

    user_id: UUID
    username: str
    display_name: str
    role: str
    status: str
    # "catalog", "observer" or "database"; only the last one is editable.
    source: str
    editable: bool
    groups: list[GroupRef] = Field(default_factory=list)


class CourseRoster(BaseModel):
    course_id: UUID
    entries: list[RosterEntry] = Field(default_factory=list)


class UpdateCourseMemberRequest(BaseModel):
    """A teacher's edit to one member; omitted fields are left untouched.

    Bounds stay in the service layer rather than in pydantic so a client sees
    one stable 422 member_update_invalid code instead of a mix of 400 and 422
    envelopes, matching the registration payloads.
    """

    display_name: str | None = None
    group_name: str | None = None
    status: str | None = None
