"""Teacher-only local Demo configuration; credentials never enter read DTOs."""

import base64
import hmac
import json
import logging
import os
import re
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import Error, PlatformError, conflict, forbidden
from app.core.models import (
    Agent,
    AgentVersion,
    Course,
    Group,
    Job,
    KnowledgeSnapshot,
    ProviderOperation,
)
from app.modules.auth.dependencies import get_db, require_auth, require_authenticated_mutation
from app.modules.auth.service import AuthContext
from app.modules.debates.models import Debate
from app.providers.control_repository import ProviderRepository

from .access import course_member
from .chat_provider import digest, real_reply, retrieve_sources
from .models import Conversation, ProviderPreferences
from .schemas import (
    CheckProvider,
    ComponentKey,
    ComponentStatus,
    ProviderSettings,
    UpdateProviderSettings,
)

router = APIRouter(
    tags=["Provider settings"],
    responses={
        401: {"model": Error},
        403: {"model": Error},
        404: {"model": Error},
        409: {"model": Error},
    },
)
COMPONENTS: tuple[ComponentKey, ...] = ("embedding", "llm", "tts", "voice", "report")
_KEY_CONTEXT = b"maya/provider-preferences/v1"
logger = logging.getLogger("maya.workspace")


def preferences_settings(settings: Settings, row: ProviderPreferences | None) -> Settings:
    if row is None:
        return settings
    values: dict[str, Any] = {}
    modes = json.loads(row.modes_json)
    if not isinstance(modes, dict) or any(
        k not in COMPONENTS or v not in ("real", "mock") for k, v in modes.items()
    ):
        raise RuntimeError("Provider preferences are invalid")
    for key, mode in modes.items():
        values[f"{key}_provider"] = "dashscope" if mode == "real" else "mock"
    # DASHSCOPE_API_KEY is the rotation source. A key saved from the teacher
    # dialog applies only when that variable is empty, so replacing the
    # environment value and restarting does not require a database edit.
    env_key = (settings.dashscope_api_key or "").strip()
    if row.encrypted_key and not env_key:
        try:
            raw = base64.b64decode(row.encrypted_key, validate=True)
            key = hmac.digest(settings.secret_bytes, _KEY_CONTEXT, "sha256")
            values["dashscope_api_key"] = (
                AESGCM(key).decrypt(raw[:12], raw[12:], _KEY_CONTEXT).decode()
            )
        except Exception:
            raise RuntimeError("Provider preferences could not be unlocked") from None
    result = settings.model_copy(update=values)
    result.validate_provider_configuration()
    return result


def teacher_scope(db: Session, context: AuthContext, course_id: UUID, settings: Settings) -> None:
    course_member(db, context, str(course_id), teacher=True)
    if not settings.demo_mode or db.scalar(select(func.count()).select_from(Course)) != 1:
        raise forbidden("Provider controls are limited to the single-course local Demo.")


def settings_view(settings: Settings, row: ProviderPreferences | None) -> ProviderSettings:
    checks = json.loads(row.checks_json) if row else {}
    return ProviderSettings(
        revision=row.revision if row else 0,
        credential_ready=bool(settings.dashscope_api_key),
        components=[
            ComponentStatus.model_validate(
                {
                    "key": key,
                    "mode": "real"
                    if getattr(settings, f"{key}_provider") == "dashscope"
                    else "mock",
                    "switchable": key not in {"tts", "voice"},
                    "status": "deferred"
                    if key in {"tts", "voice"}
                    else checks.get(key, {}).get("status", "unchecked"),
                    "checked_at": checks.get(key, {}).get("checked_at"),
                    "safe_error_code": checks.get(key, {}).get("safe_error_code"),
                }
            )
            for key in COMPONENTS
        ],
    )


@router.get(
    "/courses/{course_id}/provider-settings",
    response_model=ProviderSettings,
    operation_id="getProviderSettings",
)
def get_provider_settings(
    course_id: UUID,
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ProviderSettings:
    teacher_scope(db, context, course_id, settings)
    return settings_view(settings, db.get(ProviderPreferences, 1))


@router.post(
    "/courses/{course_id}/provider-settings",
    response_model=ProviderSettings,
    operation_id="updateProviderSettings",
)
def update_provider_settings(
    course_id: UUID,
    payload: UpdateProviderSettings,
    request: Request,
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ProviderSettings:
    teacher_scope(db, context, course_id, settings)
    with request.app.state.workspace_lock:
        settings = request.app.state.settings
        row = db.get(ProviderPreferences, 1)
        if (row.revision if row else 0) != payload.expected_revision:
            raise conflict(
                "provider_settings_changed", "Refresh the settings before changing them."
            )
        if payload.component in {"tts", "voice"}:
            raise conflict("provider_deferred", "Voice and TTS integration is deferred.")
        if (payload.component is None) != (payload.mode is None):
            raise PlatformError("malformed_request", "Choose a component and mode together.", 400)
        if (
            request.app.state.prewarm_scheduler.busy
            or db.scalar(select(Job.id).where(Job.state.in_(("running", "pending"))).limit(1))
            or db.scalar(select(Debate.id).where(Debate.status == "running").limit(1))
            or db.scalar(
                select(Conversation.id).where(Conversation.active_request_id.is_not(None)).limit(1)
            )
            or db.scalar(
                select(ProviderOperation.id)
                .where(ProviderOperation.state.in_(("reserved", "sending")))
                .limit(1)
            )
        ):
            raise conflict("provider_busy", "Finish active work before changing Provider settings.")
        if row is None:
            row = ProviderPreferences(id=1, revision=0, modes_json="{}", checks_json="{}")
        modes = json.loads(row.modes_json)
        checks = json.loads(row.checks_json)
        if payload.component:
            modes[payload.component] = payload.mode
            checks.pop(payload.component, None)
        encrypted = row.encrypted_key
        if payload.api_key is not None:
            checks = {}
            secret = payload.api_key.get_secret_value().strip()
            if not 8 <= len(secret) <= 1024 or any(ord(ch) < 33 for ch in secret):
                raise PlatformError("provider_key_invalid", "Enter a valid API key.", 400)
            nonce = os.urandom(12)
            encryption_key = hmac.digest(settings.secret_bytes, _KEY_CONTEXT, "sha256")
            encrypted = base64.b64encode(
                nonce + AESGCM(encryption_key).encrypt(nonce, secret.encode(), _KEY_CONTEXT)
            ).decode()
        if payload.mode == "real" and not (encrypted or settings.dashscope_api_key):
            raise conflict("provider_key_required", "Add an API key before selecting Real.")
        candidate = ProviderPreferences(
            id=1,
            revision=row.revision + 1,
            modes_json=json.dumps(modes),
            encrypted_key=encrypted,
            checks_json=json.dumps(checks),
        )
        try:
            effective = preferences_settings(request.app.state.base_settings, candidate)
            effective.validate_runtime()
            apply = request.app.state.prepare_provider_settings(effective)
        except (RuntimeError, ValueError):
            raise conflict(
                "provider_configuration_invalid",
                "Provider policy or configuration needs attention.",
            ) from None
        row.revision = candidate.revision
        row.modes_json = candidate.modes_json
        row.encrypted_key = encrypted
        row.checks_json = candidate.checks_json
        db.add(row)
        db.commit()
        apply()
        return settings_view(effective, row)


@router.post(
    "/courses/{course_id}/provider-settings/{component}/check",
    response_model=ProviderSettings,
    operation_id="checkProvider",
)
def check_provider(
    course_id: UUID,
    component: ComponentKey,
    payload: CheckProvider,
    request: Request,
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ProviderSettings:
    teacher_scope(db, context, course_id, settings)
    with request.app.state.workspace_lock:
        settings = request.app.state.settings
        row = db.get(ProviderPreferences, 1)
        if (row.revision if row else 0) != payload.expected_revision:
            raise conflict("provider_settings_changed", "Refresh the settings before checking.")
        if component in {"tts", "voice"}:
            return settings_view(settings, row)
        if row is None:
            row = ProviderPreferences(id=1, revision=0, modes_json="{}", checks_json="{}")
            db.add(row)
            db.commit()
        checks = json.loads(row.checks_json)
        if checks.get(component, {}).get("request_id") == str(payload.request_id):
            return settings_view(settings, row)
        real = getattr(settings, f"{component}_provider") == "dashscope"
        if real and not payload.confirm_real_call:
            raise conflict(
                "provider_check_confirmation_required",
                "This check makes one paid Provider request.",
            )
        result: dict[str, object] = {
            "request_id": str(payload.request_id),
            "status": "ready",
            "checked_at": datetime.now(UTC).isoformat(),
            "safe_error_code": None,
        }
        try:
            if real and not settings.dashscope_api_key:
                raise conflict("provider_key_required", "Add an API key first.")
            if real and component in {"llm", "report"}:
                _, operation = real_reply(
                    db,
                    settings,
                    scope_id=f"check:{component}:{payload.request_id}",
                    request_id=str(payload.request_id),
                    course_id=str(course_id),
                    messages=[{"role": "user", "content": 'Return JSON: {"reply":"OK"}'}],
                    persona_hash=digest("provider-check-v1"),
                    component=component,
                )
                ProviderRepository(db).mark_succeeded(operation)
            elif real:
                version = db.scalar(
                    select(AgentVersion)
                    .join(Agent, Agent.current_published_version_id == AgentVersion.id)
                    .join(
                        KnowledgeSnapshot,
                        KnowledgeSnapshot.id == AgentVersion.knowledge_snapshot_id,
                    )
                    .join(Group, Group.id == Agent.group_id)
                    .where(
                        Group.course_id == str(course_id),
                        KnowledgeSnapshot.embedding_provider == "dashscope",
                        AgentVersion.state == "published",
                    )
                    .limit(1)
                )
                if version is None:
                    raise conflict(
                        "provider_check_unavailable",
                        "Publish a Real Embedding Agent before checking.",
                    )
                retrieve_sources(
                    db,
                    settings,
                    version,
                    course_id=str(course_id),
                    scope_id=f"check:{payload.request_id}",
                    request_id=str(payload.request_id),
                    message="A public connectivity check.",
                )
        except Exception as exc:
            db.rollback()
            result["status"] = "failed"
            code = getattr(exc, "code", "provider_check_failed")
            if not isinstance(code, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", code):
                code = "provider_check_failed"
            result["safe_error_code"] = code
            logger.warning(
                "Provider check failed component=%s request_id=%s code=%s",
                component,
                payload.request_id,
                code,
            )
        row = cast(ProviderPreferences, db.get(ProviderPreferences, 1))
        checks[component] = result
        row.checks_json = json.dumps(checks)
        db.commit()
        return settings_view(settings, row)
