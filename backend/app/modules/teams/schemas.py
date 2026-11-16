"""HTTP schemas for immutable Teams and their course directory projection."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


TeamVisibility = Literal["private", "public"]
TeamOwnershipScope = Literal["personal", "group"]
TeamPublicationState = Literal["published", "unpublished"]


class TeamMemberInput(StrictModel):
    agent_version_id: UUID
    is_leader: bool = False
    position: int = Field(ge=0)


class TeamDefinitionInput(StrictModel):
    display_name: str = Field(min_length=1)
    visibility: TeamVisibility
    members: list[TeamMemberInput]
    shared_knowledge_set_ids: list[UUID] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_member_relations(self) -> TeamDefinitionInput:
        if len(self.members) < 2:
            raise ValueError("A Team requires at least two different Agent versions.")
        version_ids = [member.agent_version_id for member in self.members]
        positions = [member.position for member in self.members]
        if len(version_ids) != len(set(version_ids)):
            raise ValueError("A Team cannot contain the same Agent version twice.")
        if len(positions) != len(set(positions)):
            raise ValueError("Team member positions must be unique.")
        if sum(member.is_leader for member in self.members) != 1:
            raise ValueError("A Team requires exactly one Leader.")
        set_ids = [str(set_id) for set_id in self.shared_knowledge_set_ids]
        if len(set_ids) != len(set(set_ids)):
            raise ValueError("A Knowledge Set can only be bound once.")
        return self


class CreateTeamRequest(TeamDefinitionInput):
    group_id: UUID | None = None


class SaveTeamVersionRequest(TeamDefinitionInput):
    expected_metadata_revision: int = Field(ge=0)


class TeamMemberDTO(StrictModel):
    id: UUID
    agent_id: UUID
    agent_version_id: UUID
    display_name: str
    avatar_config: dict[str, object]
    position: int = Field(ge=0)
    is_leader: bool


class TeamFaceMember(StrictModel):
    """One face on a Team card: the member's Agent and its frozen avatar theme."""

    # Null once the Agent itself is deleted (the Team version keeps its snapshot).
    agent_id: UUID | None
    # avatar_config.material_theme of the Team version's member snapshot.
    material_theme: str | None
    is_leader: bool


class TeamSummary(StrictModel):
    id: UUID
    course_id: UUID
    owner_user_id: UUID
    ownership_scope: TeamOwnershipScope
    group_id: UUID | None
    display_name: str
    visibility: TeamVisibility
    metadata_revision: int = Field(ge=0)
    authorization_epoch: int = Field(ge=0)
    current_version_id: UUID
    current_version_seq: int = Field(ge=1)
    member_count: int = Field(ge=2)
    can_edit: bool
    # Same rule as DELETE /teams/{team_id}: the owner, still in the course and,
    # for a group Team, still inside that group.
    can_delete: bool
    # Owner holds CourseMember.role == teacher in this course. Optional so
    # older clients keep working; the Studyform sticker reads "Teacher".
    is_teacher_owned: bool | None = None
    updated_at: datetime
    # No per-edit author is stored; only the owner can edit, so this is the
    # owner's display name (null when the owner account is gone).
    last_edited_by_name: str | None
    # Up to four members of the current version, Leader first, then by position.
    members: list[TeamFaceMember] = Field(max_length=4)


class SharedKnowledgeSetDTO(StrictModel):
    id: UUID
    display_name: str


class TeamDetail(TeamSummary):
    created_at: datetime
    # Detail keeps its full member list; the summary's card faces are not repeated.
    members: list[TeamMemberDTO]  # type: ignore[assignment]
    shared_knowledge_set_ids: list[UUID]
    shared_knowledge_sets: list[SharedKnowledgeSetDTO] = Field(default_factory=list)
    publication_state: TeamPublicationState


class DirectoryMemberDTO(StrictModel):
    display_name: str
    avatar_config: dict[str, object]
    position: int = Field(ge=0)
    is_leader: bool


class MayaTeamDirectoryEntry(StrictModel):
    id: UUID
    team_version_id: UUID
    course_id: UUID
    display_name: str
    leader_display_name: str
    members: list[DirectoryMemberDTO]
    published_at: datetime
