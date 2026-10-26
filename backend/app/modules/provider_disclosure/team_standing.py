"""Publisher consent for a Team's static Provider resources, without Chat data."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, cast
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from app.core.errors import PlatformError, conflict, not_found, stale_revision, unprocessable
from app.core.models import (
    Agent,
    AgentVersion,
    KnowledgeSnapshot,
    ProviderExportConfirmation,
    ProviderExportManifest,
    ProviderPolicySnapshot,
    User,
)
from app.core.sqlutil import dialect_insert
from app.modules.agents.markdown import markdown_hash
from app.modules.auth.service import AuthContext
from app.modules.knowledge.providers.sql_query import (
    SQL_QUERY_PROVIDER_OPERATION,
    SqlQueryRequestV1,
)
from app.modules.knowledge.services import course_member_role
from app.modules.knowledge.vector import REAL_EMBEDDING_IDENTITY
from app.modules.knowledge_sets.models import (
    KnowledgeAsset,
    KnowledgeAssetVersion,
    KnowledgeSet,
    KnowledgeSetSource,
)
from app.modules.learning.models import AssessmentActivity, AssessmentAttempt
from app.modules.teams.models import (
    CourseTeamPublication,
    Team,
    TeamMemberInvokeGrant,
    TeamVersion,
    TeamVersionMember,
)
from app.modules.teams.publication_access import chat_team_open_to_non_owner
from app.modules.teams.service import (
    FrozenTeamSelection,
    resolve_chat_entry,
    resolve_frozen_chat_selection,
)
from app.modules.workspace.assessment_protocol import (
    ASSESSMENT_SOURCE_REVOKED_OWNER_ACTIONS_PROTOCOL as REVOKED_ASSESSMENT_ACTION_PROTOCOL,
)
from app.modules.workspace.models import (
    Conversation,
    ConversationParticipant,
    ConversationTurn,
    TeamProviderConsentBinding,
    TeamProviderStandingGrant,
    TeamTurnResult,
)
from app.modules.workspace.schemas import TeamRouting
from app.modules.workspace.team_conversation import frozen_team_selection
from app.providers.control import (
    ExportFieldV1,
    ExportManifestV1,
    authorized_provider_model,
    canonical_json_bytes,
    confirm_export_manifest,
)
from app.providers.control_repository import (
    ProviderRepository,
    _confirmation_from_row,
    _manifest_from_row,
    _policy_from_row,
)

LOGGER = logging.getLogger(__name__)

StandingOperation = Literal["llm_agent_chat", "embedding_query"]
RevokedAssessmentSourceError = Literal[
    "assessment_resource_revoked", "assessment_question_source_stale"
]
REVOKED_ASSESSMENT_ACTIONS = (
    "abandon_request",
    "progress_request",
    "answers_request",
)
REVOKED_ASSESSMENT_ACTION_TOOL_DESCRIPTION = (
    "Read the owner's saved assessment progress or answers, or record an explicit abandonment "
    "of this attempt while its Question source is unavailable."
)


@dataclass(frozen=True)
class StandingGrantPlan:
    team_id: str
    team_version_id: str
    publication_id: str
    course_id: str
    publisher_user_id: str
    provider_operation: StandingOperation
    policy_hash: str
    resource_manifest_json: str
    resource_hash: str
    team_epoch: int
    publication_epoch: int
    safe_disclosure: dict[str, str | int]


@dataclass(frozen=True, slots=True)
class RevokedAssessmentCommandScope:
    """Server-minted owner lifecycle scope for source-independent owner actions."""

    actor_user_id: str
    source_conversation_id: str
    attempt_id: str
    activity_id: str
    turn_id: str
    result_id: str
    participant_id: str
    team_member_id: str
    source_error_code: RevokedAssessmentSourceError


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_hash(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _policy(db: Session, policy_hash: str, operation: str) -> StandingOperation:
    if operation not in {"llm_agent_chat", "embedding_query"}:
        raise unprocessable("provider_operation_invalid", "This Provider operation is unavailable.")
    if len(policy_hash) != 64:
        raise not_found()
    bind = db.get_bind()
    if isinstance(bind, Connection):
        row = (
            db.connection()
            .execute(
                select(ProviderPolicySnapshot.__table__).where(
                    ProviderPolicySnapshot.policy_hash == policy_hash
                )
            )
            .mappings()
            .first()
        )
        policy = _policy_from_row(cast(Mapping[str, object], row)) if row is not None else None
    else:
        policy = ProviderRepository(db).get_policy_snapshot(policy_hash)
    if policy is None or policy.policy_hash != policy_hash:
        raise not_found()
    return cast(StandingOperation, operation)


def _json_array(raw: str) -> list[object]:
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        raise not_found() from None
    if not isinstance(value, list):
        raise not_found()
    return value


def _set_resources(db: Session, set_id: str) -> dict[str, object]:
    row = db.get(KnowledgeSet, set_id)
    if row is None or row.deleted_at is not None:
        raise not_found()
    sources = db.scalars(
        select(KnowledgeSetSource)
        .where(
            KnowledgeSetSource.knowledge_set_id == set_id, KnowledgeSetSource.is_active.is_(True)
        )
        .order_by(KnowledgeSetSource.order_index, KnowledgeSetSource.id)
    ).all()
    assets = db.scalars(
        select(KnowledgeAsset)
        .where(KnowledgeAsset.knowledge_set_id == set_id)
        .order_by(KnowledgeAsset.id)
    ).all()
    asset_heads: list[dict[str, object]] = []
    for asset in assets:
        version = db.scalar(
            select(KnowledgeAssetVersion).where(
                KnowledgeAssetVersion.asset_id == asset.id,
                KnowledgeAssetVersion.version_seq == asset.current_version_seq,
            )
        )
        if asset.current_version_seq and version is None:
            raise not_found()
        asset_heads.append(
            {
                "id": asset.id,
                "kind": asset.kind,
                "version_id": version.id if version else None,
                "content_hash": version.content_hash if version else None,
            }
        )
    return {
        "id": row.id,
        "authorization_epoch": row.authorization_epoch,
        "content_revision": row.content_revision,
        "sources": [
            {
                "id": source.id,
                "document_id": source.document_id,
                "stored_file_id": source.stored_file_id,
                "content_hash": source.source_content_hash,
                "file_sha256": source.source_file_sha256,
                "authorization_epoch": source.source_authorization_epoch,
                "index_revision": source.source_index_revision,
            }
            for source in sources
        ],
        "asset_heads": asset_heads,
    }


def _manifest(
    db: Session,
    selection: FrozenTeamSelection,
    policy_hash: str,
    operation: StandingOperation,
    selected_ids: set[str],
) -> dict[str, object]:
    if not selected_ids or not selected_ids.issubset(
        {member.binding_id for member in selection.members}
    ):
        raise not_found()
    members: list[dict[str, object]] = []
    for frozen in selection.members:
        if frozen.binding_id not in selected_ids:
            continue
        member = db.get(TeamVersionMember, frozen.binding_id)
        version = db.get(AgentVersion, frozen.agent_version_id)
        if (
            member is None
            or version is None
            or member.team_version_id != selection.team_version_id
            or member.agent_version_id != version.id
        ):
            raise not_found()
        members.append(
            {
                "binding_id": member.id,
                "agent_id": member.agent_id,
                "agent_version_id": version.id,
                "agent_md_hash": _digest(version.agent_md),
                "snapshot_id": version.knowledge_snapshot_id,
                "raw_source_fences": _json_array(member.raw_source_fences_json),
                "own_sets": [_set_resources(db, set_id) for set_id in frozen.own_knowledge_set_ids],
            }
        )
    return {
        "team_id": selection.team_id,
        "team_version_id": selection.team_version_id,
        "publication_id": selection.publication_id,
        "course_id": selection.course_id,
        "publisher_user_id": selection.owner_user_id,
        "team_epoch": selection.team_authorization_epoch,
        "publication_epoch": selection.publication_epoch,
        "policy_hash": policy_hash,
        "provider_operation": operation,
        "shared_sets": [
            _set_resources(db, set_id) for set_id in selection.shared_knowledge_set_ids
        ],
        "members": members,
    }


def _publisher_selection(
    db: Session, actor: AuthContext | str, team_version_id: str
) -> FrozenTeamSelection:
    actor_id = actor.user.id if isinstance(actor, AuthContext) else actor
    version = db.get(TeamVersion, team_version_id)
    if version is None:
        raise not_found()
    team = db.get(Team, version.team_id)
    if (
        team is None
        or team.owner_user_id != actor_id
        or course_member_role(db, actor_id, team.course_id) != "teacher"
    ):
        raise not_found()
    selection = resolve_chat_entry(
        db,
        actor,
        team.id,
        version.id,
        require_publication=True,
    )
    if selection.publication_id is None or selection.publication_epoch is None:
        raise not_found()
    return selection


def prepare_team_standing_grant(
    db: Session,
    actor: AuthContext | str,
    *,
    team_version_id: str,
    policy_hash: str,
    provider_operation: str,
) -> StandingGrantPlan:
    """Preview exact static resources; no student Chat or Provider call is touched."""

    operation = _policy(db, policy_hash, provider_operation)
    selection = _publisher_selection(db, actor, team_version_id)
    resources = _manifest(
        db,
        selection,
        policy_hash,
        operation,
        {member.binding_id for member in selection.members},
    )
    encoded = _canonical(resources)
    publication_id = selection.publication_id
    publication_epoch = selection.publication_epoch
    if publication_id is None or publication_epoch is None:
        raise not_found()
    members = cast(list[dict[str, object]], resources["members"])
    sets = [*cast(list[dict[str, object]], resources["shared_sets"])]
    sets.extend(
        own for member in members for own in cast(list[dict[str, object]], member["own_sets"])
    )
    return StandingGrantPlan(
        team_id=selection.team_id,
        team_version_id=selection.team_version_id,
        publication_id=publication_id,
        course_id=selection.course_id,
        publisher_user_id=selection.owner_user_id,
        provider_operation=operation,
        policy_hash=policy_hash,
        resource_manifest_json=encoded,
        resource_hash=_digest(encoded),
        team_epoch=selection.team_authorization_epoch,
        publication_epoch=publication_epoch,
        safe_disclosure={
            "provider_operation": operation,
            "policy_hash": policy_hash,
            "member_count": len(members),
            "knowledge_set_count": len({str(item["id"]) for item in sets}),
            "source_count": sum(
                len(cast(list[object], member["raw_source_fences"])) for member in members
            )
            + sum(len(cast(list[object], item["sources"])) for item in sets),
            "resource_hash": _digest(encoded),
        },
    )


def confirm_team_standing_grant(
    db: Session,
    actor: AuthContext | str,
    *,
    team_version_id: str,
    policy_hash: str,
    provider_operation: str,
    expected_resource_hash: str,
    expected_team_epoch: int,
    expected_publication_epoch: int,
) -> TeamProviderStandingGrant:
    """Bind one explicit Teacher confirmation; caller commits this transaction."""

    plan = prepare_team_standing_grant(
        db,
        actor,
        team_version_id=team_version_id,
        policy_hash=policy_hash,
        provider_operation=provider_operation,
    )
    if (
        plan.resource_hash != expected_resource_hash
        or plan.team_epoch != expected_team_epoch
        or plan.publication_epoch != expected_publication_epoch
    ):
        raise stale_revision()
    current = (
        select(TeamProviderStandingGrant)
        .where(
            TeamProviderStandingGrant.team_version_id == plan.team_version_id,
            TeamProviderStandingGrant.publication_id == plan.publication_id,
            TeamProviderStandingGrant.provider_operation == plan.provider_operation,
            TeamProviderStandingGrant.policy_hash == plan.policy_hash,
            TeamProviderStandingGrant.resource_hash == plan.resource_hash,
            TeamProviderStandingGrant.publisher_user_id == plan.publisher_user_id,
            TeamProviderStandingGrant.revoked_at.is_(None),
        )
        .execution_options(populate_existing=True)
    )
    existing = db.scalar(current)
    if existing is not None:
        return existing
    # Load test (2026-10-19, 40 students, one published Team): the first
    # messages all found no grant and each recorded the operator's standing
    # consent. The losers hit uq_team_provider_standing_scope and the member
    # failed with IntegrityError. One grant per scope: a concurrent insert is
    # skipped and its row read back once the winner commits.
    table = TeamProviderStandingGrant.__table__
    db.execute(
        dialect_insert(db, table)
        .values(
            id=str(uuid4()),
            team_id=plan.team_id,
            team_version_id=plan.team_version_id,
            publication_id=plan.publication_id,
            course_id=plan.course_id,
            publisher_user_id=plan.publisher_user_id,
            provider_operation=plan.provider_operation,
            policy_hash=plan.policy_hash,
            resource_manifest_json=plan.resource_manifest_json,
            resource_hash=plan.resource_hash,
            team_epoch=plan.team_epoch,
            publication_epoch=plan.publication_epoch,
            disclosure_revision=1,
            confirmed_at=datetime.now(UTC),
            revoked_at=None,
        )
        .on_conflict_do_nothing(
            index_elements=[
                table.c.team_version_id,
                table.c.publication_id,
                table.c.provider_operation,
                table.c.policy_hash,
                table.c.resource_hash,
                table.c.publisher_user_id,
            ],
            index_where=table.c.revoked_at.is_(None),
        )
    )
    grant = db.scalar(current)
    if grant is None:  # revoked between the insert and this read
        raise stale_revision()
    return grant


@dataclass(frozen=True)
class TeamDispatchAuthorization:
    confirmation_id: str
    standing_grant_id: str | None
    confirmer_kind: Literal["custom_owner", "published_chat_owner"]


def _revoked_assessment_tool_is_closed(tools: object) -> bool:
    if not isinstance(tools, list) or len(tools) != 1:
        return False
    tool = tools[0]
    if not isinstance(tool, dict) or set(tool) != {"type", "function"}:
        return False
    function = tool.get("function")
    if (
        tool.get("type") != "function"
        or not isinstance(function, dict)
        or set(function) != {"name", "description", "parameters"}
        or function.get("name") != "assessment_action"
        or function.get("description") != REVOKED_ASSESSMENT_ACTION_TOOL_DESCRIPTION
    ):
        return False
    parameters = function.get("parameters")
    if (
        not isinstance(parameters, dict)
        or set(parameters) != {"type", "properties", "required", "additionalProperties"}
        or parameters.get("type") != "object"
        or parameters.get("required") != ["arguments"]
        or parameters.get("additionalProperties") is not False
    ):
        return False
    properties = parameters.get("properties")
    if not isinstance(properties, dict) or set(properties) != {"arguments"}:
        return False
    arguments = properties["arguments"]
    if (
        not isinstance(arguments, dict)
        or set(arguments) != {"type", "properties", "required", "additionalProperties", "title"}
        or arguments.get("type") != "object"
        or arguments.get("title") != "AssessmentActionArguments"
        or arguments.get("required") != ["classification"]
        or arguments.get("additionalProperties") is not False
    ):
        return False
    action_properties = arguments.get("properties")
    if not isinstance(action_properties, dict) or set(action_properties) != {"classification"}:
        return False
    classification = action_properties["classification"]
    return (
        isinstance(classification, dict)
        and classification.get("type") == "string"
        and classification.get("enum") == list(REVOKED_ASSESSMENT_ACTIONS)
        and "const" not in classification
        and set(classification) == {"type", "enum"}
    )


def _revoked_assessment_wire_is_closed(
    wire: bytes,
    *,
    expected_model: str,
    current_user_message: str,
) -> bool:
    try:
        body = json.loads(wire)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
        return False
    if not isinstance(body, dict):
        return False
    # No output cap is sent (2026-10-18), so a body naming max_tokens is not
    # the closed shape this grant covers.
    allowed_keys = {"model", "messages", "stream", "enable_thinking", "tools"}
    if "tool_choice" in body:
        allowed_keys.add("tool_choice")
    if (
        set(body) != allowed_keys
        or body.get("model") != expected_model
        or body.get("stream") is not False
        or body.get("enable_thinking") is not False
        or body.get("tool_choice", "auto") != "auto"
    ):
        return False
    messages = body.get("messages")
    if (
        not isinstance(messages, list)
        or len(messages) != 2
        or messages[0] != {"role": "system", "content": REVOKED_ASSESSMENT_ACTION_PROTOCOL}
        or messages[1] != {"role": "user", "content": current_user_message}
    ):
        return False
    if not _revoked_assessment_tool_is_closed(body.get("tools")):
        return False
    try:
        return canonical_json_bytes(body) == wire
    except (TypeError, ValueError):
        return False


def _revoked_assessment_grant(
    db: Session,
    *,
    team_id: str,
    team_version_id: str,
    publication_id: str,
    course_id: str,
    publisher_user_id: str,
    team_epoch: int,
    publication_epoch: int,
    policy_hash: str,
    current_member_bindings: set[str],
    current_member_versions: dict[str, tuple[str, str]],
    selected_binding_ids: set[str],
) -> TeamProviderStandingGrant | None:
    rows = db.scalars(
        select(TeamProviderStandingGrant).where(
            TeamProviderStandingGrant.team_id == team_id,
            TeamProviderStandingGrant.team_version_id == team_version_id,
            TeamProviderStandingGrant.publication_id == publication_id,
            TeamProviderStandingGrant.course_id == course_id,
            TeamProviderStandingGrant.publisher_user_id == publisher_user_id,
            TeamProviderStandingGrant.provider_operation == "llm_agent_chat",
            TeamProviderStandingGrant.policy_hash == policy_hash,
            TeamProviderStandingGrant.team_epoch == team_epoch,
            TeamProviderStandingGrant.publication_epoch == publication_epoch,
            TeamProviderStandingGrant.revoked_at.is_(None),
        )
    ).all()
    if not selected_binding_ids < current_member_bindings:
        return None
    for grant in rows:
        if _digest(grant.resource_manifest_json) != grant.resource_hash:
            continue
        try:
            resource_manifest = json.loads(grant.resource_manifest_json)
        except (TypeError, ValueError):
            continue
        if (
            not isinstance(resource_manifest, dict)
            or _canonical(resource_manifest) != grant.resource_manifest_json
            or resource_manifest.get("team_id") != team_id
            or resource_manifest.get("team_version_id") != team_version_id
            or resource_manifest.get("publication_id") != publication_id
            or resource_manifest.get("course_id") != course_id
            or resource_manifest.get("publisher_user_id") != publisher_user_id
            or resource_manifest.get("team_epoch") != team_epoch
            or resource_manifest.get("publication_epoch") != publication_epoch
            or resource_manifest.get("policy_hash") != policy_hash
            or resource_manifest.get("provider_operation") != "llm_agent_chat"
            or not isinstance(resource_manifest.get("shared_sets"), list)
        ):
            continue
        granted_members = resource_manifest.get("members")
        if not isinstance(granted_members, list):
            continue
        granted_member_versions: dict[str, tuple[str, str]] = {}
        for member in granted_members:
            if not isinstance(member, dict):
                break
            binding_id = member.get("binding_id")
            agent_id = member.get("agent_id")
            agent_version_id = member.get("agent_version_id")
            if (
                not isinstance(binding_id, str)
                or not isinstance(agent_id, str)
                or not isinstance(agent_version_id, str)
            ):
                break
            granted_member_versions[binding_id] = (agent_id, agent_version_id)
        if len(granted_member_versions) != len(granted_members):
            continue
        granted_bindings = set(granted_member_versions)
        if (
            granted_bindings != current_member_bindings
            or len(granted_members) != len(current_member_bindings)
            or granted_member_versions != current_member_versions
            or not selected_binding_ids < granted_bindings
        ):
            continue
        return grant
    return None


def _authorize_revoked_assessment_dispatch(
    db: Session,
    *,
    actor_user_id: str,
    result: TeamTurnResult,
    participant: ConversationParticipant,
    turn: ConversationTurn,
    conversation: Conversation,
    manifest: ExportManifestV1,
    selected_binding_ids: set[str],
    claim_token: str,
    scope: RevokedAssessmentCommandScope,
    serialized_request: bytes,
    current_policy_hash: str,
) -> tuple[TeamProviderStandingGrant, str | None, str]:
    if (
        scope.actor_user_id != actor_user_id
        or scope.source_conversation_id != conversation.id
        or scope.turn_id != turn.id
        or scope.result_id != result.id
        or scope.participant_id != participant.id
        or scope.team_member_id != participant.team_member_id
        or scope.source_error_code
        not in {"assessment_resource_revoked", "assessment_question_source_stale"}
        or conversation.entry_kind != "maya_team"
        or conversation.origin != "published_course_team"
        or conversation.publication_id is None
        or conversation.publication_epoch is None
        or conversation.team_id is None
        or conversation.team_version_id is None
        or conversation.team_owner_user_id is None
        or conversation.team_authorization_epoch is None
        or manifest.scope_id != f"team-result:{result.id}"
        or manifest.provider_operation != "llm_agent_chat"
        or manifest.policy_hash != current_policy_hash
        or manifest.model_key != authorized_provider_model("llm_agent_chat")
        or manifest.debate_id is not None
        or manifest.turn_id is not None
        or manifest.persona_spec_hash != _canonical_hash(REVOKED_ASSESSMENT_ACTION_PROTOCOL)
        or manifest.build_manifest_hash != hashlib.sha256(serialized_request).hexdigest()
        or not _revoked_assessment_wire_is_closed(
            serialized_request,
            expected_model=manifest.model_key,
            current_user_message=turn.user_text,
        )
        or [field.canonical_dict() for field in manifest.fields]
        != [
            {
                "field_class": "private_conversation_messages",
                "value_sha256": _canonical_hash([{"role": "user", "content": turn.user_text}]),
            },
            {
                "field_class": "topic_and_platform_rules",
                "value_sha256": _canonical_hash(REVOKED_ASSESSMENT_ACTION_PROTOCOL),
            },
        ]
        or selected_binding_ids != {participant.team_member_id}
    ):
        raise not_found()
    if (
        turn.claim_token != claim_token
        or conversation.active_request_id != turn.id
        or turn.state != "pending"
        or result.state not in {"running", "ready"}
        or conversation.withdrawn_at is not None
        or conversation.user_id != actor_user_id
    ):
        raise not_found()

    attempt_values = db.execute(
        select(
            AssessmentAttempt.activity_id,
            AssessmentAttempt.team_id,
            AssessmentAttempt.recipe_id,
            AssessmentAttempt.actor_user_id,
            AssessmentAttempt.source_conversation_id,
            AssessmentAttempt.chat_visibility,
            AssessmentAttempt.status,
        ).where(AssessmentAttempt.id == scope.attempt_id)
    ).one_or_none()
    activity_values = db.execute(
        select(
            AssessmentActivity.course_id,
            AssessmentActivity.team_id,
            AssessmentActivity.team_version_id,
            AssessmentActivity.publication_id,
            AssessmentActivity.recipe_id,
            AssessmentActivity.publisher_user_id,
        ).where(AssessmentActivity.id == scope.activity_id)
    ).one_or_none()
    if (
        attempt_values is None
        or activity_values is None
        or tuple(attempt_values[:2]) != (scope.activity_id, conversation.team_id)
        or attempt_values[3] != actor_user_id
        or attempt_values[4] != conversation.id
        or attempt_values[5] != conversation.chat_visibility
        or attempt_values[6] not in {"in_progress", "paused"}
        or tuple(activity_values[:4])
        != (
            conversation.course_id,
            conversation.team_id,
            conversation.team_version_id,
            conversation.publication_id,
        )
        or activity_values[4] != attempt_values[2]
        or activity_values[5] != conversation.team_owner_user_id
    ):
        raise not_found()

    user_status = db.scalar(select(User.status).where(User.id == actor_user_id))
    publisher_status = db.scalar(
        select(User.status).where(User.id == conversation.team_owner_user_id)
    )
    if (
        user_status != "active"
        or publisher_status != "active"
        or course_member_role(db, actor_user_id, conversation.course_id) != "student"
        or course_member_role(db, conversation.team_owner_user_id, conversation.course_id)
        != "teacher"
    ):
        raise not_found()

    team_values = db.execute(
        select(
            Team.course_id,
            Team.owner_user_id,
            Team.ownership_scope,
            Team.visibility,
            Team.authorization_epoch,
            Team.current_version_seq,
            Team.deleted_at,
        ).where(Team.id == conversation.team_id)
    ).one_or_none()
    version_values = db.execute(
        select(
            TeamVersion.team_id,
            TeamVersion.version_seq,
            TeamVersion.authorization_epoch,
            TeamVersion.visibility,
        ).where(TeamVersion.id == conversation.team_version_id)
    ).one_or_none()
    publication_values = db.execute(
        select(
            CourseTeamPublication.team_id,
            CourseTeamPublication.team_version_id,
            CourseTeamPublication.course_id,
            CourseTeamPublication.publisher_user_id,
            CourseTeamPublication.authorization_epoch,
            CourseTeamPublication.state,
        ).where(CourseTeamPublication.id == conversation.publication_id)
    ).one_or_none()
    if (
        team_values is None
        or version_values is None
        or publication_values is None
        or team_values[0] != conversation.course_id
        or team_values[1] != conversation.team_owner_user_id
        or team_values[2] != "personal"
        or team_values[3] != "public"
        or team_values[4] != conversation.team_authorization_epoch
        or team_values[5] != version_values[1]
        or team_values[6] is not None
        or version_values[0] != conversation.team_id
        or version_values[2] != conversation.team_authorization_epoch
        or version_values[3] != "public"
        or publication_values[0] != conversation.team_id
        or publication_values[1] != conversation.team_version_id
        or publication_values[2] != conversation.course_id
        or publication_values[3] != conversation.team_owner_user_id
        or publication_values[4] != conversation.publication_epoch
        or publication_values[4] != conversation.team_authorization_epoch
        or publication_values[5] != "published"
    ):
        raise not_found()

    version_members = db.execute(
        select(
            TeamVersionMember.id,
            TeamVersionMember.agent_id,
            TeamVersionMember.agent_version_id,
            TeamVersionMember.position,
            TeamVersionMember.is_leader,
        )
        .where(TeamVersionMember.team_version_id == conversation.team_version_id)
        .order_by(TeamVersionMember.position)
    ).all()
    participants = db.execute(
        select(
            ConversationParticipant.id,
            ConversationParticipant.team_member_id,
            ConversationParticipant.agent_id,
            ConversationParticipant.agent_version_id,
            ConversationParticipant.snapshot_id,
            ConversationParticipant.agent_authorization_epoch,
            ConversationParticipant.position,
            ConversationParticipant.is_leader,
            ConversationParticipant.invoke_grant_id,
        )
        .where(ConversationParticipant.conversation_id == conversation.id)
        .order_by(ConversationParticipant.position)
    ).all()
    if len(version_members) < 2 or len(version_members) != len(participants):
        raise not_found()
    members_by_id = {str(member.id): member for member in version_members}
    participants_by_member = {str(row.team_member_id): row for row in participants}
    if (
        len(members_by_id) != len(version_members)
        or len(participants_by_member) != len(participants)
        or set(members_by_id) != set(participants_by_member)
        or sum(bool(member.is_leader) for member in version_members) != 1
    ):
        raise not_found()
    selected_participant = participants_by_member.get(scope.team_member_id)
    if selected_participant is None or selected_participant.id != participant.id:
        raise not_found()
    for member_id, member in members_by_id.items():
        row = participants_by_member[member_id]
        if (
            member.agent_id != row.agent_id
            or member.agent_version_id != row.agent_version_id
            or member.position != row.position
            or member.is_leader != row.is_leader
        ):
            raise not_found()
        agent_values = db.execute(
            select(
                Agent.course_id,
                Agent.authorization_epoch,
                Agent.status,
                Agent.deleted_at,
                Agent.group_id,
            ).where(Agent.id == row.agent_id)
        ).one_or_none()
        agent_version_values = db.execute(
            select(
                AgentVersion.agent_id,
                AgentVersion.state,
                AgentVersion.authorization_epoch,
                AgentVersion.knowledge_snapshot_id,
            ).where(AgentVersion.id == row.agent_version_id)
        ).one_or_none()
        if (
            agent_values is None
            or agent_version_values is None
            or agent_values[0] != conversation.course_id
            or agent_values[1] != row.agent_authorization_epoch
            or agent_values[2] != "active"
            or agent_values[3] is not None
            or agent_version_values[0] != row.agent_id
            or agent_version_values[1] not in {"published", "superseded"}
            or agent_version_values[2] != agent_values[1]
            or agent_version_values[3] != row.snapshot_id
        ):
            raise not_found()

    leader_ids = {str(member.id) for member in version_members if bool(member.is_leader)}
    if (
        leader_ids != {scope.team_member_id}
        or selected_binding_ids != leader_ids
        or scope.participant_id != str(selected_participant.id)
        or selected_participant.id != participant.id
    ):
        raise not_found()
    selected_group_id = db.scalar(
        select(Agent.group_id).where(Agent.id == selected_participant.agent_id)
    )
    selected_agent_version_id = str(selected_participant.agent_version_id)
    try:
        routing = TeamRouting.model_validate_json(turn.routing_json or "{}")
    except ValueError:
        raise not_found() from None
    if routing.mode != "selected" or {str(value) for value in routing.participant_ids} != {
        str(participant.id)
    }:
        raise not_found()
    invoke_grant_id = db.scalar(
        select(TeamMemberInvokeGrant.id).where(
            TeamMemberInvokeGrant.publication_id == conversation.publication_id,
            TeamMemberInvokeGrant.team_version_id == conversation.team_version_id,
            TeamMemberInvokeGrant.team_member_id == scope.team_member_id,
            TeamMemberInvokeGrant.agent_id == participant.agent_id,
            TeamMemberInvokeGrant.agent_version_id == participant.agent_version_id,
            TeamMemberInvokeGrant.authorization_epoch == conversation.team_authorization_epoch,
        )
    )
    if invoke_grant_id is None or invoke_grant_id != selected_participant.invoke_grant_id:
        raise not_found()

    _policy(db, current_policy_hash, "llm_agent_chat")
    standing_grant = _revoked_assessment_grant(
        db,
        team_id=conversation.team_id,
        team_version_id=conversation.team_version_id,
        publication_id=conversation.publication_id,
        course_id=conversation.course_id,
        publisher_user_id=conversation.team_owner_user_id,
        team_epoch=conversation.team_authorization_epoch,
        publication_epoch=conversation.publication_epoch,
        policy_hash=current_policy_hash,
        current_member_bindings=set(members_by_id),
        current_member_versions={
            member_id: (str(member.agent_id), str(member.agent_version_id))
            for member_id, member in members_by_id.items()
        },
        selected_binding_ids=selected_binding_ids,
    )
    if standing_grant is None:
        raise PlatformError(
            "provider_authorization_revoked",
            "The published Team's current Provider authorization is unavailable.",
            409,
        )
    return standing_grant, selected_group_id, selected_agent_version_id


def authorize_team_dispatch(
    db: Session,
    *,
    actor_user_id: str,
    result_id: str,
    manifest: ExportManifestV1,
    selected_binding_ids: set[str],
    claim_token: str,
    revoked_assessment_scope: RevokedAssessmentCommandScope | None = None,
    serialized_request: bytes | None = None,
    current_policy_hash: str | None = None,
    operator_consent: bool = False,
) -> TeamDispatchAuthorization:
    """Bind the sender's current Chat action to its exact outbound bytes.

    Published Team resources additionally need the Teacher's current standing
    authorization, or the operator's standing consent recorded as that grant.
    This keeps student Chat contents outside that approval.
    """

    result = db.get(TeamTurnResult, result_id)
    participant = db.get(ConversationParticipant, result.participant_id) if result else None
    turn = db.get(ConversationTurn, result.turn_id) if result else None
    conversation = db.get(Conversation, result.conversation_id) if result else None
    if (
        result is None
        or participant is None
        or turn is None
        or conversation is None
        or conversation.withdrawn_at is not None
        or conversation.user_id != actor_user_id
        or participant.conversation_id != conversation.id
        or turn.conversation_id != conversation.id
        or result.state not in {"running", "ready"}
        or turn.state != "pending"
        or turn.claim_token is None
        or turn.claim_token != claim_token
        or conversation.active_request_id != turn.id
        or manifest.scope_id != f"team-result:{result.id}"
        or manifest.provider_operation not in {"llm_agent_chat", "embedding_query"}
    ):
        raise not_found()
    if revoked_assessment_scope is None:
        if serialized_request is not None or current_policy_hash is not None:
            raise not_found()
        agent = db.get(Agent, participant.agent_id)
        version = db.get(AgentVersion, participant.agent_version_id)
        if (
            agent is None
            or version is None
            or version.agent_id != participant.agent_id
            or version.knowledge_snapshot_id != participant.snapshot_id
            or agent.authorization_epoch != participant.agent_authorization_epoch
        ):
            raise not_found()
        selection = frozen_team_selection(db, conversation)
        if (
            not selected_binding_ids
            or not selected_binding_ids.issubset(
                {member.binding_id for member in selection.members}
            )
            or participant.team_member_id not in selected_binding_ids
        ):
            raise not_found()
        routing = TeamRouting.model_validate_json(turn.routing_json or "{}")
        participants = list(
            db.scalars(
                select(ConversationParticipant)
                .where(ConversationParticipant.conversation_id == conversation.id)
                .order_by(ConversationParticipant.position)
            )
        )
        requested_ids = {str(value) for value in routing.participant_ids}
        selected_participants = (
            [item for item in participants if item.id in requested_ids]
            if routing.mode == "selected"
            else participants
        )
        expected_binding_ids = {item.team_member_id for item in selected_participants}
        if selected_binding_ids != expected_binding_ids:
            raise not_found()
        resolve_frozen_chat_selection(db, actor_user_id, selection, selected_binding_ids)

        if conversation.entry_kind == "team":
            if conversation.origin != "custom_team" or conversation.publication_id is not None:
                raise not_found()
            if any(item.invoke_grant_id is not None for item in selected_participants):
                raise not_found()
            standing_grant = None
            confirmer_kind: Literal["custom_owner", "published_chat_owner"] = "custom_owner"
        elif conversation.entry_kind == "maya_team":
            if (
                conversation.origin != "published_course_team"
                or conversation.publication_id is None
            ):
                raise not_found()
            standing_grant = current_standing_grant(
                db,
                actor_user_id,
                selection,
                selected_binding_ids,
                manifest.policy_hash,
                manifest.provider_operation,
            )
            if standing_grant is None and operator_consent:
                standing_grant = operator_standing_grant(
                    db,
                    actor_user_id,
                    selection,
                    selected_binding_ids,
                    manifest.policy_hash,
                    manifest.provider_operation,
                )
            if standing_grant is None:
                raise PlatformError(
                    "provider_authorization_revoked",
                    "The published Team's current Provider authorization is unavailable.",
                    409,
                )
            confirmer_kind = "published_chat_owner"
        else:
            raise not_found()
        agent_group_id = agent.group_id
        agent_version_id = version.id
    else:
        if serialized_request is None or current_policy_hash is None:
            raise not_found()
        standing_grant, agent_group_id, agent_version_id = _authorize_revoked_assessment_dispatch(
            db,
            actor_user_id=actor_user_id,
            result=result,
            participant=participant,
            turn=turn,
            conversation=conversation,
            manifest=manifest,
            selected_binding_ids=selected_binding_ids,
            claim_token=claim_token,
            scope=revoked_assessment_scope,
            serialized_request=serialized_request,
            current_policy_hash=current_policy_hash,
        )
        confirmer_kind = "published_chat_owner"

    # The grant flush holds SQLite's writer lock. Repository writes use a
    # second connection and BEGIN IMMEDIATE, so commit first or that
    # connection waits until busy_timeout and fails closed as database locked.
    db.commit()
    repository = ProviderRepository(db)
    policy = repository.get_policy_snapshot(manifest.policy_hash)
    policy_id = db.scalar(
        select(ProviderPolicySnapshot.id).where(
            ProviderPolicySnapshot.policy_hash == manifest.policy_hash
        )
    )
    if policy is None or policy_id is None:
        raise PlatformError("provider_preflight_blocked", "Provider policy is unavailable.", 409)
    # The manifest and its confirmation commit together (one transaction).
    with repository.one_transaction():
        repository.ensure_export_manifest(
            manifest,
            policy_snapshot_id=str(policy_id),
            course_id=conversation.course_id,
            group_id=agent_group_id,
            agent_version_id=agent_version_id,
        )
        confirmation = repository.get_export_confirmation(manifest.manifest_hash)
        if confirmation is None:
            confirmation = confirm_export_manifest(
                manifest,
                policy,
                confirmed_at=datetime.now(UTC).isoformat(),
                expected_manifest_hash=manifest.manifest_hash,
                expected_policy_hash=policy.policy_hash,
            )
            manifest_id = repository.get_export_manifest_id(manifest.manifest_hash)
            if manifest_id is None:
                raise conflict(
                    "provider_preflight_blocked", "Provider authorization is unavailable."
                )
            confirmation_id = repository.save_export_confirmation(manifest_id, confirmation)
        else:
            if (
                confirmation.manifest_hash != manifest.manifest_hash
                or confirmation.policy_hash != manifest.policy_hash
                or confirmation.confirmation_revision != manifest.operation_revision
            ):
                raise conflict("provider_preflight_stale", "Provider authorization changed.")
            confirmation_row_id = repository.get_export_confirmation_id(manifest.manifest_hash)
            if confirmation_row_id is None:
                raise conflict(
                    "provider_preflight_blocked", "Provider authorization is unavailable."
                )
            confirmation_id = str(confirmation_row_id)

    expected_binding = {
        "confirmation_id": confirmation_id,
        "result_id": result.id,
        "actor_user_id": actor_user_id,
        "confirmer_user_id": actor_user_id,
        "confirmer_kind": confirmer_kind,
        "standing_grant_id": standing_grant.id if standing_grant else None,
        "team_epoch": conversation.team_authorization_epoch,
        "publication_epoch": conversation.publication_epoch,
    }
    binding = db.get(TeamProviderConsentBinding, manifest.manifest_hash)
    if binding is None:
        db.add(
            TeamProviderConsentBinding(
                manifest_hash=manifest.manifest_hash,
                **expected_binding,
                created_at=datetime.now(UTC),
            )
        )
        db.flush()
    elif any(getattr(binding, key) != value for key, value in expected_binding.items()):
        raise conflict("provider_preflight_stale", "Provider authorization changed.")
    return TeamDispatchAuthorization(
        confirmation_id=confirmation_id,
        standing_grant_id=standing_grant.id if standing_grant else None,
        confirmer_kind=confirmer_kind,
    )


def current_standing_grant(
    db: Session,
    actor_id: str,
    frozen_selection: FrozenTeamSelection,
    selected_binding_ids: set[str],
    policy_hash: str,
    provider_operation: str,
) -> TeamProviderStandingGrant | None:
    """Recheck selected members against a stored publisher grant before dispatch."""

    if not frozen_selection.require_publication or not selected_binding_ids:
        return None
    try:
        operation = _policy(db, policy_hash, provider_operation)
        resolve_frozen_chat_selection(db, actor_id, frozen_selection, selected_binding_ids)
        if (
            course_member_role(db, frozen_selection.owner_user_id, frozen_selection.course_id)
            != "teacher"
        ):
            return None
        current = _manifest(db, frozen_selection, policy_hash, operation, selected_binding_ids)
        current_projection = _canonical(current)
    except Exception:
        return None
    rows = db.scalars(
        select(TeamProviderStandingGrant)
        .where(
            TeamProviderStandingGrant.team_id == frozen_selection.team_id,
            TeamProviderStandingGrant.team_version_id == frozen_selection.team_version_id,
            TeamProviderStandingGrant.publication_id == frozen_selection.publication_id,
            TeamProviderStandingGrant.course_id == frozen_selection.course_id,
            TeamProviderStandingGrant.publisher_user_id == frozen_selection.owner_user_id,
            TeamProviderStandingGrant.provider_operation == operation,
            TeamProviderStandingGrant.policy_hash == policy_hash,
            TeamProviderStandingGrant.team_epoch == frozen_selection.team_authorization_epoch,
            TeamProviderStandingGrant.publication_epoch == frozen_selection.publication_epoch,
            TeamProviderStandingGrant.revoked_at.is_(None),
        )
        .order_by(TeamProviderStandingGrant.confirmed_at.desc())
    ).all()
    for row in rows:
        try:
            saved = json.loads(row.resource_manifest_json)
            if (
                not isinstance(saved, dict)
                or _digest(row.resource_manifest_json) != row.resource_hash
            ):
                continue
            saved_members = saved.get("members")
            if not isinstance(saved_members, list):
                continue
            projected = {
                **saved,
                "members": [
                    item
                    for item in saved_members
                    if isinstance(item, dict) and item.get("binding_id") in selected_binding_ids
                ],
            }
            if _canonical(projected) == current_projection:
                return row
        except (TypeError, ValueError):
            continue
    return None


def operator_standing_grant(
    db: Session,
    actor_id: str,
    frozen_selection: FrozenTeamSelection,
    selected_binding_ids: set[str],
    policy_hash: str,
    provider_operation: str,
) -> TeamProviderStandingGrant | None:
    """Record the operator's standing consent as the publisher's Team grant.

    The grant is prepared and confirmed exactly as the publisher's own action
    would be, then rechecked against the selected members before dispatch.
    """

    if not frozen_selection.require_publication:
        return None
    try:
        plan = prepare_team_standing_grant(
            db,
            frozen_selection.owner_user_id,
            team_version_id=frozen_selection.team_version_id,
            policy_hash=policy_hash,
            provider_operation=provider_operation,
        )
        confirm_team_standing_grant(
            db,
            frozen_selection.owner_user_id,
            team_version_id=frozen_selection.team_version_id,
            policy_hash=policy_hash,
            provider_operation=provider_operation,
            expected_resource_hash=plan.resource_hash,
            expected_team_epoch=plan.team_epoch,
            expected_publication_epoch=plan.publication_epoch,
        )
    except PlatformError as error:
        LOGGER.warning("Team operator consent unavailable code=%s", error.code)
        return None
    LOGGER.warning(
        "Team Provider grant recorded by standing operator consent operation=%s",
        provider_operation,
    )
    return current_standing_grant(
        db,
        actor_id,
        frozen_selection,
        selected_binding_ids,
        policy_hash,
        provider_operation,
    )


def current_team_dispatch_is_authorized(
    connection: Connection,
    *,
    operation: Mapping[str, object],
    actor_user_id: str,
    result_id: str,
    claim_token: str,
    selected_binding_ids: set[str],
    serialized_request: bytes | None,
    current_policy_hash: str,
    query_context: SqlQueryRequestV1 | None = None,
    revoked_assessment_scope: RevokedAssessmentCommandScope | None = None,
) -> bool:
    """Recheck current Team consent and resources inside the send CAS transaction."""

    if not connection.in_transaction():
        return False
    try:
        with Session(
            bind=connection,
            autoflush=False,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        ) as db:
            return _current_team_dispatch_is_authorized(
                db,
                operation=operation,
                actor_user_id=actor_user_id,
                result_id=result_id,
                claim_token=claim_token,
                selected_binding_ids=selected_binding_ids,
                serialized_request=serialized_request,
                current_policy_hash=current_policy_hash,
                query_context=query_context,
                revoked_assessment_scope=revoked_assessment_scope,
            )
    except Exception:
        return False


def _current_team_dispatch_is_authorized(
    db: Session,
    *,
    operation: Mapping[str, object],
    actor_user_id: str,
    result_id: str,
    claim_token: str,
    selected_binding_ids: set[str],
    serialized_request: bytes | None,
    current_policy_hash: str,
    query_context: SqlQueryRequestV1 | None,
    revoked_assessment_scope: RevokedAssessmentCommandScope | None,
) -> bool:
    operation_id = operation.get("id")
    operation_kind = operation.get("provider_operation")
    manifest_hash = operation.get("export_manifest_hash")
    if (
        not isinstance(operation_id, str)
        or not isinstance(operation_kind, str)
        or operation_kind not in {"llm_agent_chat", "embedding_query"}
        or not isinstance(manifest_hash, str)
        or operation.get("state") not in {"prepared", "reserved"}
        or operation.get("scope_id") != f"team-result:{result_id}"
        or operation.get("policy_hash") != current_policy_hash
        or not selected_binding_ids
    ):
        return False
    if revoked_assessment_scope is not None and (
        operation_kind != "llm_agent_chat" or serialized_request is None
    ):
        return False
    body: dict[str, object] | None = None
    wire_hash: str | None = None
    if operation_kind == "llm_agent_chat":
        if serialized_request is None or query_context is not None:
            return False
        wire_hash = hashlib.sha256(serialized_request).hexdigest()
        if operation.get("request_hash") != wire_hash:
            return False
        try:
            decoded = json.loads(serialized_request)
            if not isinstance(decoded, dict) or canonical_json_bytes(decoded) != serialized_request:
                return False
            body = decoded
        except (TypeError, ValueError):
            return False
    elif operation_kind == SQL_QUERY_PROVIDER_OPERATION:
        if serialized_request is not None or query_context is None:
            return False
    else:
        return False

    connection = db.connection()
    manifest_row = (
        connection.execute(
            select(ProviderExportManifest.__table__).where(
                ProviderExportManifest.manifest_hash == manifest_hash
            )
        )
        .mappings()
        .first()
    )
    confirmation_row = (
        connection.execute(
            select(ProviderExportConfirmation.__table__).where(
                ProviderExportConfirmation.manifest_hash == manifest_hash
            )
        )
        .mappings()
        .first()
    )
    manifest = (
        _manifest_from_row(cast(Mapping[str, object], manifest_row))
        if manifest_row is not None
        else None
    )
    confirmation = (
        _confirmation_from_row(cast(Mapping[str, object], confirmation_row))
        if confirmation_row is not None
        else None
    )
    confirmation_id = str(confirmation_row["id"]) if confirmation_row is not None else None
    if (
        manifest is None
        or confirmation is None
        or confirmation_id is None
        or manifest.manifest_hash != manifest_hash
        or manifest.scope_id != f"team-result:{result_id}"
        or manifest.provider_operation != operation_kind
        or manifest.policy_hash != current_policy_hash
        or confirmation.manifest_hash != manifest_hash
        or confirmation.policy_hash != current_policy_hash
        or confirmation.confirmation_revision != manifest.operation_revision
    ):
        return False
    if operation_kind == "llm_agent_chat":
        if (
            wire_hash is None
            or body is None
            or manifest.build_manifest_hash != wire_hash
            or manifest.model_key != authorized_provider_model(operation_kind)
            or body.get("model") != manifest.model_key
        ):
            return False
    elif query_context is None or manifest.model_key != query_context.identity.model_key:
        return False

    result = db.get(TeamTurnResult, result_id)
    participant = db.get(ConversationParticipant, result.participant_id) if result else None
    turn = db.get(ConversationTurn, result.turn_id) if result else None
    conversation = db.get(Conversation, result.conversation_id) if result else None
    actor = db.get(User, actor_user_id)
    if (
        result is None
        or participant is None
        or turn is None
        or conversation is None
        or actor is None
        or actor.status != "active"
        or result.state != "running"
        or turn.state != "pending"
        or turn.claim_token != claim_token
        or conversation.active_request_id != turn.id
        or conversation.withdrawn_at is not None
        or conversation.user_id != actor_user_id
        or participant.conversation_id != conversation.id
        or turn.conversation_id != conversation.id
        or conversation.entry_kind not in {"team", "maya_team"}
        or conversation.course_id is None
        or course_member_role(db, actor_user_id, conversation.course_id)
        not in {"student", "teacher"}
        or not _policy(db, current_policy_hash, operation_kind)
    ):
        return False
    if operation_kind == SQL_QUERY_PROVIDER_OPERATION and not _query_context_matches_current_turn(
        db,
        operation=operation,
        query_context=query_context,
        manifest=manifest,
        current_policy_hash=current_policy_hash,
        result_id=result_id,
        turn=turn,
        participant=participant,
        conversation=conversation,
    ):
        return False

    try:
        routing = TeamRouting.model_validate_json(turn.routing_json or "{}")
    except ValueError:
        return False
    participants = list(
        db.scalars(
            select(ConversationParticipant)
            .where(ConversationParticipant.conversation_id == conversation.id)
            .order_by(ConversationParticipant.position)
        )
    )
    requested_ids = {str(value) for value in routing.participant_ids}
    selected_participants = (
        [item for item in participants if item.id in requested_ids]
        if routing.mode == "selected"
        else participants
    )
    if (
        not selected_participants
        or {item.team_member_id for item in selected_participants} != selected_binding_ids
        or participant.team_member_id not in selected_binding_ids
    ):
        return False

    if conversation.entry_kind == "team":
        if (
            conversation.origin != "custom_team"
            or (
                conversation.team_owner_user_id != actor_user_id
                and not chat_team_open_to_non_owner(
                    db,
                    actor_user_id=actor_user_id,
                    team_id=conversation.team_id,
                    team_version_id=conversation.team_version_id,
                    team_authorization_epoch=conversation.team_authorization_epoch,
                )
            )
            or conversation.publication_id is not None
            or conversation.publication_epoch is not None
            or any(item.invoke_grant_id is not None for item in selected_participants)
            or revoked_assessment_scope is not None
        ):
            return False
        try:
            selection = frozen_team_selection(db, conversation)
            resolve_frozen_chat_selection(db, actor_user_id, selection, selected_binding_ids)
        except Exception:
            return False
        standing_grant_id = None
        confirmer_kind = "custom_owner"
        expected_confirmer_id = actor_user_id
    else:
        if (
            conversation.origin != "published_course_team"
            or conversation.publication_id is None
            or conversation.publication_epoch is None
            or conversation.team_owner_user_id is None
        ):
            return False
        publisher = db.get(User, conversation.team_owner_user_id)
        if (
            publisher is None
            or publisher.status != "active"
            or course_member_role(db, publisher.id, conversation.course_id) != "teacher"
        ):
            return False
        if revoked_assessment_scope is None:
            try:
                selection = frozen_team_selection(db, conversation)
                resolve_frozen_chat_selection(db, actor_user_id, selection, selected_binding_ids)
                grant = current_standing_grant(
                    db,
                    actor_user_id,
                    selection,
                    selected_binding_ids,
                    current_policy_hash,
                    operation_kind,
                )
            except Exception:
                return False
            if grant is None:
                return False
        else:
            if serialized_request is None:
                return False
            try:
                grant, _group_id, _agent_version_id = _authorize_revoked_assessment_dispatch(
                    db,
                    actor_user_id=actor_user_id,
                    result=result,
                    participant=participant,
                    turn=turn,
                    conversation=conversation,
                    manifest=manifest,
                    selected_binding_ids=selected_binding_ids,
                    claim_token=claim_token,
                    scope=revoked_assessment_scope,
                    serialized_request=serialized_request,
                    current_policy_hash=current_policy_hash,
                )
            except Exception:
                return False
        standing_grant_id = grant.id
        confirmer_kind = "published_chat_owner"
        expected_confirmer_id = actor_user_id

    binding = db.get(TeamProviderConsentBinding, manifest_hash)
    if (
        binding is None
        or binding.confirmation_id != confirmation_id
        or binding.result_id != result_id
        or binding.actor_user_id != actor_user_id
        or binding.confirmer_user_id != expected_confirmer_id
        or binding.confirmer_kind != confirmer_kind
        or binding.standing_grant_id != standing_grant_id
        or binding.team_epoch != conversation.team_authorization_epoch
        or binding.publication_epoch != conversation.publication_epoch
    ):
        return False
    return True


def _query_context_matches_current_turn(
    db: Session,
    *,
    operation: Mapping[str, object],
    query_context: SqlQueryRequestV1 | None,
    manifest: ExportManifestV1,
    current_policy_hash: str,
    result_id: str,
    turn: ConversationTurn,
    participant: ConversationParticipant,
    conversation: Conversation,
) -> bool:
    if query_context is None:
        return False
    try:
        query_text = turn.user_text.strip()
        query_hash = hashlib.sha256(query_text.encode("utf-8")).hexdigest()
        snapshot = db.get(KnowledgeSnapshot, participant.snapshot_id)
        version = db.get(AgentVersion, participant.agent_version_id)
        agent = db.get(Agent, participant.agent_id)
        if (
            not query_text
            or snapshot is None
            or version is None
            or agent is None
            or agent.deleted_at is not None
            or agent.course_id != conversation.course_id
            or agent.authorization_epoch != participant.agent_authorization_epoch
            or version.agent_id != agent.id
            or version.knowledge_snapshot_id != snapshot.id
            or snapshot.agent_version_id != version.id
            or query_context.scope_id != f"team-result:{result_id}"
            or query_context.snapshot_id != snapshot.id
            or query_context.policy_hash != current_policy_hash
            or operation.get("logical_item_id") != query_context.logical_item_id
            or operation.get("export_manifest_hash") != query_context.export_manifest_hash
            or operation.get("build_manifest_hash") != query_context.build_manifest_hash
            or operation.get("model_key") != query_context.identity.model_key
            or query_context.export_manifest_hash != manifest.manifest_hash
            or query_context.build_manifest_hash != manifest.build_manifest_hash
            or query_context.query_hashes != (query_hash,)
            or query_context.attempt_no != operation.get("attempt_no")
            or query_context.logical_item_id != f"team:{turn.id}:{participant.id}"
            or query_context.confirmation_revision != manifest.operation_revision
        ):
            return False

        identity = query_context.identity
        snapshot_identity = (
            snapshot.embedding_provider,
            snapshot.embedding_key,
            snapshot.embedding_region,
            snapshot.embedding_dimension,
            snapshot.embedding_policy_version,
        )
        expected_identity = (
            REAL_EMBEDDING_IDENTITY.provider,
            REAL_EMBEDDING_IDENTITY.model_key,
            REAL_EMBEDDING_IDENTITY.region,
            REAL_EMBEDDING_IDENTITY.dimension,
            REAL_EMBEDDING_IDENTITY.policy_version,
        )
        request_identity = (
            identity.provider,
            identity.model_key,
            identity.region,
            identity.dimension,
            identity.policy_version,
        )
        if snapshot_identity != expected_identity or request_identity != expected_identity:
            return False

        persona_hash = markdown_hash(version.agent_md)
        transcript_hash = hashlib.sha256(turn.user_text.encode("utf-8")).hexdigest()
        expected_build_hash = _canonical_hash(
            {
                "version": "embedding-query-export-v1",
                "scope_id": f"team-result:{result_id}",
                "turn_id": turn.id,
                "snapshot_id": snapshot.id,
                "identity": {
                    "provider": identity.provider,
                    "model_key": identity.model_key,
                    "region": identity.region,
                    "dimension": identity.dimension,
                    "policy_version": identity.policy_version,
                },
                "transcript_hash": transcript_hash,
                "persona_spec_hash": persona_hash,
                "subqueries": [{"kind": "context", "text": query_text, "query_hash": query_hash}],
            }
        )
        expected_field_hash = _canonical_hash([query_text])
        if (
            manifest.build_manifest_hash != expected_build_hash
            or manifest.persona_spec_hash != persona_hash
            or manifest.model_key != identity.model_key
            or manifest.fields != (ExportFieldV1("current_evidence_excerpt", expected_field_hash),)
            or manifest.max_attempts != 1
            or manifest.contains_secret
            or manifest.contains_identity
            or manifest.contains_private_audio
            or manifest.contains_teacher_note
        ):
            return False

        total_tokens = operation.get("max_tokens")
        if isinstance(total_tokens, bool) or not isinstance(total_tokens, int) or total_tokens < 1:
            return False
        expected_request_hash = _canonical_hash(
            {
                "version": "embedding-query-sql-v1",
                "scope_id": query_context.scope_id,
                "snapshot_id": query_context.snapshot_id,
                "provider_operation": SQL_QUERY_PROVIDER_OPERATION,
                "logical_item_id": query_context.logical_item_id,
                "attempt_no": query_context.attempt_no,
                "policy_hash": query_context.policy_hash,
                "export_manifest_hash": query_context.export_manifest_hash,
                "build_manifest_hash": query_context.build_manifest_hash,
                "query_hashes": query_context.query_hashes,
                "total_tokens": total_tokens,
                "identity": {
                    "provider": identity.provider,
                    "model_key": identity.model_key,
                    "region": identity.region,
                    "dimension": identity.dimension,
                    "policy_version": identity.policy_version,
                },
            }
        )
        return operation.get("request_hash") == expected_request_hash
    except (AttributeError, TypeError, ValueError):
        return False
