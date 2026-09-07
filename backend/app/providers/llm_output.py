"""Strict Qwen output validation and server-owned reference mapping."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, cast

from app.modules.debates.generation.prompt_request import PromptRequestV1
from app.modules.debates.generation.speech_match import speech_contains_claim
from app.modules.debates.generation.types import (
    EngagementV1,
    EvidenceTraceClaimType,
    EvidenceTraceClaimV1,
    KeyClaimV1,
    MutualLearningTurnResultV1,
    TurnQuestion,
)

LLM_TURN_OUTPUT_SCHEMA_HASH: Final = (
    "77769a5fdc0e6ef368c048a6e2b28891c1702a2d904da2471bcf7b2ed9df253f"
)
LLM_TURN_OUTPUT_SCHEMA_NAME: Final = "maya_llm_turn_output_v1"
LLM_TURN_OUTPUT_SCHEMA_VERSION: Final = "llm_turn_output_v1"
LLM_REPAIR_FEEDBACK_SCHEMA_HASH: Final = (
    "d5b81d460ecd713f4b3d52b5732efc935b63455c2a29b5a5ab2471b17d00050b"
)
LLM_REPAIR_FEEDBACK_VERSION: Final = "repair_feedback_v1"
REPAIR_CODES: Final = frozenset(
    {"output_truncated", "json_invalid", "schema_invalid", "rule_invalid"}
)
_POINTER_RE = re.compile(r"^/(?:[^~/]|~0|~1)*(?:/(?:[^~/]|~0|~1)*)*$")


class LLMOutputError(ValueError):
    """A supplier output failed closed validation without echoing its value."""

    def __init__(
        self,
        message: str = "LLM output is invalid",
        *,
        code: str = "schema_invalid",
        json_pointers: Sequence[str] = (),
    ) -> None:
        super().__init__(message)
        self.code = code
        self.json_pointers = tuple(dict.fromkeys(str(item) for item in json_pointers))[:12]


LLMOutputValidationError = LLMOutputError
LLMStructuredOutputError = LLMOutputError


@dataclass(frozen=True, slots=True)
class RepairFeedbackV1:
    """Finite server-authored structure feedback for attempt two."""

    code: str
    json_pointers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.code, str) or self.code not in REPAIR_CODES:
            raise LLMOutputError(code="repair_feedback_invalid")
        pointers = tuple(self.json_pointers)
        if len(pointers) > 12 or len(set(pointers)) != len(pointers):
            raise LLMOutputError(code="repair_feedback_invalid")
        if any(
            not isinstance(pointer, str)
            or len(pointer) < 1
            or len(pointer) > 160
            or not pointer.isascii()
            or _POINTER_RE.fullmatch(pointer) is None
            for pointer in pointers
        ):
            raise LLMOutputError(code="repair_feedback_invalid")
        if pointers != tuple(sorted(pointers)):
            raise LLMOutputError(code="repair_feedback_invalid")

    def as_dict(self) -> dict[str, object]:
        return {"code": self.code, "json_pointers": list(self.json_pointers)}

    @classmethod
    def from_value(cls, value: object) -> RepairFeedbackV1:
        if not isinstance(value, Mapping):
            raise LLMOutputError(code="repair_feedback_invalid")
        # PromptRequestV1 from the previous provider-neutral seam called this
        # field ``safe_error_code``.  Accept it as an input alias, but always
        # expose the exact closed repair_feedback_v1 object to the supplier.
        code_value = value.get("code", value.get("safe_error_code"))
        pointers_value = value.get("json_pointers", ())
        if not isinstance(code_value, str) or not isinstance(pointers_value, (list, tuple)):
            raise LLMOutputError(code="repair_feedback_invalid")
        return cls(code=code_value, json_pointers=tuple(pointers_value))


@dataclass(frozen=True, slots=True)
class MappedLLMTurnV1:
    """Output mapped to provider-neutral Maya IDs after strict validation."""

    result: MutualLearningTurnResultV1
    provider_output: Mapping[str, object]
    provider_output_json: str
    provider_output_hash: str
    schema_hash: str = LLM_TURN_OUTPUT_SCHEMA_HASH

    @property
    def output_json(self) -> str:
        return self.provider_output_json

    @property
    def output_hash(self) -> str:
        return self.provider_output_hash


_SCHEMA_RELATIVE_PATH = "contracts/llm-turn-output.v1.schema.json"


def _schema_candidates() -> tuple[Path, ...]:
    """Return every layout that can hold the frozen wire schema.

    A repository checkout keeps the file three levels above ``providers``
    (``providers`` -> ``app`` -> ``backend`` -> repository root).  The backend
    image is built from the ``backend`` directory alone, so the same file is
    mounted beside the application package instead.  ``load`` still verifies the
    exact content hash, so accepting either layout cannot widen the boundary.

    The schema lives in ``contracts/`` beside the frozen OpenAPI and WebSocket
    schemas because it is a runtime asset the wire depends on, not prose.
    """

    module = Path(__file__).resolve()
    return (
        module.parents[3] / _SCHEMA_RELATIVE_PATH,
        module.parents[2] / _SCHEMA_RELATIVE_PATH,
    )


def _schema_path() -> Path:
    for candidate in _schema_candidates():
        if candidate.is_file():
            return candidate
    return _schema_candidates()[0]


def load_llm_turn_output_schema() -> dict[str, object]:
    """Load and hash-check the exact repository schema used on the wire."""

    try:
        raw = _schema_path().read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise LLMOutputError("LLM output schema is unavailable", code="schema_unavailable") from exc
    if digest != LLM_TURN_OUTPUT_SCHEMA_HASH or not isinstance(value, dict):
        raise LLMOutputError("LLM output schema hash is stale", code="schema_hash_changed")
    return cast(dict[str, object], value)


# The supplier's structured-output validator rejects an array that also carries
# any of these keywords.  They are ordinary JSON Schema, so the frozen contract
# keeps them and local validation keeps enforcing them; only the wire copy drops
# them.  Removing a constraint from the request cannot widen what we accept back.
_PROVIDER_UNSUPPORTED_ARRAY_KEYWORDS = frozenset(
    {"uniqueItems", "contains", "minContains", "maxContains"}
)


def _provider_dialect(node: object) -> object:
    if isinstance(node, dict):
        drop = _PROVIDER_UNSUPPORTED_ARRAY_KEYWORDS if node.get("type") == "array" else frozenset()
        return {key: _provider_dialect(item) for key, item in node.items() if key not in drop}
    if isinstance(node, list):
        return [_provider_dialect(item) for item in node]
    return node


def provider_wire_output_schema() -> dict[str, object]:
    """Return the frozen schema projected into the supplier's dialect.

    The repository schema stays the hash-checked authority for validating a
    response.  This projection exists only because the supplier refuses a
    request whose ``response_format`` schema constrains an array with
    ``uniqueItems``; sending the frozen copy fails closed with HTTP 400 before
    the model ever runs.
    """

    return cast(dict[str, object], _provider_dialect(load_llm_turn_output_schema()))


def _canonical(value: object) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise LLMOutputError(code="schema_invalid") from exc


def _pointer(path: str) -> str:
    if not path:
        return "/"
    if path.startswith("/"):
        path = path[1:]
    return "/" + "/".join(
        segment.replace("~", "~0").replace("/", "~1") for segment in path.split("/")
    )


def _json_type_matches(value: object, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, Mapping)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "number":
        return (isinstance(value, int) and not isinstance(value, bool)) or isinstance(value, float)
    if expected == "null":
        return value is None
    return False


def _schema_errors(value: object, schema: Mapping[str, object], path: str = "") -> list[str]:
    errors: list[str] = []
    expected_type = schema.get("type")
    if isinstance(expected_type, str) and not _json_type_matches(value, expected_type):
        return [_pointer(path)]
    if "const" in schema and value != schema["const"]:
        errors.append(_pointer(path))
    enum = schema.get("enum")
    if isinstance(enum, list) and value not in enum:
        errors.append(_pointer(path))
    if isinstance(value, str):
        minimum = schema.get("minLength")
        maximum = schema.get("maxLength")
        if isinstance(minimum, int) and len(value) < minimum:
            errors.append(_pointer(path))
        if isinstance(maximum, int) and len(value) > maximum:
            errors.append(_pointer(path))
        pattern = schema.get("pattern")
        if isinstance(pattern, str):
            try:
                matched = re.fullmatch(pattern, value) is not None
            except re.error:
                matched = False
            if not matched:
                errors.append(_pointer(path))
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if isinstance(minimum, (int, float)) and value < minimum:
            errors.append(_pointer(path))
        if isinstance(maximum, (int, float)) and value > maximum:
            errors.append(_pointer(path))
    if isinstance(value, list):
        minimum = schema.get("minItems")
        maximum = schema.get("maxItems")
        if isinstance(minimum, int) and len(value) < minimum:
            errors.append(_pointer(path))
        if isinstance(maximum, int) and len(value) > maximum:
            errors.append(_pointer(path))
        if schema.get("uniqueItems") is True:
            try:
                if len({_canonical(item) for item in value}) != len(value):
                    errors.append(_pointer(path))
            except LLMOutputError:
                errors.append(_pointer(path))
        item_schema = schema.get("items")
        if isinstance(item_schema, Mapping):
            for index, item in enumerate(value):
                errors.extend(_schema_errors(item, item_schema, f"{path}/{index}"))
    if isinstance(value, Mapping):
        required = schema.get("required")
        if isinstance(required, list):
            for key in required:
                if isinstance(key, str) and key not in value:
                    errors.append(_pointer(f"{path}/{key}"))
        properties = schema.get("properties")
        property_map = properties if isinstance(properties, Mapping) else {}
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in property_map:
                    errors.append(_pointer(f"{path}/{key}"))
        for key, nested in value.items():
            nested_schema = property_map.get(key)
            if isinstance(nested_schema, Mapping):
                errors.extend(_schema_errors(nested, nested_schema, f"{path}/{key}"))
    return errors


class _DuplicateKeyError(ValueError):
    pass


def _no_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError()
        result[key] = value
    return result


def parse_llm_output_json(content: str) -> dict[str, object]:
    """Parse the assistant content and apply the exact strict schema."""

    if not isinstance(content, str) or not content:
        raise LLMOutputError(code="json_invalid")
    try:
        decoded = json.loads(
            content,
            object_pairs_hook=_no_duplicate_pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise LLMOutputError(code="json_invalid") from exc
    if not isinstance(decoded, dict):
        raise LLMOutputError(code="schema_invalid", json_pointers=("/",))
    schema = load_llm_turn_output_schema()
    errors = tuple(sorted(set(_schema_errors(decoded, schema))))
    if errors:
        raise LLMOutputError(code="schema_invalid", json_pointers=errors)
    return decoded


def validate_llm_output(value: object) -> dict[str, object]:
    """Validate a decoded strict output object without serializing secrets."""

    if not isinstance(value, Mapping):
        raise LLMOutputError(code="schema_invalid", json_pointers=("/",))
    schema = load_llm_turn_output_schema()
    errors = tuple(sorted(set(_schema_errors(value, schema))))
    if errors:
        raise LLMOutputError(code="schema_invalid", json_pointers=errors)
    # Convert to a regular dict so no provider-owned mutable mapping can be
    # changed after stage hashing.
    return cast(
        dict[str, object],
        json.loads(_canonical(value), object_pairs_hook=_no_duplicate_pairs),
    )


def _integer_ref(value: object, *, label: str, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > maximum:
        raise LLMOutputError(code="reference_invalid")
    return value


def validate_repair_feedback(value: object) -> RepairFeedbackV1:
    """Validate the exact public ``repair_feedback_v1`` grammar."""

    if not isinstance(value, Mapping) or set(value) != {"code", "json_pointers"}:
        raise LLMOutputError(code="repair_feedback_invalid")
    return RepairFeedbackV1.from_value(value)


def canonical_repair_feedback(value: object) -> str:
    return _canonical(validate_repair_feedback(value).as_dict())


def map_provider_output(
    value: object,
    request: PromptRequestV1,
    *,
    question_target_ids: Sequence[str] = (),
) -> MappedLLMTurnV1:
    """Map bounded supplier references to server-owned Maya IDs.

    No supplier field is accepted for a claim/evidence/query/question/turn ID.
    The only IDs entering the result are selected from the frozen request
    catalogs or derived from the current server turn ID.
    """

    payload = validate_llm_output(value)
    if payload.get("phase") != request.phase:
        raise LLMOutputError(code="rule_invalid", json_pointers=("/phase",))
    speech = payload.get("speech")
    if not isinstance(speech, str) or not speech:
        raise LLMOutputError(code="schema_invalid", json_pointers=("/speech",))

    evidence = request.evidence_catalog
    claims_raw = payload.get("key_claims")
    if not isinstance(claims_raw, list):
        raise LLMOutputError(code="schema_invalid", json_pointers=("/key_claims",))
    claim_ids: list[str] = []
    claims: list[KeyClaimV1] = []
    traces: list[EvidenceTraceClaimV1] = []
    all_evidence_ids: list[str] = []
    for index, raw_claim in enumerate(claims_raw):
        if not isinstance(raw_claim, Mapping):
            raise LLMOutputError(code="schema_invalid", json_pointers=(f"/key_claims/{index}",))
        claim_text = raw_claim.get("claim_text")
        # The same containment rule the evidence trace applies, with the same
        # tolerance: a provider's curly quote is not a different sentence.
        if not isinstance(claim_text, str) or not speech_contains_claim(speech, claim_text):
            raise LLMOutputError(
                code="rule_invalid", json_pointers=(f"/key_claims/{index}/claim_text",)
            )
        refs = raw_claim.get("used_evidence_refs")
        if not isinstance(refs, list):
            raise LLMOutputError(
                code="schema_invalid", json_pointers=(f"/key_claims/{index}/used_evidence_refs",)
            )
        mapped_evidence: list[str] = []
        for ref_index, ref in enumerate(refs):
            resolved = _integer_ref(ref, label="evidence ref", maximum=63)
            if resolved >= len(evidence):
                raise LLMOutputError(
                    code="reference_invalid",
                    json_pointers=(f"/key_claims/{index}/used_evidence_refs/{ref_index}",),
                )
            mapped_evidence.append(evidence[resolved].evidence_id)
        claim_id = f"{request.turn_id}:claim-{index + 1}"
        if claim_id in claim_ids or claim_text in {claim.claim_text for claim in claims}:
            raise LLMOutputError(code="rule_invalid", json_pointers=(f"/key_claims/{index}",))
        claim_ids.append(claim_id)
        claim_type = raw_claim.get("claim_type")
        if not isinstance(claim_type, str):
            raise LLMOutputError(
                code="schema_invalid", json_pointers=(f"/key_claims/{index}/claim_type",)
            )
        claims.append(
            KeyClaimV1(
                claim_id=claim_id,
                claim_text=claim_text,
                claim_type=cast(Any, claim_type),
                used_evidence_ids=mapped_evidence,
            )
        )
        all_evidence_ids.extend(mapped_evidence)
        trace_type = (
            "background"
            if claim_type == "interpretation"
            else cast(EvidenceTraceClaimType, claim_type)
        )
        traces.append(
            EvidenceTraceClaimV1(
                claim_text=claim_text,
                claim_type=trace_type,
                used_evidence_ids=mapped_evidence,
                support_mode="direct" if mapped_evidence else "general_reasoning",
            )
        )

    engagements: list[EngagementV1] = []
    engagements_raw = payload.get("engagements")
    if not isinstance(engagements_raw, list):
        raise LLMOutputError(code="schema_invalid", json_pointers=("/engagements",))
    for index, raw_engagement in enumerate(engagements_raw):
        if not isinstance(raw_engagement, Mapping):
            raise LLMOutputError(code="schema_invalid", json_pointers=(f"/engagements/{index}",))
        turn_ref = raw_engagement.get("target_turn_ref")
        if (
            isinstance(turn_ref, bool)
            or not isinstance(turn_ref, int)
            or turn_ref < 0
            or turn_ref >= len(request.predecessors)
        ):
            raise LLMOutputError(
                code="reference_invalid", json_pointers=(f"/engagements/{index}/target_turn_ref",)
            )
        claim_ref = raw_engagement.get("target_claim_ref")
        if isinstance(claim_ref, bool) or not isinstance(claim_ref, int) or claim_ref < -1:
            raise LLMOutputError(
                code="reference_invalid", json_pointers=(f"/engagements/{index}/target_claim_ref",)
            )
        target_claim_id: str | None = None
        if claim_ref >= 0:
            target_claims = request.predecessors[turn_ref].key_claims
            if claim_ref >= len(target_claims):
                raise LLMOutputError(
                    code="reference_invalid",
                    json_pointers=(f"/engagements/{index}/target_claim_ref",),
                )
            target_claim_id = target_claims[claim_ref].claim_id
        relation = raw_engagement.get("relation")
        faithful = raw_engagement.get("faithful_summary")
        response = raw_engagement.get("response_summary")
        if not all(isinstance(item, str) and item for item in (relation, faithful, response)):
            raise LLMOutputError(code="schema_invalid", json_pointers=(f"/engagements/{index}",))
        engagements.append(
            EngagementV1(
                target_turn_id=request.predecessors[turn_ref].turn_id,
                target_claim_id=target_claim_id,
                relation=cast(Any, relation),
                faithful_summary=cast(str, faithful),
                response_summary=cast(str, response),
            )
        )

    pending = request.pending_question
    answered = payload.get("answered_required_question")
    if not isinstance(answered, bool):
        raise LLMOutputError(code="schema_invalid", json_pointers=("/answered_required_question",))
    # Derived, not taken from the model. Whether a question is pending is the
    # server's own fact, and the boolean never carried anything else: the only
    # way a turn could pass was to report true exactly when pending existed, so
    # the field could reject a good turn and never accept a bad one. Deriving it
    # removes that failure class without weakening a check that never held.
    del answered
    answered_ids = [pending.question_id] if pending is not None else []

    question_raw = payload.get("question")
    if not isinstance(question_raw, Mapping):
        raise LLMOutputError(code="schema_invalid", json_pointers=("/question",))
    mode = question_raw.get("mode")
    target_ref = question_raw.get("target_participant_ref")
    text = question_raw.get("text")
    if mode == "none":
        if target_ref != -1 or text != "":
            raise LLMOutputError(code="rule_invalid", json_pointers=("/question",))
        question = TurnQuestion(type="none")
    elif mode == "ask":
        if isinstance(target_ref, bool) or not isinstance(target_ref, int) or target_ref < 0:
            raise LLMOutputError(
                code="reference_invalid", json_pointers=("/question/target_participant_ref",)
            )
        targets = tuple(question_target_ids)
        if not targets and request.next_participant_id:
            targets = (request.next_participant_id,)
        # With a single legal target the server already knows who is asked, and
        # the model's index carries nothing: it can only be 0 or wrong. Taking
        # the target removes a way for an otherwise good turn to be rejected.
        # A future RuleSet offering a real choice still has its index checked.
        # Separate pointers matter for that case: "/question" alone could not
        # tell a repair attempt whether the reference or the text was wrong.
        if len(targets) > 1 and target_ref >= len(targets):
            raise LLMOutputError(
                code="reference_invalid",
                json_pointers=("/question/target_participant_ref",),
            )
        if len(targets) == 1:
            target_ref = 0
        if not isinstance(text, str) or not text:
            raise LLMOutputError(code="reference_invalid", json_pointers=("/question/text",))
        question = TurnQuestion(type="agent", target_participant_id=targets[target_ref], text=text)
    else:
        raise LLMOutputError(code="schema_invalid", json_pointers=("/question/mode",))

    def _strings(name: str, maximum: int) -> list[str]:
        raw = payload.get(name)
        if (
            not isinstance(raw, list)
            or len(raw) > maximum
            or any(not isinstance(item, str) for item in raw)
        ):
            raise LLMOutputError(code="schema_invalid", json_pointers=(f"/{name}",))
        return list(raw)

    learned = _strings("learned_from_others", 6)
    uncertainty = _strings("remaining_uncertainty", 6)
    missing = _strings("missing_information", 6)
    unresolved_questions = _strings("unresolved_questions", 8)
    position_summary = payload.get("position_summary")
    position_update_reason = payload.get("position_update_reason")
    unresolved_issue = payload.get("unresolved_issue")
    change_from_opening = payload.get("change_from_opening")
    recommendation = payload.get("final_recommendation")
    if not all(
        isinstance(item, str)
        for item in (
            position_summary,
            position_update_reason,
            unresolved_issue,
            change_from_opening,
            recommendation,
        )
    ):
        raise LLMOutputError(code="schema_invalid", json_pointers=("/position_summary",))
    final_consensus = _strings("final_consensus", 8)
    final_disagreements_raw = payload.get("final_disagreements")
    if not isinstance(final_disagreements_raw, list):
        raise LLMOutputError(code="schema_invalid", json_pointers=("/final_disagreements",))
    from app.modules.debates.generation.types import MutualLearningDisagreementV1

    final_disagreements = [
        MutualLearningDisagreementV1(
            summary=cast(str, item["summary"]),
            category=cast(Any, item["category"]),
            claim_ids=[],
        )
        for item in final_disagreements_raw
        if isinstance(item, Mapping)
    ]
    result = MutualLearningTurnResultV1(
        speech=speech,
        key_claims=claims,
        evidence_trace_claims=traces,
        engagements=engagements,
        answered_question_ids=answered_ids,
        learned_from_others=learned,
        position_summary=cast(str, position_summary),
        position_update=cast(Any, payload.get("position_update")),
        position_update_reason=cast(str, position_update_reason),
        remaining_uncertainty=uncertainty,
        unresolved_issue=cast(str, unresolved_issue) or None,
        question=question,
        used_evidence_id=list(dict.fromkeys(all_evidence_ids)),
        missing_information=missing,
        unresolved_questions=unresolved_questions,
        # The closed Provider schema uses an empty string sentinel because
        # strict JSON schema cannot omit phase-specific keys.  The domain
        # contract uses ``None`` so opening/exchange validators can distinguish
        # absent final-only values from real final-integration content.
        change_from_opening=cast(str, change_from_opening) or None,
        final_consensus=final_consensus,
        final_disagreements=final_disagreements,
        final_recommendation=cast(str, recommendation) or None,
    )
    canonical = _canonical(payload)
    return MappedLLMTurnV1(
        result=result,
        provider_output=payload,
        provider_output_json=canonical,
        provider_output_hash=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    )


# Descriptive aliases for runtime/tests.
map_llm_output = map_provider_output
map_provider_turn_output = map_provider_output
validate_provider_output = validate_llm_output
parse_provider_output = parse_llm_output_json
RepairFeedback = RepairFeedbackV1
LLMProviderOutputV1 = MappedLLMTurnV1
ProviderTurnOutputV1 = MappedLLMTurnV1


__all__ = [
    "LLMOutputError",
    "LLMOutputValidationError",
    "LLMStructuredOutputError",
    "LLM_REPAIR_FEEDBACK_SCHEMA_HASH",
    "LLM_REPAIR_FEEDBACK_VERSION",
    "LLM_TURN_OUTPUT_SCHEMA_HASH",
    "LLM_TURN_OUTPUT_SCHEMA_NAME",
    "LLM_TURN_OUTPUT_SCHEMA_VERSION",
    "MappedLLMTurnV1",
    "LLMProviderOutputV1",
    "ProviderTurnOutputV1",
    "REPAIR_CODES",
    "RepairFeedback",
    "RepairFeedbackV1",
    "canonical_repair_feedback",
    "load_llm_turn_output_schema",
    "provider_wire_output_schema",
    "map_llm_output",
    "map_provider_output",
    "map_provider_turn_output",
    "parse_llm_output_json",
    "parse_provider_output",
    "validate_repair_feedback",
    "validate_llm_output",
    "validate_provider_output",
]
