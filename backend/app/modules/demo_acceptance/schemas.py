"""Closed safe DTOs for the local Real-Core Demo acceptance ledger."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.providers.control import DEMO_ACCEPTANCE_MAX_CALLS, DEMO_ACCEPTANCE_PLAN_VERSION

_SHA256_PATTERN = r"^[0-9a-f]{64}$"
AcceptanceRunState = Literal["prepared", "executing", "executed", "verified"]
ProviderOperationState = Literal[
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


class _ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DemoAcceptanceRunCreateRequest(_ClosedModel):
    fixture_hash: str = Field(pattern=_SHA256_PATTERN)
    target_agent_id: UUID
    target_version_id: UUID
    debate_id: UUID | None = None


class DemoAcceptanceRunBindDebateRequest(_ClosedModel):
    debate_id: UUID


class DemoAcceptanceRunBindReportRequest(_ClosedModel):
    report_revision_id: UUID


class DemoAcceptanceCallRequest(_ClosedModel):
    operation_id: UUID
    call_no: int = Field(ge=1, le=DEMO_ACCEPTANCE_MAX_CALLS)


class DemoAcceptanceCall(_ClosedModel):
    """A provider-neutral operation status bound to one call ordinal."""

    operation_id: UUID
    call_no: int = Field(ge=1, le=DEMO_ACCEPTANCE_MAX_CALLS)
    purpose: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9_]+$")
    state: ProviderOperationState
    request_count: int = Field(ge=0)
    charged_request_count: int = Field(ge=0)


class DemoAcceptanceRunResponse(_ClosedModel):
    id: UUID
    plan_version: Literal["real_core_demo_v2"] = DEMO_ACCEPTANCE_PLAN_VERSION
    fixture_hash: str = Field(pattern=_SHA256_PATTERN)
    baseline_agent_id: UUID
    baseline_version_id: UUID
    baseline_snapshot_id: UUID
    target_agent_id: UUID
    target_version_id: UUID
    debate_id: UUID | None = None
    report_revision_id: UUID | None = None
    state: AcceptanceRunState
    starting_charged_requests: Literal[0] = 0
    call_count: int = Field(ge=0, le=DEMO_ACCEPTANCE_MAX_CALLS)
    charged_request_count: int = Field(ge=0)
    calls: tuple[DemoAcceptanceCall, ...] = ()


# Short aliases keep the module easy to discover without widening the wire DTOs.
AcceptanceRunCreateRequest = DemoAcceptanceRunCreateRequest
AcceptanceRunResponse = DemoAcceptanceRunResponse
AcceptanceCallRequest = DemoAcceptanceCallRequest


__all__ = [
    "AcceptanceCallRequest",
    "AcceptanceRunCreateRequest",
    "AcceptanceRunResponse",
    "DemoAcceptanceCall",
    "DemoAcceptanceCallRequest",
    "DemoAcceptanceRunBindDebateRequest",
    "DemoAcceptanceRunBindReportRequest",
    "DemoAcceptanceRunCreateRequest",
    "DemoAcceptanceRunResponse",
]
