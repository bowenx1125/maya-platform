"""Server-only ProviderDataCallV1 control boundary.

This module owns no provider selector and performs no I/O.  It provides the
small immutable policy/export values and the durable-operation repository port
that the application layer can adapt to SQL.  ``InMemoryProviderOperationRepository``
is a deterministic test double; it deliberately does not replace the ORM or
the existing voice-operation ledger.

Supplier names, endpoints and policy evidence stay on this server-only
boundary.  Nothing in this module is a browser/API DTO.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from threading import RLock
from types import MappingProxyType
from typing import Literal, Protocol
from urllib.parse import urlsplit
from uuid import uuid4

PROVIDER_DATA_CALL_VERSION = "ProviderDataCallV1"
FIXED_REGION = "cn-beijing"
# A policy row whose policy_id starts with this prefix was derived from local
# configuration in DEMO_MODE, not from a person reading the supplier's
# documents. Each real slice gets its own row, so the ids are suffixed. Anything
# showing Real/Mock composition must show that difference; nothing may treat
# such a row as an audited policy.
DEMO_UNREVIEWED_POLICY_PREFIX = "demo-unreviewed"
FIXED_MODELS: Mapping[str, str] = MappingProxyType(
    {
        "embedding": "text-embedding-v4",
        "embedding_snapshot": "text-embedding-v4",
        "embedding_query": "text-embedding-v4",
        "llm_debate": "qwen3.8-max-2026-09-02",
        "llm_debate_turn": "qwen3.8-max-2026-09-02",
        "llm_maya_report": "qwen3.8-max-2026-09-02",
        "llm_agent_chat": "qwen3.8-max-2026-09-02",
        "llm_knowledge_generate": "qwen3.8-max-2026-09-02",
        "tts": "qwen-audio-3.1-tts-flash",
        "voice_enrollment": "voice-enrollment",
    }
)
PROVIDER_BUDGET_BUCKETS = frozenset(
    {
        "embedding_snapshot",
        "embedding_query",
        "llm_debate_turn",
        "llm_barrage_insight",
        "llm_maya_report",
        "tts_synthesis",
        "voice_enrollment",
    }
)
BUDGET_BUCKETS = PROVIDER_BUDGET_BUCKETS
EMBEDDING_SNAPSHOT_BUCKET = "embedding_snapshot"
EMBEDDING_QUERY_BUCKET = "embedding_query"
LLM_DEBATE_TURN_BUCKET = "llm_debate_turn"
LLM_BARRAGE_INSIGHT_BUCKET = "llm_barrage_insight"
LLM_MAYA_REPORT_BUCKET = "llm_maya_report"
TTS_SYNTHESIS_BUCKET = "tts_synthesis"
VOICE_ENROLLMENT_BUCKET = "voice_enrollment"
REPAIR_FEEDBACK_POLICY_VERSION = "repair_feedback_v1"
REPAIR_FEEDBACK_POLICY_HASH = "d5b81d460ecd713f4b3d52b5732efc935b63455c2a29b5a5ab2471b17d00050b"
REPAIR_FEEDBACK_V2_VERSION = "repair_feedback_v2"
REPAIR_FEEDBACK_V2_HASH = "d911e9af5381af8cea22f171fdd11f1a07f18ccdf2f703bdfbee1e4d096292f7"
REPAIR_FEEDBACK_POLICIES = {
    REPAIR_FEEDBACK_POLICY_VERSION: REPAIR_FEEDBACK_POLICY_HASH,
    REPAIR_FEEDBACK_V2_VERSION: REPAIR_FEEDBACK_V2_HASH,
}
LLM_TURN_OUTPUT_SCHEMA_HASH = "77769a5fdc0e6ef368c048a6e2b28891c1702a2d904da2471bcf7b2ed9df253f"
LLM_RECOVERY_INPUT_VERSION = "llm_recovery_input_v1"
LLM_RECOVERY_INPUT_BYTES_LIMIT = 256 * 1024
DEMO_ACCEPTANCE_PLAN_VERSION: Literal["real_core_demo_v2"] = "real_core_demo_v2"
# The mutual-learning protocol admits 2-5 Agents over 2-5 rounds, so a Demo run
# has no single call count.  The expected count is computed from the Debate's
# own shape; only the absolute ceiling below is a constant, and it exists to
# bound a runaway ordinal rather than to describe any particular run.
DEMO_ACCEPTANCE_MIN_AGENTS = 2
DEMO_ACCEPTANCE_MAX_AGENTS = 5
DEMO_ACCEPTANCE_MIN_ROUNDS = 2
DEMO_ACCEPTANCE_MAX_ROUNDS = 5


def demo_acceptance_expected_calls(
    *,
    agent_count: int,
    round_count: int,
    real_snapshot_agents: int = 1,
    include_report: bool = True,
) -> int:
    """Return the happy-path provider call count for one Debate shape.

    One immutable Snapshot embedding is charged once for the run. Every turn
    spoken by an Agent whose Snapshot carries the real embedding identity also
    charges one retrieval query, every turn charges one debate-LLM call, and the
    Maya Report charges one more. A structure-repair attempt is an extra call
    that this happy-path count deliberately excludes; the ceiling covers it.
    """

    if not DEMO_ACCEPTANCE_MIN_AGENTS <= agent_count <= DEMO_ACCEPTANCE_MAX_AGENTS:
        raise ProviderControlError("Demo acceptance agent count is out of range")
    if not DEMO_ACCEPTANCE_MIN_ROUNDS <= round_count <= DEMO_ACCEPTANCE_MAX_ROUNDS:
        raise ProviderControlError("Demo acceptance round count is out of range")
    if not 0 <= real_snapshot_agents <= agent_count:
        raise ProviderControlError("Demo acceptance real Snapshot count is out of range")
    turns = agent_count * round_count
    queries = real_snapshot_agents * round_count
    return 1 + queries + turns + (1 if include_report else 0)


def demo_acceptance_max_calls(
    *,
    agent_count: int,
    round_count: int,
    real_snapshot_agents: int = 1,
) -> int:
    """Return the ceiling for one Debate shape, allowing one repair per turn."""

    happy = demo_acceptance_expected_calls(
        agent_count=agent_count,
        round_count=round_count,
        real_snapshot_agents=real_snapshot_agents,
    )
    return happy + agent_count * round_count


# Historical plan estimate retained for callers; it no longer limits ordinals.
DEMO_ACCEPTANCE_MAX_CALLS = demo_acceptance_max_calls(
    agent_count=DEMO_ACCEPTANCE_MAX_AGENTS,
    round_count=DEMO_ACCEPTANCE_MAX_ROUNDS,
    real_snapshot_agents=DEMO_ACCEPTANCE_MAX_AGENTS,
)
# Descriptive aliases keep the bounded Demo contract discoverable to callers.
REAL_CORE_DEMO_PLAN_VERSION = DEMO_ACCEPTANCE_PLAN_VERSION
REAL_CORE_DEMO_CALL_LIMIT = DEMO_ACCEPTANCE_MAX_CALLS
_OPERATION_BUCKETS: Mapping[str, str] = MappingProxyType(
    {
        # 0010/0013 used ``embedding`` for snapshot publication.  Keep this
        # alias when reading old operations, while all new callers use the
        # explicit bucket name.
        "embedding": EMBEDDING_SNAPSHOT_BUCKET,
        "embedding_snapshot": EMBEDDING_SNAPSHOT_BUCKET,
        "embedding_query": EMBEDDING_QUERY_BUCKET,
        "llm_debate_turn": LLM_DEBATE_TURN_BUCKET,
        "llm_barrage_insight": LLM_BARRAGE_INSIGHT_BUCKET,
        "llm_maya_report": LLM_MAYA_REPORT_BUCKET,
        "llm_agent_chat": LLM_DEBATE_TURN_BUCKET,
        "llm_knowledge_generate": LLM_DEBATE_TURN_BUCKET,
        # A Debate card is one more Debate model call, accounted beside its turns.
        "llm_debate_card": LLM_DEBATE_TURN_BUCKET,
        "tts_synthesis": TTS_SYNTHESIS_BUCKET,
        "tts": TTS_SYNTHESIS_BUCKET,
        "voice_enrollment": VOICE_ENROLLMENT_BUCKET,
        "voice": VOICE_ENROLLMENT_BUCKET,
    }
)
ALLOWED_ACCOUNT_PRODUCTS = frozenset(
    {
        "payg_api",
        "pay-as-you-go api",
        "pay-as-you-go API",
        "token_plan_team",
        "Token Plan Team",
    }
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_CODE_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
_RECOVERY_INPUT_FORBIDDEN_KEYS = frozenset(
    {
        "agent_md",
        "agent_markdown",
        "raw_agent_md",
        "teacher_note",
        "student_identity",
        "student_id",
        "student_name",
        "user_id",
        "user_name",
        "member_id",
        "member_name",
        "nickname",
        "email",
        "phone",
        "credential",
        "credentials",
        "api_key",
        "authorization",
        "bearer",
        "password",
        "secret",
        "header",
        "headers",
        "endpoint",
        "url",
        "workspace",
        "workspace_id",
        "provider",
        "supplier",
        "model",
        "usage",
        "policy",
    }
)
_RECOVERY_INPUT_IDENTITY_KEYS = frozenset(
    {
        "request_hash",
        "prompt_hash",
        "prompt_contract_version",
        "schema_hash",
        "tokenizer_id",
        "tokenizer_hash",
        "rule_set_hash",
        "persona_spec_hash",
        "transcript_hash",
        "receipt_hash",
        "policy_hash",
        "export_manifest_hash",
        "build_manifest_hash",
        "repair_policy_hash",
        "generation_fence",
        "model_key",
        "debate_id",
        "turn_id",
        "attempt_no",
    }
)
_RECOVERY_INPUT_TOP_LEVEL_KEYS = frozenset({"identity", "input"})
_RECOVERY_INPUT_FORBIDDEN_VALUE_RE = re.compile(
    r"(?ix)(?:\b(?:api[\s_-]*key|authorization|credential(?:s)?|"
    r"password|secret|token)\b\s*[=:]|\bbearer\b(?:\s*[=:]|\s+[A-Za-z0-9._-]+)|"
    r"\bsk-[A-Za-z0-9._-]+\b|\b(?:agent\.md|teacher[\s_-]*note)\b|"
    r"(?:^|[\s\"'])/(?:Users|home|tmp|var|private|workspace|root)/)"
)


def budget_bucket_for_operation(provider_operation: str) -> str:
    """Resolve a provider operation to one closed, non-transferable bucket."""

    try:
        return _OPERATION_BUCKETS[provider_operation]
    except KeyError as exc:
        raise ProviderControlError(
            "provider operation has no closed budget bucket",
            code="budget_bucket_invalid",
        ) from exc


def validate_budget_bucket(value: str) -> str:
    """Validate the persisted budget identity before any SQL operation."""

    if value not in PROVIDER_BUDGET_BUCKETS:
        raise ProviderControlError("budget bucket is not allowlisted", code="budget_bucket_invalid")
    return value


def validate_demo_acceptance_call_no(value: int) -> int:
    """Validate a positive accounting ordinal without a call-count ceiling."""

    if isinstance(value, bool) or not isinstance(value, int):
        raise ProviderControlError(
            "Demo acceptance call ordinal is invalid",
            code="acceptance_call_invalid",
        )
    if value < 1:
        raise ProviderControlError(
            "Demo acceptance call ordinal must be positive",
            code="acceptance_call_invalid",
        )
    return value


def _legacy_budget_bucket_for_operation(provider_operation: str) -> str | None:
    """Read-only compatibility for pre-0014 hydrated operation rows."""

    if provider_operation == "llm_debate":
        return LLM_DEBATE_TURN_BUCKET
    return _OPERATION_BUCKETS.get(provider_operation)


class ProviderControlError(ValueError):
    """A provider call cannot cross the frozen server-side control boundary."""

    def __init__(self, message: str, *, code: str = "provider_control_invalid") -> None:
        super().__init__(message)
        self.code = code


class PolicyValidationError(ProviderControlError):
    """The policy snapshot is incomplete, stale or not fail-closed."""


class ExportManifestError(ProviderControlError):
    """The outbound manifest contains forbidden or inconsistent data."""


class OperationStateError(RuntimeError):
    """A durable operation CAS or lifecycle transition failed."""


class BudgetExceeded(OperationStateError):
    """A scope's request/token/cost reservation would exceed its cap."""


class DuplicateOperation(OperationStateError):
    """The frozen idempotency tuple already exists."""


class ProviderNotSentError(RuntimeError):
    """The adapter proved the request did not reach supplier acceptance."""


class ProviderAcceptanceUnknownError(RuntimeError):
    """The adapter cannot exclude supplier acceptance; retry is forbidden."""


def canonical_json_bytes(value: object) -> bytes:
    """Return one deterministic, non-NaN JSON encoding for hashes."""

    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ProviderControlError("canonical JSON value is invalid") from exc


def sha256_hex(value: bytes | str) -> str:
    raw = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(raw).hexdigest()


def _hash(value: str, *, field_name: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ProviderControlError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def _https_url(value: str, *, field_name: str) -> str:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise PolicyValidationError(f"{field_name} is invalid", code="policy_url_invalid") from exc
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or port is not None
    ):
        raise PolicyValidationError(f"{field_name} is invalid", code="policy_url_invalid")
    return value


def _safe_identifier(value: str, *, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise ProviderControlError(f"{field_name} is invalid")
    return value


@dataclass(frozen=True, slots=True)
class ProviderPolicySnapshotV1:
    """Server-only evidence of the supplier account and data controls."""

    policy_id: str = "provider-policy-v1"
    supplier: str = "Alibaba Cloud Model Studio"
    region: str = FIXED_REGION
    account_product: str = "payg_api"
    endpoint: str = "https://dashscope.aliyuncs.com"
    privacy_notice_url: str = "https://example.invalid/privacy"
    privacy_notice_retrieved_at: str = ""
    privacy_notice_sha256: str = ""
    service_terms_url: str = "https://example.invalid/terms"
    service_terms_retrieved_at: str = ""
    service_terms_sha256: str = ""
    faq_url: str = "https://example.invalid/faq"
    faq_retrieved_at: str = ""
    faq_sha256: str = ""
    no_training_basis: str = ""
    prompt_response_logging_disabled: bool | None = None
    inference_log_backflow_disabled: bool | None = None
    optional_content_logging_disabled: bool | None = None
    service_improvement_disabled: bool | None = None
    storage_disclosed: bool = False
    retention_setting: str | None = None
    snapshot_revision: int = 1

    def __post_init__(self) -> None:
        _safe_identifier(self.policy_id, field_name="policy id")
        _safe_identifier(self.supplier, field_name="supplier")
        if self.region != FIXED_REGION:
            raise PolicyValidationError(
                "provider region is not Beijing", code="policy_region_invalid"
            )
        if self.account_product not in ALLOWED_ACCOUNT_PRODUCTS:
            raise PolicyValidationError(
                "provider account product is not authorized", code="policy_account_product_invalid"
            )
        _https_url(self.endpoint, field_name="provider endpoint")
        for name, value in (
            ("privacy_notice_url", self.privacy_notice_url),
            ("service_terms_url", self.service_terms_url),
            ("faq_url", self.faq_url),
        ):
            _https_url(value, field_name=name)
        for name, value in (
            ("privacy_notice_sha256", self.privacy_notice_sha256),
            ("service_terms_sha256", self.service_terms_sha256),
            ("faq_sha256", self.faq_sha256),
        ):
            _hash(value, field_name=name)
        for name, value in (
            ("privacy_notice_retrieved_at", self.privacy_notice_retrieved_at),
            ("service_terms_retrieved_at", self.service_terms_retrieved_at),
            ("faq_retrieved_at", self.faq_retrieved_at),
            ("no_training_basis", self.no_training_basis),
        ):
            _safe_identifier(value, field_name=name)
        controls = (
            self.prompt_response_logging_disabled,
            self.inference_log_backflow_disabled,
            self.optional_content_logging_disabled,
            self.service_improvement_disabled,
        )
        if any(value is not True for value in controls):
            raise PolicyValidationError(
                "all supplier logging/backflow controls must be explicitly disabled",
                code="policy_controls_unknown",
            )
        if self.storage_disclosed is not True:
            raise PolicyValidationError(
                "supplier storage disclosure is required", code="policy_storage_unknown"
            )
        if self.retention_setting is not None:
            _safe_identifier(self.retention_setting, field_name="retention setting")
        if self.snapshot_revision < 1:
            raise PolicyValidationError(
                "policy revision is invalid", code="policy_revision_invalid"
            )

    def canonical_dict(self) -> dict[str, object]:
        return {
            "version": PROVIDER_DATA_CALL_VERSION,
            "policy_id": self.policy_id,
            "supplier": self.supplier,
            "region": self.region,
            "account_product": self.account_product,
            "endpoint": self.endpoint,
            "privacy_notice_url": self.privacy_notice_url,
            "privacy_notice_retrieved_at": self.privacy_notice_retrieved_at,
            "privacy_notice_sha256": self.privacy_notice_sha256,
            "service_terms_url": self.service_terms_url,
            "service_terms_retrieved_at": self.service_terms_retrieved_at,
            "service_terms_sha256": self.service_terms_sha256,
            "faq_url": self.faq_url,
            "faq_retrieved_at": self.faq_retrieved_at,
            "faq_sha256": self.faq_sha256,
            "no_training_basis": self.no_training_basis,
            "prompt_response_logging_disabled": self.prompt_response_logging_disabled,
            "inference_log_backflow_disabled": self.inference_log_backflow_disabled,
            "optional_content_logging_disabled": self.optional_content_logging_disabled,
            "service_improvement_disabled": self.service_improvement_disabled,
            "storage_disclosed": self.storage_disclosed,
            "retention_setting": self.retention_setting,
            "snapshot_revision": self.snapshot_revision,
        }

    @property
    def policy_hash(self) -> str:
        return sha256_hex(canonical_json_bytes(self.canonical_dict()))

    @property
    def hash(self) -> str:
        return self.policy_hash

    def assert_current(self, expected_hash: str) -> None:
        if expected_hash != self.policy_hash:
            raise PolicyValidationError("ProviderPolicySnapshot is stale", code="policy_hash_stale")

    def validate(self) -> ProviderPolicySnapshotV1:
        return validate_policy_snapshot(self)


_ALLOWED_EXPORT_CLASSES = frozenset(
    {
        "topic_and_platform_rules",
        "confirmed_structured_persona",
        "public_predecessor_speech",
        "current_evidence_excerpt",
        "opaque_local_id",
        "public_agent_name",
        "anonymous_insight_summary",
        "anonymous_classroom_barrage",
        "session_discussion_memory",
        "private_conversation_messages",
        "aggregate_vote_count",
        "aggregate_evidence_grade",
        "current_tts_speech",
        "server_authored_structure_repair_feedback",
        "teacher_agent_instructions",
        "authorized_courseware_text",
    }
)
_FORBIDDEN_EXPORT_TERMS = frozenset(
    {
        "api_key",
        "authorization",
        "bearer",
        "credential",
        "password",
        "secret",
        "student_name",
        "student_id",
        "user_id",
        "nickname",
        "identity",
        "private_audio",
        "audio_sample",
        "agent.md",
        "teacher_note",
        "source_path",
        "absolute_path",
    }
)
_FORBIDDEN_VALUE_RE = re.compile(
    r"(?:api[_-]?key|authorization|bearer\s+[A-Za-z0-9._-]+|"
    r"password\s*[:=]|secret\s*[:=]|sk-[A-Za-z0-9])",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class ExportFieldV1:
    """One data class in an export manifest; values are represented by hashes."""

    field_class: str
    value_sha256: str

    def __post_init__(self) -> None:
        if self.field_class not in _ALLOWED_EXPORT_CLASSES:
            raise ExportManifestError(
                "export field is not allowlisted", code="export_field_forbidden"
            )
        _hash(self.value_sha256, field_name="export field hash")

    def canonical_dict(self) -> dict[str, str]:
        return {"field_class": self.field_class, "value_sha256": self.value_sha256}


@dataclass(frozen=True, slots=True)
class ExportManifestV1:
    """Exact server-side allowlist bound to a policy snapshot by CAS."""

    scope_id: str
    provider_operation: str
    model_key: str
    policy_hash: str
    build_manifest_hash: str
    persona_spec_hash: str
    fields: tuple[ExportFieldV1, ...] = ()
    operation_revision: int = 1
    contains_secret: bool = False
    contains_identity: bool = False
    contains_private_audio: bool = False
    contains_teacher_note: bool = False
    # Debate/Turn are nullable for legacy Embedding/TTS manifests.  They are
    # persisted as owner bindings, but remain out of the canonical payload for
    # older manifests whose hashes predate Wave 4 owner columns.
    debate_id: str | None = None
    turn_id: str | None = None
    max_attempts: int = 1
    max_total_tokens: int = 0
    max_cost_cny: float = 0.0
    repair_policy_version: str | None = None
    repair_policy_hash: str | None = None

    def __post_init__(self) -> None:
        _safe_identifier(self.scope_id, field_name="export scope")
        _safe_identifier(self.provider_operation, field_name="provider operation")
        _safe_identifier(self.model_key, field_name="export model")
        _hash(self.policy_hash, field_name="export policy hash")
        _hash(self.build_manifest_hash, field_name="export build hash")
        _hash(self.persona_spec_hash, field_name="export PersonaSpec hash")
        if self.operation_revision < 1:
            raise ExportManifestError("export revision is invalid", code="export_revision_invalid")
        if (self.debate_id is None) != (self.turn_id is None):
            raise ExportManifestError(
                "Debate and Turn manifest owners must be both present or absent",
                code="export_owner_invalid",
            )
        for value, name in ((self.debate_id, "Debate owner"), (self.turn_id, "Turn owner")):
            if value is not None:
                _safe_identifier(value, field_name=name)
        if self.max_attempts < 1 or self.max_attempts > 2:
            raise ExportManifestError(
                "export attempt cap is invalid", code="export_attempts_invalid"
            )
        if self.max_total_tokens < 0:
            raise ExportManifestError("export token cap is invalid", code="export_tokens_invalid")
        try:
            max_cost = Decimal(str(self.max_cost_cny))
        except (InvalidOperation, ValueError) as exc:
            raise ExportManifestError(
                "export cost cap is invalid", code="export_cost_invalid"
            ) from exc
        if not max_cost.is_finite() or max_cost < 0:
            raise ExportManifestError("export cost cap is invalid", code="export_cost_invalid")
        if (self.repair_policy_version is None) != (self.repair_policy_hash is None):
            raise ExportManifestError(
                "repair policy version/hash must be paired",
                code="repair_policy_invalid",
            )
        if self.repair_policy_version is not None:
            _safe_identifier(self.repair_policy_version, field_name="repair policy version")
            _hash(self.repair_policy_hash or "", field_name="repair policy hash")
        repair_fields = {
            item.field_class
            for item in self.fields
            if item.field_class == "server_authored_structure_repair_feedback"
        }
        if self.provider_operation == "llm_debate" and (
            self.debate_id is not None
            or self.turn_id is not None
            or self.max_attempts != 1
            or self.max_total_tokens != 0
            or self.max_cost_cny != 0
            or self.repair_policy_version is not None
            or self.repair_policy_hash is not None
            or repair_fields
        ):
            raise ExportManifestError(
                "legacy llm_debate manifests are read-only",
                code="provider_operation_legacy",
            )
        is_llm_turn = self.provider_operation == "llm_debate_turn"
        is_knowledge_generation = self.provider_operation == "llm_knowledge_generate"
        if is_llm_turn:
            if self.max_attempts == 2:
                if (
                    self.repair_policy_version not in REPAIR_FEEDBACK_POLICIES
                    or REPAIR_FEEDBACK_POLICIES.get(self.repair_policy_version)
                    != self.repair_policy_hash
                    or not repair_fields
                ):
                    raise ExportManifestError(
                        "LLM turn manifest must disclose repair feedback policy",
                        code="repair_policy_invalid",
                    )
            elif (
                self.repair_policy_version is not None
                or self.repair_policy_hash is not None
                or repair_fields
            ):
                raise ExportManifestError(
                    "one-shot LLM turn manifests cannot disclose repair feedback",
                    code="repair_policy_invalid",
                )
        elif is_knowledge_generation and (
            self.max_attempts != 1
            or self.repair_policy_version is not None
            or self.repair_policy_hash is not None
            or repair_fields
        ):
            raise ExportManifestError(
                "Knowledge generation manifests are single-invoke and have no repair feedback",
                code="knowledge_generation_attempts_invalid",
            )
        elif repair_fields or self.repair_policy_version is not None:
            raise ExportManifestError(
                "repair feedback policy is only valid for LLM turn manifests",
                code="repair_policy_invalid",
            )
        if (
            self.contains_secret
            or self.contains_identity
            or self.contains_private_audio
            or self.contains_teacher_note
        ):
            raise ExportManifestError(
                "export manifest contains forbidden data", code="export_data_forbidden"
            )
        seen: set[str] = set()
        for field_value in self.fields:
            if field_value.field_class in seen:
                raise ExportManifestError(
                    "export field class is duplicated", code="export_field_duplicate"
                )
            seen.add(field_value.field_class)
        if not self.fields:
            raise ExportManifestError(
                "export manifest must contain an outbound field",
                code="export_fields_missing",
            )

    def canonical_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "version": PROVIDER_DATA_CALL_VERSION,
            "scope_id": self.scope_id,
            "provider_operation": self.provider_operation,
            "model_key": self.model_key,
            "policy_hash": self.policy_hash,
            "build_manifest_hash": self.build_manifest_hash,
            "persona_spec_hash": self.persona_spec_hash,
            "fields": [field_value.canonical_dict() for field_value in self.fields],
            "operation_revision": self.operation_revision,
            "contains_secret": self.contains_secret,
            "contains_identity": self.contains_identity,
            "contains_private_audio": self.contains_private_audio,
            "contains_teacher_note": self.contains_teacher_note,
        }
        # Keep old 0010/0013 manifest hashes stable.  New LLM manifests bind
        # the disclosed retry budget/policy in their canonical hash.
        if (
            self.max_attempts != 1
            or self.max_total_tokens != 0
            or self.max_cost_cny != 0
            or self.repair_policy_version is not None
            or self.repair_policy_hash is not None
        ):
            value.update(
                {
                    "max_attempts": self.max_attempts,
                    "max_total_tokens": self.max_total_tokens,
                    "max_cost_cny": str(Decimal(str(self.max_cost_cny))),
                    "repair_policy_version": self.repair_policy_version,
                    "repair_policy_hash": self.repair_policy_hash,
                }
            )
        return value

    @property
    def manifest_hash(self) -> str:
        return sha256_hex(canonical_json_bytes(self.canonical_dict()))

    @property
    def hash(self) -> str:
        return self.manifest_hash

    def validate(self) -> ExportManifestV1:
        return validate_export_manifest(self)


@dataclass(frozen=True, slots=True)
class ExportConfirmationV1:
    """Teacher/operator CAS confirmation for one exact manifest and policy."""

    manifest_hash: str
    policy_hash: str
    confirmed_at: str
    confirmation_revision: int = 1

    def __post_init__(self) -> None:
        _hash(self.manifest_hash, field_name="confirmation manifest hash")
        _hash(self.policy_hash, field_name="confirmation policy hash")
        _safe_identifier(self.confirmed_at, field_name="confirmation time")
        if self.confirmation_revision < 1:
            raise ExportManifestError(
                "confirmation revision is invalid", code="export_confirmation_invalid"
            )


def confirm_export_manifest(
    manifest: ExportManifestV1,
    policy: ProviderPolicySnapshotV1,
    *,
    confirmed_at: str,
    expected_manifest_hash: str | None = None,
    expected_policy_hash: str | None = None,
) -> ExportConfirmationV1:
    """Create a confirmation only when both expected CAS hashes are current."""

    if manifest.policy_hash != policy.policy_hash:
        raise PolicyValidationError("export references a stale policy", code="policy_hash_stale")
    if expected_manifest_hash is not None and expected_manifest_hash != manifest.manifest_hash:
        raise ExportManifestError("export manifest CAS is stale", code="export_hash_stale")
    if expected_policy_hash is not None and expected_policy_hash != policy.policy_hash:
        raise PolicyValidationError("policy CAS is stale", code="policy_hash_stale")
    return ExportConfirmationV1(
        manifest_hash=manifest.manifest_hash,
        policy_hash=policy.policy_hash,
        confirmed_at=confirmed_at,
    )


def validate_policy_snapshot(policy: ProviderPolicySnapshotV1) -> ProviderPolicySnapshotV1:
    """Re-run the constructor-level fail-closed checks at a persistence boundary."""

    if not isinstance(policy, ProviderPolicySnapshotV1):
        raise PolicyValidationError("provider policy snapshot is invalid", code="policy_invalid")
    # The immutable dataclass was validated on construction.  Returning it
    # keeps this helper useful to repository adapters without copying secrets.
    return policy


def validate_export_manifest(manifest: ExportManifestV1) -> ExportManifestV1:
    """Re-run type/immutability checks before a confirmation or request."""

    if not isinstance(manifest, ExportManifestV1):
        raise ExportManifestError("provider export manifest is invalid", code="export_invalid")
    return manifest


@dataclass(frozen=True, slots=True)
class ProviderPreflightV1:
    """Non-public, hash-only result of policy/export/model preflight."""

    scope_id: str
    provider_operation: str
    model_key: str
    region: str
    policy_hash: str
    export_manifest_hash: str


def _scan_forbidden(value: object, *, path: str = "payload") -> None:
    """Reject secret/identity/private fields before a payload can be sent."""

    if isinstance(value, Mapping):
        for key, nested in value.items():
            folded = str(key).casefold().replace("-", "_")
            if any(term in folded for term in _FORBIDDEN_EXPORT_TERMS):
                raise ExportManifestError(
                    f"forbidden export field at {path}", code="export_data_forbidden"
                )
            _scan_forbidden(nested, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple, set, frozenset)):
        for index, nested in enumerate(value):
            _scan_forbidden(nested, path=f"{path}[{index}]")
    elif isinstance(value, str) and _FORBIDDEN_VALUE_RE.search(value):
        raise ExportManifestError(f"forbidden export value at {path}", code="export_data_forbidden")


_LLM_MODEL_OPERATIONS = frozenset(
    {
        "llm_debate",
        "llm_debate_turn",
        "llm_debate_card",
        "llm_maya_report",
        "llm_agent_chat",
        "llm_knowledge_generate",
    }
)


def authorized_provider_model(provider_operation: str) -> str | None:
    """Embedding and speech stay pinned. LLM calls follow LLM_MODEL, Debates
    DEBATE_LLM_MODEL when it is set."""

    if provider_operation in {"llm_debate", "llm_debate_turn", "llm_debate_card"}:
        # The same setting the Debate adapter sends (DEBATE_LLM_MODEL, else LLM_MODEL).
        from app.core.config import configured_debate_llm_model

        return configured_debate_llm_model()
    if provider_operation in _LLM_MODEL_OPERATIONS:
        from app.core.config import configured_llm_model

        return configured_llm_model()
    return FIXED_MODELS.get(provider_operation)


def validate_provider_preflight(
    policy: ProviderPolicySnapshotV1,
    manifest: ExportManifestV1,
    confirmation: ExportConfirmationV1,
    *,
    scope_id: str,
    provider_operation: str,
    model_key: str,
    region: str = FIXED_REGION,
    payload: object | None = None,
) -> ProviderPreflightV1:
    """Fail closed on stale policy/export hashes or forbidden outbound data."""

    if provider_operation == "llm_debate":
        raise ExportManifestError(
            "legacy llm_debate authority is read-only",
            code="provider_operation_legacy",
        )
    if region != FIXED_REGION or policy.region != region:
        raise PolicyValidationError(
            "provider region is not authorized", code="policy_region_invalid"
        )
    expected_model = authorized_provider_model(provider_operation)
    if expected_model is None or model_key != expected_model:
        raise PolicyValidationError("provider model is not fixed/authorized", code="model_invalid")
    if manifest.scope_id != scope_id or manifest.provider_operation != provider_operation:
        raise ExportManifestError(
            "export scope/operation does not match request", code="export_scope_mismatch"
        )
    if manifest.model_key != model_key:
        raise ExportManifestError(
            "export model does not match request", code="export_model_mismatch"
        )
    if confirmation.policy_hash != policy.policy_hash:
        raise PolicyValidationError(
            "provider policy confirmation is stale", code="policy_hash_stale"
        )
    if confirmation.manifest_hash != manifest.manifest_hash:
        raise ExportManifestError("provider export confirmation is stale", code="export_hash_stale")
    if manifest.policy_hash != policy.policy_hash:
        raise PolicyValidationError("export policy hash is stale", code="policy_hash_stale")
    if payload is not None:
        _scan_forbidden(payload)
    return ProviderPreflightV1(
        scope_id=scope_id,
        provider_operation=provider_operation,
        model_key=model_key,
        region=region,
        policy_hash=policy.policy_hash,
        export_manifest_hash=manifest.manifest_hash,
    )


OperationState = Literal[
    "prepared",
    "reserved",
    "sending",
    "accepted",
    "succeeded",
    "not_sent",
    "acceptance_unknown",
    "failed",
    "abandoned",
]
ReservationState = Literal[
    "prepared",
    "reserved",
    "sending",
    "accepted",
    "succeeded",
    "not_sent",
    "acceptance_unknown",
    "failed",
    "abandoned",
]


@dataclass(frozen=True, slots=True)
class ProviderReservationRequestV1:
    """One unique, conservative allowance request."""

    scope_id: str
    provider_operation: str
    logical_item_id: str
    attempt_no: int
    request_hash: str
    max_tokens: int
    max_cost_cny: float
    policy_hash: str
    export_manifest_hash: str
    build_manifest_hash: str = ""
    model_key: str = ""
    operation_id: str = ""
    budget_bucket: str = ""

    def __post_init__(self) -> None:
        for value, name in (
            (self.scope_id, "scope id"),
            (self.provider_operation, "provider operation"),
            (self.logical_item_id, "logical item id"),
        ):
            _safe_identifier(value, field_name=name)
        if self.attempt_no < 1 or self.max_tokens < 0:
            raise ProviderControlError("reservation attempt/tokens are invalid")
        _hash(self.request_hash, field_name="request hash")
        _hash(self.policy_hash, field_name="policy hash")
        _hash(self.export_manifest_hash, field_name="export manifest hash")
        if self.build_manifest_hash:
            _hash(self.build_manifest_hash, field_name="build manifest hash")
        if self.model_key:
            _safe_identifier(self.model_key, field_name="model key")
        inferred_bucket = budget_bucket_for_operation(self.provider_operation)
        if self.budget_bucket:
            validate_budget_bucket(self.budget_bucket)
            if self.budget_bucket != inferred_bucket:
                raise ProviderControlError(
                    "provider operation and budget bucket do not match",
                    code="budget_bucket_mismatch",
                )
        else:
            # Keep construction compatible with pre-0014 callers while
            # making the bucket explicit in every durable record.
            object.__setattr__(self, "budget_bucket", inferred_bucket)
        try:
            amount = Decimal(str(self.max_cost_cny))
        except (InvalidOperation, ValueError) as exc:
            raise ProviderControlError("reservation cost is invalid") from exc
        if not amount.is_finite() or amount < 0:
            raise ProviderControlError("reservation cost is invalid")

    @property
    def idempotency_key(self) -> tuple[str, str, str, int]:
        return (
            self.scope_id,
            self.provider_operation,
            self.logical_item_id,
            self.attempt_no,
        )

    def as_record(self) -> dict[str, object]:
        return {
            "scope_id": self.scope_id,
            "provider_operation": self.provider_operation,
            "logical_item_id": self.logical_item_id,
            "attempt_no": self.attempt_no,
            "request_hash": self.request_hash,
            "max_tokens": self.max_tokens,
            "max_cost_cny": self.max_cost_cny,
            "policy_hash": self.policy_hash,
            "export_manifest_hash": self.export_manifest_hash,
            "build_manifest_hash": self.build_manifest_hash,
            "model_key": self.model_key,
            "budget_bucket": self.budget_bucket,
        }


@dataclass(frozen=True, slots=True)
class ProviderOperationV1:
    """Persistable provider operation metadata with no payload or secret."""

    id: str
    scope_id: str
    provider_operation: str
    logical_item_id: str
    attempt_no: int
    request_hash: str
    max_tokens: int
    max_cost_cny: float
    policy_hash: str
    export_manifest_hash: str
    build_manifest_hash: str = ""
    model_key: str = ""
    state: OperationState = "prepared"
    reservation_id: str | None = None
    request_count: int = 0
    charged_request_count: int = 0
    staged_response_hash: str | None = None
    safe_error_code: str | None = None
    acceptance_run_id: str | None = None
    call_no: int | None = None

    def __post_init__(self) -> None:
        if (self.acceptance_run_id is None) != (self.call_no is None):
            raise ProviderControlError(
                "Demo acceptance run and call ordinal must be paired",
                code="acceptance_call_invalid",
            )
        if self.call_no is not None:
            validate_demo_acceptance_call_no(self.call_no)

    @property
    def budget_bucket(self) -> str:
        return _legacy_budget_bucket_for_operation(
            self.provider_operation
        ) or budget_bucket_for_operation(self.provider_operation)

    @property
    def idempotency_key(self) -> tuple[str, str, str, int]:
        return (
            self.scope_id,
            self.provider_operation,
            self.logical_item_id,
            self.attempt_no,
        )

    def as_record(self) -> dict[str, object]:
        return {
            "id": self.id,
            "scope_id": self.scope_id,
            "provider_operation": self.provider_operation,
            "logical_item_id": self.logical_item_id,
            "attempt_no": self.attempt_no,
            "request_hash": self.request_hash,
            "max_tokens": self.max_tokens,
            "max_cost_cny": self.max_cost_cny,
            "policy_hash": self.policy_hash,
            "export_manifest_hash": self.export_manifest_hash,
            "build_manifest_hash": self.build_manifest_hash,
            "model_key": self.model_key,
            "state": self.state,
            "reservation_id": self.reservation_id,
            "request_count": self.request_count,
            "charged_request_count": self.charged_request_count,
            "staged_response_hash": self.staged_response_hash,
            "safe_error_code": self.safe_error_code,
            "acceptance_run_id": self.acceptance_run_id,
            "call_no": self.call_no,
            "budget_bucket": self.budget_bucket,
        }


@dataclass(frozen=True, slots=True)
class KnowledgeGenerationAcceptedStageV1:
    """Sanitized, exact accepted output for one K2b1 Provider operation."""

    run_id: str
    claim_token: str
    operation_id: str
    request_hash: str
    manifest_hash: str
    policy_hash: str
    model_key: str
    schema_hash: str
    canonical_stage_json: str | None
    canonical_stage_hash: str
    item_count: int
    usage_json: str | None = None
    safe_error_code: str | None = None

    def __post_init__(self) -> None:
        for value, name in (
            (self.run_id, "Knowledge generation run id"),
            (self.claim_token, "Knowledge generation claim token"),
            (self.operation_id, "Provider operation id"),
            (self.model_key, "Provider model key"),
        ):
            _safe_identifier(value, field_name=name)
        for value, name in (
            (self.request_hash, "Knowledge request hash"),
            (self.manifest_hash, "Knowledge export manifest hash"),
            (self.policy_hash, "Knowledge policy hash"),
            (self.schema_hash, "Knowledge response schema hash"),
            (self.canonical_stage_hash, "Knowledge canonical stage hash"),
        ):
            _hash(value, field_name=name)
        if (
            isinstance(self.item_count, bool)
            or not isinstance(self.item_count, int)
            or self.item_count < 0
        ):
            raise ProviderControlError("Knowledge stage item count is invalid")
        if self.canonical_stage_json is None:
            if self.item_count != 0 or self.safe_error_code is None:
                raise ProviderControlError("suppressed Knowledge stage identity is invalid")
            suppressed_json = canonical_json_bytes(
                {"safe_error_code": self.safe_error_code, "suppressed": True}
            ).decode("utf-8")
            if sha256_hex(suppressed_json) != self.canonical_stage_hash:
                raise ProviderControlError("suppressed Knowledge stage hash is stale")
        else:
            try:
                parsed = json.loads(self.canonical_stage_json)
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ProviderControlError("Knowledge stage JSON is invalid") from exc
            if canonical_json_bytes(parsed).decode("utf-8") != self.canonical_stage_json:
                raise ProviderControlError("Knowledge stage JSON is not canonical")
            if self.safe_error_code is not None:
                raise ProviderControlError("accepted Knowledge stage cannot include an error")
            if sha256_hex(self.canonical_stage_json.encode("utf-8")) != self.canonical_stage_hash:
                raise ProviderControlError("Knowledge stage hash is stale")
        if self.safe_error_code is not None and not _SAFE_CODE_RE.fullmatch(self.safe_error_code):
            raise ProviderControlError("Knowledge stage safe error code is invalid")
        if self.usage_json is not None:
            try:
                usage = json.loads(self.usage_json)
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ProviderControlError("Knowledge stage usage is invalid") from exc
            if (
                not isinstance(usage, dict)
                or canonical_json_bytes(usage).decode("utf-8") != self.usage_json
            ):
                raise ProviderControlError("Knowledge stage usage is not canonical")


@dataclass(frozen=True, slots=True)
class ProviderReservationV1:
    """Persistable reservation row, kept separate from operation metadata."""

    id: str
    operation_id: str
    scope_id: str
    provider_operation: str
    logical_item_id: str
    attempt_no: int
    max_tokens: int
    max_cost_cny: float
    state: ReservationState = "prepared"

    @property
    def budget_bucket(self) -> str:
        return _legacy_budget_bucket_for_operation(
            self.provider_operation
        ) or budget_bucket_for_operation(self.provider_operation)

    def as_record(self) -> dict[str, object]:
        return {
            "id": self.id,
            "operation_id": self.operation_id,
            "scope_id": self.scope_id,
            "provider_operation": self.provider_operation,
            "logical_item_id": self.logical_item_id,
            "attempt_no": self.attempt_no,
            "max_tokens": self.max_tokens,
            "max_cost_cny": self.max_cost_cny,
            "state": self.state,
            "budget_bucket": self.budget_bucket,
        }


@dataclass(frozen=True, slots=True)
class ProviderScopeBudgetV1:
    """Atomic cap for one debate/snapshot/report/TTS scope."""

    max_requests: int = 20
    max_total_tokens: int = 120_000
    max_cost_cny: float = 0.10
    budget_bucket: str = EMBEDDING_SNAPSHOT_BUCKET

    def __post_init__(self) -> None:
        if self.max_requests < 1 or self.max_total_tokens < 0:
            raise ProviderControlError("scope budget counts are invalid")
        validate_budget_bucket(self.budget_bucket)
        try:
            amount = Decimal(str(self.max_cost_cny))
        except (InvalidOperation, ValueError) as exc:
            raise ProviderControlError("scope budget cost is invalid") from exc
        if not amount.is_finite() or amount < 0:
            raise ProviderControlError("scope budget cost is invalid")


def _validate_nonnegative_decimal(value: object, *, field_name: str) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ProviderControlError(f"{field_name} is invalid") from exc
    if not amount.is_finite() or amount < 0:
        raise ProviderControlError(f"{field_name} is invalid")
    return amount


@dataclass(frozen=True, slots=True)
class LLMAcceptedStageV1:
    """Sanitized immutable output/usage stage for one accepted LLM attempt.

    The stage contains the provider's already-sanitized structured JSON only;
    no response envelope, raw headers, supplier request ID or credential is
    represented.  It is intentionally independent of SQLAlchemy so a worker
    can validate it locally before opening the product publication transaction.
    """

    operation_id: str
    turn_id: str
    attempt_no: int
    request_hash: str
    prompt_hash: str
    prompt_contract_version: str
    schema_hash: str
    tokenizer_id: str
    tokenizer_hash: str
    rule_set_hash: str
    persona_spec_hash: str
    transcript_hash: str
    receipt_hash: str
    policy_hash: str
    export_manifest_hash: str
    build_manifest_hash: str
    model_key: str
    output_json: str
    output_hash: str
    prompt_tokens: int = 0
    cached_input_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    price_card_version: str = "price-card-v1"
    input_price_cny_per_million: str | float | Decimal = 0
    cached_input_price_cny_per_million: str | float | Decimal = 0
    output_price_cny_per_million: str | float | Decimal = 0
    estimated_cost_cny: str | float | Decimal = 0
    actual_cost_cny: str | float | Decimal | None = None
    retrieval_reused: bool = False
    safe_error_code: str | None = None
    repair_policy_version: str | None = None
    repair_policy_hash: str | None = None
    generation_fence: str = ""
    # Provider/PromptBudget terminology aliases.  They are normalized to the
    # canonical prompt/completion names before persistence.
    input_tokens: int | None = None
    output_tokens: int | None = None

    def __post_init__(self) -> None:
        if self.input_tokens is not None:
            if self.prompt_tokens not in {0, self.input_tokens}:
                raise ProviderControlError("input token aliases disagree", code="llm_usage_invalid")
            object.__setattr__(self, "prompt_tokens", self.input_tokens)
        if self.output_tokens is not None:
            if self.completion_tokens not in {0, self.output_tokens}:
                raise ProviderControlError(
                    "output token aliases disagree", code="llm_usage_invalid"
                )
            object.__setattr__(self, "completion_tokens", self.output_tokens)
        if self.total_tokens == 0 and (self.prompt_tokens or self.completion_tokens):
            object.__setattr__(
                self,
                "total_tokens",
                self.prompt_tokens + self.completion_tokens,
            )
        object.__setattr__(self, "input_tokens", self.prompt_tokens)
        object.__setattr__(self, "output_tokens", self.completion_tokens)
        for value, name in (
            (self.operation_id, "LLM stage operation id"),
            (self.turn_id, "LLM stage turn id"),
            (self.prompt_contract_version, "prompt contract version"),
            (self.tokenizer_id, "tokenizer id"),
            (self.model_key, "LLM model key"),
            (self.price_card_version, "price card version"),
        ):
            _safe_identifier(value, field_name=name)
        if self.attempt_no < 1 or self.attempt_no > 2:
            raise ProviderControlError("LLM stage attempt is invalid", code="llm_stage_invalid")
        for value, name in (
            (self.request_hash, "LLM stage request hash"),
            (self.prompt_hash, "LLM stage prompt hash"),
            (self.schema_hash, "LLM stage schema hash"),
            (self.tokenizer_hash, "LLM stage tokenizer hash"),
            (self.rule_set_hash, "LLM stage rule hash"),
            (self.persona_spec_hash, "LLM stage Persona hash"),
            (self.transcript_hash, "LLM stage transcript hash"),
            (self.receipt_hash, "LLM stage receipt hash"),
            (self.policy_hash, "LLM stage policy hash"),
            (self.export_manifest_hash, "LLM stage export hash"),
            (self.build_manifest_hash, "LLM stage build hash"),
            (self.output_hash, "LLM stage output hash"),
        ):
            _hash(value, field_name=name)
        if self.repair_policy_hash is not None:
            _hash(self.repair_policy_hash, field_name="LLM stage repair policy hash")
        if self.repair_policy_version is not None:
            _safe_identifier(
                self.repair_policy_version, field_name="LLM stage repair policy version"
            )
        for token_value, name in (
            (self.prompt_tokens, "prompt token count"),
            (self.cached_input_tokens, "cached input token count"),
            (self.completion_tokens, "completion token count"),
            (self.total_tokens, "total token count"),
        ):
            if isinstance(token_value, bool) or not isinstance(token_value, int) or token_value < 0:
                raise ProviderControlError(f"{name} is invalid", code="llm_usage_invalid")
        if self.cached_input_tokens > self.prompt_tokens:
            raise ProviderControlError(
                "cached input exceeds prompt tokens", code="llm_usage_invalid"
            )
        if self.total_tokens != self.prompt_tokens + self.completion_tokens:
            raise ProviderControlError("LLM usage total does not add up", code="llm_usage_invalid")
        for price_value, name in (
            (self.input_price_cny_per_million, "input price"),
            (self.cached_input_price_cny_per_million, "cached input price"),
            (self.output_price_cny_per_million, "output price"),
            (self.estimated_cost_cny, "estimated cost"),
        ):
            _validate_nonnegative_decimal(price_value, field_name=name)
        if self.actual_cost_cny is not None:
            _validate_nonnegative_decimal(self.actual_cost_cny, field_name="actual cost")
        try:
            json_value = json.loads(self.output_json)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ProviderControlError(
                "LLM stage output JSON is invalid", code="llm_stage_invalid"
            ) from exc
        if not isinstance(json_value, dict):
            raise ProviderControlError(
                "LLM stage output JSON must be an object", code="llm_stage_invalid"
            )
        canonical_output_hash = sha256_hex(canonical_json_bytes(json_value))
        if self.output_hash != canonical_output_hash:
            raise ProviderControlError(
                "LLM stage output hash does not match canonical output JSON",
                code="llm_output_hash_mismatch",
            )
        if self.safe_error_code is not None and not _SAFE_CODE_RE.fullmatch(self.safe_error_code):
            raise ProviderControlError("LLM stage safe error is invalid", code="llm_stage_invalid")

    @property
    def provider_output_json(self) -> str:
        """Compatibility name used by adapter implementations."""

        return self.output_json

    def as_record(self) -> dict[str, object]:
        """Return the immutable SQL/storage projection without provider data."""

        return {
            "operation_id": self.operation_id,
            "turn_id": self.turn_id,
            "attempt_no": self.attempt_no,
            "request_hash": self.request_hash,
            "prompt_hash": self.prompt_hash,
            "prompt_contract_version": self.prompt_contract_version,
            "schema_hash": self.schema_hash,
            "tokenizer_id": self.tokenizer_id,
            "tokenizer_hash": self.tokenizer_hash,
            "rule_set_hash": self.rule_set_hash,
            "persona_spec_hash": self.persona_spec_hash,
            "transcript_hash": self.transcript_hash,
            "receipt_hash": self.receipt_hash,
            "policy_hash": self.policy_hash,
            "export_manifest_hash": self.export_manifest_hash,
            "build_manifest_hash": self.build_manifest_hash,
            "repair_policy_hash": self.repair_policy_hash,
            "generation_fence": self.generation_fence,
            "model_key": self.model_key,
            "output_json": self.output_json,
            "output_hash": self.output_hash,
            "prompt_tokens": self.prompt_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "price_card_version": self.price_card_version,
            "input_price_cny_per_million": str(
                _validate_nonnegative_decimal(
                    self.input_price_cny_per_million, field_name="input price"
                )
            ),
            "cached_input_price_cny_per_million": str(
                _validate_nonnegative_decimal(
                    self.cached_input_price_cny_per_million,
                    field_name="cached input price",
                )
            ),
            "output_price_cny_per_million": str(
                _validate_nonnegative_decimal(
                    self.output_price_cny_per_million, field_name="output price"
                )
            ),
            "estimated_cost_cny": str(
                _validate_nonnegative_decimal(self.estimated_cost_cny, field_name="estimated cost")
            ),
            "actual_cost_cny": (
                str(_validate_nonnegative_decimal(self.actual_cost_cny, field_name="actual cost"))
                if self.actual_cost_cny is not None
                else None
            ),
            "retrieval_reused": self.retrieval_reused,
            "safe_error_code": self.safe_error_code,
            "repair_policy_version": self.repair_policy_version,
        }


def _recovery_input_no_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, nested in pairs:
        if key in value:
            raise ProviderControlError(
                "LLM recovery input JSON contains duplicate keys",
                code="llm_recovery_input_invalid",
            )
        value[key] = nested
    return value


def _scan_recovery_input_value(value: object, *, path: tuple[str, ...] = ()) -> None:
    """Reject private/control fields without including their values in errors."""

    if isinstance(value, Mapping):
        for key, nested in value.items():
            if not isinstance(key, str):
                raise ProviderControlError(
                    "LLM recovery input contains an invalid field",
                    code="llm_recovery_input_forbidden",
                )
            folded = re.sub(r"[\s.-]+", "_", key.casefold())
            identity_path = (
                path
                in {
                    ("input", "persona_provider_view"),
                    ("input", "request", "persona_provider_view"),
                }
                and folded == "identity"
            )
            if (
                folded in _RECOVERY_INPUT_FORBIDDEN_KEYS
                or folded == "identity"
                and not identity_path
                or any(
                    marker in folded
                    for marker in (
                        "agent_md",
                        "teacher_note",
                        "student_identity",
                        "user_identity",
                        "member_identity",
                        "credential",
                        "authorization",
                        "endpoint",
                        "workspace",
                    )
                )
            ):
                raise ProviderControlError(
                    "LLM recovery input contains a forbidden field",
                    code="llm_recovery_input_forbidden",
                )
            _scan_recovery_input_value(nested, path=path + (folded,))
        return
    if isinstance(value, (list, tuple)):
        for nested in value:
            _scan_recovery_input_value(nested, path=path)
        return
    if isinstance(value, str) and _RECOVERY_INPUT_FORBIDDEN_VALUE_RE.search(value):
        raise ProviderControlError(
            "LLM recovery input contains a forbidden value",
            code="llm_recovery_input_forbidden",
        )
    if value is not None and not isinstance(value, (str, int, float, bool)):
        raise ProviderControlError(
            "LLM recovery input contains an unsupported value",
            code="llm_recovery_input_invalid",
        )


@dataclass(frozen=True, slots=True)
class LLMRecoveryInputV1:
    """Immutable canonical input retained for zero-network local recovery."""

    operation_id: str
    turn_id: str
    attempt_no: int
    input_version: str
    input_json: str
    input_hash: str

    @staticmethod
    def _identity(decoded: Mapping[str, object]) -> Mapping[str, object]:
        if set(decoded) != _RECOVERY_INPUT_TOP_LEVEL_KEYS:
            raise ProviderControlError(
                "LLM recovery input envelope is not closed",
                code="llm_recovery_input_invalid",
            )
        identity = decoded.get("identity")
        nested_input = decoded.get("input")
        if not isinstance(identity, Mapping) or not isinstance(nested_input, Mapping):
            raise ProviderControlError(
                "LLM recovery input envelope is invalid",
                code="llm_recovery_input_invalid",
            )
        if set(identity) != _RECOVERY_INPUT_IDENTITY_KEYS:
            raise ProviderControlError(
                "LLM recovery input identity is not closed",
                code="llm_recovery_input_identity_invalid",
            )
        return identity

    def identity(self) -> Mapping[str, object]:
        try:
            decoded = json.loads(
                self.input_json,
                object_pairs_hook=_recovery_input_no_duplicate_pairs,
                parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
            )
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ProviderControlError(
                "LLM recovery input JSON is invalid",
                code="llm_recovery_input_invalid",
            ) from exc
        if not isinstance(decoded, Mapping):
            raise ProviderControlError(
                "LLM recovery input envelope is invalid",
                code="llm_recovery_input_invalid",
            )
        return self._identity(decoded)

    def assert_stage_identity(
        self,
        stage: LLMAcceptedStageV1,
        operation: ProviderOperationV1 | None = None,
    ) -> None:
        """Bind the canonical envelope identity to its operation and stage."""

        identity = self.identity()
        expected = {
            "request_hash": stage.request_hash,
            "prompt_hash": stage.prompt_hash,
            "prompt_contract_version": stage.prompt_contract_version,
            "schema_hash": stage.schema_hash,
            "tokenizer_id": stage.tokenizer_id,
            "tokenizer_hash": stage.tokenizer_hash,
            "rule_set_hash": stage.rule_set_hash,
            "persona_spec_hash": stage.persona_spec_hash,
            "transcript_hash": stage.transcript_hash,
            "receipt_hash": stage.receipt_hash,
            "policy_hash": stage.policy_hash,
            "export_manifest_hash": stage.export_manifest_hash,
            "build_manifest_hash": stage.build_manifest_hash,
            "repair_policy_hash": stage.repair_policy_hash,
            "generation_fence": stage.generation_fence,
            "model_key": stage.model_key,
            "debate_id": operation.scope_id if operation is not None else identity.get("debate_id"),
            "turn_id": stage.turn_id,
            "attempt_no": stage.attempt_no,
        }
        if dict(identity) != expected:
            raise ProviderControlError(
                "LLM recovery input identity does not match accepted stage",
                code="llm_recovery_input_identity_mismatch",
            )

    def __post_init__(self) -> None:
        for value, name in (
            (self.operation_id, "LLM recovery operation id"),
            (self.turn_id, "LLM recovery turn id"),
        ):
            _safe_identifier(value, field_name=name)
        if (
            isinstance(self.attempt_no, bool)
            or not isinstance(self.attempt_no, int)
            or self.attempt_no not in {1, 2}
        ):
            raise ProviderControlError(
                "LLM recovery input attempt is invalid",
                code="llm_recovery_input_invalid",
            )
        if self.input_version != LLM_RECOVERY_INPUT_VERSION:
            raise ProviderControlError(
                "LLM recovery input version is unsupported",
                code="llm_recovery_input_version_invalid",
            )
        if not isinstance(self.input_json, str):
            raise ProviderControlError(
                "LLM recovery input JSON is invalid",
                code="llm_recovery_input_invalid",
            )
        try:
            raw = self.input_json.encode("utf-8")
        except UnicodeError as exc:
            raise ProviderControlError(
                "LLM recovery input JSON is invalid",
                code="llm_recovery_input_invalid",
            ) from exc
        if not raw:
            raise ProviderControlError(
                "LLM recovery input JSON is invalid",
                code="llm_recovery_input_invalid",
            )
        try:
            decoded = json.loads(
                self.input_json,
                object_pairs_hook=_recovery_input_no_duplicate_pairs,
                parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
            )
            canonical = canonical_json_bytes(decoded).decode("utf-8")
        except (TypeError, ValueError, UnicodeError) as exc:
            raise ProviderControlError(
                "LLM recovery input JSON is invalid",
                code="llm_recovery_input_invalid",
            ) from exc
        if not isinstance(decoded, Mapping) or canonical != self.input_json:
            raise ProviderControlError(
                "LLM recovery input JSON is not canonical",
                code="llm_recovery_input_canonical_invalid",
            )
        identity = self._identity(decoded)
        for key, identity_value in identity.items():
            if key.endswith("_hash"):
                if identity_value is None and key == "repair_policy_hash":
                    continue
                if not isinstance(identity_value, str):
                    raise ProviderControlError(
                        "LLM recovery identity hash is invalid",
                        code="llm_recovery_input_identity_invalid",
                    )
                _hash(identity_value, field_name="LLM recovery identity hash")
            elif key == "attempt_no":
                if (
                    isinstance(identity_value, bool)
                    or not isinstance(identity_value, int)
                    or identity_value not in {1, 2}
                ):
                    raise ProviderControlError(
                        "LLM recovery identity attempt is invalid",
                        code="llm_recovery_input_identity_invalid",
                    )
            elif key == "generation_fence":
                if not isinstance(identity_value, str):
                    raise ProviderControlError(
                        "LLM recovery identity fence is invalid",
                        code="llm_recovery_input_identity_invalid",
                    )
                if identity_value:
                    _safe_identifier(identity_value, field_name="LLM recovery identity fence")
            elif not isinstance(identity_value, str):
                raise ProviderControlError(
                    "LLM recovery identity value is invalid",
                    code="llm_recovery_input_identity_invalid",
                )
            elif not identity_value:
                raise ProviderControlError(
                    "LLM recovery identity value is invalid",
                    code="llm_recovery_input_identity_invalid",
                )
        _scan_recovery_input_value(decoded["input"], path=("input",))
        _hash(self.input_hash, field_name="LLM recovery input hash")
        if sha256_hex(raw) != self.input_hash:
            raise ProviderControlError(
                "LLM recovery input hash does not match canonical JSON",
                code="llm_recovery_input_hash_mismatch",
            )

    @property
    def hash(self) -> str:
        return self.input_hash

    @property
    def canonical_json(self) -> str:
        return self.input_json

    def as_record(self) -> dict[str, object]:
        return {
            "operation_id": self.operation_id,
            "turn_id": self.turn_id,
            "attempt_no": self.attempt_no,
            "input_version": self.input_version,
            "input_json": self.input_json,
            "input_hash": self.input_hash,
        }


@dataclass(frozen=True, slots=True)
class LLMAcceptedBundleV1:
    """The exact accepted stage and its canonical input recovery pair."""

    stage: LLMAcceptedStageV1
    recovery_input: LLMRecoveryInputV1

    @property
    def input(self) -> LLMRecoveryInputV1:
        return self.recovery_input

    def __iter__(self) -> Iterator[object]:
        yield self.stage
        yield self.recovery_input


LLMUsageLedgerV1 = LLMAcceptedStageV1
LlmAcceptedStageV1 = LLMAcceptedStageV1
LlmUsageLedgerV1 = LLMUsageLedgerV1
LLMAcceptedStage = LLMAcceptedStageV1
LLMUsageLedger = LLMUsageLedgerV1
LLMUsageV1 = LLMAcceptedStageV1
LlmAcceptedStage = LLMAcceptedStageV1
LlmUsageLedger = LLMUsageLedgerV1
LLMUsage = LLMAcceptedStageV1


@dataclass(frozen=True, slots=True)
class ProviderSuccessResultV1:
    status: Literal["succeeded"]
    operation: ProviderOperationV1
    response_hash: str


@dataclass(frozen=True, slots=True)
class ProviderNotSentResultV1:
    status: Literal["not_sent"]
    operation: ProviderOperationV1
    safe_error_code: str = "provider_not_sent"


@dataclass(frozen=True, slots=True)
class ProviderAcceptanceUnknownResultV1:
    """An uncertain attempt retained against the cap and never auto-retried."""

    status: Literal["acceptance_unknown"]
    operation: ProviderOperationV1
    safe_error_code: str = "acceptance_unknown"
    retry_allowed: Literal[False] = False

    @property
    def requires_reconciliation(self) -> bool:
        return True


@dataclass(frozen=True, slots=True)
class ProviderFailureResultV1:
    status: Literal["failed"]
    operation: ProviderOperationV1
    safe_error_code: str = "provider_failed"


ProviderCallResultV1 = (
    ProviderSuccessResultV1
    | ProviderNotSentResultV1
    | ProviderAcceptanceUnknownResultV1
    | ProviderFailureResultV1
)
AcceptanceUnknownResult = ProviderAcceptanceUnknownResultV1


class ProviderOperationRepository(Protocol):
    """Durable repository port; SQL implementation belongs to the main window."""

    def create_prepared(self, request: ProviderReservationRequestV1) -> ProviderOperationV1:
        """Insert one unique prepared operation."""

    def reserve(self, operation_id: str) -> ProviderReservationV1:
        """Atomically reserve scope count/max usage before network I/O."""

    def transition(
        self,
        operation_id: str,
        *,
        expected: OperationState,
        state: OperationState,
        safe_error_code: str | None = None,
        response_hash: str | None = None,
    ) -> ProviderOperationV1:
        """Compare-and-set a provider operation state."""

    def get(self, operation_id: str) -> ProviderOperationV1 | None:
        """Read one operation by opaque local ID."""

    def attach_acceptance_call(
        self,
        operation_id: str,
        *,
        acceptance_run_id: str,
        call_no: int,
    ) -> ProviderOperationV1:
        """Atomically bind one pre-send operation to a Demo call ordinal."""

    def mark_not_sent(
        self, operation_id: str, *, safe_error_code: str = "provider_not_sent"
    ) -> ProviderOperationV1:
        """Release allowance only after no supplier acceptance is proven."""

    def mark_acceptance_unknown(
        self, operation_id: str, *, safe_error_code: str = "acceptance_unknown"
    ) -> ProviderOperationV1:
        """Retain allowance and require reconciliation; never auto-retry."""

    def mark_accepted(self, operation_id: str, *, response_hash: str) -> ProviderOperationV1:
        """Stage the sanitized accepted response before validation/publication."""

    def stage_llm_accepted(self, stage: LLMAcceptedStageV1) -> LLMAcceptedStageV1:
        """Persist one immutable accepted LLM stage before local validation."""

    def get_llm_accepted_stage(self, operation_id: str) -> LLMAcceptedStageV1 | None:
        """Read the immutable accepted LLM stage for local recovery."""

    def stage_llm_accepted_with_recovery(
        self,
        stage: LLMAcceptedStageV1,
        recovery_input: LLMRecoveryInputV1,
    ) -> LLMAcceptedStageV1:
        """Persist an accepted stage and canonical input atomically."""

    def stage_segment_accepted_with_recovery(
        self,
        stage: LLMAcceptedStageV1,
        recovery_input: object,
    ) -> LLMAcceptedStageV1:
        """Persist the explicit v2 segment stage/input pair atomically."""

    def load_llm_accepted_bundle(
        self,
        operation_id: str,
    ) -> object | None:
        """Load an exact stage/input pair, or no recoverable bundle."""

    def mark_succeeded(self, operation_id: str) -> ProviderOperationV1:
        """Commit the final success and usage ledger atomically in production."""

    def mark_failed(
        self, operation_id: str, *, safe_error_code: str = "provider_failed"
    ) -> ProviderOperationV1:
        """Record a terminal validation/provider failure."""

    def recover_startup(self) -> tuple[ProviderOperationV1, ...]:
        """Recover stranded operations without issuing a request."""


def can_transition(current: OperationState, target: OperationState) -> bool:
    allowed: dict[OperationState, frozenset[OperationState]] = {
        "prepared": frozenset({"reserved", "failed", "not_sent"}),
        "reserved": frozenset({"sending", "not_sent"}),
        "sending": frozenset({"accepted", "not_sent", "acceptance_unknown", "failed"}),
        "accepted": frozenset({"succeeded", "failed", "acceptance_unknown", "not_sent"}),
        "succeeded": frozenset(),
        # A local failure or a proven not_sent can be prepared again. The
        # supplier reply was not stored, so the same attempt is sent again.
        "not_sent": frozenset({"prepared"}),
        "acceptance_unknown": frozenset({"accepted", "not_sent", "abandoned", "failed"}),
        "failed": frozenset({"prepared", "accepted", "abandoned"}),
        "abandoned": frozenset(),
    }
    return target in allowed[current]


def startup_recovery_state(
    state: OperationState, *, staged_response_complete: bool = False
) -> OperationState:
    """Return the only safe startup recovery target for one operation."""

    if state == "reserved":
        return "not_sent"
    if state == "sending":
        return "acceptance_unknown"
    if state == "accepted" and not staged_response_complete:
        return "acceptance_unknown"
    return state


def safe_provider_error_code(error: object) -> str:
    """Classify an exception without returning its message or supplier body."""

    if isinstance(error, ProviderNotSentError):
        return "provider_not_sent"
    if isinstance(error, ProviderAcceptanceUnknownError):
        return "acceptance_unknown"
    if isinstance(error, TimeoutError):
        return "acceptance_unknown"
    if isinstance(error, ConnectionError):
        return "acceptance_unknown"
    if isinstance(error, ProviderControlError):
        return error.code if _SAFE_CODE_RE.fullmatch(error.code) else "provider_control_invalid"
    return "provider_failed"


def _safe_code(value: str | None, default: str = "provider_failed") -> str:
    if value is None or not _SAFE_CODE_RE.fullmatch(value):
        return default
    return value


class InMemoryProviderOperationRepository(ProviderOperationRepository):
    """Thread-safe local ledger used by deterministic control tests only."""

    _RESERVED_STATES = frozenset(
        {"reserved", "sending", "accepted", "succeeded", "acceptance_unknown"}
    )

    def __init__(
        self,
        *,
        default_budget: ProviderScopeBudgetV1 | None = None,
        scope_budgets: Mapping[object, ProviderScopeBudgetV1] | None = None,
    ) -> None:
        self.default_budget = default_budget or ProviderScopeBudgetV1()
        self._scope_budgets = dict(scope_budgets or {})
        self._operations: dict[str, ProviderOperationV1] = {}
        self._reservations: dict[str, ProviderReservationV1] = {}
        self._llm_stages: dict[str, LLMAcceptedStageV1] = {}
        self._llm_recovery_inputs: dict[str, LLMRecoveryInputV1] = {}
        self._segment_recovery_inputs: dict[str, object] = {}
        self._by_key: dict[tuple[str, str, str, int], str] = {}
        self._acceptance_calls: dict[tuple[str, int], str] = {}
        self._lock = RLock()

    def _budget(self, scope_id: str, budget_bucket: str) -> ProviderScopeBudgetV1:
        value = self._scope_budgets.get((scope_id, budget_bucket))
        if value is None:
            # Accept the pre-0014 string key only as an in-memory compatibility
            # path.  Durable SQL always requires an explicit composite key.
            value = self._scope_budgets.get(scope_id)
        return value or self.default_budget

    def create_prepared(self, request: ProviderReservationRequestV1) -> ProviderOperationV1:
        with self._lock:
            if request.idempotency_key in self._by_key:
                raise DuplicateOperation("provider attempt already exists")
            operation = ProviderOperationV1(
                id=request.operation_id or str(uuid4()),
                scope_id=request.scope_id,
                provider_operation=request.provider_operation,
                logical_item_id=request.logical_item_id,
                attempt_no=request.attempt_no,
                request_hash=request.request_hash,
                max_tokens=request.max_tokens,
                max_cost_cny=float(request.max_cost_cny),
                policy_hash=request.policy_hash,
                export_manifest_hash=request.export_manifest_hash,
                build_manifest_hash=request.build_manifest_hash,
                model_key=request.model_key,
            )
            self._operations[operation.id] = operation
            self._by_key[operation.idempotency_key] = operation.id
            return operation

    def attach_acceptance_call(
        self,
        operation_id: str,
        *,
        acceptance_run_id: str,
        call_no: int,
    ) -> ProviderOperationV1:
        validate_demo_acceptance_call_no(call_no)
        if not acceptance_run_id:
            raise ProviderControlError(
                "Demo acceptance run is required",
                code="acceptance_run_invalid",
            )
        with self._lock:
            operation = self.operation(operation_id)
            if operation.acceptance_run_id is not None or operation.call_no is not None:
                raise OperationStateError("provider operation already has an acceptance call")
            if operation.state != "prepared" or operation.request_count != 0:
                raise OperationStateError("provider operation is no longer pre-send")
            if operation.charged_request_count != 0:
                raise OperationStateError("provider operation has already been charged")
            if (acceptance_run_id, call_no) in self._acceptance_calls:
                raise OperationStateError("Demo acceptance call ordinal is already bound")
            updated = replace(
                operation,
                acceptance_run_id=acceptance_run_id,
                call_no=call_no,
            )
            self._operations[operation_id] = updated
            self._acceptance_calls[(acceptance_run_id, call_no)] = operation_id
            return updated

    def create(self, request: ProviderReservationRequestV1) -> ProviderOperationV1:
        return self.create_prepared(request)

    def get(self, operation_id: str) -> ProviderOperationV1 | None:
        with self._lock:
            return self._operations.get(operation_id)

    def operation(self, operation_id: str) -> ProviderOperationV1:
        operation = self.get(operation_id)
        if operation is None:
            raise OperationStateError("provider operation does not exist")
        return operation

    def _scope_totals(self, scope_id: str, budget_bucket: str) -> tuple[int, int, float]:
        rows = [
            operation
            for operation in self._operations.values()
            if operation.scope_id == scope_id
            and operation.budget_bucket == budget_bucket
            and (
                operation.state in self._RESERVED_STATES
                or operation.state == "failed"
                and operation.reservation_id is not None
                or operation.state == "abandoned"
                and operation.reservation_id is not None
            )
        ]
        return (
            len(rows),
            sum(row.max_tokens for row in rows),
            sum(row.max_cost_cny for row in rows),
        )

    def reserve(self, operation_id: str) -> ProviderReservationV1:
        with self._lock:
            current = self.operation(operation_id)
            if current.state != "prepared":
                raise OperationStateError("provider operation is not reservable")
            reservation = ProviderReservationV1(
                id=str(uuid4()),
                operation_id=current.id,
                scope_id=current.scope_id,
                provider_operation=current.provider_operation,
                logical_item_id=current.logical_item_id,
                attempt_no=current.attempt_no,
                max_tokens=current.max_tokens,
                max_cost_cny=current.max_cost_cny,
                state="reserved",
            )
            self._reservations[reservation.id] = reservation
            self._operations[current.id] = replace(
                current,
                state="reserved",
                reservation_id=reservation.id,
                request_count=current.request_count + 1,
                charged_request_count=current.charged_request_count + 1,
            )
            return reservation

    def reservation(self, operation_id: str) -> ProviderReservationV1:
        operation = self.operation(operation_id)
        if operation.reservation_id is None:
            raise OperationStateError("provider operation has no reservation")
        try:
            return self._reservations[operation.reservation_id]
        except KeyError as exc:
            raise OperationStateError("provider reservation is missing") from exc

    def _set_reservation_state(self, operation_id: str, state: ReservationState) -> None:
        reservation = self.reservation(operation_id)
        self._reservations[reservation.id] = replace(reservation, state=state)

    def transition(
        self,
        operation_id: str,
        *,
        expected: OperationState,
        state: OperationState,
        safe_error_code: str | None = None,
        response_hash: str | None = None,
    ) -> ProviderOperationV1:
        with self._lock:
            current = self.operation(operation_id)
            if current.state != expected:
                raise OperationStateError("provider operation CAS fence failed")
            if not can_transition(expected, state):
                raise OperationStateError(
                    f"invalid provider operation transition: {expected}->{state}"
                )
            if response_hash is not None:
                _hash(response_hash, field_name="staged response hash")
            updated = replace(
                current,
                state=state,
                safe_error_code=(
                    _safe_code(safe_error_code) if safe_error_code else current.safe_error_code
                ),
                staged_response_hash=response_hash or current.staged_response_hash,
            )
            self._operations[operation_id] = updated
            if current.reservation_id is not None:
                self._set_reservation_state(operation_id, state)
            return updated

    def mark_not_sent(
        self, operation_id: str, *, safe_error_code: str = "provider_not_sent"
    ) -> ProviderOperationV1:
        operation = self.operation(operation_id)
        return self.transition(
            operation_id,
            expected=operation.state,
            state="not_sent",
            safe_error_code=safe_error_code,
        )

    def mark_acceptance_unknown(
        self,
        operation_id: str,
        *,
        safe_error_code: str = "acceptance_unknown",
    ) -> ProviderOperationV1:
        operation = self.operation(operation_id)
        return self.transition(
            operation_id,
            expected=operation.state,
            state="acceptance_unknown",
            safe_error_code=safe_error_code,
        )

    def mark_accepted(self, operation_id: str, *, response_hash: str) -> ProviderOperationV1:
        operation = self.operation(operation_id)
        return self.transition(
            operation_id,
            expected=operation.state,
            state="accepted",
            response_hash=response_hash,
        )

    def stage_llm_accepted(self, stage: LLMAcceptedStageV1) -> LLMAcceptedStageV1:
        """Persist an accepted LLM stage and advance the operation atomically."""

        stage.__post_init__()
        with self._lock:
            operation = self.operation(stage.operation_id)
            if operation.provider_operation != "llm_debate_turn":
                raise OperationStateError("LLM stage operation type is invalid")
            if (
                operation.logical_item_id != stage.turn_id
                or operation.attempt_no != stage.attempt_no
                or operation.request_hash != stage.request_hash
                or operation.policy_hash != stage.policy_hash
                or operation.export_manifest_hash != stage.export_manifest_hash
                or operation.model_key != stage.model_key
            ):
                raise OperationStateError("LLM accepted stage does not match operation")
            existing = self._llm_stages.get(stage.operation_id)
            if existing is not None:
                if existing != stage:
                    raise OperationStateError("LLM accepted stage is immutable")
                return existing
            if operation.state not in {"sending", "accepted"}:
                raise OperationStateError("LLM accepted stage requires an accepted response")
            self._llm_stages[stage.operation_id] = stage
            if operation.state == "sending":
                self.mark_accepted(operation.id, response_hash=stage.output_hash)
            return stage

    def stage_segment_accepted_with_recovery(
        self,
        stage: LLMAcceptedStageV1,
        recovery_input: object,
    ) -> LLMAcceptedStageV1:
        """Persist one explicit v2 frozen request beside its accepted stage."""

        from app.providers.llm_segments import SegmentRecoveryInputV2

        if not isinstance(recovery_input, SegmentRecoveryInputV2):
            raise OperationStateError("segment recovery input has the wrong version")
        stage.__post_init__()
        recovery_input.__post_init__()
        if (
            recovery_input.operation_id != stage.operation_id
            or recovery_input.turn_id != stage.turn_id
            or recovery_input.attempt_no != stage.attempt_no
        ):
            raise OperationStateError("segment recovery input does not match stage")
        with self._lock:
            operation = self.operation(stage.operation_id)
            if operation.provider_operation != "llm_debate_turn":
                raise OperationStateError("LLM stage operation type is invalid")
            try:
                recovery_input.assert_stage_identity(stage, operation)
            except Exception as exc:
                raise OperationStateError("segment recovery input identity is corrupt") from exc
            existing_stage = self._llm_stages.get(stage.operation_id)
            existing_input = self._segment_recovery_inputs.get(stage.operation_id)
            if existing_stage is not None or existing_input is not None:
                if existing_stage != stage or existing_input != recovery_input:
                    raise OperationStateError("LLM accepted bundle is immutable")
                if operation.state not in {"accepted", "succeeded"}:
                    raise OperationStateError("LLM accepted bundle operation state is invalid")
                if existing_stage is None:
                    raise OperationStateError("LLM accepted bundle is partial")
                return existing_stage
            if operation.state not in {"sending", "accepted"}:
                raise OperationStateError("LLM accepted bundle requires an accepted response")
            if (
                operation.logical_item_id != stage.turn_id
                or operation.attempt_no != stage.attempt_no
                or operation.request_hash != stage.request_hash
                or operation.policy_hash != stage.policy_hash
                or operation.export_manifest_hash != stage.export_manifest_hash
                or operation.model_key != stage.model_key
            ):
                raise OperationStateError("LLM accepted stage does not match operation")
            if (
                operation.state == "accepted"
                and operation.staged_response_hash != stage.output_hash
            ):
                raise OperationStateError("LLM accepted stage response hash is stale")
            self._segment_recovery_inputs[recovery_input.operation_id] = recovery_input
            self._llm_stages[stage.operation_id] = stage
            if operation.state == "sending":
                self.mark_accepted(operation.id, response_hash=stage.output_hash)
            return stage

    def stage_llm_accepted_with_recovery(
        self,
        stage: LLMAcceptedStageV1,
        recovery_input: LLMRecoveryInputV1,
    ) -> LLMAcceptedStageV1:
        """Persist an accepted stage and its canonical input atomically."""

        stage.__post_init__()
        recovery_input.__post_init__()
        if recovery_input.operation_id != stage.operation_id:
            raise OperationStateError("LLM recovery input does not match operation")
        if recovery_input.turn_id != stage.turn_id or recovery_input.attempt_no != stage.attempt_no:
            raise OperationStateError("LLM recovery input does not match stage")
        with self._lock:
            operation = self.operation(stage.operation_id)
            if operation.provider_operation != "llm_debate_turn":
                raise OperationStateError("LLM stage operation type is invalid")
            recovery_input.assert_stage_identity(stage, operation)
            existing_stage = self._llm_stages.get(stage.operation_id)
            existing_input = self._llm_recovery_inputs.get(stage.operation_id)
            if existing_stage is not None or existing_input is not None:
                if existing_stage != stage or existing_input != recovery_input:
                    raise OperationStateError("LLM accepted bundle is immutable")
                if operation.state not in {"accepted", "succeeded"}:
                    raise OperationStateError("LLM accepted bundle operation state is invalid")
                if existing_stage is None:
                    raise OperationStateError("LLM accepted bundle is partial")
                return existing_stage
            if operation.state not in {"sending", "accepted"}:
                raise OperationStateError("LLM accepted bundle requires an accepted response")
            if (
                operation.logical_item_id != stage.turn_id
                or operation.attempt_no != stage.attempt_no
                or operation.request_hash != stage.request_hash
                or operation.policy_hash != stage.policy_hash
                or operation.export_manifest_hash != stage.export_manifest_hash
                or operation.model_key != stage.model_key
            ):
                raise OperationStateError("LLM accepted stage does not match operation")
            if (
                operation.state == "accepted"
                and operation.staged_response_hash != stage.output_hash
            ):
                raise OperationStateError("LLM accepted stage response hash is stale")
            self._llm_recovery_inputs[recovery_input.operation_id] = recovery_input
            self._llm_stages[stage.operation_id] = stage
            if operation.state == "sending":
                self.mark_accepted(operation.id, response_hash=stage.output_hash)
            return stage

    def load_llm_accepted_bundle(
        self,
        operation_id: str,
    ) -> object | None:
        with self._lock:
            stage = self._llm_stages.get(operation_id)
            segment_input = self._segment_recovery_inputs.get(operation_id)
            recovery_input = self._llm_recovery_inputs.get(operation_id)
            if stage is None and recovery_input is None and segment_input is None:
                return None
            if stage is None:
                raise OperationStateError("LLM recovery input has no accepted stage")
            if segment_input is not None:
                from app.providers.llm_segments import (
                    SegmentAcceptedBundleV2,
                    SegmentRecoveryInputV2,
                )

                if not isinstance(segment_input, SegmentRecoveryInputV2):
                    raise OperationStateError("LLM accepted bundle has the wrong version")
                operation = self._operations.get(operation_id)
                if operation is None:
                    raise OperationStateError("LLM accepted bundle operation does not exist")
                try:
                    segment_input.__post_init__()
                    segment_input.assert_stage_identity(stage, operation)
                except Exception as exc:
                    raise OperationStateError("LLM accepted bundle identity is corrupt") from exc
                if operation.state not in {"accepted", "succeeded"}:
                    raise OperationStateError("LLM accepted bundle operation state is invalid")
                return SegmentAcceptedBundleV2(stage=stage, recovery_input=segment_input)
            # A stage without an input is a pre-0015 accepted row: keep the
            # old stage readable, but never present it as recoverable input.
            if recovery_input is None:
                return None
            operation = self._operations.get(operation_id)
            if operation is None:
                raise OperationStateError("LLM accepted bundle operation does not exist")
            if (
                recovery_input.operation_id != stage.operation_id
                or recovery_input.turn_id != stage.turn_id
                or recovery_input.attempt_no != stage.attempt_no
            ):
                raise OperationStateError("LLM accepted bundle identity is corrupt")
            try:
                recovery_input.__post_init__()
                recovery_input.assert_stage_identity(stage, operation)
            except ProviderControlError as exc:
                raise OperationStateError("LLM accepted bundle identity is corrupt") from exc
            if operation.state not in {"accepted", "succeeded"}:
                raise OperationStateError("LLM accepted bundle operation state is invalid")
            return LLMAcceptedBundleV1(stage=stage, recovery_input=recovery_input)

    save_llm_accepted_stage = stage_llm_accepted

    def get_llm_accepted_stage(self, operation_id: str) -> LLMAcceptedStageV1 | None:
        with self._lock:
            return self._llm_stages.get(operation_id)

    def mark_succeeded(self, operation_id: str) -> ProviderOperationV1:
        operation = self.operation(operation_id)
        if (
            operation.provider_operation == "llm_debate_turn"
            and operation.id not in self._llm_stages
        ):
            raise OperationStateError("LLM operation has no accepted stage")
        return self.transition(operation_id, expected=operation.state, state="succeeded")

    def mark_failed(
        self, operation_id: str, *, safe_error_code: str = "provider_failed"
    ) -> ProviderOperationV1:
        operation = self.operation(operation_id)
        return self.transition(
            operation_id,
            expected=operation.state,
            state="failed",
            safe_error_code=safe_error_code,
        )

    def abandon(self, operation_id: str) -> ProviderOperationV1:
        operation = self.operation(operation_id)
        return self.transition(operation_id, expected=operation.state, state="abandoned")

    def recover_one(
        self,
        operation_id: str,
        *,
        staged_response_complete: bool = False,
    ) -> ProviderOperationV1:
        operation = self.operation(operation_id)
        legacy_accepted_stage = False
        if operation.provider_operation == "llm_debate_turn":
            legacy_stage = self._llm_stages.get(operation_id)
            legacy_accepted_stage = (
                operation.state == "accepted"
                and legacy_stage is not None
                and operation_id not in self._llm_recovery_inputs
            )
            if legacy_accepted_stage and legacy_stage is not None:
                try:
                    legacy_stage.__post_init__()
                except ProviderControlError:
                    legacy_accepted_stage = False
            try:
                staged_response_complete = self.load_llm_accepted_bundle(operation_id) is not None
            except OperationStateError:
                staged_response_complete = False
            if legacy_accepted_stage:
                # 0014 accepted rows are authoritative output stages, but
                # cannot be resumed without the additive 0015 input.  Keep
                # their acceptance state and let callers surface the blocked
                # recovery explicitly instead of relabeling it uncertain.
                return operation
        target = startup_recovery_state(
            operation.state,
            staged_response_complete=staged_response_complete,
        )
        if target == operation.state:
            return operation
        if target == "not_sent":
            return self.mark_not_sent(operation_id, safe_error_code="recovered_not_sent")
        return self.mark_acceptance_unknown(
            operation_id,
            safe_error_code="recovered_acceptance_unknown",
        )

    def recover_startup(self) -> tuple[ProviderOperationV1, ...]:
        with self._lock:
            ids = tuple(
                operation.id
                for operation in self._operations.values()
                if operation.state in {"reserved", "sending", "accepted"}
            )
            return tuple(self.recover_one(operation_id) for operation_id in ids)

    def recover_llm_startup(self) -> tuple[ProviderOperationV1, ...]:
        with self._lock:
            ids = tuple(
                operation.id
                for operation in self._operations.values()
                if operation.provider_operation == "llm_debate_turn"
                and operation.state in {"reserved", "sending", "accepted"}
            )
            return tuple(self.recover_one(operation_id) for operation_id in ids)

    def operations(self, *, scope_id: str | None = None) -> tuple[ProviderOperationV1, ...]:
        with self._lock:
            values = tuple(self._operations.values())
            if scope_id is None:
                return values
            return tuple(operation for operation in values if operation.scope_id == scope_id)


def execute_provider_call(
    request: ProviderReservationRequestV1,
    repository: ProviderOperationRepository,
    call: Callable[[], object],
    *,
    response_validator: Callable[[object], object] | None = None,
) -> ProviderCallResultV1:
    """Run one fake/injected call through reservation and uncertainty states.

    The SQL implementation can mirror this sequencing: create/commit
    ``prepared``, atomically reserve/commit ``reserved``, commit ``sending``
    immediately before the adapter, stage/mark ``accepted`` before validation,
    then commit ``succeeded`` or ``failed``.
    """

    operation = repository.create_prepared(request)
    try:
        repository.reserve(operation.id)
        repository.transition(operation.id, expected="reserved", state="sending")
    except OperationStateError:
        failed = repository.mark_failed(operation.id, safe_error_code="provider_reservation_failed")
        return ProviderFailureResultV1("failed", failed, "provider_reservation_failed")
    try:
        response = call()
    except ProviderNotSentError:
        not_sent = repository.mark_not_sent(operation.id)
        return ProviderNotSentResultV1("not_sent", not_sent)
    except (ProviderAcceptanceUnknownError, TimeoutError, ConnectionError):
        unknown = repository.mark_acceptance_unknown(operation.id)
        return ProviderAcceptanceUnknownResultV1("acceptance_unknown", unknown)
    except Exception as error:
        failed = repository.mark_failed(
            operation.id, safe_error_code=safe_provider_error_code(error)
        )
        return ProviderFailureResultV1("failed", failed, safe_provider_error_code(error))
    try:
        response_hash = sha256_hex(canonical_json_bytes(response))
    except ProviderControlError:
        unknown = repository.mark_acceptance_unknown(
            operation.id,
            safe_error_code="provider_response_staging_unknown",
        )
        return ProviderAcceptanceUnknownResultV1(
            "acceptance_unknown", unknown, "provider_response_staging_unknown"
        )
    try:
        repository.mark_accepted(operation.id, response_hash=response_hash)
    except (ProviderControlError, OperationStateError):
        failed = repository.mark_failed(operation.id, safe_error_code="provider_response_invalid")
        return ProviderFailureResultV1("failed", failed, "provider_response_invalid")
    if response_validator is not None:
        try:
            response_validator(response)
        except Exception as error:
            failed = repository.mark_failed(
                operation.id,
                safe_error_code=safe_provider_error_code(error),
            )
            return ProviderFailureResultV1("failed", failed, safe_provider_error_code(error))
    succeeded = repository.mark_succeeded(operation.id)
    return ProviderSuccessResultV1("succeeded", succeeded, response_hash)


# Descriptive aliases for the main integration window.
ProviderOperation = ProviderOperationV1
ProviderDataCallV1 = ProviderOperationV1
ProviderDataCall = ProviderDataCallV1
ProviderDataCallState = OperationState
ProviderReservation = ProviderReservationV1
ProviderReservationRequest = ProviderReservationRequestV1
ProviderPolicySnapshot = ProviderPolicySnapshotV1
ExportManifest = ExportManifestV1
ProviderRepository = ProviderOperationRepository
ProviderOperationRepositoryPort = ProviderOperationRepository


__all__ = [
    "ALLOWED_ACCOUNT_PRODUCTS",
    "AcceptanceUnknownResult",
    "BUDGET_BUCKETS",
    "EMBEDDING_QUERY_BUCKET",
    "EMBEDDING_SNAPSHOT_BUCKET",
    "LLM_BARRAGE_INSIGHT_BUCKET",
    "LLM_DEBATE_TURN_BUCKET",
    "LLM_MAYA_REPORT_BUCKET",
    "LLM_RECOVERY_INPUT_BYTES_LIMIT",
    "LLM_RECOVERY_INPUT_VERSION",
    "LLM_TURN_OUTPUT_SCHEMA_HASH",
    "LLMAcceptedBundleV1",
    "LLMAcceptedStage",
    "LLMAcceptedStageV1",
    "LLMRecoveryInputV1",
    "LLMUsageLedger",
    "LLMUsageLedgerV1",
    "LLMUsageV1",
    "LLMUsage",
    "LlmAcceptedStage",
    "LlmUsageLedger",
    "BudgetExceeded",
    "DuplicateOperation",
    "ExportConfirmationV1",
    "ExportFieldV1",
    "ExportManifest",
    "ExportManifestError",
    "ExportManifestV1",
    "FIXED_MODELS",
    "FIXED_REGION",
    "InMemoryProviderOperationRepository",
    "OperationState",
    "OperationStateError",
    "PolicyValidationError",
    "DEMO_UNREVIEWED_POLICY_PREFIX",
    "PROVIDER_DATA_CALL_VERSION",
    "ProviderAcceptanceUnknownError",
    "ProviderAcceptanceUnknownResultV1",
    "ProviderCallResultV1",
    "ProviderControlError",
    "ProviderDataCall",
    "ProviderDataCallState",
    "ProviderDataCallV1",
    "ProviderFailureResultV1",
    "ProviderNotSentError",
    "ProviderNotSentResultV1",
    "ProviderOperation",
    "ProviderOperationRepository",
    "ProviderOperationRepositoryPort",
    "ProviderOperationV1",
    "ProviderPolicySnapshot",
    "ProviderPolicySnapshotV1",
    "ProviderPreflightV1",
    "ProviderRepository",
    "ProviderReservation",
    "ProviderReservationRequest",
    "ProviderReservationRequestV1",
    "ProviderReservationV1",
    "ProviderScopeBudgetV1",
    "ProviderSuccessResultV1",
    "PROVIDER_BUDGET_BUCKETS",
    "REPAIR_FEEDBACK_POLICY_HASH",
    "REPAIR_FEEDBACK_V2_HASH",
    "REPAIR_FEEDBACK_V2_VERSION",
    "REPAIR_FEEDBACK_POLICIES",
    "REPAIR_FEEDBACK_POLICY_VERSION",
    "ReservationState",
    "TTS_SYNTHESIS_BUCKET",
    "VOICE_ENROLLMENT_BUCKET",
    "budget_bucket_for_operation",
    "canonical_json_bytes",
    "can_transition",
    "confirm_export_manifest",
    "execute_provider_call",
    "safe_provider_error_code",
    "sha256_hex",
    "startup_recovery_state",
    "validate_export_manifest",
    "validate_budget_bucket",
    "validate_policy_snapshot",
    "validate_provider_preflight",
]
