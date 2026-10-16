"""Fixed-provider adapter primitives for the explicit ``segments_v2`` turn.

This is a sibling of the legacy v1 adapter.  It shares only provider ports
(transport, tokenizer, price card and outbound privacy scanning); it never
converts a paragraph result into the old claim/position DTO.  The caller keeps
the immutable :class:`SegmentInputSnapshot` beside every request so recovery
can validate the accepted output without retrieving again.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Literal, cast

import httpx

from app.core.errors import PlatformError
from app.modules.debates.generation.prompt_budget import (
    PromptBudgetError,
    preflight_prompt_budget,
)
from app.modules.debates.generation.segments import (
    SegmentInputSnapshot,
    SegmentProtocolError,
    SegmentTurnResult,
    build_segment_system_prompt,
    parse_segment_output_json,
    validate_segment_output,
)
from app.providers.llm_adapter import LLMAdapterError, LLMUsageV1
from app.providers.llm_price_card import (
    LLM_INPUT_TOKEN_CAP,
    LLM_MODEL_KEY,
    LLM_REQUEST_BYTES_CAP,
    LLM_REQUESTED_OUTPUT_TOKEN_CAP,
)
from app.providers.llm_privacy import (
    LLM_ANONYMOUS_BARRAGE_FIELD_CLASS,
    LLM_SESSION_DISCUSSION_MEMORY_FIELD_CLASS,
    LLMOutboundManifestV1,
    LLMOutboundPrivacyError,
    scan_segment_outbound_messages,
)
from app.providers.llm_tokenizer import (
    ConservativeLLMTokenizer,
    LLMTokenizerError,
    LLMTokenizerPort,
    tokenizer_asset_hash_valid,
)
from app.providers.llm_transport import (
    HttpxLLMTransport,
    LLMAcceptanceUnknown,
    LLMTransport,
    LLMTransportError,
    LLMTransportNotSent,
)

SEGMENT_PROTOCOL: Literal["segments_v2"] = "segments_v2"
SEGMENT_PROMPT_VERSION = "segment_prompt_v2"
FOUR_ROUND_SEGMENT_PROMPT_VERSION = "segment_prompt_four_round_v1"
SEGMENT_OUTPUT_SCHEMA_ID = "maya_llm_turn_output_v2"
SEGMENT_OPERATION = "llm_debate_turn"
SEGMENT_ENDPOINT_PATH = "/compatible-mode/v1/chat/completions"
SEGMENT_RECOVERY_INPUT_VERSION = "segment_recovery_input_v2"
SEGMENT_RECOVERY_INPUT_BYTES_LIMIT = 256 * 1024

# The schema is optional-field compatible: old frozen requests retain their
# persisted schema hash and remain readable during recovery, while new
# requests bind this updated wire schema hash. Git may check this text file out
# with CRLF on Windows, so the pin covers LF-canonical bytes.
SEGMENT_SCHEMA_SHA256 = "aca03345f91e4e34c07fa9bbdc02020131bafc972778fc4cc3dd67a2ca52a26b"


def segment_prompt_version(snapshot: SegmentInputSnapshot) -> str:
    return (
        FOUR_ROUND_SEGMENT_PROMPT_VERSION
        if getattr(snapshot, "discussion_json", None) is not None
        else SEGMENT_PROMPT_VERSION
    )


def _schema_candidates() -> tuple[Path, Path]:
    module = Path(__file__).resolve()
    relative = "contracts/llm-turn-output.v2.schema.json"
    return module.parents[3] / relative, module.parents[2] / relative


def _schema_bytes() -> bytes:
    try:
        candidate = next(path for path in _schema_candidates() if path.is_file())
        raw = candidate.read_bytes().replace(b"\r\n", b"\n")
    except (OSError, StopIteration) as exc:
        raise LLMAdapterError(code="llm_schema_invalid") from exc
    if hashlib.sha256(raw).hexdigest() != SEGMENT_SCHEMA_SHA256:
        raise LLMAdapterError(code="llm_schema_invalid")
    return raw


def _canonical(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _hash(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _query_record(value: object) -> dict[str, str]:
    if isinstance(value, Mapping):
        kind = value.get("query_kind")
        text = value.get("text", value.get("query_text"))
        query_hash = value.get("query_hash")
        query_id = value.get("query_id", value.get("id"))
    else:
        kind = getattr(value, "query_kind", None)
        text = getattr(value, "text", getattr(value, "query_text", None))
        query_hash = getattr(value, "query_hash", None)
        query_id = getattr(value, "query_id", getattr(value, "id", None))
    if (
        not isinstance(kind, str)
        or not kind.strip()
        or not isinstance(text, str)
        or not text.strip()
    ):
        raise LLMAdapterError(code="llm_query_invalid")
    expected_hash = hashlib.sha256(text.strip().encode("utf-8")).hexdigest()
    if query_hash is not None and str(query_hash) != expected_hash:
        raise LLMAdapterError(code="llm_query_hash_invalid")
    resolved_hash = expected_hash
    resolved_id = (
        str(query_id) if query_id is not None and str(query_id) else f"query-{resolved_hash[:16]}"
    )
    return {
        "query_id": resolved_id,
        "query_kind": kind,
        "text": text,
        "query_hash": resolved_hash,
    }


def _query_records(value: object) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, list):
        raise LLMAdapterError(code="llm_query_invalid")
    result: list[Mapping[str, object]] = []
    seen_ids: set[str] = set()
    for item in value:
        record = _query_record(item)
        if record["query_id"] in seen_ids:
            raise LLMAdapterError(code="llm_query_invalid")
        seen_ids.add(record["query_id"])
        result.append(record)
    return tuple(result)


def _no_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, item in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = item
    return result


def _schema() -> dict[str, object]:
    try:
        value = json.loads(_schema_bytes().decode("utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise LLMAdapterError(code="llm_schema_invalid") from exc
    if not isinstance(value, dict):
        raise LLMAdapterError(code="llm_schema_invalid")
    return value


def _wire_schema(value: object) -> object:
    if isinstance(value, dict):
        unsupported = {"uniqueItems", "contains", "minContains", "maxContains"}
        return {
            key: _wire_schema(item)
            for key, item in value.items()
            if not (value.get("type") == "array" and key in unsupported)
        }
    if isinstance(value, list):
        return [_wire_schema(item) for item in value]
    return value


def segment_output_schema_hash() -> str:
    _schema_bytes()
    return SEGMENT_SCHEMA_SHA256


@dataclass(frozen=True, slots=True)
class SegmentMessageV2:
    role: Literal["system", "user"]
    content: str

    def __post_init__(self) -> None:
        if (
            self.role not in {"system", "user"}
            or not isinstance(self.content, str)
            or not self.content
        ):
            raise LLMAdapterError(code="llm_message_invalid")


@dataclass(frozen=True, slots=True)
class SegmentLLMRequestV2:
    """Exact v2 request identity and its immutable logical snapshot."""

    snapshot: SegmentInputSnapshot
    endpoint: str
    method: Literal["POST"]
    body: Mapping[str, object]
    messages: tuple[SegmentMessageV2, SegmentMessageV2]
    budget: object
    request_hash: str
    schema_hash: str
    prompt_hash: str
    protocol: Literal["segments_v2"] = SEGMENT_PROTOCOL
    prompt_contract_version: str = SEGMENT_PROMPT_VERSION
    debate_id: str = ""
    turn_id: str = ""
    generation_fence: str = ""
    policy_hash: str = ""
    export_manifest_hash: str = ""
    build_manifest_hash: str = ""
    repair_policy_hash: str = ""
    attempt_no: int = 1
    retrieval_reused: bool = False
    identity_tokens: tuple[str, ...] = ()
    outbound_field_classes: tuple[str, ...] = ()
    queries: tuple[Mapping[str, object], ...] = ()
    authorized_max_attempts: int = 2

    @property
    def system_message(self) -> SegmentMessageV2:
        return self.messages[0]

    @property
    def user_message(self) -> SegmentMessageV2:
        return self.messages[1]

    @property
    def input_hash(self) -> str:
        return self.snapshot.input_hash

    def frozen_payload(self) -> dict[str, object]:
        """Return the provider-independent request identity for recovery."""

        return SegmentFrozenRequestV2(
            snapshot=self.snapshot,
            request_hash=self.request_hash,
            prompt_hash=self.prompt_hash,
            schema_hash=self.schema_hash,
            debate_id=self.debate_id,
            turn_id=self.turn_id,
            generation_fence=self.generation_fence,
            policy_hash=self.policy_hash,
            export_manifest_hash=self.export_manifest_hash,
            build_manifest_hash=self.build_manifest_hash,
            repair_policy_hash=self.repair_policy_hash,
            attempt_no=self.attempt_no,
            retrieval_reused=self.retrieval_reused,
            queries=self.queries,
        ).as_payload()


_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class SegmentFrozenRequestV2:
    """Safe frozen request identity; endpoint/body credentials are omitted."""

    snapshot: SegmentInputSnapshot
    request_hash: str
    prompt_hash: str
    schema_hash: str
    debate_id: str
    turn_id: str
    generation_fence: str
    policy_hash: str
    export_manifest_hash: str
    build_manifest_hash: str
    repair_policy_hash: str = ""
    attempt_no: int = 1
    retrieval_reused: bool = False
    queries: tuple[Mapping[str, object], ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot, SegmentInputSnapshot):
            raise LLMAdapterError(code="llm_snapshot_invalid")
        for value, name in (
            (self.request_hash, "request hash"),
            (self.prompt_hash, "prompt hash"),
            (self.schema_hash, "schema hash"),
            (self.policy_hash, "policy hash"),
            (self.export_manifest_hash, "export manifest hash"),
            (self.build_manifest_hash, "build manifest hash"),
        ):
            if not isinstance(value, str) or _HASH_RE.fullmatch(value) is None:
                raise LLMAdapterError(code=f"llm_{name.replace(' ', '_')}_invalid")
        if self.repair_policy_hash and _HASH_RE.fullmatch(self.repair_policy_hash) is None:
            raise LLMAdapterError(code="llm_repair_policy_hash_invalid")
        if not self.debate_id or not self.turn_id:
            raise LLMAdapterError(code="llm_owner_invalid")
        if not isinstance(self.generation_fence, str):
            raise LLMAdapterError(code="llm_generation_fence_invalid")
        if self.attempt_no not in {1, 2} or isinstance(self.attempt_no, bool):
            raise LLMAdapterError(code="llm_attempt_invalid")
        if not isinstance(self.retrieval_reused, bool):
            raise LLMAdapterError(code="llm_retrieval_reused_invalid")
        normalized_queries = _query_records(list(self.queries))
        object.__setattr__(self, "queries", normalized_queries)
        if self.prompt_hash != self.snapshot.input_hash:
            raise LLMAdapterError(code="llm_snapshot_hash_changed")

    def as_payload(self) -> dict[str, object]:
        return {
            "protocol": SEGMENT_PROTOCOL,
            "snapshot": self.snapshot.to_server_payload(),
            "request_hash": self.request_hash,
            "prompt_hash": self.prompt_hash,
            "schema_hash": self.schema_hash,
            "debate_id": self.debate_id,
            "turn_id": self.turn_id,
            "generation_fence": self.generation_fence,
            "policy_hash": self.policy_hash,
            "export_manifest_hash": self.export_manifest_hash,
            "build_manifest_hash": self.build_manifest_hash,
            "repair_policy_hash": self.repair_policy_hash,
            "attempt_no": self.attempt_no,
            "retrieval_reused": self.retrieval_reused,
            "queries": [dict(item) for item in self.queries],
        }


def load_segment_request_v2(value: Mapping[str, object]) -> SegmentFrozenRequestV2:
    """Load a persisted v2 request identity without rebuilding provider wire data."""

    fields = {
        "protocol",
        "snapshot",
        "request_hash",
        "prompt_hash",
        "schema_hash",
        "debate_id",
        "turn_id",
        "generation_fence",
        "policy_hash",
        "export_manifest_hash",
        "build_manifest_hash",
        "repair_policy_hash",
        "attempt_no",
        "retrieval_reused",
        "queries",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise LLMAdapterError(code="llm_frozen_request_invalid")
    if value.get("protocol") != SEGMENT_PROTOCOL:
        raise LLMAdapterError(code="llm_protocol_invalid")
    snapshot_value = value.get("snapshot")
    if not isinstance(snapshot_value, Mapping):
        raise LLMAdapterError(code="llm_snapshot_invalid")
    try:
        snapshot = SegmentInputSnapshot.from_server_payload(snapshot_value)
        return SegmentFrozenRequestV2(
            snapshot=snapshot,
            request_hash=cast(str, value.get("request_hash")),
            prompt_hash=cast(str, value.get("prompt_hash")),
            schema_hash=cast(str, value.get("schema_hash")),
            debate_id=cast(str, value.get("debate_id")),
            turn_id=cast(str, value.get("turn_id")),
            generation_fence=cast(str, value.get("generation_fence")),
            policy_hash=cast(str, value.get("policy_hash")),
            export_manifest_hash=cast(str, value.get("export_manifest_hash")),
            build_manifest_hash=cast(str, value.get("build_manifest_hash")),
            repair_policy_hash=cast(str, value.get("repair_policy_hash")),
            attempt_no=cast(int, value.get("attempt_no")),
            retrieval_reused=cast(bool, value.get("retrieval_reused")),
            queries=_query_records(value.get("queries")),
        )
    except LLMAdapterError:
        raise
    except (TypeError, ValueError, KeyError) as exc:
        raise LLMAdapterError(code="llm_frozen_request_invalid") from exc


@dataclass(frozen=True, slots=True)
class SegmentRecoveryInputV2:
    """Canonical server-only recovery envelope for one v2 attempt.

    ``input_json`` is the exact :class:`SegmentFrozenRequestV2` payload.  The
    provider endpoint, request body, headers, and response envelope never
    enter this persisted value.  The separate ``input_version`` discriminator
    lets the SQL recovery adapter keep the legacy v1 envelope readable.
    """

    operation_id: str
    turn_id: str
    attempt_no: int
    input_version: Literal["segment_recovery_input_v2"]
    input_json: str
    input_hash: str

    @classmethod
    def from_request(
        cls,
        request: SegmentLLMRequestV2,
        *,
        operation_id: str | None = None,
    ) -> SegmentRecoveryInputV2:
        payload = request.frozen_payload()
        input_json = _canonical(payload)
        return cls(
            operation_id=operation_id or request.turn_id,
            turn_id=request.turn_id,
            attempt_no=request.attempt_no,
            input_version="segment_recovery_input_v2",
            input_json=input_json,
            input_hash=hashlib.sha256(input_json.encode("utf-8")).hexdigest(),
        )

    @property
    def frozen_request(self) -> SegmentFrozenRequestV2:
        try:
            value = json.loads(
                self.input_json,
                object_pairs_hook=_no_duplicate_pairs,
                parse_constant=lambda _item: (_ for _ in ()).throw(ValueError()),
            )
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise LLMAdapterError(code="llm_recovery_input_invalid") from exc
        if not isinstance(value, Mapping):
            raise LLMAdapterError(code="llm_recovery_input_invalid")
        return load_segment_request_v2(value)

    def frozen_payload(self) -> dict[str, object]:
        return self.frozen_request.as_payload()

    def identity(self) -> Mapping[str, object]:
        request = self.frozen_request
        return {
            "protocol": SEGMENT_PROTOCOL,
            "request_hash": request.request_hash,
            "prompt_hash": request.prompt_hash,
            "schema_hash": request.schema_hash,
            "debate_id": request.debate_id,
            "turn_id": request.turn_id,
            "generation_fence": request.generation_fence,
            "policy_hash": request.policy_hash,
            "export_manifest_hash": request.export_manifest_hash,
            "build_manifest_hash": request.build_manifest_hash,
            "repair_policy_hash": request.repair_policy_hash,
            "attempt_no": request.attempt_no,
            "retrieval_reused": request.retrieval_reused,
        }

    def as_record(self) -> dict[str, object]:
        return {
            "operation_id": self.operation_id,
            "turn_id": self.turn_id,
            "attempt_no": self.attempt_no,
            "input_version": self.input_version,
            "input_json": self.input_json,
            "input_hash": self.input_hash,
        }

    def assert_stage_identity(self, stage: object, operation: object | None = None) -> None:
        request = self.frozen_request
        expected = {
            "operation_id": self.operation_id,
            "turn_id": self.turn_id,
            "attempt_no": self.attempt_no,
            "request_hash": request.request_hash,
            "prompt_hash": request.prompt_hash,
            "schema_hash": request.schema_hash,
            "policy_hash": request.policy_hash,
            "export_manifest_hash": request.export_manifest_hash,
            "build_manifest_hash": request.build_manifest_hash,
            "generation_fence": request.generation_fence,
        }
        for name, value in expected.items():
            actual = getattr(stage, name, None)
            if str(actual) != str(value):
                raise LLMAdapterError(code="llm_recovery_input_identity_mismatch")
        if getattr(stage, "prompt_contract_version", None) != segment_prompt_version(
            request.snapshot
        ):
            raise LLMAdapterError(code="llm_recovery_input_identity_mismatch")
        if operation is not None:
            for name, value in (
                ("id", self.operation_id),
                ("logical_item_id", self.turn_id),
                ("attempt_no", self.attempt_no),
                ("request_hash", request.request_hash),
                ("policy_hash", request.policy_hash),
                ("export_manifest_hash", request.export_manifest_hash),
                ("build_manifest_hash", request.build_manifest_hash),
            ):
                actual = getattr(operation, name, None)
                if str(actual) != str(value):
                    raise LLMAdapterError(code="llm_recovery_input_identity_mismatch")

    def __post_init__(self) -> None:
        if (
            not isinstance(self.operation_id, str)
            or not self.operation_id
            or not isinstance(self.turn_id, str)
            or not self.turn_id
            or isinstance(self.attempt_no, bool)
            or self.attempt_no not in {1, 2}
            or self.input_version != SEGMENT_RECOVERY_INPUT_VERSION
            or not isinstance(self.input_json, str)
            or not self.input_json
            or not isinstance(self.input_hash, str)
            or _HASH_RE.fullmatch(self.input_hash) is None
        ):
            raise LLMAdapterError(code="llm_recovery_input_invalid")
        encoded = self.input_json.encode("utf-8")
        if hashlib.sha256(encoded).hexdigest() != self.input_hash:
            raise LLMAdapterError(code="llm_recovery_input_hash_mismatch")
        try:
            parsed = json.loads(
                self.input_json,
                object_pairs_hook=_no_duplicate_pairs,
                parse_constant=lambda _item: (_ for _ in ()).throw(ValueError()),
            )
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise LLMAdapterError(code="llm_recovery_input_invalid") from exc
        if not isinstance(parsed, Mapping) or _canonical(parsed) != self.input_json:
            raise LLMAdapterError(code="llm_recovery_input_canonical_invalid")
        request = load_segment_request_v2(parsed)
        if (
            request.turn_id != self.turn_id
            or request.attempt_no != self.attempt_no
            or not request.debate_id
        ):
            raise LLMAdapterError(code="llm_recovery_input_identity_mismatch")


@dataclass(frozen=True, slots=True)
class SegmentAcceptedBundleV2:
    """Typed accepted stage plus its v2 frozen request for restart recovery."""

    stage: object
    recovery_input: SegmentRecoveryInputV2

    @property
    def input(self) -> SegmentRecoveryInputV2:
        return self.recovery_input


@dataclass(frozen=True, slots=True)
class SegmentAcceptedCandidateV2:
    request: SegmentLLMRequestV2
    http_status: int
    finish_reason: str | None
    usage: LLMUsageV1 | None
    output_json: str | None = None
    output_hash: str | None = None
    provider_output: Mapping[str, object] | None = None
    safe_error_code: str | None = None
    json_pointers: tuple[str, ...] = ()
    estimated_cost_cny: Decimal = Decimal("0")
    actual_cost_cny: Decimal | None = None

    @property
    def schema_valid(self) -> bool:
        return self.provider_output is not None

    @property
    def stage_json(self) -> str:
        payload: dict[str, object] = {
            "stage_version": "llm_accepted_stage_v1",
            "status": "schema_valid" if self.provider_output is not None else "diagnostic",
            "http_status": self.http_status,
            "finish_reason": self.finish_reason,
            "usage": _usage_payload(self.usage),
            "output_hash": self.output_hash,
            "output": self.provider_output if self.provider_output is not None else None,
            "safe_error_code": self.safe_error_code,
            "json_pointers": list(self.json_pointers),
        }
        return _canonical({key: item for key, item in payload.items() if item is not None})


@dataclass(frozen=True, slots=True)
class SegmentValidatedResultV2:
    status: Literal["succeeded", "failed", "not_sent", "acceptance_unknown"]
    acceptance: Literal["accepted", "not_sent", "unknown"]
    failure_kind: Literal[
        "none", "structure_invalid", "provider_terminal", "transport_not_sent", "transport_unknown"
    ]
    safe_error_code: str | None
    request: SegmentLLMRequestV2
    candidate: SegmentAcceptedCandidateV2 | None = None
    result: SegmentTurnResult | None = None

    @property
    def succeeded(self) -> bool:
        return self.status == "succeeded" and self.result is not None


def _usage_payload(value: LLMUsageV1 | None) -> dict[str, object] | None:
    if value is None:
        return None
    return {
        "prompt_tokens": value.prompt_tokens,
        "completion_tokens": value.completion_tokens,
        "total_tokens": value.total_tokens,
        "prompt_tokens_details": {"cached_tokens": value.cached_input_tokens},
    }


def _usage(value: object) -> LLMUsageV1 | None:
    if not isinstance(value, Mapping):
        return None
    prompt = value.get("prompt_tokens")
    completion = value.get("completion_tokens")
    total = value.get("total_tokens")
    cached_value = value.get("prompt_tokens_details", {})
    cached = cached_value.get("cached_tokens", 0) if isinstance(cached_value, Mapping) else None
    if any(
        isinstance(item, bool) or not isinstance(item, int) or item < 0
        for item in (prompt, completion, total, cached)
    ):
        return None
    if cast(int, total) != cast(int, prompt) + cast(int, completion) or cast(int, cached) > cast(
        int, prompt
    ):
        return None
    return LLMUsageV1(cast(int, prompt), cast(int, cached), cast(int, completion), cast(int, total))


def _response_parts(response: object) -> tuple[int, object]:
    status = getattr(response, "status_code", None)
    json_method = getattr(response, "json", None)
    if isinstance(status, int) and callable(json_method):
        try:
            return status, json_method()
        except Exception as exc:
            raise LLMAdapterError(code="provider_response_invalid") from exc
    if isinstance(response, Mapping):
        return 200, response
    raise LLMAdapterError(code="provider_response_invalid")


class SegmentLLMAdapter:
    """One-shot v2 request builder and sanitized response mapper."""

    key = "dashscope"
    provider = "dashscope"
    protocol = SEGMENT_PROTOCOL

    def __init__(
        self,
        config: object,
        transport: LLMTransport | None = None,
        *,
        tokenizer: LLMTokenizerPort | object | None = None,
        identity_tokens: Sequence[str] = (),
        outbound_manifest: LLMOutboundManifestV1 | None = None,
    ) -> None:
        self.config = config
        self.transport = transport or HttpxLLMTransport()
        self.tokenizer = tokenizer or ConservativeLLMTokenizer()
        self.identity_tokens = tuple(identity_tokens)
        self.outbound_manifest = outbound_manifest

    def _endpoint(self) -> str:
        value = getattr(self.config, "resolved_endpoint", None)
        if isinstance(value, str) and value:
            return value
        raise LLMAdapterError(code="llm_endpoint_invalid")

    def _validate_local_ports(self) -> None:
        tokenizer_id = getattr(self.tokenizer, "tokenizer_id", None)
        asset_hash = getattr(self.tokenizer, "asset_hash", None)
        if (
            not isinstance(tokenizer_id, str)
            or not tokenizer_id
            or not isinstance(asset_hash, str)
            or not tokenizer_asset_hash_valid(asset_hash)
        ):
            raise LLMAdapterError(code="llm_tokenizer_invalid")

    def build_request(
        self,
        snapshot: SegmentInputSnapshot,
        *,
        debate_id: str = "",
        turn_id: str = "",
        generation_fence: str = "",
        policy_hash: str = "",
        export_manifest_hash: str = "",
        build_manifest_hash: str = "",
        repair_policy_hash: str = "",
        attempt_no: int = 1,
        retrieval_reused: bool = False,
        identity_tokens: Sequence[str] | None = None,
        outbound_manifest: LLMOutboundManifestV1 | None = None,
        repair_feedback: Mapping[str, object] | None = None,
        queries: Sequence[object] = (),
    ) -> SegmentLLMRequestV2:
        if not isinstance(snapshot, SegmentInputSnapshot):
            raise LLMAdapterError(code="llm_prompt_invalid")
        if (
            isinstance(attempt_no, bool)
            or not isinstance(attempt_no, int)
            or attempt_no not in {1, 2}
        ):
            raise LLMAdapterError(code="llm_attempt_invalid")
        manifest = outbound_manifest or self.outbound_manifest
        if not isinstance(manifest, LLMOutboundManifestV1):
            raise LLMAdapterError(code="llm_manifest_required")
        if attempt_no > manifest.max_attempts:
            raise LLMAdapterError(code="llm_attempt_exceeds_manifest")
        if snapshot.barrages and LLM_ANONYMOUS_BARRAGE_FIELD_CLASS not in manifest.field_classes:
            raise LLMAdapterError(code="llm_anonymous_barrage_manifest_missing")
        if (
            getattr(snapshot, "discussion_json", None) is not None
            and LLM_SESSION_DISCUSSION_MEMORY_FIELD_CLASS not in manifest.field_classes
        ):
            raise LLMAdapterError(code="llm_discussion_manifest_missing")
        self._validate_local_ports()
        resolved_tokens = tuple(
            self.identity_tokens if identity_tokens is None else identity_tokens
        )
        query_catalog = tuple(_query_record(item) for item in queries)
        system = build_segment_system_prompt(snapshot)
        if repair_feedback is not None:
            system += (
                " Repair the prior output using the same frozen input and this server feedback;"
                " follow the prompt's upper-length guidance without padding the answer;"
                " return the complete corrected JSON once: " + _canonical(repair_feedback)
            )
        messages = (
            SegmentMessageV2(role="system", content=system),
            SegmentMessageV2(role="user", content=snapshot.to_user_json()),
        )
        try:
            scan_segment_outbound_messages(
                messages,
                identity_tokens=resolved_tokens,
                workspace_id=getattr(self.config, "workspace_id", None),
                field_classes=manifest.field_classes,
            )
            budget = preflight_prompt_budget(
                tuple(item.content for item in messages),
                request_bytes=len(messages[1].content.encode("utf-8")),
                requested_output_tokens=LLM_REQUESTED_OUTPUT_TOKEN_CAP,
                input_token_limit=LLM_INPUT_TOKEN_CAP,
                request_bytes_limit=LLM_REQUEST_BYTES_CAP,
                output_token_limit=LLM_REQUESTED_OUTPUT_TOKEN_CAP,
                token_counter=self.tokenizer,
            )
        except (LLMOutboundPrivacyError, PromptBudgetError, LLMTokenizerError, ValueError) as exc:
            raise LLMAdapterError(code=getattr(exc, "code", "llm_request_invalid")) from exc
        schema_value = _schema()
        properties = cast(dict[str, object], schema_value["properties"])
        if getattr(snapshot, "discussion_json", None) is not None:
            schema_value["required"] = ["segments", "question", "discussion_memory"]
            segment_items = cast(
                dict[str, object], cast(dict[str, object], properties["segments"])["items"]
            )
            segment_items["required"] = ["text", "source_ids", "reply_to", "support_mode"]
        else:
            # Legacy requests keep their original closed output surface.
            properties.pop("question", None)
            properties.pop("discussion_memory", None)
        schema = _wire_schema(schema_value)
        body: dict[str, object] = {
            "model": getattr(self.config, "model", LLM_MODEL_KEY),
            "messages": [{"role": item.role, "content": item.content} for item in messages],
            "enable_thinking": False,
            "stream": False,
            "temperature": 0.2,
            "top_p": 0.8,
            "n": 1,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": SEGMENT_OUTPUT_SCHEMA_ID, "strict": True, "schema": schema},
            },
        }
        schema_hash = segment_output_schema_hash()
        request_hash = _hash(
            {
                "body": body,
                "protocol": SEGMENT_PROTOCOL,
                "prompt_hash": snapshot.input_hash,
                "receipt_hash": snapshot.receipt_hash,
                "debate_id": debate_id,
                "turn_id": turn_id,
                "generation_fence": generation_fence,
                "policy_hash": policy_hash,
                "export_manifest_hash": export_manifest_hash,
                "build_manifest_hash": build_manifest_hash,
                "repair_policy_hash": repair_policy_hash,
                "attempt_no": attempt_no,
                "authorized_max_attempts": manifest.max_attempts,
                "retrieval_reused": retrieval_reused,
                "queries": query_catalog,
            }
        )
        return SegmentLLMRequestV2(
            snapshot=snapshot,
            endpoint=self._endpoint(),
            method="POST",
            body=body,
            messages=messages,
            budget=budget,
            request_hash=request_hash,
            schema_hash=schema_hash,
            prompt_hash=snapshot.input_hash,
            prompt_contract_version=segment_prompt_version(snapshot),
            debate_id=debate_id,
            turn_id=turn_id,
            generation_fence=generation_fence,
            policy_hash=policy_hash,
            export_manifest_hash=export_manifest_hash,
            build_manifest_hash=build_manifest_hash,
            repair_policy_hash=repair_policy_hash,
            attempt_no=attempt_no,
            retrieval_reused=retrieval_reused,
            identity_tokens=resolved_tokens,
            outbound_field_classes=tuple(manifest.field_classes),
            queries=query_catalog,
            authorized_max_attempts=manifest.max_attempts,
        )

    prepare = build_request

    def send_accepted(self, request: SegmentLLMRequestV2) -> SegmentAcceptedCandidateV2:
        if not isinstance(request, SegmentLLMRequestV2):
            raise LLMAdapterError(code="llm_request_invalid")
        try:
            scan_segment_outbound_messages(
                request.messages,
                identity_tokens=request.identity_tokens,
                workspace_id=getattr(self.config, "workspace_id", None),
                field_classes=request.outbound_field_classes,
            )
            response = self.transport.post(
                request.endpoint,
                headers=self._headers(),
                json=request.body,
                timeout=HttpxLLMTransport.timeout(),
            )
        except PlatformError:
            raise
        except LLMTransportNotSent:
            raise
        except LLMAcceptanceUnknown:
            raise
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
            raise LLMTransportNotSent() from exc
        except (
            httpx.WriteError,
            httpx.WriteTimeout,
            httpx.ReadError,
            httpx.ReadTimeout,
            httpx.RemoteProtocolError,
            httpx.NetworkError,
            httpx.TimeoutException,
            TimeoutError,
            ConnectionError,
            OSError,
            LLMTransportError,
        ) as exc:
            raise LLMAcceptanceUnknown() from exc
        except LLMOutboundPrivacyError as exc:
            raise LLMAdapterError(code=exc.code) from exc
        except Exception as exc:
            raise LLMAcceptanceUnknown() from exc
        return self._stage_response(request, *_response_parts(response))

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        api_key = getattr(self.config, "api_key", "")
        if isinstance(api_key, str) and api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        return headers

    def _candidate(
        self,
        request: SegmentLLMRequestV2,
        *,
        status: int,
        finish: str | None,
        usage: LLMUsageV1 | None,
        code: str | None = None,
        pointers: Sequence[str] = (),
        output: Mapping[str, object] | None = None,
        content_hash: str | None = None,
        actual_cost: Decimal | None = None,
    ) -> SegmentAcceptedCandidateV2:
        output_json = _canonical(output) if output is not None else None
        return SegmentAcceptedCandidateV2(
            request=request,
            http_status=status,
            finish_reason=finish,
            usage=usage,
            output_json=output_json,
            output_hash=_hash(output) if output is not None else None,
            provider_output=output,
            safe_error_code=code,
            json_pointers=tuple(dict.fromkeys(str(item) for item in pointers))[:12],
            estimated_cost_cny=Decimal("0"),
            actual_cost_cny=actual_cost,
        )

    def _stage_response(
        self,
        request: SegmentLLMRequestV2,
        status: int,
        payload: object,
    ) -> SegmentAcceptedCandidateV2:
        usage = _usage(payload.get("usage")) if isinstance(payload, Mapping) else None
        if status != 200 or not isinstance(payload, Mapping):
            return self._candidate(
                request, status=status, finish=None, usage=usage, code="llm_http_rejected"
            )
        if payload.get("object") != "chat.completion":
            return self._candidate(
                request, status=status, finish=None, usage=usage, code="provider_envelope_invalid"
            )
        choices = payload.get("choices")
        if (
            not isinstance(choices, list)
            or len(choices) != 1
            or not isinstance(choices[0], Mapping)
        ):
            return self._candidate(
                request, status=status, finish=None, usage=usage, code="provider_choices_invalid"
            )
        choice = choices[0]
        finish = (
            choice.get("finish_reason") if isinstance(choice.get("finish_reason"), str) else None
        )
        message = choice.get("message")
        if (
            choice.get("index") != 0
            or not isinstance(message, Mapping)
            or message.get("role") != "assistant"
        ):
            return self._candidate(
                request, status=status, finish=finish, usage=usage, code="provider_message_invalid"
            )
        content = message.get("content")
        content_hash = (
            hashlib.sha256(content.encode("utf-8")).hexdigest()
            if isinstance(content, str)
            else None
        )
        if not isinstance(content, str) or not content:
            return self._candidate(
                request,
                status=status,
                finish=finish,
                usage=usage,
                code="provider_content_invalid",
                content_hash=content_hash,
            )
        if usage is None:
            return self._candidate(
                request,
                status=status,
                finish=finish,
                usage=None,
                code="provider_usage_unknown",
                content_hash=content_hash,
            )
        if finish == "length":
            return self._candidate(
                request,
                status=status,
                finish=finish,
                usage=usage,
                code="output_truncated",
                content_hash=content_hash,
            )
        if finish != "stop":
            return self._candidate(
                request,
                status=status,
                finish=finish,
                usage=usage,
                code="provider_finish_reason_invalid",
                content_hash=content_hash,
            )
        try:
            parsed = parse_segment_output_json(content)
        except SegmentProtocolError as exc:
            return self._candidate(
                request,
                status=status,
                finish=finish,
                usage=usage,
                code=exc.code,
                pointers=exc.json_pointers,
                content_hash=content_hash,
            )
        return self._candidate(request, status=status, finish=finish, usage=usage, output=parsed)

    def validate_accepted(self, candidate: SegmentAcceptedCandidateV2) -> SegmentTurnResult:
        if (
            not isinstance(candidate, SegmentAcceptedCandidateV2)
            or candidate.provider_output is None
        ):
            raise SegmentProtocolError(
                "the accepted segment candidate has no structured output",
                code=candidate.safe_error_code
                if isinstance(candidate, SegmentAcceptedCandidateV2) and candidate.safe_error_code
                else "provider_response_invalid",
            )
        return validate_segment_output(candidate.provider_output, candidate.request.snapshot)

    def execute(
        self,
        snapshot: SegmentInputSnapshot,
        *,
        debate_id: str = "",
        turn_id: str = "",
        generation_fence: str = "",
        policy_hash: str = "",
        export_manifest_hash: str = "",
        build_manifest_hash: str = "",
        repair_policy_hash: str = "",
        attempt_no: int = 1,
        retrieval_reused: bool = False,
        identity_tokens: Sequence[str] | None = None,
        outbound_manifest: LLMOutboundManifestV1 | None = None,
        repair_feedback: Mapping[str, object] | None = None,
    ) -> SegmentValidatedResultV2:
        request = self.build_request(
            snapshot,
            debate_id=debate_id,
            turn_id=turn_id,
            generation_fence=generation_fence,
            policy_hash=policy_hash,
            export_manifest_hash=export_manifest_hash,
            build_manifest_hash=build_manifest_hash,
            repair_policy_hash=repair_policy_hash,
            attempt_no=attempt_no,
            retrieval_reused=retrieval_reused,
            identity_tokens=identity_tokens,
            outbound_manifest=outbound_manifest,
            repair_feedback=repair_feedback,
        )
        try:
            candidate = self.send_accepted(request)
        except LLMTransportNotSent:
            return SegmentValidatedResultV2(
                "not_sent", "not_sent", "transport_not_sent", "provider_not_sent", request
            )
        except LLMAcceptanceUnknown:
            return SegmentValidatedResultV2(
                "acceptance_unknown", "unknown", "transport_unknown", "acceptance_unknown", request
            )
        if candidate.provider_output is None:
            return SegmentValidatedResultV2(
                "failed",
                "accepted",
                "structure_invalid"
                if candidate.safe_error_code
                in {"json_invalid", "schema_invalid", "segment_shape_invalid"}
                else "provider_terminal",
                candidate.safe_error_code,
                request,
                candidate,
            )
        try:
            result = self.validate_accepted(candidate)
        except SegmentProtocolError as exc:
            return SegmentValidatedResultV2(
                "failed", "accepted", "structure_invalid", exc.code, request, candidate
            )
        return SegmentValidatedResultV2(
            "succeeded", "accepted", "none", None, request, candidate, result
        )

    def generate_segments(
        self,
        snapshot: SegmentInputSnapshot,
        *,
        repair_feedback: Mapping[str, object] | None = None,
    ) -> SegmentTurnResult:
        result = self.execute(snapshot, repair_feedback=repair_feedback)
        if result.result is None:
            raise SegmentProtocolError(
                "segment provider did not return a validated result",
                code=result.safe_error_code or "provider_response_invalid",
            )
        return result.result


__all__ = [
    "SEGMENT_ENDPOINT_PATH",
    "SEGMENT_OPERATION",
    "SEGMENT_OUTPUT_SCHEMA_ID",
    "SEGMENT_PROMPT_VERSION",
    "FOUR_ROUND_SEGMENT_PROMPT_VERSION",
    "segment_prompt_version",
    "SEGMENT_PROTOCOL",
    "SEGMENT_RECOVERY_INPUT_BYTES_LIMIT",
    "SEGMENT_RECOVERY_INPUT_VERSION",
    "SegmentAcceptedBundleV2",
    "SegmentAcceptedCandidateV2",
    "SegmentFrozenRequestV2",
    "SegmentLLMAdapter",
    "SegmentLLMRequestV2",
    "SegmentMessageV2",
    "SegmentRecoveryInputV2",
    "SegmentValidatedResultV2",
    "load_segment_request_v2",
    "segment_output_schema_hash",
]
