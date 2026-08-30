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
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from threading import RLock
from types import MappingProxyType
from typing import Literal, Protocol
from urllib.parse import urlsplit
from uuid import uuid4

PROVIDER_DATA_CALL_VERSION = "ProviderDataCallV1"
FIXED_REGION = "cn-beijing"
FIXED_MODELS: Mapping[str, str] = MappingProxyType(
    {
        "embedding": "text-embedding-v4",
        "embedding_query": "text-embedding-v4",
        "llm_debate": "qwen3.7-plus-2026-05-26",
        "tts": "qwen3-tts-vc-2026-01-22",
        "voice_enrollment": "qwen-voice-enrollment",
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
        "current_tts_speech",
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

    def __post_init__(self) -> None:
        _safe_identifier(self.scope_id, field_name="export scope")
        _safe_identifier(self.provider_operation, field_name="provider operation")
        _safe_identifier(self.model_key, field_name="export model")
        _hash(self.policy_hash, field_name="export policy hash")
        _hash(self.build_manifest_hash, field_name="export build hash")
        _hash(self.persona_spec_hash, field_name="export PersonaSpec hash")
        if self.operation_revision < 1:
            raise ExportManifestError("export revision is invalid", code="export_revision_invalid")
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
        return {
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

    if region != FIXED_REGION or policy.region != region:
        raise PolicyValidationError(
            "provider region is not authorized", code="policy_region_invalid"
        )
    expected_model = FIXED_MODELS.get(provider_operation)
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
        }


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
        }


@dataclass(frozen=True, slots=True)
class ProviderScopeBudgetV1:
    """Atomic cap for one debate/snapshot/report/TTS scope."""

    max_requests: int = 20
    max_total_tokens: int = 120_000
    max_cost_cny: float = 0.10

    def __post_init__(self) -> None:
        if self.max_requests < 1 or self.max_total_tokens < 0:
            raise ProviderControlError("scope budget counts are invalid")
        try:
            amount = Decimal(str(self.max_cost_cny))
        except (InvalidOperation, ValueError) as exc:
            raise ProviderControlError("scope budget cost is invalid") from exc
        if not amount.is_finite() or amount < 0:
            raise ProviderControlError("scope budget cost is invalid")


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
        "not_sent": frozenset(),
        "acceptance_unknown": frozenset({"accepted", "not_sent", "abandoned", "failed"}),
        "failed": frozenset({"abandoned"}),
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
        scope_budgets: Mapping[str, ProviderScopeBudgetV1] | None = None,
    ) -> None:
        self.default_budget = default_budget or ProviderScopeBudgetV1()
        self._scope_budgets = dict(scope_budgets or {})
        self._operations: dict[str, ProviderOperationV1] = {}
        self._reservations: dict[str, ProviderReservationV1] = {}
        self._by_key: dict[tuple[str, str, str, int], str] = {}
        self._lock = RLock()

    def _budget(self, scope_id: str) -> ProviderScopeBudgetV1:
        return self._scope_budgets.get(scope_id, self.default_budget)

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

    def _scope_totals(self, scope_id: str) -> tuple[int, int, float]:
        rows = [
            operation
            for operation in self._operations.values()
            if operation.scope_id == scope_id
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
            budget = self._budget(current.scope_id)
            requests, tokens, cost = self._scope_totals(current.scope_id)
            if (
                requests + 1 > budget.max_requests
                or tokens + current.max_tokens > budget.max_total_tokens
                or cost + current.max_cost_cny > budget.max_cost_cny + 1e-12
            ):
                raise BudgetExceeded("provider scope allowance exceeded")
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

    def mark_succeeded(self, operation_id: str) -> ProviderOperationV1:
        operation = self.operation(operation_id)
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
    "ReservationState",
    "canonical_json_bytes",
    "can_transition",
    "confirm_export_manifest",
    "execute_provider_call",
    "safe_provider_error_code",
    "sha256_hex",
    "startup_recovery_state",
    "validate_export_manifest",
    "validate_policy_snapshot",
    "validate_provider_preflight",
]
