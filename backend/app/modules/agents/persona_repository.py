"""SQLAlchemy adapter for the pure Persona confirmation service.

The adapter is deliberately thin: all grammar, hash and CAS policy lives in
``persona.py``/``persona_service.py``.  It only maps AgentVersion rows to the
typed port and applies one SQL revision/hash CAS without copying ``agent_md``.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.models import Agent, AgentVersion, CourseMember, Group, GroupMember
from app.modules.agents.persona import diagnostics_json
from app.modules.agents.persona_service import (
    PersonaCompilationWrite,
    PersonaConfirmationRequest,
    PersonaDomainError,
    PersonaStore,
    PersonaVersionState,
)


class SqlAlchemyPersonaStore(PersonaStore):
    """Map current AgentVersion rows to the PersonaStore protocol."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def get_persona_version(self, version_id: str) -> PersonaVersionState | None:
        row = self.db.execute(
            select(AgentVersion, Agent)
            .join(Agent, Agent.id == AgentVersion.agent_id)
            .where(AgentVersion.id == version_id)
        ).first()
        if row is None:
            return None
        version, agent = row
        return PersonaVersionState(
            version_id=version.id,
            agent_id=version.agent_id,
            group_id=agent.group_id,
            agent_name=agent.name,
            state=version.state,
            revision=version.revision,
            agent_md=version.agent_md,
            raw_agent_md_hash=version.raw_agent_md_hash,
            persona_spec_json=version.persona_spec_json,
            persona_spec_hash=version.persona_spec_hash,
            persona_compiler_version=version.persona_compiler_version,
            persona_confirmation_revision=version.persona_confirmation_revision,
            student_confirmed_at=version.student_confirmed_at,
            confirming_user_id=version.persona_confirming_user_id,
            persona_required=bool(getattr(version, "persona_required", True)),
        )

    def is_current_group_member(self, user_id: str, group_id: str) -> bool:
        return (
            self.db.scalar(
                select(GroupMember.user_id)
                .join(Group, Group.id == GroupMember.group_id)
                .join(CourseMember, CourseMember.course_id == Group.course_id)
                .where(
                    GroupMember.group_id == group_id,
                    GroupMember.user_id == user_id,
                    CourseMember.user_id == user_id,
                )
            )
            is not None
        )

    def save_persona_compilation(self, payload: PersonaCompilationWrite) -> PersonaVersionState:
        diagnostics = diagnostics_json(payload.diagnostics) if payload.diagnostics else None
        changed = self.db.execute(
            update(AgentVersion)
            .where(
                AgentVersion.id == payload.version_id,
                AgentVersion.state == "draft",
                AgentVersion.revision == payload.expected_revision,
            )
            .values(
                raw_agent_md_hash=payload.raw_agent_md_hash,
                persona_spec_json=payload.persona_spec_json,
                persona_spec_hash=payload.persona_spec_hash,
                persona_compiler_version=(
                    payload.compiler_version if payload.persona_spec_json is not None else None
                ),
                persona_diagnostics_json=diagnostics,
                persona_confirmation_revision=None,
                student_confirmed_at=None,
                persona_confirming_user_id=None,
            )
        )
        if getattr(changed, "rowcount", 0) != 1:
            current = self.db.scalar(
                select(AgentVersion.revision).where(AgentVersion.id == payload.version_id)
            )
            if current is None:
                raise PersonaDomainError(
                    "persona_version_not_found", "The Agent version was not found."
                )
            raise PersonaDomainError(
                "stale_revision",
                "The Agent draft revision is stale.",
                {"current_revision": current},
            )
        self.db.flush()
        state = self.get_persona_version(payload.version_id)
        if state is None:  # pragma: no cover - guarded by the UPDATE
            raise PersonaDomainError(
                "persona_version_not_found", "The Agent version was not found."
            )
        return state

    def confirm_persona(
        self,
        request: PersonaConfirmationRequest,
        confirming_user_id: str,
    ) -> PersonaVersionState:
        timestamp = datetime.now(UTC)
        changed = self.db.execute(
            update(AgentVersion)
            .where(
                AgentVersion.id == request.version_id,
                AgentVersion.state == "draft",
                AgentVersion.revision == request.expected_revision,
                AgentVersion.raw_agent_md_hash == request.raw_agent_md_hash,
                AgentVersion.persona_spec_hash == request.persona_spec_hash,
                AgentVersion.persona_compiler_version == request.compiler_version,
                AgentVersion.persona_spec_json.is_not(None),
            )
            .values(
                persona_confirmation_revision=AgentVersion.revision,
                student_confirmed_at=timestamp,
                persona_confirming_user_id=confirming_user_id,
            )
        )
        if getattr(changed, "rowcount", 0) != 1:
            state = self.get_persona_version(request.version_id)
            if state is None:
                raise PersonaDomainError(
                    "persona_version_not_found", "The Agent version was not found."
                )
            raise PersonaDomainError(
                "persona_confirmation_required",
                "The Persona draft changed; review and confirm the current preview again.",
                {"current_revision": state.revision},
            )
        self.db.flush()
        state = self.get_persona_version(request.version_id)
        if state is None:  # pragma: no cover - guarded by the UPDATE
            raise PersonaDomainError(
                "persona_version_not_found", "The Agent version was not found."
            )
        return state


__all__ = ["SqlAlchemyPersonaStore"]
