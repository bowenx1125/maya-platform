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
    word_count: int | None = Field(default=None, ge=0)
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
    word_count: int = Field(ge=0)
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
    # Present for new segment manifests; absent on older reports whose
    # paragraph output had no support_mode field.
    score_summary: ReportScoreSummary | None = None
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
    # These are retained for legacy report manifests.  segments_v2 carries
    # its position in the authored paragraph text and must not manufacture a
    # position-history projection just to fill these fields.
    initial_position_summary: str = ""
    current_position_summary: str = ""


class ManifestTurn(ClosedModel):
    turn_id: UUID
    participant_id: UUID
    round_no: int = Field(ge=1, le=5)
    turn_index: int = Field(ge=0)
    text_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class ManifestTurnV2(ManifestTurn):
    """A segment turn with its actual canonical evidence references."""

    used_evidence_ids: list[str] = Field(default_factory=list)


class ManifestBarrage(ClosedModel):
    """One frozen, already-anonymized classroom message."""

    barrage_id: str = Field(pattern=r"^B[1-9][0-9]*$")
    turn_index: int = Field(ge=0)
    text: str = Field(min_length=1, max_length=300)


class ManifestReply(ClosedModel):
    """One actual segment-to-barrage binding from a final speech."""

    barrage_id: str = Field(pattern=r"^B[1-9][0-9]*$")
    slot: Literal["A", "B", "C", "D", "E"]
    turn_index: int = Field(ge=0)
    paragraph_index: int = Field(ge=0)


class ManifestTurnSource(ClosedModel):
    turn_source_id: UUID
    turn_id: UUID
    turn_index: int = Field(ge=0)
    rank: int = Field(ge=1, le=6)
    snapshot_id: UUID
    chunk_id: UUID
    chunk_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_filename: str


class ManifestTurnSourceV2(ManifestTurnSource):
    """A deduplicated source row keyed by the canonical receipt ID."""

    evidence_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9_.:-]+$",
    )


class ManifestVote(ClosedModel):
    participant_id: UUID
    order_index: int = Field(ge=0, le=4)
    count: int = Field(ge=0)


class ReportAgentScore(ClosedModel):
    """Code-owned evidence grade counts for one public Agent slot."""

    slot: Literal["A", "B", "C", "D", "E"]
    direct_count: int = Field(ge=0)
    contextual_count: int = Field(ge=0)
    no_match_count: int = Field(ge=0)
    ungraded_count: int = Field(ge=0)
    total_points: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_points(self) -> ReportAgentScore:
        expected = self.direct_count * 5 + self.contextual_count * 2
        if self.total_points != expected:
            raise ValueError("score total does not match grade counts")
        return self


class ReportScoreSummary(ClosedModel):
    """Deterministic per-Agent grade summary carried by new v2 reports."""

    agents: list[ReportAgentScore] = Field(min_length=2, max_length=5)
    direct_count: int = Field(ge=0)
    contextual_count: int = Field(ge=0)
    no_match_count: int = Field(ge=0)
    ungraded_count: int = Field(ge=0)
    total_points: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_totals(self) -> ReportScoreSummary:
        if len({item.slot for item in self.agents}) != len(self.agents):
            raise ValueError("score summary has duplicate Agent slots")
        expected = {
            "direct_count": sum(item.direct_count for item in self.agents),
            "contextual_count": sum(item.contextual_count for item in self.agents),
            "no_match_count": sum(item.no_match_count for item in self.agents),
            "ungraded_count": sum(item.ungraded_count for item in self.agents),
            "total_points": sum(item.total_points for item in self.agents),
        }
        if any(getattr(self, key) != value for key, value in expected.items()):
            raise ValueError("score summary totals do not match Agent rows")
        return self


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


class _ReportInputManifestBase(ClosedModel):
    """Canonical, hashable report input boundary.

    Arrays are normalized in ``canonical_payload`` according to the frozen
    ordering rules.  This model intentionally contains no raw barrage list,
    nickname mapping, unused chunk, full RAG snapshot or provider metadata.
    """

    policy_version: Literal["mock_barrage_insight_v1"] = "mock_barrage_insight_v1"
    render_version: Literal["mock_maya_report_v1"] = "mock_maya_report_v1"
    validator_version: Literal["mock_maya_report_validator_v1"] = "mock_maya_report_validator_v1"
    # Production builders always populate these identity/context fields;
    # defaults keep policy-only fixtures small and backward-compatible.
    debate_id: UUID | None = None
    topic: str = ""
    participants: list[ManifestParticipant]
    votes: list[ManifestVote]
    insight: ManifestInsight

    @model_validator(mode="after")
    def validate_no_float_values(self) -> _ReportInputManifestBase:
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


class ReportInputManifestV1(_ReportInputManifestBase):
    manifest_version: Literal["report_input_manifest_v1"] = "report_input_manifest_v1"
    turns: list[ManifestTurn]
    turn_sources: list[ManifestTurnSource]


class ReportDiscussionInfluence(ClosedModel):
    slot: Literal["A", "B", "C", "D", "E"]
    point: str = Field(min_length=1)


class ReportDiscussionMemory(ClosedModel):
    """Session-only reflection; never a Persona update or classroom speech."""

    slot: Literal["A", "B", "C", "D", "E"]
    position: str = Field(min_length=1)
    change: Literal["retained", "qualified", "revised"]
    reason: str = Field(min_length=1)
    influence: ReportDiscussionInfluence | None = None
    unresolved_question: str


class ReportInputManifestV2(_ReportInputManifestBase):
    """Versioned manifest for segment turns and anonymous final input."""

    manifest_version: Literal["report_input_manifest_v2"] = "report_input_manifest_v2"
    turn_protocol: Literal["segments_v2"] = "segments_v2"
    turns: list[ManifestTurnV2]
    turn_sources: list[ManifestTurnSourceV2]
    classroom_barrages: list[ManifestBarrage] = Field(default_factory=list)
    replies: list[ManifestReply] = Field(default_factory=list)
    # Optional so manifests written before paragraph grading retain their
    # exact canonical bytes and input hash.
    score_summary: ReportScoreSummary | None = None
    discussion_memories: list[ReportDiscussionMemory] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_segment_manifest(self) -> ReportInputManifestV2:
        barrage_ids = [item.barrage_id for item in self.classroom_barrages]
        if len(barrage_ids) != len(set(barrage_ids)):
            raise ValueError("segment report manifest has duplicate barrage IDs")
        reply_keys = [
            (item.slot, item.turn_index, item.paragraph_index, item.barrage_id)
            for item in self.replies
        ]
        if len(reply_keys) != len(set(reply_keys)):
            raise ValueError("segment report manifest has duplicate reply bindings")
        if any(item.barrage_id not in set(barrage_ids) for item in self.replies):
            raise ValueError("segment report manifest reply is outside frozen barrages")
        known_turns = {item.turn_index for item in self.turns}
        if any(item.turn_index not in known_turns for item in self.replies):
            raise ValueError("segment report manifest reply is outside public turns")
        source_ids = {item.evidence_id for item in self.turn_sources}
        used_ids = {evidence_id for turn in self.turns for evidence_id in turn.used_evidence_ids}
        if not used_ids.issubset(source_ids):
            raise ValueError("segment report manifest evidence is outside source rows")
        if self.score_summary is not None:
            participant_slots = {item.slot for item in self.participants}
            score_slots = {item.slot for item in self.score_summary.agents}
            if score_slots != participant_slots:
                raise ValueError("segment report score rows do not match participants")
        known_slots = {item.slot for item in self.participants}
        memory_slots = [item.slot for item in self.discussion_memories]
        if len(memory_slots) != len(set(memory_slots)) or not set(memory_slots).issubset(
            known_slots
        ):
            raise ValueError("discussion memories do not match participants")
        if any(
            item.influence is not None and item.influence.slot not in known_slots
            for item in self.discussion_memories
        ):
            raise ValueError("discussion memory influence is outside the debate")
        return self

    def canonical_payload(self) -> dict[str, Any]:
        payload = super().canonical_payload()
        if not payload.get("discussion_memories"):
            payload.pop("discussion_memories", None)
        else:
            payload["discussion_memories"] = sorted(
                payload["discussion_memories"], key=lambda row: str(row["slot"])
            )
        if payload.get("score_summary") is None:
            payload.pop("score_summary", None)
        elif isinstance(payload.get("score_summary"), dict):
            score_summary = payload["score_summary"]
            if isinstance(score_summary.get("agents"), list):
                score_summary["agents"] = sorted(
                    score_summary["agents"], key=lambda row: str(row["slot"])
                )
        payload["classroom_barrages"] = sorted(
            payload["classroom_barrages"],
            key=lambda row: (str(row["barrage_id"]), int(row["turn_index"])),
        )
        payload["replies"] = sorted(
            payload["replies"],
            key=lambda row: (
                int(row["turn_index"]),
                int(row["paragraph_index"]),
                str(row["slot"]),
                str(row["barrage_id"]),
            ),
        )
        return payload


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
    "ManifestTurnV2",
    "ManifestTurnSource",
    "ManifestTurnSourceV2",
    "ManifestBarrage",
    "ManifestReply",
    "ManifestVote",
    "MockBarrageInsightResult",
    "ReadyReportRevision",
    "Report",
    "ContinueRealReportRequest",
    "ReportInputManifestV1",
    "ReportInputManifestV2",
    "ReportAgentScore",
    "ReportScoreSummary",
    "ReportRevisionSummary",
    "ReportSectionOutput",
]
