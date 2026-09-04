"""Closed M14 DTOs and immutable report-manifest types."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ClosedModel(BaseModel):
    """A DTO boundary that rejects accidental provider/private fields."""

    model_config = ConfigDict(extra="forbid")


InsightCategory = Literal["support", "challenge", "question"]
InsightStatus = Literal["not_started", "generating", "ready", "failed"]
ReportStatus = Literal["not_started", "generating", "ready", "failed"]


class BarrageInsightInput(ClosedModel):
    """The only input accepted by a BarrageInsightPolicy.

    In particular this type has no nickname, author, user, vote, device or
    participant field.  A self-disclosed name inside ``raw_text`` remains
    ordinary free text and is outside the Demo's semantic PII promise.
    """

    message_id: UUID
    raw_text: str


class BarrageInsightItem(ClosedModel):
    category: InsightCategory
    summary: str
    count: int = Field(ge=1)


class BarrageInsight(ClosedModel):
    status: InsightStatus
    included_count: int = Field(ge=0)
    filtered_count: int = Field(ge=0)
    items: list[BarrageInsightItem]


class ReportRevisionSummary(ClosedModel):
    id: UUID
    revision_no: int = Field(ge=1)
    status: Literal["generating", "ready", "failed"]
    word_count: int | None = Field(default=None, ge=600, le=900)
    safe_error_code: str | None = None
    created_at: datetime

    @model_validator(mode="after")
    def validate_shape(self) -> ReportRevisionSummary:
        if self.status == "ready" and self.word_count is None:
            raise ValueError("ready report revision requires word_count")
        if self.status != "ready" and self.word_count is not None:
            raise ValueError("non-ready report revision cannot expose word_count")
        if self.status == "failed" and not self.safe_error_code:
            raise ValueError("failed report revision requires safe_error_code")
        if self.status != "failed" and self.safe_error_code is not None:
            raise ValueError("only failed report revisions expose safe_error_code")
        return self


class GeneratingReportRevision(ClosedModel):
    id: UUID
    revision_no: int = Field(ge=1)
    status: Literal["generating"]
    english_markdown: None = None
    word_count: None = None
    safe_error_code: None = None
    created_at: datetime


class ReadyReportRevision(ClosedModel):
    id: UUID
    revision_no: int = Field(ge=1)
    status: Literal["ready"]
    english_markdown: str = Field(min_length=1)
    word_count: int = Field(ge=600, le=900)
    safe_error_code: None = None
    created_at: datetime


class FailedReportRevision(ClosedModel):
    id: UUID
    revision_no: int = Field(ge=1)
    status: Literal["failed"]
    english_markdown: None = None
    word_count: None = None
    safe_error_code: str = Field(min_length=1)
    created_at: datetime


ReportRevision = GeneratingReportRevision | ReadyReportRevision | FailedReportRevision


class Report(ClosedModel):
    debate_id: UUID
    generation_status: ReportStatus
    latest_attempt_status: ReportStatus
    insight: BarrageInsight
    active_revision_id: UUID | None = None
    current_success_revision: ReadyReportRevision | None = None


class ContinueRealReportRequest(ClosedModel):
    """Teacher-runner acknowledgement for one already attached report call."""

    manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    call_no: int = Field(ge=1, le=8)


# Internal deterministic Mock policy result.  ``item_key`` is an in-memory
# grouping key and is never exposed in a public DTO or report manifest.
class InsightItemCandidate(ClosedModel):
    item_key: str
    category: InsightCategory
    summary: str
    first_order: int = Field(ge=0)


class InsightAssignmentCandidate(ClosedModel):
    message_id: UUID
    disposition: Literal["included", "filtered"]
    item_key: str | None = None
    filter_reason: str | None = None


class MockBarrageInsightResult(ClosedModel):
    policy_key: Literal["mock_barrage_insight_v1"] = "mock_barrage_insight_v1"
    items: list[InsightItemCandidate]
    assignments: list[InsightAssignmentCandidate]
    included_count: int = Field(ge=0)
    filtered_count: int = Field(ge=0)


class ManifestParticipant(ClosedModel):
    participant_id: UUID
    slot: Literal["A", "B", "C", "D", "E"]
    order_index: int = Field(ge=0, le=4)
    agent_name: str
    stance_mode: Literal["assigned", "open"]
    initial_stance: Literal["support", "oppose", "neutral"] | None
    current_stance: Literal["support", "oppose", "neutral"] | None
    initial_position_summary: str
    current_position_summary: str


class ManifestTurn(ClosedModel):
    turn_id: UUID
    participant_id: UUID
    round_no: int = Field(ge=1, le=2)
    turn_index: int = Field(ge=0)
    text_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class ManifestTurnSource(ClosedModel):
    turn_source_id: UUID
    turn_id: UUID
    turn_index: int = Field(ge=0)
    rank: int = Field(ge=1, le=6)
    snapshot_id: UUID
    chunk_id: UUID
    chunk_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_filename: str


class ManifestVote(ClosedModel):
    participant_id: UUID
    order_index: int = Field(ge=0, le=4)
    count: int = Field(ge=0)


class ManifestInsightItem(ClosedModel):
    item_id: UUID
    order_index: int = Field(ge=0)
    category: InsightCategory
    summary: str
    count: int = Field(ge=1)


class ManifestInsight(ClosedModel):
    snapshot_id: UUID
    revision: int = Field(ge=1)
    included_count: int = Field(ge=0)
    filtered_count: int = Field(ge=0)
    items: list[ManifestInsightItem]


class ReportInputManifestV1(ClosedModel):
    """Canonical, hashable report input boundary.

    Arrays are normalized in ``canonical_payload`` according to the frozen
    ordering rules.  This model intentionally contains no raw barrage list,
    nickname mapping, unused chunk, full RAG snapshot or provider metadata.
    """

    manifest_version: Literal["report_input_manifest_v1"] = "report_input_manifest_v1"
    policy_version: Literal["mock_barrage_insight_v1"] = "mock_barrage_insight_v1"
    render_version: Literal["mock_maya_report_v1"] = "mock_maya_report_v1"
    validator_version: Literal["mock_maya_report_validator_v1"] = "mock_maya_report_validator_v1"
    # Production builders always populate these identity/context fields;
    # defaults keep policy-only fixtures small and backward-compatible.
    debate_id: UUID | None = None
    topic: str = ""
    participants: list[ManifestParticipant]
    turns: list[ManifestTurn]
    turn_sources: list[ManifestTurnSource]
    votes: list[ManifestVote]
    insight: ManifestInsight

    @model_validator(mode="after")
    def validate_no_float_values(self) -> ReportInputManifestV1:
        _reject_floats(self.model_dump(mode="python"))
        return self

    def canonical_payload(self) -> dict[str, Any]:
        payload = self.model_dump(mode="json", exclude_none=False)
        payload["participants"] = sorted(
            payload["participants"],
            key=lambda row: (row["order_index"], row["participant_id"]),
        )
        payload["turns"] = sorted(
            payload["turns"], key=lambda row: (row["turn_index"], row["turn_id"])
        )
        payload["turn_sources"] = sorted(
            payload["turn_sources"],
            key=lambda row: (row["turn_index"], row["rank"], row["turn_source_id"]),
        )
        payload["votes"] = sorted(
            payload["votes"],
            key=lambda row: (row["order_index"], row["participant_id"]),
        )
        insight = payload["insight"]
        insight["items"] = sorted(
            insight["items"], key=lambda row: (row["order_index"], row["item_id"])
        )
        _reject_floats(payload)
        return payload

    def canonical_json_bytes(self) -> bytes:
        return json.dumps(
            self.canonical_payload(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")

    def canonical_json(self) -> str:
        return self.canonical_json_bytes().decode("utf-8")

    def input_hash(self) -> str:
        return hashlib.sha256(self.canonical_json_bytes()).hexdigest()


class ReportSectionOutput(ClosedModel):
    """Closed structured output produced before Markdown rendering."""

    debate_overview: str
    evidence_and_arguments: str
    areas_of_convergence: str
    continuing_tensions_and_questions: str
    classroom_perspectives: str
    mutual_learning_reflection: str


def _reject_floats(value: Any) -> None:
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("manifest cannot contain non-finite floating values")
        raise ValueError("manifest cannot contain floating-point values")
    if isinstance(value, dict):
        for child in value.values():
            _reject_floats(child)
    elif isinstance(value, list):
        for child in value:
            _reject_floats(child)


__all__ = [
    "BarrageInsight",
    "BarrageInsightInput",
    "BarrageInsightItem",
    "FailedReportRevision",
    "GeneratingReportRevision",
    "InsightAssignmentCandidate",
    "InsightItemCandidate",
    "ManifestInsight",
    "ManifestInsightItem",
    "ManifestParticipant",
    "ManifestTurn",
    "ManifestTurnSource",
    "ManifestVote",
    "MockBarrageInsightResult",
    "ReadyReportRevision",
    "Report",
    "ContinueRealReportRequest",
    "ReportInputManifestV1",
    "ReportRevisionSummary",
    "ReportSectionOutput",
]
