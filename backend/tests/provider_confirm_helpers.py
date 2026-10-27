"""Service-level stand-ins for the removed Provider disclosure HTTP routes.

Tests that need an explicit chat/Team standing grant or an exact disclosure
confirmation as *setup* call the same internal service functions the removed
routes called, so sending-guard coverage is unchanged.
"""

from __future__ import annotations

from typing import Any

from app.modules.provider_disclosure.schemas import ProviderDataCallConfirmationRequestV1
from app.modules.provider_disclosure.service import (
    ProviderDisclosureService,
    SqlAlchemyProviderDisclosureStore,
    prepare_chat_standing_disclosure,
)
from app.modules.provider_disclosure.team_standing import (
    StandingGrantPlan,
    confirm_team_standing_grant,
    prepare_team_standing_grant,
)
from app.modules.workspace.models import TeamProviderStandingGrant


def chat_standing_disclosure(
    database: Any,
    actor_user_id: str,
    *,
    course_id: str,
    policy_hash: str,
    provider_operation: str = "llm_agent_chat",
) -> dict[str, Any]:
    with database.session() as db:
        response = prepare_chat_standing_disclosure(
            db,
            actor_user_id=actor_user_id,
            course_id=course_id,
            policy_hash=policy_hash,
            provider_operation=provider_operation,
        )
        return response.model_dump(mode="json")


def confirm_disclosure(
    database: Any,
    actor_user_id: str,
    *,
    policy_hash: str,
    manifest_hash: str,
    expected_revision: int,
) -> dict[str, Any]:
    with database.session() as db:
        service = ProviderDisclosureService(SqlAlchemyProviderDisclosureStore(db))
        response = service.confirm(
            ProviderDataCallConfirmationRequestV1(
                policy_hash=policy_hash,
                manifest_hash=manifest_hash,
                expected_revision=expected_revision,
            ),
            actor_user_id=actor_user_id,
            manifest_ref=manifest_hash,
        )
        return response.model_dump(mode="json")


def preview_team_standing(
    database: Any,
    actor_user_id: str,
    *,
    team_version_id: str,
    policy_hash: str,
    provider_operation: str,
) -> StandingGrantPlan:
    with database.session() as db:
        return prepare_team_standing_grant(
            db,
            actor_user_id,
            team_version_id=team_version_id,
            policy_hash=policy_hash,
            provider_operation=provider_operation,
        )


def confirm_team_standing(
    database: Any,
    actor_user_id: str,
    *,
    team_version_id: str,
    policy_hash: str,
    provider_operation: str,
    plan: StandingGrantPlan,
) -> str:
    with database.session() as db:
        grant: TeamProviderStandingGrant = confirm_team_standing_grant(
            db,
            actor_user_id,
            team_version_id=team_version_id,
            policy_hash=policy_hash,
            provider_operation=provider_operation,
            expected_resource_hash=plan.resource_hash,
            expected_team_epoch=plan.team_epoch,
            expected_publication_epoch=plan.publication_epoch,
        )
        return grant.id
