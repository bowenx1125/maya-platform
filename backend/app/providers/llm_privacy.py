"""Fail-closed privacy checks for the exact two LLM messages.

Provider-control manifests protect structured exports, while this module scans
the bytes that are actually about to leave the server.  It has no database or
selector dependency and never includes a matched value in an exception.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final, cast

LLM_REPAIR_FEEDBACK_POLICY_HASH: Final = (
    "d5b81d460ecd713f4b3d52b5732efc935b63455c2a29b5a5ab2471b17d00050b"
)
LLM_REPAIR_FEEDBACK_POLICY_VERSION: Final = "repair_feedback_v1"
LLM_REPAIR_FEEDBACK_FIELD_CLASS: Final = "server_authored_structure_repair_feedback"

LLM_ALLOWED_OUTBOUND_FIELD_CLASSES: Final = frozenset(
    {
        "topic_and_platform_rules",
        "confirmed_structured_persona",
        "public_predecessor_speech",
        "current_evidence_excerpt",
        "opaque_local_id",
        LLM_REPAIR_FEEDBACK_FIELD_CLASS,
    }
)
LLM_REQUIRED_OUTBOUND_FIELD_CLASSES: Final = frozenset(
    {
        "topic_and_platform_rules",
        "confirmed_structured_persona",
        "public_predecessor_speech",
        "current_evidence_excerpt",
        "opaque_local_id",
    }
)


class LLMOutboundPrivacyError(ValueError):
    """The exact message contains a forbidden value or unknown field."""

    def __init__(
        self,
        message: str = "LLM outbound data is not allowed",
        *,
        code: str = "llm_outbound_data_forbidden",
    ) -> None:
        # ``message`` is always a fixed, value-free description at call sites.
        super().__init__(message)
        self.code = code


OutboundLLMDataError = LLMOutboundPrivacyError
LLMPrivacyError = LLMOutboundPrivacyError


@dataclass(frozen=True, slots=True)
class LLMOutboundScanResult:
    """Hash-only result of scanning the exact outbound messages."""

    message_hash: str
    message_bytes: int
    field_classes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LLMOutboundManifestV1:
    """Pure manifest check used before a runtime persists/export-confirms."""

    field_classes: tuple[str, ...] = tuple(
        sorted(LLM_REQUIRED_OUTBOUND_FIELD_CLASSES | {LLM_REPAIR_FEEDBACK_FIELD_CLASS})
    )
    max_attempts: int = 2
    repair_policy_version: str | None = LLM_REPAIR_FEEDBACK_POLICY_VERSION
    repair_policy_hash: str | None = LLM_REPAIR_FEEDBACK_POLICY_HASH

    def __post_init__(self) -> None:
        if isinstance(self.max_attempts, bool) or not isinstance(self.max_attempts, int):
            raise LLMOutboundPrivacyError(
                "LLM outbound manifest is invalid", code="llm_manifest_invalid"
            )
        if self.max_attempts not in {1, 2}:
            raise LLMOutboundPrivacyError(
                "LLM outbound manifest is invalid", code="llm_manifest_invalid"
            )
        classes = tuple(self.field_classes)
        if len(classes) != len(set(classes)) or any(
            field_class not in LLM_ALLOWED_OUTBOUND_FIELD_CLASSES for field_class in classes
        ):
            raise LLMOutboundPrivacyError(
                "LLM outbound manifest is invalid", code="llm_manifest_field_forbidden"
            )
        if not LLM_REQUIRED_OUTBOUND_FIELD_CLASSES.issubset(classes):
            raise LLMOutboundPrivacyError(
                "LLM outbound manifest is incomplete", code="llm_manifest_fields_missing"
            )
        if self.max_attempts == 2:
            if self.repair_policy_version != LLM_REPAIR_FEEDBACK_POLICY_VERSION:
                raise LLMOutboundPrivacyError(
                    "LLM repair policy is missing", code="llm_repair_policy_missing"
                )
            if self.repair_policy_hash != LLM_REPAIR_FEEDBACK_POLICY_HASH:
                raise LLMOutboundPrivacyError(
                    "LLM repair policy is stale", code="llm_repair_policy_stale"
                )
            if LLM_REPAIR_FEEDBACK_FIELD_CLASS not in classes:
                raise LLMOutboundPrivacyError(
                    "LLM repair field is not allowlisted", code="llm_repair_field_missing"
                )
        elif self.repair_policy_version is not None or self.repair_policy_hash is not None:
            raise LLMOutboundPrivacyError(
                "LLM repair policy is unexpected", code="llm_repair_policy_unexpected"
            )

    @property
    def repair_feedback_allowed(self) -> bool:
        return self.max_attempts == 2


_UUID_RE = re.compile(r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
_EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?86[\s-]?)?1[3-9]\d{9}(?!\d)")
_BEARER_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}")
_SECRET_TOKEN_RE = re.compile(
    r"\b(?:sk|key|token)[-_][A-Za-z0-9][A-Za-z0-9_-]{7,}\b", re.IGNORECASE
)
_CREDENTIAL_LABEL_RE = re.compile(
    r"(?ix)\b(?:api[\s_-]*key|authorization|bearer|credential(?:s)?|password|secret|token)\b"
    r"\s*[\"']?\s*(?:[:=]|\bis\b)"
)
_PRIVATE_ID_LABEL_RE = re.compile(
    r"(?ix)\b(?:student|user|member|teacher|personal|private)[\s_-]+"
    r"(?:id|identifier|name|email|phone|telephone|mobile|nickname|username|identity|account)\b"
    r"\s*[\"']?\s*(?:[:=]|\bis\b)"
)
_PRIVATE_ID_CJK_RE = re.compile(
    r"(?:学生|用户|参与者|教师|成员)(?:编号|号码|姓名|名字|邮箱|电话|账号|身份)\s*[：:]"
)
_PATH_RE = re.compile(
    r"(?:^|[\s\"'])/(?:Users|home|tmp|var|private|workspace|root)/|\b[^\s/]+\.(?:md|json|sqlite3?|yaml|yml)\b",
    re.IGNORECASE,
)

# UUID-shaped values are allowed only where the PromptRequest contract carries
# an opaque server-local reference.  A UUID in topic/speech/Persona/evidence
# text remains a private-data violation.  List item paths are handled by
# ``_path_allows_uuid`` below.
_UUID_ID_KEYS = frozenset(
    {
        "debate_id",
        "turn_id",
        "participant_id",
        "next_participant_id",
        "claim_id",
        "target_turn_id",
        "target_claim_id",
        "question_id",
        "source_turn_id",
        "source_participant_id",
        "target_participant_id",
        "query_id",
        "evidence_id",
        "query_ids",
        "evidence_ids",
        "used_evidence_ids",
        "answered_question_ids",
    }
)

# The user message is PromptRequestV1's canonical object.  These keys are
# explicit rather than inferred, preventing a future provider-facing field
# from silently crossing the privacy boundary.
_REQUEST_KEYS = frozenset(
    {
        "request_version",
        "debate_id",
        "turn_id",
        "rule_set_id",
        "rule_set_hash",
        "phase",
        "round_no",
        "round_count",
        "turn_index",
        "participant_id",
        "participant_slot",
        "participant_order_index",
        "next_participant_id",
        "is_final_round",
        "is_final_turn",
        "topic",
        "assigned_stance",
        "persona_provider_view",
        "persona_spec_hash",
        "predecessors",
        "pending_question",
        "query_catalog",
        "evidence_catalog",
        "transcript_hash",
        "receipt_hash",
        "output_schema_id",
        "evidence_trace_schema_id",
        "repair_feedback",
    }
)
_PERSONA_KEYS = frozenset(
    {
        "schema_version",
        "identity",
        "cultural_lens",
        "core_values",
        "initial_position",
        "speaking_style",
        "debate_strategy",
        "boundaries",
    }
)
_PERSONA_IDENTITY_KEYS = frozenset({"name", "role", "historical_or_cultural_context"})
_PERSONA_STYLE_KEYS = frozenset({"tone", "argument_pattern", "concession_style", "question_style"})
_PREDECESSOR_KEYS = frozenset(
    {
        "turn_id",
        "participant_id",
        "round_no",
        "turn_index",
        "speech",
        "key_claims",
        "engagements",
        "answered_question_ids",
        "learned_from_others",
        "position_summary",
        "position_update",
        "position_update_reason",
        "remaining_uncertainty",
        "unresolved_issue",
        "question",
        "missing_information",
        "unresolved_questions",
        "change_from_opening",
        "final_consensus",
        "final_disagreements",
        "final_recommendation",
        "used_evidence_ids",
    }
)
_CLAIM_KEYS = frozenset({"claim_id", "claim_text", "claim_type", "used_evidence_ids"})
_ENGAGEMENT_KEYS = frozenset(
    {"target_turn_id", "target_claim_id", "relation", "faithful_summary", "response_summary"}
)
_QUESTION_KEYS = frozenset(
    {
        "type",
        "question_id",
        "source_turn_id",
        "source_participant_id",
        "target_participant_id",
        "text",
    }
)
_QUERY_KEYS = frozenset({"query_id", "query_kind", "query_text", "query_hash", "evidence_ids"})
_EVIDENCE_KEYS = frozenset({"evidence_id", "excerpt", "query_ids"})
_DISAGREEMENT_KEYS = frozenset({"summary", "category", "claim_ids"})
_REPAIR_KEYS = frozenset({"code", "json_pointers", "safe_error_code"})


def _message_parts(messages: Sequence[object]) -> tuple[tuple[str, str], ...]:
    parts: list[tuple[str, str]] = []
    for item in messages:
        if isinstance(item, (tuple, list)) and len(item) == 2:
            role, content = item
        else:
            role = getattr(item, "role", None)
            content = getattr(item, "content", None)
        if not isinstance(role, str) or not isinstance(content, str) or not content:
            raise LLMOutboundPrivacyError(code="llm_outbound_message_invalid")
        parts.append((role, content))
    if tuple(role for role, _ in parts) != ("system", "user"):
        raise LLMOutboundPrivacyError(code="llm_outbound_message_shape_invalid")
    return tuple(parts)


def _reject(
    message: str = "LLM outbound data is not allowed", *, code: str = "llm_outbound_data_forbidden"
) -> None:
    raise LLMOutboundPrivacyError(message, code=code)


def _walk_keys(value: object, *, allowed: frozenset[str], path: str) -> None:
    """Check one object level; callers select the correct child schema."""

    del path  # Paths never enter user-visible errors; keep the argument for readability.
    if not isinstance(value, Mapping):
        return
    for key in value:
        if not isinstance(key, str) or key not in allowed:
            _reject(code="llm_outbound_field_forbidden")


def _validate_request_key_tree(value: object) -> None:
    if not isinstance(value, Mapping):
        _reject(code="llm_outbound_json_invalid")
    request = cast(Mapping[str, object], value)
    _walk_keys(request, allowed=_REQUEST_KEYS, path="request")
    # Validate nested objects with a separate closed set.  This catches a
    # malicious nested ``student_name`` even when its parent key is known.
    for key, nested in request.items():
        if key == "persona_provider_view" and isinstance(nested, Mapping):
            _walk_keys(nested, allowed=_PERSONA_KEYS, path="persona")
            identity = nested.get("identity")
            if isinstance(identity, Mapping):
                _walk_keys(identity, allowed=_PERSONA_IDENTITY_KEYS, path="persona.identity")
            style = nested.get("speaking_style")
            if isinstance(style, Mapping):
                _walk_keys(style, allowed=_PERSONA_STYLE_KEYS, path="persona.speaking_style")
        elif key == "predecessors" and isinstance(nested, list):
            for predecessor in nested:
                if isinstance(predecessor, Mapping):
                    _walk_keys(predecessor, allowed=_PREDECESSOR_KEYS, path="predecessor")
                    for claim in (
                        predecessor.get("key_claims", ())
                        if isinstance(predecessor.get("key_claims"), list)
                        else ()
                    ):
                        if isinstance(claim, Mapping):
                            _walk_keys(claim, allowed=_CLAIM_KEYS, path="claim")
                    for engagement in (
                        predecessor.get("engagements", ())
                        if isinstance(predecessor.get("engagements"), list)
                        else ()
                    ):
                        if isinstance(engagement, Mapping):
                            _walk_keys(engagement, allowed=_ENGAGEMENT_KEYS, path="engagement")
                    question = predecessor.get("question")
                    if isinstance(question, Mapping):
                        _walk_keys(question, allowed=_QUESTION_KEYS, path="question")
                    for disagreement in (
                        predecessor.get("final_disagreements", ())
                        if isinstance(predecessor.get("final_disagreements"), list)
                        else ()
                    ):
                        if isinstance(disagreement, Mapping):
                            _walk_keys(
                                disagreement, allowed=_DISAGREEMENT_KEYS, path="disagreement"
                            )
        elif key == "pending_question" and isinstance(nested, Mapping):
            _walk_keys(
                nested,
                allowed=frozenset(
                    {
                        "question_id",
                        "source_turn_id",
                        "source_participant_id",
                        "target_participant_id",
                        "text",
                    }
                ),
                path="pending_question",
            )
        elif key == "query_catalog" and isinstance(nested, list):
            for query in nested:
                if isinstance(query, Mapping):
                    _walk_keys(query, allowed=_QUERY_KEYS, path="query")
        elif key == "evidence_catalog" and isinstance(nested, list):
            for evidence in nested:
                if isinstance(evidence, Mapping):
                    _walk_keys(evidence, allowed=_EVIDENCE_KEYS, path="evidence")
        elif key == "repair_feedback" and isinstance(nested, Mapping):
            _walk_keys(nested, allowed=_REPAIR_KEYS, path="repair_feedback")


def _contains_identity_token(folded_text: str, token: str) -> bool:
    """Whether one supplied identity token appears in already case-folded text.

    Matching is on word boundaries, not substrings, because a short token
    otherwise rejects unrelated vocabulary - "himalaya" contains "maya",
    "jaded" contains "jade" - and one such word fails a whole turn closed
    behind a safe code that names no cause.

    The Debate path supplies only authenticated user IDs here. Callers may
    still pass any token they need withheld. High-entropy identifiers (UUIDs,
    emails, phone numbers, bearer tokens, the workspace ID) keep their own
    unconditional checks below and do not depend on this list.
    """

    needle = token.casefold().strip()
    if not needle:
        return False
    return re.search(rf"(?<![0-9a-z]){re.escape(needle)}(?![0-9a-z])", folded_text) is not None


def _scan_text(
    text: str,
    *,
    identity_tokens: Sequence[str],
    workspace_id: str | None,
    allow_uuid: bool = False,
) -> None:
    folded = text.casefold()
    if workspace_id and workspace_id.casefold() in folded:
        _reject()
    for token in identity_tokens:
        if isinstance(token, str) and token.strip() and _contains_identity_token(folded, token):
            _reject()
    if (
        (not allow_uuid and _UUID_RE.search(text))
        or _EMAIL_RE.search(text)
        or _PHONE_RE.search(text)
        or _BEARER_RE.search(text)
        or _SECRET_TOKEN_RE.search(text)
        or _CREDENTIAL_LABEL_RE.search(text)
        or _PRIVATE_ID_LABEL_RE.search(text)
        or _PRIVATE_ID_CJK_RE.search(text)
        or re.search(
            r"(?i)\bagent\.md\b|\bteacher[_ -]?note\b|\bsource[_ -]?(?:filename|path)\b", text
        )
        or _PATH_RE.search(text)
    ):
        _reject()


def _path_allows_uuid(path: tuple[str, ...]) -> bool:
    if not path:
        return False
    if path[-1] in _UUID_ID_KEYS:
        return True
    return len(path) > 1 and path[-2] in _UUID_ID_KEYS and path[-1].isdigit()


def _scan_value(
    value: object,
    *,
    path: tuple[str, ...],
    identity_tokens: Sequence[str],
    workspace_id: str | None,
) -> None:
    if isinstance(value, str):
        _scan_text(
            value,
            identity_tokens=identity_tokens,
            workspace_id=workspace_id,
            allow_uuid=_path_allows_uuid(path),
        )
    elif isinstance(value, Mapping):
        for key, nested in value.items():
            if isinstance(key, str):
                _scan_value(
                    nested,
                    path=path + (key,),
                    identity_tokens=identity_tokens,
                    workspace_id=workspace_id,
                )
    elif isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            _scan_value(
                nested,
                path=path + (str(index),),
                identity_tokens=identity_tokens,
                workspace_id=workspace_id,
            )


class _DuplicateKeyError(ValueError):
    pass


def _no_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError()
        result[key] = value
    return result


def scan_llm_outbound_messages(
    messages: Sequence[object],
    *,
    identity_tokens: Iterable[str] = (),
    workspace_id: str | None = None,
    field_classes: Iterable[str] = (),
) -> LLMOutboundScanResult:
    """Scan the exact system/user strings immediately before sending."""

    parts = _message_parts(messages)
    tokens = tuple(
        str(token) for token in identity_tokens if isinstance(token, str) and token.strip()
    )
    # The system message is ordinary provider prose: UUIDs there are never
    # opaque local references.  The user message is scanned by parsed field
    # path below so UUID-shaped catalog IDs can remain opaque and allowed.
    _scan_text(parts[0][1], identity_tokens=tokens, workspace_id=workspace_id)
    try:
        decoded = json.loads(
            parts[1][1],
            object_pairs_hook=_no_duplicate_pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (TypeError, ValueError, json.JSONDecodeError):
        _reject(code="llm_outbound_json_invalid")
    _validate_request_key_tree(decoded)
    _scan_value(
        decoded,
        path=(),
        identity_tokens=tokens,
        workspace_id=workspace_id,
    )
    classes = tuple(dict.fromkeys(str(value) for value in field_classes))
    if any(value not in LLM_ALLOWED_OUTBOUND_FIELD_CLASSES for value in classes):
        _reject(code="llm_manifest_field_forbidden")
    raw = "\x1e".join(content for _role, content in parts).encode("utf-8")
    return LLMOutboundScanResult(
        message_hash=hashlib.sha256(raw).hexdigest(),
        message_bytes=sum(len(content.encode("utf-8")) for _role, content in parts),
        field_classes=classes,
    )


def scan_real_llm_messages(*args: object, **kwargs: object) -> LLMOutboundScanResult:
    """Alias named after the real-provider boundary used by tests/runtime."""

    return scan_llm_outbound_messages(*args, **kwargs)  # type: ignore[arg-type]


validate_llm_outbound_messages = scan_llm_outbound_messages
validate_real_llm_messages = scan_llm_outbound_messages


__all__ = [
    "LLM_ALLOWED_OUTBOUND_FIELD_CLASSES",
    "LLMOutboundManifestV1",
    "LLMOutboundPrivacyError",
    "LLMOutboundScanResult",
    "LLMPrivacyError",
    "LLM_REQUIRED_OUTBOUND_FIELD_CLASSES",
    "LLM_REPAIR_FEEDBACK_FIELD_CLASS",
    "LLM_REPAIR_FEEDBACK_POLICY_HASH",
    "LLM_REPAIR_FEEDBACK_POLICY_VERSION",
    "OutboundLLMDataError",
    "scan_llm_outbound_messages",
    "scan_real_llm_messages",
    "validate_llm_outbound_messages",
    "validate_real_llm_messages",
]
