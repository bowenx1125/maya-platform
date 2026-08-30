"""Bounded, fail-closed PromptRequestV1 attempt semantics.

The state machine here is intentionally small and side-effect free.  It tells
an ORM/provider adapter whether it may prepare a second attempt; it never
sends a request, retries retrieval, or records an external operation itself.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from .prompt_request import PromptRepairFeedbackV1, PromptRequestV1

MAX_PROMPT_ATTEMPTS = 2


class PromptAcceptanceState(StrEnum):
    """What the adapter can prove about supplier acceptance."""

    NOT_SENT = "not_sent"
    ACCEPTED = "accepted"
    UNKNOWN = "unknown"


class PromptFailureKind(StrEnum):
    """Safe classes used by the retry decision, not raw provider errors."""

    STRUCTURE_INVALID = "structure_invalid"
    TRANSPORT_NOT_SENT = "transport_not_sent"
    TRANSPORT_UNKNOWN = "transport_unknown"
    BUDGET = "budget"
    AUTH = "auth"
    SAFETY = "safety"
    MODEL_UNAVAILABLE = "model_unavailable"
    STALE_FENCE = "stale_generation_fence"
    HASH_CHANGED = "hash_changed"
    PROVIDER_REJECTED = "provider_rejected"
    UNKNOWN = "unknown"
    RETRIEVAL_TECHNICAL = "retrieval_technical"


RetryAction = Literal["retry_structure", "retry_transport", "retry_retrieval", "fail_closed"]


class PromptAttemptError(ValueError):
    """The local attempt state or repair feedback is not contract-valid."""

    def __init__(self, message: str, *, code: str = "prompt_attempt_invalid") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class PromptAttemptDecision:
    """Pure decision returned to the durable operation adapter."""

    attempt_no: int
    retry: bool
    action: RetryAction
    safe_error_code: str
    next_attempt_no: int | None = None
    reuse_request: bool = True
    reuse_retrieval: bool = True

    @property
    def retry_allowed(self) -> bool:
        return self.retry


@dataclass(frozen=True, slots=True)
class FrozenPromptIdentity:
    """Hashes/identity that must remain stable across a repair attempt."""

    request_hash: str
    rule_set_hash: str
    persona_spec_hash: str
    transcript_hash: str
    receipt_hash: str

    @classmethod
    def from_request(cls, request: PromptRequestV1) -> FrozenPromptIdentity:
        return cls(
            request_hash=request.request_hash,
            rule_set_hash=request.rule_set_hash,
            persona_spec_hash=request.persona_spec_hash,
            transcript_hash=request.transcript_hash,
            receipt_hash=request.receipt_hash,
        )

    def matches(self, request: PromptRequestV1) -> bool:
        return (
            request.rule_set_hash == self.rule_set_hash
            and request.persona_spec_hash == self.persona_spec_hash
            and request.transcript_hash == self.transcript_hash
            and request.receipt_hash == self.receipt_hash
        )


class PromptAttemptPolicy:
    """Authorize at most one frozen transport or structure retry."""

    def __init__(self, *, max_attempts: int = MAX_PROMPT_ATTEMPTS) -> None:
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or max_attempts < 1:
            raise ValueError("max_attempts must be a positive integer")
        if max_attempts > MAX_PROMPT_ATTEMPTS:
            raise ValueError("PromptRequestV1 permits at most two attempts")
        self.max_attempts = max_attempts

    def decide(
        self,
        *,
        attempt_no: int,
        failure: PromptFailureKind | str,
        acceptance: PromptAcceptanceState | str,
    ) -> PromptAttemptDecision:
        """Classify a known local outcome without inspecting raw errors.

        Structure repair is eligible only when the supplier response is known
        accepted.  A transport retry is eligible only when no acceptance is
        proven.  Unknown acceptance, including a timeout after acceptance,
        always fails closed.
        """

        if isinstance(attempt_no, bool) or not isinstance(attempt_no, int) or attempt_no < 1:
            raise PromptAttemptError("attempt number is invalid")
        try:
            failure_kind = PromptFailureKind(failure)
            acceptance_state = PromptAcceptanceState(acceptance)
        except ValueError:
            # Unknown classifications are fail-closed rather than accidentally
            # treated as a transport that is safe to resend.
            return PromptAttemptDecision(
                attempt_no=attempt_no,
                retry=False,
                action="fail_closed",
                safe_error_code="prompt_attempt_unknown",
                reuse_request=True,
                reuse_retrieval=True,
            )
        if attempt_no >= self.max_attempts:
            return PromptAttemptDecision(
                attempt_no=attempt_no,
                retry=False,
                action="fail_closed",
                safe_error_code="prompt_attempt_exhausted",
            )
        if (
            failure_kind is PromptFailureKind.RETRIEVAL_TECHNICAL
            and acceptance_state is PromptAcceptanceState.NOT_SENT
        ):
            # Retrieval retry is intentionally distinct from an LLM attempt:
            # the caller may search again only before any LLM request exists.
            return PromptAttemptDecision(
                attempt_no=attempt_no,
                retry=True,
                action="retry_retrieval",
                safe_error_code="prompt_retrieval_technical",
                next_attempt_no=attempt_no,
                reuse_request=False,
                reuse_retrieval=False,
            )
        if failure_kind is PromptFailureKind.STRUCTURE_INVALID:
            if acceptance_state is PromptAcceptanceState.ACCEPTED:
                return PromptAttemptDecision(
                    attempt_no=attempt_no,
                    retry=True,
                    action="retry_structure",
                    safe_error_code="prompt_structure_invalid",
                    next_attempt_no=attempt_no + 1,
                    reuse_request=False,
                    reuse_retrieval=True,
                )
            return PromptAttemptDecision(
                attempt_no=attempt_no,
                retry=False,
                action="fail_closed",
                safe_error_code="prompt_acceptance_unknown"
                if acceptance_state is PromptAcceptanceState.UNKNOWN
                else "prompt_structure_not_accepted",
            )
        if (
            failure_kind is PromptFailureKind.TRANSPORT_NOT_SENT
            and acceptance_state is PromptAcceptanceState.NOT_SENT
        ):
            return PromptAttemptDecision(
                attempt_no=attempt_no,
                retry=True,
                action="retry_transport",
                safe_error_code="prompt_transport_not_sent",
                next_attempt_no=attempt_no + 1,
                reuse_request=True,
                reuse_retrieval=True,
            )
        safe_code = {
            PromptFailureKind.TRANSPORT_UNKNOWN: "prompt_acceptance_unknown",
            PromptFailureKind.BUDGET: "prompt_budget_failed",
            PromptFailureKind.AUTH: "prompt_auth_failed",
            PromptFailureKind.SAFETY: "prompt_safety_refused",
            PromptFailureKind.MODEL_UNAVAILABLE: "prompt_model_unavailable",
            PromptFailureKind.STALE_FENCE: "prompt_stale_generation_fence",
            PromptFailureKind.HASH_CHANGED: "prompt_hash_changed",
            PromptFailureKind.PROVIDER_REJECTED: "prompt_provider_rejected",
            PromptFailureKind.UNKNOWN: "prompt_attempt_unknown",
            PromptFailureKind.RETRIEVAL_TECHNICAL: "prompt_retrieval_technical",
        }.get(failure_kind, "prompt_attempt_failed")
        return PromptAttemptDecision(
            attempt_no=attempt_no,
            retry=False,
            action="fail_closed",
            safe_error_code=safe_code,
        )


def repair_prompt_request(
    request: PromptRequestV1,
    *,
    safe_error_code: str,
    json_pointers: Sequence[str] = (),
) -> PromptRequestV1:
    """Append pointer-only structure feedback to a frozen request.

    The returned request is the only permitted attempt-two difference.  No
    retrieval callable is accepted here, making an accidental re-retrieval
    impossible at this seam.
    """

    if request.repair_feedback is not None:
        raise PromptAttemptError(
            "a PromptRequestV1 can receive structure feedback only once",
            code="prompt_repair_already_applied",
        )
    try:
        feedback = PromptRepairFeedbackV1(
            safe_error_code=safe_error_code,
            json_pointers=tuple(json_pointers),
        )
    except ValueError as exc:
        raise PromptAttemptError("structure repair feedback is invalid") from exc
    repaired = request.model_copy(update={"repair_feedback": feedback})
    identity = FrozenPromptIdentity.from_request(request)
    if not identity.matches(repaired):
        raise PromptAttemptError("structure repair changed a frozen request hash")
    return repaired


def assert_frozen_prompt_identity(
    base: PromptRequestV1,
    candidate: PromptRequestV1,
) -> None:
    """Raise unless only the allowed repair feedback differs."""

    if base.repair_feedback is not None:
        raise PromptAttemptError("the base request already contains repair feedback")
    if candidate.repair_feedback is None:
        raise PromptAttemptError("the repair request must contain feedback")
    if not FrozenPromptIdentity.from_request(base).matches(candidate):
        raise PromptAttemptError("rule, Persona, transcript or receipt hash changed")
    if candidate.model_copy(update={"repair_feedback": None}) != base:
        raise PromptAttemptError("structure repair changed fields beyond safe feedback")


def decide_prompt_retry(
    *,
    attempt_no: int,
    failure: PromptFailureKind | str,
    acceptance: PromptAcceptanceState | str,
    max_attempts: int = MAX_PROMPT_ATTEMPTS,
) -> PromptAttemptDecision:
    return PromptAttemptPolicy(max_attempts=max_attempts).decide(
        attempt_no=attempt_no,
        failure=failure,
        acceptance=acceptance,
    )


def can_retry_prompt(
    *,
    attempt_no: int,
    failure: PromptFailureKind | str,
    acceptance: PromptAcceptanceState | str,
) -> bool:
    return decide_prompt_retry(
        attempt_no=attempt_no,
        failure=failure,
        acceptance=acceptance,
    ).retry


# Friendly aliases for callers that use "structure feedback" terminology.
append_repair_feedback = repair_prompt_request
PromptRepairFeedback = PromptRepairFeedbackV1
AttemptDecision = PromptAttemptDecision


__all__ = [
    "AttemptDecision",
    "FrozenPromptIdentity",
    "MAX_PROMPT_ATTEMPTS",
    "PromptAcceptanceState",
    "PromptAttemptDecision",
    "PromptAttemptError",
    "PromptAttemptPolicy",
    "PromptFailureKind",
    "PromptRepairFeedback",
    "append_repair_feedback",
    "assert_frozen_prompt_identity",
    "can_retry_prompt",
    "decide_prompt_retry",
    "repair_prompt_request",
]
