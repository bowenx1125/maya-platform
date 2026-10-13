"""Organization DTOs.

The course and group projections are read-only.  The roster adds the one
teacher-facing write surface: it carries the account facts an edit depends
on, including which source provisions the account and therefore whether an
edit would survive the next restart.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class Member(BaseModel):
    user_id: UUID
    display_name: str
    avatar: str | None = None
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
    avatar: str | None = None
    role: str
    status: str
    # "catalog" or "database"; only the latter is editable.
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


class OverviewWork(BaseModel):
    id: UUID
    name: str
    visibility: str


class OverviewMember(BaseModel):
    """One student of the group and the work they made in it."""

    user_id: UUID
    display_name: str
    avatar: str | None = None
    agents: list[OverviewWork] = Field(default_factory=list)
    teams: list[OverviewWork] = Field(default_factory=list)
    rag_count: int = 0
    voice_count: int = 0


class OverviewQuestion(BaseModel):
    number: int
    prompt: str
    answers: list[str] = Field(default_factory=list)
    skipped: bool = False
    points_awarded: float | None = None
    points_total: float | None = None
    feedback: str = ""


class OverviewResult(BaseModel):
    """One formal test attempt by a group member, with its answer sheet."""

    attempt_id: UUID
    user_id: UUID
    student_name: str
    test_name: str
    team_name: str
    status: Literal["in_progress", "paused", "completed"]
    started_at: datetime
    ended_at: datetime | None = None
    points_awarded: float | None = None
    points_total: float | None = None
    questions: list[OverviewQuestion] = Field(default_factory=list)
    report_download_path: str | None = None


class OverviewEvent(BaseModel):
    kind: Literal[
        "agent_created",
        "agent_published",
        "team_created",
        "rag_added",
        "voice_added",
        "test_completed",
    ]
    at: datetime
    user_id: UUID
    display_name: str
    title: str


class GroupOverview(BaseModel):
    """What a group is doing, for a course teacher who has entered it."""

    group_id: UUID
    members: list[OverviewMember] = Field(default_factory=list)
    results: list[OverviewResult] = Field(default_factory=list)
    activity: list[OverviewEvent] = Field(default_factory=list)
