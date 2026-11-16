"""Derived per-Agent cards; authored versions and publication are never changed here."""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Connection, Engine, select, update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import PlatformError
from app.core.llm_admission import llm_admission_slot
from app.core.locks import held_lock
from app.core.models import Agent, AgentDebateCard, AgentVersion
from app.modules.agents.markdown import markdown_hash
from app.modules.debates.cards import (
    CARD_PROMPT_VERSION,
    CardOutcome,
    CardStatus,
    CardTeacherReason,
    card_teacher_projection,
    compile_card_core,
)
from app.modules.debates.owned_copies import FrozenOwner
from app.modules.debates.schemas import DebateCard
from app.providers.factory import llm_provider
from app.providers.llm_adapter import DashScopeLLMAdapter

LOGGER = logging.getLogger(__name__)


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
) -> CardOutcome:
    adapter = llm_provider(settings, model_key=settings.debate_llm_model or settings.llm_model)
    if not isinstance(adapter, DashScopeLLMAdapter):
        return CardOutcome("fallback", safe_error_code="debate_card_mock_provider")
    scope_id = f"agent_card:{agent.id}"
    logical_item_id = f"{version.id}:{markdown_hash(markdown)}"
    # Ordinary LLM admission queues below live Debate writes. The core still
    # enters debate_llm_slot, reusing this held capacity through its standard
    # re-entrant path rather than taking a second supplier slot.
    try:
        with llm_admission_slot(settings):
            return compile_card_core(
                db,
                row=SimpleNamespace(id=logical_item_id, debate_id=scope_id, agent_name=agent.name),
                owner=FrozenOwner(
                    agent.course_id, agent.group_id, version.id, markdown, markdown_hash(markdown)
                ),
                language=language,
                scope_id=scope_id,
                logical_item_id=logical_item_id,
                build_identity={"agent_id": agent.id, "agent_version_id": version.id},
                adapter=adapter,
                policy_hash=settings.provider_policy_hash_for("llm"),
                settings=settings,
            )
    except PlatformError:
        LOGGER.warning(
            "agent_card_fallback agent_id=%s code=debate_card_admission_refused", agent.id
        )
        return CardOutcome("fallback", safe_error_code="debate_card_admission_refused")


@contextmanager
def _agent_card_lock(bind: Engine | Connection, agent_id: str, *, wait: bool) -> Iterator[bool]:
    while True:
        with held_lock(bind, f"agent-card:{agent_id}") as acquired:
            if acquired or not wait:
                yield acquired
                return
        # Waiting saves must release the lock connection; otherwise a burst
        # can exhaust the pool needed to settle the active provider ledger.
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
) -> AgentDebateCard | None:
    # Session locks survive the ledger's commits. A losing caller reads compiling;
    # no transaction or row lock is held during the supplier request.
    db.commit()
    with _agent_card_lock(db.get_bind(), agent_id, wait=wait) as acquired:
        db.expire_all()
        row = db.get(AgentDebateCard, agent_id)
        if not acquired:
            return row
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
        if row is not None and row.agent_md_hash == digest:
            # Same text across versions reuses the card, but must follow the
            # current version so pruning an older version cannot erase it.
            if row.agent_version_id != version.id:
                row.agent_version_id = version.id
                row.updated_at = datetime.now(UTC)
                db.commit()
            if row.card_status == "compiling":
                # With no live lock holder this is an interrupted claim. Never
                # resend a possibly accepted request, even after a process crash.
                row.card_status = "fallback"
                row.card_safe_error_code = "debate_card_attempt_used"
                row.compiled_at = row.updated_at = datetime.now(UTC)
                LOGGER.warning(
                    "agent_card_fallback agent_id=%s code=debate_card_attempt_used", agent_id
                )
                db.commit()
            return row
        now = datetime.now(UTC)
        language = "zh" if re.search(r"[\u3400-\u9fff]", source) else "en"
        if row is None:
            row = AgentDebateCard(agent_id=agent_id, created_at=now)
            db.add(row)
        row.agent_version_id = version.id
        row.agent_md_hash = digest
        row.language = language
        row.card_status = "compiling"
        row.card_json = row.card_safe_error_code = row.compiled_at = None
        row.salvaged = False
        row.prompt_version = CARD_PROMPT_VERSION
        row.updated_at = now
        db.commit()
        try:
            outcome = compile_source(db, agent, version, source, language, settings)
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
            )
            .values(
                card_status=outcome.status,
                card_json=json.dumps(outcome.card, ensure_ascii=False)
                if outcome.status == "ready"
                else None,
                card_safe_error_code=outcome.safe_error_code,
                salvaged=outcome.status == "ready" and outcome.salvaged,
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
        row = ensure_agent_card(db, agent_id, settings, version_id=version_id, markdown=markdown)
        if row is None or row.agent_md_hash != markdown_hash(markdown):
            return AgentCardResponse(card_status="compiling")
        return projection(row)
