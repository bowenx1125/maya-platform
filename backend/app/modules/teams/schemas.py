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


class SharedKnowledgeSetDTO(StrictModel):
    id: UUID
    display_name: str


class TeamDetail(TeamSummary):
    created_at: datetime
    updated_at: datetime
    members: list[TeamMemberDTO]
    shared_knowledge_set_ids: list[UUID]
    shared_knowledge_sets: list[SharedKnowledgeSetDTO] = Field(default_factory=list)
    publication_state: TeamPublicationState


class TeamVersionDTO(StrictModel):
    id: UUID
    team_id: UUID
    version_seq: int = Field(ge=1)
    display_name: str
    visibility: TeamVisibility
    authorization_epoch: int = Field(ge=0)
    members: list[TeamMemberDTO]
    shared_knowledge_set_ids: list[UUID]
    created_at: datetime


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
