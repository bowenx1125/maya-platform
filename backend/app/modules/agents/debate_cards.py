"""Derived per-Agent cards; authored versions and publication are never changed here."""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Connection, Engine, select, update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import PlatformError
from app.core.llm_admission import llm_admission_slot
from app.core.locks import held_lock
from app.core.models import Agent, AgentDebateCard, AgentVersion, ProviderOperation
from app.modules.agents.markdown import markdown_hash
from app.modules.debates.cards import (
    CARD_OPERATION,
    CARD_PROMPT_VERSION,
    CARD_TIMEOUT_SECONDS,
    CardOutcome,
    CardStatus,
    CardTeacherReason,
    card_teacher_projection,
    compile_card_core,
)
from app.modules.debates.owned_copies import FrozenOwner
from app.modules.debates.schemas import DebateCard
from app.providers.control_repository import ProviderRepository
from app.providers.factory import llm_provider
from app.providers.llm_adapter import DashScopeLLMAdapter

LOGGER = logging.getLogger(__name__)
CARD_RETRY_LIMIT = 3
CARD_RETRY_COOLDOWN_SECONDS = 60


def claim_timeout_seconds(settings: Settings) -> float:
    return (
        max(settings.adaptive_admission_wait_seconds, settings.llm_admission_wait_seconds)
        + CARD_TIMEOUT_SECONDS
        + 60
    )


@contextmanager
def _claim_guard(db: Session, agent_id: str) -> Iterator[None]:
    while True:
        db.commit()
        with held_lock(db.get_bind(), f"agent-card-claim:{agent_id}") as acquired:
            if acquired:
                try:
                    yield
                    db.commit()
                except BaseException:
                    db.rollback()
                    raise
                return
        time.sleep(0.05)


class AgentCardRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_md: str | None = None


class AgentCardResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    card_status: CardStatus
    card: DebateCard | None = None
    card_teacher_reason: CardTeacherReason | None = None
    card_teacher_notice: str | None = None


def projection(row: AgentDebateCard) -> AgentCardResponse:
    return AgentCardResponse.model_validate(
        {
            "card_status": row.card_status,
            "card": json.loads(row.card_json) if row.card_json else None,
            **card_teacher_projection(row.card_status, row.card_safe_error_code),
        }
    )


def compile_source(
    db: Session,
    agent: Agent,
    version: AgentVersion,
    markdown: str,
    language: str,
    settings: Settings,
    retry_no: int = 0,
    claim_token: str | None = None,
) -> CardOutcome:
    adapter = llm_provider(settings, model_key=settings.debate_llm_model or settings.llm_model)
    if not isinstance(adapter, DashScopeLLMAdapter):
        return CardOutcome("fallback", safe_error_code="debate_card_mock_provider")
    agent_id, version_id, agent_name = agent.id, version.id, agent.name
    owner = FrozenOwner(
        agent.course_id, agent.group_id, version_id, markdown, markdown_hash(markdown)
    )
    scope_id = f"agent_card:{agent_id}"
    logical_item_id = f"{version_id}:{markdown_hash(markdown)}"
    if retry_no:
        logical_item_id += f":r{retry_no}"

    @contextmanager
    def dispatch_guard() -> Iterator[bool]:
        with _claim_guard(db, agent_id):
            db.expire_all()
            current = db.get(AgentDebateCard, agent_id)
            yield current is not None and current.claim_token == claim_token

    # Ordinary LLM admission queues below live Debate writes. The core still
    # enters debate_llm_slot, reusing this held capacity through its standard
    # re-entrant path rather than taking a second supplier slot.
    db.commit()
    try:
        with llm_admission_slot(settings):
            return compile_card_core(
                db,
                row=SimpleNamespace(id=logical_item_id, debate_id=scope_id, agent_name=agent_name),
                owner=owner,
                language=language,
                scope_id=scope_id,
                logical_item_id=logical_item_id,
                build_identity={
                    "agent_id": agent_id,
                    "agent_version_id": version_id,
                    "retry_no": str(retry_no),
                },
                dispatch_guard=dispatch_guard,
                adapter=adapter,
                policy_hash=settings.provider_policy_hash_for("llm"),
                settings=settings,
            )
    except PlatformError:
        LOGGER.warning(
            "agent_card_fallback agent_id=%s code=debate_card_admission_refused", agent_id
        )
        return CardOutcome("fallback", safe_error_code="debate_card_admission_refused")


@contextmanager
def _claim_slot(db: Session, agent_id: str, settings: Settings, *, wait: bool) -> Iterator[bool]:
    while True:
        with _claim_guard(db, agent_id):
            db.expire_all()
            row = db.get(AgentDebateCard, agent_id)
            active = False
            if row is not None and row.card_status == "compiling" and row.claim_token:
                with held_lock(db.get_bind(), f"agent-card-worker:{row.claim_token}") as free:
                    # Terminal publication does not take the claim guard, so
                    # the worker may have finished since this session read it.
                    db.refresh(row)
                    active = (
                        row.card_status == "compiling"
                        and not free
                        and (datetime.now(UTC) - row.updated_at).total_seconds()
                        < claim_timeout_seconds(settings)
                    )
            if not active or not wait:
                yield not active
                return
            db.commit()
        # Waiting must release query and advisory connections so the active
        # worker retains pool capacity to settle its provider ledger.
        time.sleep(0.25)


def ensure_agent_card(
    db: Session,
    agent_id: str,
    settings: Settings,
    *,
    version_id: str | None = None,
    markdown: str | None = None,
    published_only: bool = False,
    wait: bool = False,
    retry_failed: bool = False,
) -> AgentDebateCard | None:
    db.commit()
    with ExitStack() as locks:
        with _claim_slot(db, agent_id, settings, wait=wait) as acquired:
            row = db.get(AgentDebateCard, agent_id)
            if not acquired:
                return row
            now = datetime.now(UTC)
            agent = db.get(Agent, agent_id)
            if agent is None or agent.deleted_at is not None:
                return None
            if published_only:
                version_id = agent.current_published_version_id
                if not version_id:
                    return None
            version = (
                db.get(AgentVersion, version_id)
                if version_id
                else db.scalar(
                    select(AgentVersion)
                    .where(
                        AgentVersion.agent_id == agent_id,
                        AgentVersion.state.in_(("draft", "published")),
                    )
                    .order_by(AgentVersion.version_seq.desc())
                    .limit(1)
                )
            )
            if version is None or version.agent_id != agent_id:
                return None
            source = markdown if markdown is not None else version.agent_md
            digest = markdown_hash(source)
            same_hash = row is not None and row.agent_md_hash == digest
            if same_hash and row is not None:
                if row.card_status == "ready" or (
                    row.card_status == "fallback" and not retry_failed
                ):
                    row.agent_version_id = version.id
                    db.commit()
                    return row
                if (
                    row.card_status == "fallback"
                    and (now - row.updated_at).total_seconds() < CARD_RETRY_COOLDOWN_SECONDS
                ):
                    return row
            base_item = f"{version.id}:{digest}"
            operations = list(
                db.scalars(
                    select(ProviderOperation).where(
                        ProviderOperation.scope_id == f"agent_card:{agent_id}",
                        ProviderOperation.provider_operation == CARD_OPERATION,
                        (ProviderOperation.logical_item_id == base_item)
                        | ProviderOperation.logical_item_id.startswith(base_item + ":r"),
                    )
                )
            )
            previous = max(
                (
                    0
                    if op.logical_item_id == base_item
                    else int(op.logical_item_id.removeprefix(base_item + ":r"))
                    for op in operations
                ),
                default=-1,
            )
            retry_no = max(previous + 1, row.retry_count + 1 if same_hash and row else 0)
            if (
                same_hash
                and row is not None
                and row.card_status == "fallback"
                and (retry_no > CARD_RETRY_LIMIT)
            ):
                return row
            cooling = (
                bool(operations)
                and (now - max(op.updated_at for op in operations)).total_seconds()
                < CARD_RETRY_COOLDOWN_SECONDS
            )
            # Recovery never silently duplicates an ambiguous export. An explicit
            # later Check may authorize a distinct run; the old ledger stays terminal.
            ambiguous = [
                op
                for op in operations
                if op.state in {"reserved", "sending", "accepted", "acceptance_unknown"}
            ]
            blocked = bool(ambiguous) and (
                not retry_failed or any(op.state != "acceptance_unknown" for op in ambiguous)
            )
            if row is None:
                row = AgentDebateCard(agent_id=agent_id, created_at=now)
                db.add(row)
            row.agent_version_id = version.id
            row.agent_md_hash = digest
            row.language = "zh" if re.search(r"[\u3400-\u9fff]", source) else "en"
            row.salvaged = False
            row.prompt_version = CARD_PROMPT_VERSION
            if (
                blocked
                or cooling
                or retry_no > CARD_RETRY_LIMIT
                or (operations and not same_hash and not retry_failed)
            ):
                for operation in ambiguous:
                    ProviderRepository(db).recover_one(operation.id, staged_response_complete=False)
                row.card_status = "fallback"
                row.card_json = row.claim_token = None
                row.card_safe_error_code = (
                    "debate_card_acceptance_unknown" if blocked else "debate_card_attempt_used"
                )
                row.retry_count = min(
                    max(previous, (row.retry_count or 0) if same_hash else 0), CARD_RETRY_LIMIT
                )
                row.compiled_at = row.updated_at = now
                LOGGER.warning(
                    "agent_card_fallback agent_id=%s code=%s", agent_id, row.card_safe_error_code
                )
                db.commit()
                return row
            token = str(uuid4())
            locks.enter_context(held_lock(db.get_bind(), f"agent-card-worker:{token}", wait=True))
            row.card_status = "compiling"
            row.card_json = row.card_safe_error_code = row.compiled_at = None
            row.retry_count = retry_no
            row.claim_token = token
            row.updated_at = now
            language = row.language
            db.commit()
        try:
            outcome = compile_source(
                db, agent, version, source, language, settings, retry_no, token
            )
        except Exception as exc:
            db.rollback()
            LOGGER.warning(
                "agent_card_fallback agent_id=%s code=debate_card_failed error=%s",
                agent_id,
                type(exc).__name__,
            )
            outcome = CardOutcome("fallback", safe_error_code="debate_card_failed")
        db.execute(
            update(AgentDebateCard)
            .where(
                AgentDebateCard.agent_id == agent_id,
                AgentDebateCard.agent_md_hash == digest,
                AgentDebateCard.card_status == "compiling",
                AgentDebateCard.claim_token == token,
            )
            .values(
                card_status=outcome.status,
                card_json=json.dumps(outcome.card, ensure_ascii=False)
                if outcome.status == "ready"
                else None,
                card_safe_error_code=outcome.safe_error_code,
                salvaged=outcome.status == "ready" and outcome.salvaged,
                claim_token=None,
                compiled_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        db.commit()
        db.refresh(row)
        return row


def compile_after_save(engine: Engine | Connection, agent_id: str, settings: Settings) -> None:
    try:
        with Session(engine.engine) as db:
            ensure_agent_card(db, agent_id, settings, wait=True)
    except Exception as exc:
        # The authored save has already committed. Database outages can prevent
        # even a fallback write; a later Check card conservatively settles it.
        LOGGER.warning(
            "agent_card_background_failed agent_id=%s code=debate_card_failed error=%s",
            agent_id,
            type(exc).__name__,
        )


def check_agent_card(
    engine: Engine,
    agent_id: str,
    version_id: str,
    markdown: str,
    settings: Settings,
) -> AgentCardResponse:
    # The HTTP deadline may return Compiling while this worker finishes. Its
    # session must outlive the request dependency and remain on this thread.
    with Session(engine) as db:
        row = ensure_agent_card(
            db, agent_id, settings, version_id=version_id, markdown=markdown, retry_failed=True
        )
        if row is None or row.agent_md_hash != markdown_hash(markdown):
            return AgentCardResponse(card_status="compiling")
        return projection(row)
