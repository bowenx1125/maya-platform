"""Teacher-scoped Debate draft setup and immutable snapshot resolution.

This service owns the M10 write boundary.  Generation, TTS and playback
workers consume the frozen rows later; they must not re-resolve mutable Agent
state after a Debate starts.
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import time
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import (
    PlatformError,
    conflict,
    forbidden,
    idempotency_conflict,
    invalid_state,
    not_found,
    validation_failure,
)
from app.core.models import (
    Agent,
    AgentVersion,
    Course,
    CourseMember,
    Group,
    IdempotencyRecord,
    Job,
    KnowledgeSnapshot,
    StoredFile,
    VoiceProfile,
)
from app.core.version_label import agent_version_label
from app.modules.avatars import AvatarConfigValidationError, validate_avatar_config
from app.modules.debates.generation_params import resolve_params, resolve_voice_params
from app.modules.debates.models import Debate, DebateParticipant, DebateTurn, PlaybackState
from app.modules.debates.owned_copies import (
    adopt_debate_knowledge,
    delete_debate_knowledge,
    voice_snapshot,
)
from app.modules.debates.round_count import (
    debate_teaching_protocol,
    expected_turn_count,
    preview_turn_count,
    uses_segment_protocol,
    visible_turn_predecessors,
)
from app.modules.debates.schemas import (
    RULE_SET_ID_MUTUAL_LEARNING,
    DebateDetail,
    DebateDraftRequest,
    DebateStall,
    DebateSummary,
    RetrievalSource,
)
from app.modules.debates.schemas import (
    DebateParticipant as DebateParticipantDTO,
)
from app.modules.debates.schemas import (
    DebateTurn as DebateTurnDTO,
)
from app.modules.debates.schemas import (
    PlaybackState as PlaybackStateDTO,
)
from app.modules.debates.setup.rules import (
    RuleViolation,
    build_turn_plan,
    canonical_rule_snapshot_json,
)
from app.modules.debates.teaching_rules import freeze_teaching_rules
from app.modules.debates.topic_language import TopicLanguageError, validate_topic
from app.modules.debates.voice_clones import snapshot_debate_voices, sync_debate_clones
from app.modules.interactions.service import create_closed_window
from app.providers.tts import TTS_UNAVAILABLE_CODES

LOGGER = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(UTC)


def _utc_datetime(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _as_uuid(value: str | UUID) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))


def _next_turn_ready(db: Session, debate_id: str, playback: Any) -> bool:
    """Derive the closed public readiness bit without persisting a column."""

    if playback.status not in {"playing", "paused", "waiting_next"} or not playback.current_turn_id:
        return False
    debate = db.get(Debate, debate_id)
    if debate is None:
        return False
    turns = list(
        db.scalars(
            select(DebateTurn)
            .where(DebateTurn.debate_id == debate_id)
            .order_by(DebateTurn.turn_index, DebateTurn.id)
        ).all()
    )

    if playback.mode == "replay":
        if (
            debate.status not in {"debate_finished", "completed"}
            or playback.replay_scope != "all"
            or playback.replay_index is None
        ):
            return False
        queue_ids: list[str] = []
        raw_queue = getattr(playback, "replay_turn_ids_json", None)
        if raw_queue:
            try:
                parsed_queue = json.loads(str(raw_queue))
            except (TypeError, ValueError):
                return False
            if not isinstance(parsed_queue, list):
                return False
            queue_ids = [str(item) for item in parsed_queue]
        if queue_ids:
            if len(set(queue_ids)) != len(queue_ids):
                return False
            by_id = {str(row.id): row for row in turns}
            if any(item not in by_id for item in queue_ids):
                return False
            queue = [by_id[item] for item in queue_ids]
        else:
            # Migrations before the durable queue column are still readable.
            queue = [
                row
                for row in turns
                if row.publication_status == "public" and row.generation_status == "final_ready"
            ]
        if not queue or any(row.publication_status != "public" for row in queue):
            return False
        try:
            indexes = [int(row.turn_index) for row in queue]
            replay_index = int(playback.replay_index)
        except (TypeError, ValueError):
            return False
        if indexes != list(range(len(queue))) or not 0 <= replay_index < len(queue):
            return False
        current = queue[replay_index]
        if str(current.id) != str(playback.current_turn_id):
            return False
        if replay_index + 1 >= len(queue):
            return False
        successor = queue[replay_index + 1]
        adjacent = [row for row in turns if row.turn_index == current.turn_index + 1]
        if len(adjacent) != 1 or str(adjacent[0].id) != str(successor.id):
            return False
        if successor.generation_status != "final_ready" or not successor.audio_file_id:
            return False
        if not uses_segment_protocol(debate):
            retained = db.scalar(
                select(Course.current_audio_debate_id).where(Course.id == debate.course_id)
            )
            if str(retained) != str(debate_id):
                return False
        try:
            from app.modules.debates.generation.evidence_trace import public_evidence_trace

            for row in (current, successor):
                raw_trace = getattr(row, "evidence_trace_json", None)
                if isinstance(raw_trace, str):
                    if not raw_trace.strip():
                        return False
                    raw_trace = json.loads(raw_trace)
                public_evidence_trace([] if raw_trace is None else raw_trace)
        except (TypeError, ValueError):
            return False
        stored = db.get(StoredFile, successor.audio_file_id)
        if stored is None:
            return False
        settings = db.info.get("maya_settings")
        data_root = getattr(settings, "resolved_data_root", None)
        if data_root is None:
            return False
        from app.modules.debates.playback._core import PlaybackCore
        from app.modules.debates.playback.audio import AudioStore

        return (
            PlaybackCore._validate_retained_audio_facts(
                AudioStore(data_root),
                course_id=str(debate.course_id),
                debate_id=str(debate.id),
                turn_id=str(successor.id),
                record_kind=stored.kind,
                record_state=stored.state,
                relative_path=stored.relative_path,
                expected_sha256=stored.sha256,
                expected_size=stored.size_bytes,
                expected_duration_ms=successor.audio_duration_ms,
            )
            is not None
        )

    if playback.mode != "live" or debate.status != "running":
        return False
    live_current = next((row for row in turns if row.id == playback.current_turn_id), None)
    if live_current is None or live_current.publication_status != "public":
        return False
    successors = [row for row in turns if row.turn_index == live_current.turn_index + 1]
    if len(successors) != 1:
        return False
    successor = successors[0]
    if successor.publication_status != "unpublished":
        return False
    if successor.generation_status not in {"final_ready", "ready", "completed"}:
        return False
    from app.modules.debates.playback._core import PlaybackCore

    text_fallback = PlaybackCore._turn_text_fallback_ready(
        successor
    ) or PlaybackCore._turn_text_only(successor)
    if not successor.audio_file_id and not text_fallback:
        return False
    if successor.transcript_hash is None:
        return False
    try:
        predecessor_ids = json.loads(successor.predecessor_turn_ids_json)
    except (TypeError, ValueError):
        return False
    is_mutual = str(debate.rule_set_id) == RULE_SET_ID_MUTUAL_LEARNING
    visible_predecessors = visible_turn_predecessors(debate, successor, turns)
    expected_ids = [row.id for row in visible_predecessors]
    expected_cutoff = (
        max((int(row.turn_index) for row in visible_predecessors), default=-1)
        if is_mutual
        else successor.turn_index - 1
    )
    if successor.cutoff_turn_index != expected_cutoff:
        return False
    if predecessor_ids != expected_ids:
        return False
    if any(row.publication_status != "public" for row in visible_predecessors):
        return False
    if text_fallback:
        return True
    return (
        db.scalar(
            select(StoredFile.id).where(
                StoredFile.id == successor.audio_file_id,
                StoredFile.state == "active",
            )
        )
        is not None
    )


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _round_count_from_snapshot(debate: Debate) -> int:
    """Read the frozen configured count without changing legacy rows."""

    if str(debate.rule_set_id) != RULE_SET_ID_MUTUAL_LEARNING:
        return 2
    try:
        payload = json.loads(str(debate.rule_snapshot_json))
    except (TypeError, ValueError) as exc:
        raise invalid_state("The mutual-learning rule snapshot is invalid.") from exc
    count = payload.get("round_count") if isinstance(payload, dict) else None
    if not isinstance(count, int) or isinstance(count, bool) or not 2 <= count <= 5:
        raise invalid_state("The mutual-learning round count is invalid.")
    return count


def _settings(db: Session, settings: Settings | None) -> Settings:
    if settings is not None:
        return settings
    configured = db.info.get("maya_settings")
    if isinstance(configured, Settings):
        return configured
    # The service's direct unit-test entry point is intentionally Mock-only.
    return Settings(maya_env="test")


def _independent_session(db: Session) -> Session:
    """Open a short-lived session on the same engine as ``db``.

    A create idempotency claim must be durable before the request starts
    writing its Debate rows.  Keeping the claim in its own transaction means
    a concurrent request can observe the pending claim, wait for the owner to
    finish, and replay its response instead of racing an uncommitted INSERT.
    """

    return Session(bind=db.get_bind(), autoflush=False, expire_on_commit=False)


def require_teacher_course(db: Session, actor_user_id: str, course_id: str) -> None:
    role = db.scalar(
        select(CourseMember.role).where(
            CourseMember.course_id == course_id,
            CourseMember.user_id == actor_user_id,
        )
    )
    if role is None:
        raise not_found()
    if role != "teacher":
        raise forbidden()


def _find_course(db: Session, course_id: str) -> Course:
    course = db.get(Course, course_id)
    if course is None:
        raise not_found()
    return course


def _resolve_agent_version(
    db: Session,
    *,
    course_id: str,
    agent_id: str,
    settings: Settings,
) -> tuple[
    Agent,
    Group | None,
    AgentVersion,
    KnowledgeSnapshot,
    dict[str, Any],
    str | None,
    str | None,
    str,
    bool,
]:
    """Resolve one current published Agent with one bounded relationship join.

    The four rows that define a classroom participant are read together.  In
    particular, the version is reached through the Agent's current pointer
    and the snapshot is reached through that exact version; this avoids
    resolving each row independently and accidentally combining pointers
    from different moments.  The write-side CAS in ``_participant_row``
    rechecks the captured relationship before the frozen participant is
    inserted.
    """

    # Keep this query deliberately narrow: it follows only the selected
    # Agent -> Group -> current AgentVersion -> KnowledgeSnapshot chain.  The
    # outer joins let the service preserve stable validation codes for a
    # missing current pointer or snapshot without issuing a second probe.
    # A teacher's personal Agent has no group, so the group is optional; the
    # course is then checked on the Agent itself.
    resolved = db.execute(
        select(Agent, Group, AgentVersion, KnowledgeSnapshot)
        .outerjoin(Group, Group.id == Agent.group_id)
        .outerjoin(
            AgentVersion,
            and_(
                AgentVersion.id == Agent.current_published_version_id,
                AgentVersion.agent_id == Agent.id,
                AgentVersion.state == "published",
            ),
        )
        .outerjoin(
            KnowledgeSnapshot,
            and_(
                KnowledgeSnapshot.id == AgentVersion.knowledge_snapshot_id,
                KnowledgeSnapshot.agent_version_id == AgentVersion.id,
            ),
        )
        .where(Agent.id == agent_id)
    ).one_or_none()
    if resolved is None:
        raise not_found()
    agent, group, version, snapshot = resolved
    if agent.course_id != course_id or (group is not None and group.course_id != course_id):
        raise not_found()
    if agent.deleted_at is not None:
        raise validation_failure(
            "Archived Agents are not available for new classroom work.",
            code="agent_archived",
        )
    if agent.status == "archived":
        raise validation_failure(
            "Archived Agents are not available for new classroom work.",
            code="agent_archived",
        )
    if version is None or not agent.current_published_version_id:
        raise validation_failure(
            "Only the current published Agent can be selected.",
            code="agent_not_current",
        )
    if version.agent_id != agent.id or version.state != "published":
        raise validation_failure(
            "Only the current published Agent can be selected.",
            code="agent_not_current",
        )
    if not version.knowledge_snapshot_id or snapshot is None:
        raise validation_failure(
            "The current Agent has no published knowledge snapshot.", code="rag_missing"
        )
    if snapshot.agent_version_id != version.id:
        raise validation_failure(
            "The current Agent has no published knowledge snapshot.", code="rag_missing"
        )
    try:
        avatar = json.loads(version.avatar_config_json)
        avatar_model = validate_avatar_config(avatar)
    except (ValueError, TypeError, json.JSONDecodeError, AvatarConfigValidationError) as exc:
        raise validation_failure(
            "The current Agent has no usable Avatar configuration.", code="avatar_missing"
        ) from exc

    from app.modules.voices.service import _groupmate_owner_ids, baseline_configured_voice_id

    own_voice_id = version.voice_profile_id
    requested_voice_id = own_voice_id or baseline_configured_voice_id(settings, agent.id)
    effective_voice_id: str | None = None
    effective_voice_kind = "mock_sentinel"
    fallback_active = True
    if requested_voice_id:
        custom = db.get(VoiceProfile, requested_voice_id)
        # A baseline character has no row to edit. An operator may point it at
        # a ready system profile; a student's own binding stays group-scoped.
        # A group Agent may use its group's voice; a teacher's personal Agent
        # only that teacher's personal voice.
        same_group = custom is not None and (
            (
                group is not None
                and custom.group_id == group.id
                # A clone whose owner left the group no longer speaks for it.
                and custom.consent_actor_user_id
                in set(db.scalars(_groupmate_owner_ids(db, group.id)).all())
            )
            or (
                group is None
                and custom.scope == "personal"
                and custom.consent_actor_user_id == agent.owner_user_id
            )
        )
        operator_system = (
            custom is not None
            and own_voice_id is None
            and custom.scope == "system"
            and custom.group_id is None
        )
        if custom is not None and custom.status == "ready" and (same_group or operator_system):
            effective_voice_id = custom.id
            effective_voice_kind = "platform_profile"
            fallback_active = custom.scope == "system"
    if effective_voice_id is None and settings.fallback_voice_profile_id:
        configured_fallback = db.get(VoiceProfile, settings.fallback_voice_profile_id)
        if (
            configured_fallback is not None
            and configured_fallback.scope == "system"
            and configured_fallback.status == "ready"
        ):
            effective_voice_id = configured_fallback.id
            effective_voice_kind = "platform_profile"
    # Missing speech configuration must not prevent a text Debate. Playback
    # revalidates the custom/system mapping before deciding whether audio exists.
    return (
        agent,
        group,
        version,
        snapshot,
        avatar_model.model_dump(mode="json"),
        requested_voice_id,
        effective_voice_id,
        effective_voice_kind,
        fallback_active,
    )


def _fence_resolved_agent_chain(
    db: Session,
    *,
    agent: Agent,
    group: Group | None,
    version: AgentVersion,
    snapshot: KnowledgeSnapshot,
) -> None:
    """CAS every captured Agent/version/snapshot pointer before insertion.

    A Debate draft owns no participant row until this function succeeds.  A
    stale worker or a concurrent publish/state change therefore gets a
    stable validation error and the caller's transaction can roll back the
    draft/revision atomically.
    """

    if group is not None:
        group_fence = db.execute(
            update(Group)
            .where(Group.id == group.id, Group.course_id == group.course_id)
            .values(created_at=Group.created_at)
        )
        if int(getattr(group_fence, "rowcount", 0)) != 1:
            raise validation_failure(
                "The selected Agent group changed before the Debate draft was saved.",
                code="agent_not_current",
            )

    agent_fence = db.execute(
        update(Agent)
        .where(
            Agent.id == agent.id,
            Agent.group_id.is_(None) if group is None else Agent.group_id == group.id,
            Agent.deleted_at.is_(None),
            Agent.status == "active",
            Agent.current_published_version_id == version.id,
            Agent.name == agent.name,
        )
        .values(updated_at=Agent.updated_at)
    )
    if int(getattr(agent_fence, "rowcount", 0)) != 1:
        raise validation_failure(
            "The selected Agent changed before the Debate draft was saved.",
            code="agent_not_current",
        )

    version_fence = db.execute(
        update(AgentVersion)
        .where(
            AgentVersion.id == version.id,
            AgentVersion.agent_id == agent.id,
            AgentVersion.state == "published",
            AgentVersion.version_seq == version.version_seq,
            AgentVersion.agent_md == version.agent_md,
            AgentVersion.knowledge_snapshot_id == snapshot.id,
            AgentVersion.avatar_config_json == version.avatar_config_json,
            AgentVersion.voice_profile_id == version.voice_profile_id,
            AgentVersion.published_at == version.published_at,
            AgentVersion.raw_agent_md_hash == version.raw_agent_md_hash,
            AgentVersion.persona_spec_json == version.persona_spec_json,
            AgentVersion.persona_spec_hash == version.persona_spec_hash,
            AgentVersion.persona_compiler_version == version.persona_compiler_version,
            AgentVersion.persona_confirmation_revision == version.persona_confirmation_revision,
            AgentVersion.student_confirmed_at == version.student_confirmed_at,
            AgentVersion.persona_confirming_user_id == version.persona_confirming_user_id,
        )
        .values(updated_at=AgentVersion.updated_at)
    )
    if int(getattr(version_fence, "rowcount", 0)) != 1:
        raise validation_failure(
            "The selected Agent version changed before the Debate draft was saved.",
            code="agent_not_current",
        )

    snapshot_fence = db.execute(
        update(KnowledgeSnapshot)
        .where(
            KnowledgeSnapshot.id == snapshot.id,
            KnowledgeSnapshot.agent_version_id == version.id,
            KnowledgeSnapshot.stored_file_id == snapshot.stored_file_id,
            KnowledgeSnapshot.content_hash == snapshot.content_hash,
            KnowledgeSnapshot.total_char_count == snapshot.total_char_count,
            KnowledgeSnapshot.embedding_key == snapshot.embedding_key,
            KnowledgeSnapshot.chunking_json == snapshot.chunking_json,
        )
        .values(created_at=KnowledgeSnapshot.created_at)
    )
    if int(getattr(snapshot_fence, "rowcount", 0)) != 1:
        raise validation_failure(
            "The selected knowledge snapshot changed before the Debate draft was saved.",
            code="rag_missing",
        )


def _assert_participants_ready(
    db: Session, *, course_id: str, payload: Any, settings: Settings
) -> None:
    """Refuse once with every Agent's problems, each naming its Agent.

    An Agent this course cannot see is left to the resolver, which answers
    404 without saying whether it exists.
    """

    from app.modules.agents.readiness import debate_issues

    issues: list[dict[str, Any]] = []
    for item in payload.participants:
        agent = db.get(Agent, str(item.agent_id))
        if agent is None or agent.course_id != course_id:
            # Missing and out-of-course read the same, so existence is not told.
            issues.append(_participant_issue(db, course_id, str(item.agent_id), "agent_not_found"))
            continue
        issues.extend(debate_issues(db, agent, settings))
    if issues:
        raise _agents_not_ready(course_id, issues)


def _participant_issue(db: Session, course_id: str, agent_id: str, kind: str) -> dict[str, Any]:
    from app.modules.agents.readiness import named_issue

    agent = db.get(Agent, agent_id)
    name = agent.name if agent is not None and agent.course_id == course_id else ""
    return named_issue(agent_id, name, kind)


def _agents_not_ready(course_id: str, issues: list[dict[str, Any]]) -> PlatformError:
    LOGGER.info(
        "debate_agents_not_ready course_id=%s issues=%s",
        course_id,
        ",".join(f"{item['agent_id']}:{item['issue']}" for item in issues),
    )
    return validation_failure(
        "Some selected Agents are not ready for a Debate.",
        {"issues": issues},
        code="debate_agents_not_ready",
    )


# A single refusal while resolving or fencing one participant, as the issue
# the Debate form shows next to that Agent.
_PARTICIPANT_CODES = {
    "not_found": "agent_not_found",
    "agent_archived": "agent_archived",
    "agent_not_current": "agent_not_current",
    "rag_missing": "rag_missing",
    "avatar_missing": "avatar_missing",
}


def _participant_row(
    db: Session,
    *,
    debate: Debate,
    item: Any,
    order_index: int,
    settings: Settings,
) -> DebateParticipant:
    try:
        (
            agent,
            group,
            version,
            snapshot,
            avatar,
            requested_voice_id,
            effective_voice_id,
            effective_voice_kind,
            fallback_active,
        ) = _resolve_agent_version(
            db,
            course_id=debate.course_id,
            agent_id=str(item.agent_id),
            settings=settings,
        )
        # Revalidate the complete captured relationship immediately before the
        # frozen row is returned to the caller's final write transaction.
        _fence_resolved_agent_chain(
            db,
            agent=agent,
            group=group,
            version=version,
            snapshot=snapshot,
        )
    except PlatformError as error:
        kind = _PARTICIPANT_CODES.get(error.code)
        if kind is None:
            raise
        issue = _participant_issue(db, debate.course_id, str(item.agent_id), kind)
        raise _agents_not_ready(debate.course_id, [issue]) from error
    stance = item.assigned_stance if item.stance_mode == "assigned" else None
    timestamp = utc_now()
    voice_json, voice_cipher = voice_snapshot(
        db.get(VoiceProfile, effective_voice_id) if effective_voice_id else None
    )
    return DebateParticipant(
        id=str(uuid4()),
        debate_id=debate.id,
        course_id=debate.course_id,
        group_id=group.id if group is not None else None,
        agent_id=agent.id,
        agent_version_id=version.id,
        knowledge_snapshot_id=snapshot.id,
        agent_md_snapshot=version.agent_md,
        persona_spec_hash_snapshot=version.persona_spec_hash,
        voice_snapshot_json=voice_json,
        voice_external_id_encrypted=voice_cipher,
        slot=chr(65 + order_index),
        order_index=order_index,
        agent_name=agent.name,
        version_label=agent_version_label(version.version_seq),
        avatar_config_json=json.dumps(avatar, sort_keys=True, separators=(",", ":")),
        requested_voice_profile_id=requested_voice_id,
        effective_voice_kind=effective_voice_kind,
        effective_voice_profile_id=effective_voice_id,
        voice_fallback_active=fallback_active,
        stance_mode=item.stance_mode,
        initial_stance=stance,
        current_stance=stance,
        teacher_note=item.teacher_note,
        initial_position_summary="",
        current_position_summary="",
        created_at=timestamp,
        updated_at=timestamp,
    )


def _ensure_payload(payload: DebateDraftRequest, *, teaching_protocol: str | None = None) -> None:
    if teaching_protocol == "four_round_v1" and payload.round_count != 4:
        raise validation_failure(
            "The teaching protocol requires exactly four rounds.", code="teaching_protocol_invalid"
        )
    try:
        build_turn_plan(
            [str(item.agent_id) for item in payload.participants],
            round_count=payload.round_count,
            rule_set_id=payload.rule_set_id,
            teaching_protocol=teaching_protocol,
        )
    except RuleViolation as exc:
        raise validation_failure(exc.message, code=exc.code) from exc


def _validated_topic(value: str, output_language: str = "en") -> str:
    """Apply the shared topic boundary and expose its stable API error."""

    try:
        return validate_topic(value, output_language)
    except TopicLanguageError as exc:
        raise validation_failure(exc.message, exc.details, code=exc.code) from exc


def _claim_create_idempotency(
    db: Session,
    *,
    actor_user_id: str,
    key: str,
    body_hash: str,
) -> tuple[IdempotencyRecord, DebateDetail | None]:
    if len(key) < 16:
        raise conflict(
            "idempotency_conflict", "Idempotency-Key must contain at least 16 characters."
        )
    # Release the authorization/read snapshot before opening a second writer.
    # Otherwise SQLite WAL can reject the independent claim commit when this
    # request's original transaction is upgraded after a concurrent request.
    db.rollback()
    poll_deadline = time.monotonic() + 10.0
    while True:
        claim_session = _independent_session(db)
        try:
            existing = claim_session.scalar(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.actor_user_id == actor_user_id,
                    IdempotencyRecord.operation == "createDebate",
                    IdempotencyRecord.key == key,
                )
            )
            if existing is None:
                now = utc_now()
                candidate = IdempotencyRecord(
                    id=str(uuid4()),
                    actor_user_id=actor_user_id,
                    operation="createDebate",
                    key=key,
                    request_hash=body_hash,
                    state="pending",
                    claim_token=secrets.token_urlsafe(32),
                    lease_expires_at=now + timedelta(seconds=10),
                    created_at=now,
                    updated_at=now,
                )
                claim_session.add(candidate)
                try:
                    claim_session.commit()
                except IntegrityError:
                    # Another request won the unique-key race.  Its claim is
                    # now the authority; resolve it using the same hash and
                    # lease rules below instead of returning invalid_state.
                    claim_session.rollback()
                    existing = claim_session.scalar(
                        select(IdempotencyRecord).where(
                            IdempotencyRecord.actor_user_id == actor_user_id,
                            IdempotencyRecord.operation == "createDebate",
                            IdempotencyRecord.key == key,
                        )
                    )
                else:
                    db.expire_all()
                    claimed = db.get(IdempotencyRecord, candidate.id)
                    if claimed is None:  # pragma: no cover - defensive DB fault
                        raise invalid_state("The idempotency claim could not be loaded.")
                    return claimed, None

            if existing is None or existing.request_hash != body_hash:
                raise idempotency_conflict()
            if existing.state == "completed" and existing.response_json:
                db.expire_all()
                claimed = db.get(IdempotencyRecord, existing.id)
                if claimed is None:  # pragma: no cover - defensive DB fault
                    raise invalid_state("The idempotency replay could not be loaded.")
                return claimed, DebateDetail.model_validate(json.loads(existing.response_json))

            now = utc_now()
            if existing.state == "pending" and _utc_datetime(existing.lease_expires_at) > now:
                # Do not hold this read transaction while the owner commits
                # its Debate and response.  The loop reopens a fresh read.
                pass
            elif existing.state == "pending":
                new_token = secrets.token_urlsafe(32)
                changed = claim_session.execute(
                    update(IdempotencyRecord)
                    .where(
                        IdempotencyRecord.id == existing.id,
                        IdempotencyRecord.state == "pending",
                        IdempotencyRecord.request_hash == body_hash,
                        IdempotencyRecord.claim_token == existing.claim_token,
                        IdempotencyRecord.lease_expires_at <= now,
                    )
                    .execution_options(synchronize_session=False)
                    .values(
                        claim_token=new_token,
                        lease_expires_at=now + timedelta(seconds=10),
                        updated_at=now,
                    )
                )
                if int(getattr(changed, "rowcount", 0)) == 1:
                    claim_session.commit()
                    db.expire_all()
                    claimed = db.get(IdempotencyRecord, existing.id)
                    if claimed is None:  # pragma: no cover - defensive DB fault
                        raise invalid_state("The idempotency claim could not be loaded.")
                    return claimed, None
                claim_session.rollback()
            elif existing.state == "abandoned":
                changed = claim_session.execute(
                    update(IdempotencyRecord)
                    .where(
                        IdempotencyRecord.id == existing.id,
                        IdempotencyRecord.state == "abandoned",
                        IdempotencyRecord.request_hash == body_hash,
                    )
                    .execution_options(synchronize_session=False)
                    .values(
                        state="pending",
                        claim_token=secrets.token_urlsafe(32),
                        lease_expires_at=now + timedelta(seconds=10),
                        updated_at=now,
                    )
                )
                if int(getattr(changed, "rowcount", 0)) == 1:
                    claim_session.commit()
                    db.expire_all()
                    claimed = db.get(IdempotencyRecord, existing.id)
                    if claimed is None:  # pragma: no cover - defensive DB fault
                        raise invalid_state("The idempotency claim could not be loaded.")
                    return claimed, None
                claim_session.rollback()
            else:
                raise invalid_state("The Debate creation idempotency record is invalid.")
        finally:
            claim_session.close()
        if time.monotonic() >= poll_deadline:
            raise conflict(
                "invalid_state",
                "An identical request is already in progress; retry shortly.",
                {"retry_after_seconds": 1},
            )
        time.sleep(0.05)


def _assert_create_claim_owned(db: Session, record: IdempotencyRecord) -> None:
    """Fence a stale create worker before it writes Debate rows."""

    claim_session = _independent_session(db)
    try:
        owned = claim_session.scalar(
            select(IdempotencyRecord.id).where(
                IdempotencyRecord.id == record.id,
                IdempotencyRecord.state == "pending",
                IdempotencyRecord.claim_token == record.claim_token,
                IdempotencyRecord.lease_expires_at > utc_now(),
            )
        )
    finally:
        claim_session.close()
    if owned is None:
        raise invalid_state("The Debate creation idempotency claim is no longer owned.")


def _detail(db: Session, debate: Debate) -> DebateDetail:
    # Stuck Preparing must leave the spinner before the page is projected so
    # Retry/Revocalize become visible without waiting for a process restart.
    if str(getattr(debate, "status", "")) in {"draft", "running"}:
        try:
            from app.modules.debates.playback.sql_repository import SqlPlaybackRepository

            expired = SqlPlaybackRepository().expire_stale_preparation(db, debate_id=str(debate.id))
            if expired:
                db.commit()
        except Exception:
            db.rollback()
    # Reads never build the turn plan: the plan and head prepare job are
    # written by create (same transaction), by the prewarm planner (its own
    # committed transaction) and by Start.  An uncommitted plan write here held
    # SQLite's writer lock on every polled GET and starved the prewarm worker.
    participants = db.scalars(
        select(DebateParticipant)
        .where(DebateParticipant.debate_id == debate.id)
        .order_by(DebateParticipant.order_index)
    ).all()
    turn_rows = db.scalars(
        select(DebateTurn)
        .where(
            DebateTurn.debate_id == debate.id,
            DebateTurn.publication_status == "public",
        )
        .order_by(DebateTurn.turn_index)
    ).all()
    # Generated, not published: during pre-warm nothing is public yet, and
    # progress is exactly what has been generated so far.
    prepared_turns = int(
        db.scalar(
            select(func.count())
            .select_from(DebateTurn)
            .where(
                DebateTurn.debate_id == debate.id,
                DebateTurn.generation_status.in_(("final_ready", "ready", "completed")),
            )
        )
        or 0
    )
    preview = None
    if uses_segment_protocol(debate):
        preview_expected = preview_turn_count(debate, len(participants))
        preview_prepared = int(
            db.scalar(
                select(func.count())
                .select_from(DebateTurn)
                .where(
                    DebateTurn.debate_id == debate.id,
                    DebateTurn.round_no < _round_count_from_snapshot(debate),
                    DebateTurn.generation_status.in_(("final_ready", "ready", "completed")),
                    or_(
                        DebateTurn.audio_file_id.is_not(None),
                        and_(
                            DebateTurn.audio_file_id.is_(None),
                            or_(
                                DebateTurn.audio_duration_ms.is_(None),
                                and_(
                                    DebateTurn.audio_duration_ms == 0,
                                    DebateTurn.safe_error_code == "tts_voice_unavailable",
                                ),
                            ),
                            DebateTurn.safe_error_code.in_(TTS_UNAVAILABLE_CODES),
                            func.trim(DebateTurn.speech) != "",
                        ),
                    ),
                )
            )
            or 0
        )
        preview = {
            "prepared_turns": preview_prepared,
            "expected_turns": preview_expected,
            "ready": preview_prepared == preview_expected and preview_expected > 0,
        }
    playback = db.scalar(select(PlaybackState).where(PlaybackState.debate_id == debate.id))
    if playback is None:
        playback_dto = PlaybackStateDTO(
            status="preparing",
            mode="live",
            current_turn_id=None,
            cursor_ms=0,
            control_version=0,
            next_turn_ready=False,
        )
    else:
        playback_dto = PlaybackStateDTO.model_validate(
            {
                "status": playback.status,
                "mode": playback.mode,
                "current_turn_id": (
                    _as_uuid(playback.current_turn_id) if playback.current_turn_id else None
                ),
                "cursor_ms": playback.cursor_ms,
                "control_version": playback.control_version,
                "next_turn_ready": _next_turn_ready(db, debate.id, playback),
            }
        )
    participant_dtos = [
        DebateParticipantDTO.model_validate(
            {
                "id": _as_uuid(row.id),
                "slot": row.slot,
                "order_index": row.order_index,
                "agent_id": _as_uuid(row.agent_id) if row.agent_id else None,
                "agent_name": row.agent_name,
                "agent_version_id": (
                    _as_uuid(row.agent_version_id) if row.agent_version_id else None
                ),
                "version_label": row.version_label,
                "knowledge_snapshot_id": _as_uuid(row.knowledge_snapshot_id),
                "avatar_config": json.loads(row.avatar_config_json),
                "effective_voice_profile_id": (
                    _as_uuid(row.effective_voice_profile_id)
                    if row.effective_voice_profile_id
                    else None
                ),
                "voice_fallback_active": row.voice_fallback_active,
                "stance_mode": row.stance_mode,
                "initial_stance": row.initial_stance,
                "current_stance": row.current_stance,
                "current_position_summary": row.current_position_summary,
            }
        )
        for row in participants
    ]
    turn_dtos: list[DebateTurnDTO] = []
    synthesis_inputs: list[dict[str, Any]] = []
    participant_by_id = {row.id: row for row in participants}
    from app.modules.debates.setup.segment_projection import (
        preview_turn_projection,
        segment_projection,
    )

    for row in turn_rows:
        # TurnSource is imported lazily to keep this service's core imports
        # concise and to avoid a circular type-only dependency.
        from app.modules.debates.models import TurnSource

        source_rows = db.scalars(
            select(TurnSource).where(TurnSource.turn_id == row.id).order_by(TurnSource.rank)
        ).all()
        mutual_result = None
        segment_result, segment_sources = segment_projection(
            db, row, participant_by_id[row.participant_id]
        )
        phase = None
        if segment_result is not None:
            from app.modules.debates.generation.round_phase import phase_for_round

            phase = phase_for_round(row.round_no, _round_count_from_snapshot(debate)).value
        evidence_trace: list[dict[str, Any]] = []
        if (
            str(debate.rule_set_id) == RULE_SET_ID_MUTUAL_LEARNING
            and row.structured_json
            and segment_result is None
        ):
            from app.modules.debates.generation.round_phase import phase_for_round
            from app.modules.debates.generation.types import MutualLearningTurnResultV1

            try:
                mutual_result = MutualLearningTurnResultV1.model_validate(
                    json.loads(row.structured_json)
                )
                phase = phase_for_round(row.round_no, _round_count_from_snapshot(debate)).value
                synthesis_inputs.append(
                    {
                        "participant_id": row.participant_id,
                        "round_no": row.round_no,
                        "publication_status": row.publication_status,
                        "structured": mutual_result,
                    }
                )
            except (TypeError, ValueError) as exc:
                raise invalid_state("A mutual-learning turn has invalid structured data.") from exc
        raw_trace = getattr(row, "evidence_trace_json", None)
        if raw_trace is None:
            raw_trace = getattr(row, "evidence_trace", None)
        if raw_trace is None:
            raw_trace = getattr(row, "evidence_traces", None)
        if raw_trace:
            from app.modules.debates.generation.evidence_trace import public_evidence_trace

            try:
                trace_value = (
                    json.loads(str(raw_trace)) if isinstance(raw_trace, str) else raw_trace
                )
                evidence_trace = [
                    item.model_dump(mode="json") for item in public_evidence_trace(trace_value)
                ]
            except (TypeError, ValueError) as exc:
                raise invalid_state("A Debate turn has invalid evidence trace data.") from exc
        turn_dtos.append(
            DebateTurnDTO.model_validate(
                {
                    "id": _as_uuid(row.id),
                    "participant_id": _as_uuid(row.participant_id),
                    "round_no": row.round_no,
                    "phase": phase,
                    "turn_index": row.turn_index,
                    "speech": row.speech or "",
                    "retrieval_status": row.retrieval_status or "no_match",
                    "grounding_mode": row.grounding_mode or "general_reasoning",
                    "sources": [
                        RetrievalSource(
                            source_filename=source.source_filename,
                            chunk_id=_as_uuid(source.chunk_id),
                        )
                        for source in source_rows
                    ],
                    "mutual_learning": mutual_result,
                    "segment_turn": segment_result,
                    "source_details": segment_sources,
                    "audio_ready": bool(
                        row.audio_file_id
                        and (audio_file := db.get(StoredFile, row.audio_file_id)) is not None
                        and audio_file.state == "active"
                    )
                    if uses_segment_protocol(debate)
                    else None,
                    "evidence_trace": evidence_trace,
                }
            )
        )
    synthesis = None
    if str(debate.rule_set_id) == RULE_SET_ID_MUTUAL_LEARNING:
        round_count = _round_count_from_snapshot(debate)
        final_inputs = [item for item in synthesis_inputs if item["round_no"] == round_count]
        if len(final_inputs) == len(participants):
            from app.modules.debates.generation.mutual_learning_synthesis import (
                build_mutual_learning_synthesis,
            )

            synthesis = build_mutual_learning_synthesis(final_inputs, topic=debate.topic)
    return DebateDetail.model_validate(
        {
            "id": _as_uuid(debate.id),
            "course_id": _as_uuid(debate.course_id),
            "topic": debate.topic,
            "background": debate.background,
            "status": debate.status,
            "created_at": debate.created_at,
            "revision": debate.revision,
            "last_sequence": debate.last_sequence,
            "rule_set_id": debate.rule_set_id,
            "round_count": _round_count_from_snapshot(debate),
            "output_language": debate.output_language,
            "turn_protocol": "segments_v2" if uses_segment_protocol(debate) else None,
            "teaching_protocol": debate_teaching_protocol(debate),
            "final_input_frozen": bool(debate.final_input_json),
            # The list projection has carried these since pre-warm landed; the
            # detail did not, so a debate's own page reported 0/0 and the
            # language it was generated in came back as null.
            "prepared_turns": prepared_turns,
            "expected_turns": expected_turn_count(debate, len(participant_dtos)),
            "audio_restore_needed": db.scalar(
                select(DebateTurn.id)
                .where(
                    DebateTurn.debate_id == debate.id,
                    DebateTurn.generation_status == "final_ready",
                    DebateTurn.speech.is_not(None),
                    DebateTurn.audio_file_id.is_(None),
                )
                .limit(1)
            )
            is not None,
            "preview": preview,
            "preview_turns": [
                preview_turn_projection(db, turn, participant_by_id[turn.participant_id])
                for turn in db.scalars(
                    select(DebateTurn)
                    .where(
                        DebateTurn.debate_id == debate.id,
                        DebateTurn.round_no < _round_count_from_snapshot(debate),
                    )
                    .order_by(DebateTurn.turn_index)
                ).all()
            ]
            if uses_segment_protocol(debate)
            else [],
            "participants": participant_dtos,
            "public_turns": turn_dtos,
            "playback": playback_dto,
            **_classroom_statuses(db, debate.id),
            "mutual_learning_synthesis": synthesis,
        }
    )


def _classroom_statuses(db: Session, debate_id: str) -> dict[str, str]:
    """Read interaction, insight and report status from their own tables.

    The detail used to hard-code ``closed``/``not_started``, so a Debate whose
    report Version 1 was ready still said ``report_status: not_started``.
    """

    from app.modules.interactions.models import ClassroomInteractionWindow
    from app.modules.reports.models import BarrageInsightSnapshot, CivilizationReport

    window_status = db.scalar(
        select(ClassroomInteractionWindow.status).where(
            ClassroomInteractionWindow.debate_id == debate_id
        )
    )
    insight_status = db.scalar(
        select(BarrageInsightSnapshot.status)
        .where(BarrageInsightSnapshot.debate_id == debate_id)
        .order_by(BarrageInsightSnapshot.revision_no.desc(), BarrageInsightSnapshot.id.desc())
        .limit(1)
    )
    report_status = db.scalar(
        select(CivilizationReport.generation_status).where(
            CivilizationReport.debate_id == debate_id
        )
    )
    return {
        "interaction_status": str(window_status or "closed"),
        "insight_status": str(insight_status or "not_started"),
        "report_status": str(report_status or "not_started"),
    }


def debate_summary(
    debate: Debate,
    *,
    prepared_turns: int = 0,
    expected_turns: int = 0,
    stall: DebateStall | None = None,
    preview_prepared: int = 0,
    audio_restore_needed: bool = False,
    participant_count: int = 0,
) -> DebateSummary:
    return DebateSummary.model_validate(
        {
            "id": _as_uuid(debate.id),
            "course_id": _as_uuid(debate.course_id),
            "topic": debate.topic,
            "round_count": _round_count_from_snapshot(debate),
            "status": debate.status,
            "created_at": debate.created_at,
            "prepared_turns": prepared_turns,
            "audio_restore_needed": audio_restore_needed,
            "expected_turns": expected_turns,
            "stall": stall,
            "preview": {
                "prepared_turns": preview_prepared,
                "expected_turns": preview_turn_count(debate, participant_count),
                "ready": preview_prepared == preview_turn_count(debate, participant_count)
                and participant_count > 0,
            }
            if uses_segment_protocol(debate) and participant_count > 0
            else None,
        }
    )


def create_debate_draft(
    db: Session,
    *,
    actor_user_id: str,
    course_id: str,
    payload: DebateDraftRequest,
    idempotency_key: str | None = None,
    settings: Settings | None = None,
) -> DebateDetail:
    require_teacher_course(db, actor_user_id, course_id)
    _find_course(db, course_id)
    topic = _validated_topic(payload.topic, payload.output_language)
    if payload.round_count != 4:
        raise validation_failure(
            "New debates require exactly four rounds.", code="teaching_protocol_invalid"
        )
    _ensure_payload(payload, teaching_protocol="four_round_v1")
    body_hash = _canonical_hash(
        {
            "course_id": course_id,
            **payload.model_copy(update={"topic": topic}).model_dump(mode="json"),
        }
    )
    record: IdempotencyRecord | None = None
    if idempotency_key:
        record, replay = _claim_create_idempotency(
            db, actor_user_id=actor_user_id, key=idempotency_key, body_hash=body_hash
        )
        if replay is not None:
            return replay
    # Final authority check occurs after the idempotency claim and immediately
    # before all Debate rows are inserted.
    require_teacher_course(db, actor_user_id, course_id)
    if record is not None:
        _assert_create_claim_owned(db, record)
    timestamp = utc_now()
    runtime_settings = _settings(db, settings)
    debate = Debate(
        id=str(uuid4()),
        course_id=course_id,
        topic=topic,
        background=payload.background,
        output_language=payload.output_language,
        rule_set_id=payload.rule_set_id,
        rule_snapshot_json=canonical_rule_snapshot_json(
            rule_set_id=payload.rule_set_id,
            round_count=payload.round_count,
            turn_protocol="segments_v2",
            teaching_protocol="four_round_v1",
            frozen_teaching=freeze_teaching_rules(
                payload.teaching_prompts.model_dump()
                if payload.teaching_prompts is not None
                else None,
                # Frozen with the Ruleset: every turn sends these values.
                llm_params=resolve_params(runtime_settings, payload.llm_params),
                # Every speech (preview, live, regenerated) uses these voice values.
                voice_params=resolve_voice_params(runtime_settings, payload.voice_params),
            ),
        ),
        status="draft",
        revision=0,
        last_sequence=0,
        cancellation_generation=0,
        created_by=actor_user_id,
        created_at=timestamp,
        updated_at=timestamp,
        total_duration_seconds=None,
        turn_duration_seconds=None,
    )
    db.add(debate)
    db.flush()
    # Wave 3 interaction state is a required Debate child, never a lazily
    # created side record.  Keeping it in this writer transaction guarantees
    # every committed new Debate has exactly one closed classroom window.
    create_closed_window(db, debate)
    _assert_participants_ready(
        db, course_id=debate.course_id, payload=payload, settings=runtime_settings
    )
    participant_rows = [
        _participant_row(
            db,
            debate=debate,
            item=item,
            order_index=index,
            settings=runtime_settings,
        )
        for index, item in enumerate(payload.participants)
    ]
    require_teacher_course(db, actor_user_id, course_id)
    db.add_all(participant_rows)
    db.flush()
    adopt_debate_knowledge(
        db, debate.id, list(participant_rows), runtime_settings.resolved_data_root
    )
    # The Debate keeps each voice's recording and supplier ID; no enrollment.
    snapshot_debate_voices(
        db,
        debate.id,
        list(participant_rows),
        settings=runtime_settings,
        data_root=runtime_settings.resolved_data_root,
    )
    db.add(
        PlaybackState(
            id=str(uuid4()),
            debate_id=debate.id,
            status="preparing",
            mode="live",
            current_turn_id=None,
            cursor_ms=0,
            control_version=0,
            created_at=timestamp,
            updated_at=timestamp,
        )
    )
    db.flush()
    # Line C M2: materialise the turn plan + head debate_turn_prepare job in the
    # create transaction. Prewarm remains the worker, but must not be the only
    # asker for the plan — otherwise a busy/skipped warmer leaves zero turns,
    # bare list "thinking", and an empty Preview with no Retry surface.
    from app.modules.debates.playback.sql_repository import SqlPlaybackRepository

    SqlPlaybackRepository().ensure_turn_plan(db, cast(Any, debate))
    result = _detail(db, debate)
    if record is not None:
        response_json = json.dumps(result.model_dump(mode="json"), separators=(",", ":"))
        changed = db.execute(
            update(IdempotencyRecord)
            .where(
                IdempotencyRecord.id == record.id,
                IdempotencyRecord.state == "pending",
                IdempotencyRecord.claim_token == record.claim_token,
                IdempotencyRecord.lease_expires_at > utc_now(),
            )
            .execution_options(synchronize_session=False)
            .values(
                state="completed",
                status_code=201,
                response_json=response_json,
                updated_at=utc_now(),
            )
        )
        if int(getattr(changed, "rowcount", 0)) != 1:
            raise invalid_state("The Debate creation idempotency claim is no longer owned.")
        record.state = "completed"
        record.status_code = 201
        record.response_json = response_json
        record.updated_at = utc_now()
    return result


def list_debates(db: Session, *, actor_user_id: str, course_id: str) -> list[DebateSummary]:
    require_teacher_course(db, actor_user_id, course_id)
    _find_course(db, course_id)
    rows = db.scalars(
        select(Debate)
        .where(Debate.course_id == course_id, Debate.deleted_at.is_(None))
        .order_by(Debate.created_at.desc())
    ).all()
    # One query for every Debate's turns rather than one per row: the list is
    # the screen a teacher watches while a draft warms, and it is polled.
    summaries: list[DebateSummary] = []
    audio_missing: set[str] = set()
    ready_by_debate: dict[str, int] = {}
    preview_by_debate: dict[str, int] = {}
    rounds_by_debate = {row.id: _round_count_from_snapshot(row) for row in rows}
    participants_by_debate: dict[str, int] = {}
    stall_by_debate: dict[str, DebateStall] = {}
    if rows:
        ids = [row.id for row in rows]
        # Expire stuck Preparing before projecting stall badges.
        try:
            from app.modules.debates.playback.sql_repository import SqlPlaybackRepository

            repo = SqlPlaybackRepository()
            expired_any = False
            for debate_id in ids:
                if repo.expire_stale_preparation(db, debate_id=str(debate_id)):
                    expired_any = True
            if expired_any:
                db.commit()
        except Exception:
            db.rollback()
        text_fallback = and_(
            DebateTurn.audio_file_id.is_(None),
            or_(
                DebateTurn.audio_duration_ms.is_(None),
                and_(
                    DebateTurn.audio_duration_ms == 0,
                    DebateTurn.safe_error_code == "tts_voice_unavailable",
                ),
            ),
            DebateTurn.safe_error_code.in_(TTS_UNAVAILABLE_CODES),
            func.trim(DebateTurn.speech) != "",
        )
        for debate_id, round_no, audio_ready, text_ready, ready in db.execute(
            select(
                DebateTurn.debate_id,
                DebateTurn.round_no,
                DebateTurn.audio_file_id.is_not(None),
                text_fallback,
                func.count(),
            )
            .where(
                DebateTurn.debate_id.in_(ids),
                DebateTurn.generation_status.in_(("final_ready", "ready", "completed")),
            )
            .group_by(
                DebateTurn.debate_id,
                DebateTurn.round_no,
                DebateTurn.audio_file_id.is_not(None),
                text_fallback,
            )
        ):
            key = str(debate_id)
            if not audio_ready:
                audio_missing.add(key)
            ready_by_debate[key] = ready_by_debate.get(key, 0) + int(ready)
            if int(round_no) < rounds_by_debate[key] and (audio_ready or text_ready):
                preview_by_debate[key] = preview_by_debate.get(key, 0) + int(ready)
        for debate_id, count in db.execute(
            select(DebateParticipant.debate_id, func.count())
            .where(DebateParticipant.debate_id.in_(ids))
            .group_by(DebateParticipant.debate_id)
        ):
            participants_by_debate[str(debate_id)] = int(count)
        # Ordered by turn index so setdefault keeps the earliest failure: that
        # is the turn warming stopped at, and the later ones never ran.
        for debate_id, turn_id, round_no, code in db.execute(
            select(
                DebateTurn.debate_id,
                DebateTurn.id,
                DebateTurn.round_no,
                func.coalesce(DebateTurn.safe_error_code, Job.safe_error_code),
            )
            .outerjoin(
                Job,
                and_(
                    Job.debate_id == DebateTurn.debate_id,
                    Job.turn_id == DebateTurn.id,
                    Job.operation == "debate_turn_prepare",
                ),
            )
            .where(
                DebateTurn.debate_id.in_(ids),
                or_(
                    DebateTurn.generation_status.in_(("failed", "turn_generation_failed")),
                    and_(DebateTurn.generation_status == "pending", Job.state == "failed"),
                    # Recoverable prepare timeout parks as pending + code.
                    and_(
                        DebateTurn.generation_status == "pending",
                        DebateTurn.safe_error_code.is_not(None),
                        DebateTurn.safe_error_code != "",
                    ),
                ),
            )
            .order_by(DebateTurn.debate_id, DebateTurn.turn_index)
        ):
            stall_by_debate.setdefault(
                str(debate_id),
                DebateStall(
                    turn_id=UUID(str(turn_id)),
                    round_no=int(round_no),
                    safe_error_code=str(code or "turn_generation_failed"),
                ),
            )
    for row in rows:
        summaries.append(
            debate_summary(
                row,
                prepared_turns=ready_by_debate.get(str(row.id), 0),
                expected_turns=expected_turn_count(row, participants_by_debate.get(str(row.id), 0)),
                stall=stall_by_debate.get(str(row.id)),
                preview_prepared=preview_by_debate.get(str(row.id), 0),
                audio_restore_needed=str(row.id) in audio_missing,
                participant_count=participants_by_debate.get(str(row.id), 0),
            )
        )
    return summaries


def get_debate(db: Session, *, actor_user_id: str, debate_id: str) -> DebateDetail:
    debate = db.get(Debate, debate_id)
    if debate is None or debate.deleted_at is not None:
        raise not_found()
    require_teacher_course(db, actor_user_id, debate.course_id)
    return _detail(db, debate)


def _discard_prewarmed_plan(db: Session, debate_id: str) -> None:
    """Throw away a draft's warmed turns so an edit cannot outlive them."""

    from app.modules.debates.models import TurnSource

    turn_ids = [
        row
        for row in db.scalars(select(DebateTurn.id).where(DebateTurn.debate_id == debate_id)).all()
    ]
    if not turn_ids:
        return
    db.execute(delete(Job).where(Job.turn_id.in_(turn_ids)))
    db.execute(delete(TurnSource).where(TurnSource.turn_id.in_(turn_ids)))
    db.execute(delete(DebateTurn).where(DebateTurn.debate_id == debate_id))
    db.flush()


def update_debate_draft(
    db: Session,
    *,
    actor_user_id: str,
    debate_id: str,
    payload: DebateDraftRequest,
    expected_revision: int,
    settings: Settings | None = None,
) -> DebateDetail:
    debate = db.get(Debate, debate_id)
    if debate is None:
        raise not_found()
    require_teacher_course(db, actor_user_id, debate.course_id)
    if debate.status != "draft":
        raise invalid_state("Only a draft Debate can be updated.")
    if "output_language" not in payload.model_fields_set:
        payload = payload.model_copy(update={"output_language": debate.output_language})
    topic = _validated_topic(payload.topic, payload.output_language)
    teaching_protocol = debate_teaching_protocol(debate)
    _ensure_payload(payload, teaching_protocol=teaching_protocol)
    stored_rules = json.loads(debate.rule_snapshot_json)
    if (
        payload.teaching_prompts is not None
        and payload.teaching_prompts.model_dump() != stored_rules.get("teaching_prompts")
    ):
        raise invalid_state("Teaching rules are frozen when the debate is created.")
    if (
        payload.llm_params is not None
        and payload.llm_params.model_dump() != stored_rules.get("llm_params")
    ) or (
        payload.voice_params is not None
        and payload.voice_params.model_dump() != stored_rules.get("voice_params")
    ):
        raise invalid_state("Generation parameters are frozen when the debate is created.")
    frozen_teaching = {
        key: stored_rules[key]
        for key in (
            "teaching_prompts",
            "system_prompts",
            "contract_version",
            "llm_params",
            "voice_params",
        )
        if key in stored_rules
    }
    timestamp = utc_now()
    # A draft warms its turns in the background, so an edit has to discard
    # them: the plan freezes the speaking order and every turn's predecessor
    # prefix, and changing the participants or the round count makes both
    # wrong. Turns generated against the old shape would otherwise survive
    # into a lesson that no longer matches them.
    _discard_prewarmed_plan(db, debate.id)
    changed = db.execute(
        update(Debate)
        .where(
            Debate.id == debate.id,
            Debate.status == "draft",
            Debate.revision == expected_revision,
        )
        .values(
            topic=topic,
            background=payload.background,
            output_language=payload.output_language,
            rule_set_id=payload.rule_set_id,
            rule_snapshot_json=canonical_rule_snapshot_json(
                rule_set_id=payload.rule_set_id,
                round_count=payload.round_count,
                turn_protocol="segments_v2" if teaching_protocol else payload.turn_protocol,
                teaching_protocol=teaching_protocol,
                frozen_teaching=frozen_teaching or None,
            ),
            revision=Debate.revision + 1,
            updated_at=timestamp,
        )
    )
    if int(getattr(changed, "rowcount", 0)) != 1:
        db.expire_all()
        current = db.get(Debate, debate.id)
        if current is None:
            raise not_found()
        if current.status != "draft":
            raise invalid_state("Only a draft Debate can be updated.")
        raise conflict(
            "stale_revision",
            "The Debate draft revision is stale.",
            {"current_revision": current.revision},
        )
    require_teacher_course(db, actor_user_id, debate.course_id)
    db.expire(debate)
    debate = db.get(Debate, debate.id)
    if debate is None:  # pragma: no cover - guarded by the CAS predicate
        raise not_found()
    db.execute(delete(DebateParticipant).where(DebateParticipant.debate_id == debate.id))
    db.flush()
    runtime_settings = _settings(db, settings)
    _assert_participants_ready(
        db, course_id=debate.course_id, payload=payload, settings=runtime_settings
    )
    participant_rows = [
        _participant_row(
            db,
            debate=debate,
            item=item,
            order_index=index,
            settings=runtime_settings,
        )
        for index, item in enumerate(payload.participants)
    ]
    db.add_all(participant_rows)
    db.flush()
    adopt_debate_knowledge(db, debate.id, participant_rows, runtime_settings.resolved_data_root)
    delete_debate_knowledge(db, debate.id, runtime_settings.resolved_data_root)
    sync_debate_clones(
        db, debate.id, settings=runtime_settings, data_root=runtime_settings.resolved_data_root
    )
    return _detail(db, debate)


def commit_start_plan(
    db: Session,
    *,
    debate_id: str,
    expected_revision: int | None = None,
    expected_status: str = "draft",
) -> list[DebateTurn]:
    """Create the complete deterministic plan inside a caller's start CAS.

    The M12 playback orchestrator owns the public start transaction, audio
    swap journal and course pointer.  This narrow helper only writes plan
    rows, and therefore cannot create a second public start path.  Callers
    should set Debate ``running``/pointer only after their own final CAS.
    """

    debate = db.get(Debate, debate_id)
    if debate is None:
        raise not_found()
    if debate.status != expected_status:
        raise invalid_state("The Debate is not in the expected start state.")
    if expected_revision is not None and debate.revision != expected_revision:
        raise conflict(
            "stale_revision",
            "The Debate draft revision is stale.",
            {"current_revision": debate.revision},
        )
    # A draft warming in the background materialises this same plan, so two
    # callers can arrive here for one Debate. The plan is deterministic and its
    # rows carry a unique (debate, turn_index), so the second caller must reuse
    # the first one's rows rather than insert a duplicate set.
    existing = list(
        db.scalars(
            select(DebateTurn)
            .where(DebateTurn.debate_id == debate.id)
            .order_by(DebateTurn.turn_index)
        ).all()
    )
    if existing:
        return existing
    participants = db.scalars(
        select(DebateParticipant)
        .where(DebateParticipant.debate_id == debate.id)
        .order_by(DebateParticipant.order_index)
    ).all()
    try:
        plan = build_turn_plan(
            [row.id for row in participants],
            round_count=_round_count_from_snapshot(debate),
            rule_set_id=str(debate.rule_set_id),
            teaching_protocol=debate_teaching_protocol(debate),
        )
    except RuleViolation as exc:
        raise validation_failure(exc.message, code=exc.code) from exc
    if db.scalar(select(DebateTurn.id).where(DebateTurn.debate_id == debate.id)) is not None:
        raise invalid_state("The Debate plan has already been created.")

    # UUIDs are assigned before any row is inserted so every row can freeze
    # the exact full predecessor prefix, including unpublished predecessors.
    turn_ids = [str(uuid4()) for _entry in plan]
    timestamp = utc_now()
    turns: list[DebateTurn] = []
    participants_by_id = {row.id: row for row in participants}
    for entry, turn_id in zip(plan, turn_ids, strict=True):
        participant = participants_by_id[str(entry.participant_id)]
        turns.append(
            DebateTurn(
                id=turn_id,
                debate_id=debate.id,
                participant_id=participant.id,
                knowledge_snapshot_id=participant.knowledge_snapshot_id,
                round_no=entry.round_no,
                turn_index=entry.turn_index,
                generation_status="pending",
                publication_status="unpublished",
                preparation_stage="generation",
                predecessor_turn_ids_json=json.dumps(
                    [turn_ids[index] for index in entry.predecessor_turn_indexes],
                    separators=(",", ":"),
                ),
                cutoff_turn_index=max(entry.predecessor_turn_indexes, default=-1),
                attempt=1,
                created_at=timestamp,
                updated_at=timestamp,
            )
        )
    db.add_all(turns)
    db.flush()
    return turns


def claim_debate_job(
    db: Session,
    *,
    job_id: str,
    claim_token: str,
    expected_cancellation_generation: int,
) -> bool:
    """Single SQL CAS for a Debate generation/TTS job."""

    changed = db.execute(
        update(Job)
        .where(
            Job.id == job_id,
            Job.debate_id.is_not(None),
            Job.state == "pending",
            Job.cancellation_generation == expected_cancellation_generation,
        )
        .values(state="running", claim_token=claim_token, updated_at=utc_now())
    )
    return int(getattr(changed, "rowcount", 0)) == 1


__all__ = [
    "claim_debate_job",
    "create_debate_draft",
    "debate_summary",
    "get_debate",
    "list_debates",
    "require_teacher_course",
    "commit_start_plan",
    "update_debate_draft",
]
