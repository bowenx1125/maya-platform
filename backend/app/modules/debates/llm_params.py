"""Debate generation parameters: env defaults, per-Debate overrides, request fields.

Owner decision (2026-10-24): the environment holds the global defaults
(DEBATE_LLM_*), the Debate form's parameter card overrides them for one
Debate, and the resolved values are frozen into the Debate's rule snapshot
at creation. Every turn sends the frozen values. A Debate frozen before this
existed falls back to the current defaults. A parameter that is empty (None)
is never sent.

Ranges follow the DashScope OpenAI-compatible chat endpoint. That endpoint
does not document ``frequency_penalty``, so it is accepted and stored but
never sent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.config import Settings

ParamKind = Literal["float", "int", "bool"]


@dataclass(frozen=True)
class ParamSpec:
    name: str
    kind: ParamKind
    minimum: float | None
    maximum: float | None
    # True when the bound itself is not allowed.
    exclusive_minimum: bool = False
    exclusive_maximum: bool = False
    step: float | None = None
    # False: stored and shown, never sent (the supplier does not document it).
    sent: bool = True


PARAM_SPECS: tuple[ParamSpec, ...] = (
    ParamSpec("temperature", "float", 0.0, 2.0, exclusive_maximum=True, step=0.05),
    ParamSpec("top_p", "float", 0.0, 1.0, exclusive_minimum=True, step=0.05),
    ParamSpec("presence_penalty", "float", -2.0, 2.0, step=0.1),
    ParamSpec("frequency_penalty", "float", -2.0, 2.0, step=0.1, sent=False),
    ParamSpec("repetition_penalty", "float", 0.0, 2.0, exclusive_minimum=True, step=0.01),
    ParamSpec("max_tokens", "int", 1, 32768),
    ParamSpec("enable_thinking", "bool", None, None),
    ParamSpec("seed", "int", 0, 2**31 - 1),
)
PARAM_NAMES = tuple(spec.name for spec in PARAM_SPECS)
CONTRACT_VERSION = "ruleset_contract_v3"


class DebateLLMParams(BaseModel):
    """One Debate's overrides; null means "do not send this parameter"."""

    model_config = ConfigDict(extra="forbid")

    temperature: float | None = Field(default=None, ge=0.0, lt=2.0)
    top_p: float | None = Field(default=None, gt=0.0, le=1.0)
    presence_penalty: float | None = Field(default=None, ge=-2.0, le=2.0)
    frequency_penalty: float | None = Field(default=None, ge=-2.0, le=2.0)
    repetition_penalty: float | None = Field(default=None, gt=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1, le=32768)
    enable_thinking: bool | None = None
    seed: int | None = Field(default=None, ge=0, le=2**31 - 1)


def default_params(settings: Settings) -> dict[str, Any]:
    """DEBATE_LLM_* values, checked against the same ranges as the card."""

    return DebateLLMParams.model_validate(
        {
            "temperature": settings.debate_llm_temperature,
            "top_p": settings.debate_llm_top_p,
            "presence_penalty": settings.debate_llm_presence_penalty,
            "frequency_penalty": settings.debate_llm_frequency_penalty,
            "repetition_penalty": settings.debate_llm_repetition_penalty,
            "max_tokens": settings.debate_llm_max_tokens,
            "enable_thinking": settings.debate_llm_enable_thinking,
            "seed": settings.debate_llm_seed,
        }
    ).model_dump()


def resolve_params(settings: Settings, overrides: DebateLLMParams | None) -> dict[str, Any]:
    """What a new Debate freezes: the card's values, or the defaults when none came."""

    if overrides is None:
        return default_params(settings)
    return overrides.model_dump()


def frozen_params(snapshot: dict[str, Any] | None, settings: Settings) -> dict[str, Any]:
    stored = (snapshot or {}).get("llm_params")
    if isinstance(stored, dict):
        return {name: stored.get(name) for name in PARAM_NAMES}
    return default_params(settings)


def request_fields(params: dict[str, Any]) -> dict[str, Any]:
    """Body fields for the chat request. Empty and unsent parameters are left out."""

    fields: dict[str, Any] = {}
    for spec in PARAM_SPECS:
        value = params.get(spec.name)
        if value is None or not spec.sent:
            continue
        fields[spec.name] = bool(value) if spec.kind == "bool" else value
    return fields


@dataclass(frozen=True)
class VoiceParamSpec:
    name: str
    kind: Literal["float", "int", "text"]
    minimum: float | None
    maximum: float | None
    step: float | None = None
    max_length: int | None = None


# Voice parameters (2026-10-25): sent in the SpeechSynthesizer ``input`` for
# cloned voices (qwen-audio-*-tts-flash) only; the preset qwen3-tts-flash takes
# text, voice and language_type alone. The speaking rate replaces the browser
# playback rate: every Debate plays at 1.0.
VOICE_PARAM_SPECS: tuple[VoiceParamSpec, ...] = (
    VoiceParamSpec("rate", "float", 0.5, 2.0, step=0.05),
    VoiceParamSpec("instruction", "text", None, None, max_length=500),
    VoiceParamSpec("seed", "int", 0, 65535),
)
VOICE_PARAM_NAMES = tuple(spec.name for spec in VOICE_PARAM_SPECS)


class DebateVoiceParams(BaseModel):
    """One Debate's voice overrides; null (or blank text) means "do not send"."""

    model_config = ConfigDict(extra="forbid")

    rate: float | None = Field(default=None, ge=0.5, le=2.0)
    instruction: str | None = Field(default=None, max_length=500)
    seed: int | None = Field(default=None, ge=0, le=65535)

    @field_validator("instruction")
    @classmethod
    def blank_instruction_is_unset(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


def default_voice_params(settings: Settings) -> dict[str, Any]:
    """DEBATE_TTS_* values, checked against the same ranges as the card."""

    return DebateVoiceParams.model_validate(
        {
            "rate": settings.debate_tts_rate,
            "instruction": settings.debate_tts_instruction,
            "seed": settings.debate_tts_seed,
        }
    ).model_dump()


def resolve_voice_params(settings: Settings, overrides: DebateVoiceParams | None) -> dict[str, Any]:
    """What a new Debate freezes: the card's values, or the defaults when none came."""

    if overrides is None:
        return default_voice_params(settings)
    return overrides.model_dump()


def frozen_voice_params(snapshot: dict[str, Any] | None, settings: Settings) -> dict[str, Any]:
    """The Debate's frozen voice values; a Debate frozen before them uses the defaults."""

    stored = (snapshot or {}).get("voice_params")
    if isinstance(stored, dict):
        return {name: stored.get(name) for name in VOICE_PARAM_NAMES}
    return default_voice_params(settings)


def voice_request_fields(params: dict[str, Any] | None) -> dict[str, Any]:
    """SpeechSynthesizer ``input`` fields. Empty parameters are left out."""

    fields: dict[str, Any] = {}
    for spec in VOICE_PARAM_SPECS:
        value = (params or {}).get(spec.name)
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        fields[spec.name] = value
    return fields


def defaults_payload(settings: Settings) -> dict[str, Any]:
    """The read-only defaults and ranges the Debate form starts from."""

    defaults = default_params(settings)
    voice_defaults = default_voice_params(settings)
    return {
        "params": [
            {
                "name": spec.name,
                "kind": spec.kind,
                "default": defaults[spec.name],
                "minimum": spec.minimum,
                "maximum": spec.maximum,
                "exclusive_minimum": spec.exclusive_minimum,
                "exclusive_maximum": spec.exclusive_maximum,
                "step": spec.step,
                "sent": spec.sent,
            }
            for spec in PARAM_SPECS
        ],
        "voice_params": [
            {
                "name": spec.name,
                "kind": spec.kind,
                "default": voice_defaults[spec.name],
                "minimum": spec.minimum,
                "maximum": spec.maximum,
                "step": spec.step,
                "max_length": spec.max_length,
            }
            for spec in VOICE_PARAM_SPECS
        ],
    }
