"""Teacher-only local Demo configuration; credentials never enter read DTOs."""

import base64
import hmac
import json
import logging
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import APIRouter

from app.core.config import Settings
from app.core.errors import Error

from .models import ProviderPreferences
from .schemas import (
    ComponentKey,
    ComponentStatus,
    ProviderSettings,
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
                    "status": (
                        "unchecked"
                        if getattr(settings, f"{key}_provider") == "dashscope"
                        else "deferred"
                    )
                    if key in {"tts", "voice"}
                    else checks.get(key, {}).get("status", "unchecked"),
                    "checked_at": checks.get(key, {}).get("checked_at"),
                    "safe_error_code": checks.get(key, {}).get("safe_error_code"),
                }
            )
            for key in COMPONENTS
        ],
    )
