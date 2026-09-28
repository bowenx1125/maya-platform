"""Public DTOs for the teacher ProviderDataCallV1 confirmation screen.

The disclosure object is deliberately smaller than the server-side policy and
manifest.  It contains the facts a teacher must understand before consenting,
while hash/revision fields live only in the response envelope used for CAS.
No selector, endpoint, external resource ID, credential or ledger value is a
public field here.
"""

from __future__ import annotations

from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

DisclosureFieldClass = Literal[
    "topic_and_platform_rules",
    "confirmed_structured_persona",
    "teacher_agent_instructions",
    "authorized_courseware_text",
    "public_predecessor_speech",
    "current_evidence_excerpt",
    "opaque_local_id",
    "public_agent_name",
    "anonymous_insight_summary",
    "anonymous_classroom_barrage",
    "aggregate_vote_count",
    "current_tts_speech",
    "server_authored_structure_repair_feedback",
]

_SHA256_PATTERN = r"^[0-9a-f]{64}$"


class ProviderDataCallDisclosureV1(BaseModel):
    """Exact teacher-facing data-processing disclosure."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    supplier_display_name: str = Field(min_length=1)
    region: Literal["cn-beijing"]
    purpose: str = Field(min_length=1)
    outbound_field_classes: tuple[DisclosureFieldClass, ...] = Field(min_length=1)
    storage_fact: str = Field(min_length=1)
    no_training_basis: str = Field(min_length=1)
    retention_setting: str = Field(min_length=1)


class ProviderDataCallDisclosureResponseV1(BaseModel):
    """Disclosure plus non-secret CAS material for teacher confirmation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    disclosure: ProviderDataCallDisclosureV1
    policy_hash: str = Field(pattern=_SHA256_PATTERN)
    manifest_hash: str = Field(pattern=_SHA256_PATTERN)
    confirmation_revision: int = Field(ge=1)

    @property
    def export_manifest_hash(self) -> str:
        """Compatibility name used by the server-side control contract."""

        return self.manifest_hash

    @property
    def revision(self) -> int:
        """Compatibility name for callers that used the generic revision."""

        return self.confirmation_revision


_SAFE_SCOPE_PATTERN = r"^[A-Za-z0-9_.:-]{1,255}$"


class ProviderDataCallManifestSummaryV1(BaseModel):
    """One teacher-visible, exact manifest waiting for (or holding) consent.

    This is intentionally an identity/status summary, not a disclosure.  The
    provider model, endpoint, policy details, owner IDs and manifest payload
    remain server-only.  ``confirmation_revision`` is the revision a teacher
    must review/confirm even when ``confirmed`` is false.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    manifest_hash: str = Field(pattern=_SHA256_PATTERN)
    turn_id: str | None = Field(default=None, pattern=_SAFE_SCOPE_PATTERN)
    confirmation_revision: int = Field(ge=1)
    confirmed: bool


class ProviderDataCallManifestListResponseV1(BaseModel):
    """Teacher-only list of exact embedding-query manifests for one scope."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scope_id: str = Field(pattern=_SAFE_SCOPE_PATTERN)
    items: tuple[ProviderDataCallManifestSummaryV1, ...] = ()


class ProviderDataCallDebateManifestSummaryV1(BaseModel):
    """Teacher-visible status for one exact LLM turn manifest.

    The debate envelope is intentionally separate from the older query-scope
    listing.  A turn manifest is owned by ``Turn -> Debate -> Course`` and
    therefore always has a non-null opaque turn identity.  Provider/model,
    prompt, policy and ledger details stay on the server side.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    turn_id: str = Field(pattern=_SAFE_SCOPE_PATTERN)
    manifest_hash: str = Field(pattern=_SHA256_PATTERN)
    confirmation_revision: int = Field(ge=1)
    confirmed: bool


class ProviderDataCallDebateManifestListResponseV1(BaseModel):
    """Teacher-only exact pending LLM manifests for one Debate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    debate_id: str = Field(pattern=_SAFE_SCOPE_PATTERN)
    items: tuple[ProviderDataCallDebateManifestSummaryV1, ...] = ()


class ProviderDataCallReportManifestSummaryV1(BaseModel):
    """Teacher-visible status for one immutable Real Report preparation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    report_revision_id: str | None = Field(default=None, pattern=_SAFE_SCOPE_PATTERN)
    manifest_hash: str = Field(pattern=_SHA256_PATTERN)
    confirmation_revision: int = Field(ge=1)
    confirmed: bool


class ProviderDataCallReportManifestListResponseV1(BaseModel):
    """Teacher-only pending Real Report manifests for one Debate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    debate_id: str = Field(pattern=_SAFE_SCOPE_PATTERN)
    items: tuple[ProviderDataCallReportManifestSummaryV1, ...] = ()


class ProviderDataCallPublicationManifestSummaryV1(BaseModel):
    """One teacher-visible, exact embedding publication manifest.

    Publication manifests are bound to an AgentVersion rather than a debate
    turn.  The DTO intentionally carries only the CAS/status values needed by
    the teacher confirmation flow; provider selectors, policy hashes, owner
    IDs and server-side ledger fields remain private.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    manifest_hash: str = Field(pattern=_SHA256_PATTERN)
    confirmation_revision: int = Field(ge=1)
    confirmed: bool


class ProviderDataCallPublicationManifestListResponseV1(BaseModel):
    """Teacher-only list of exact embedding manifests for one AgentVersion."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    agent_version_id: str = Field(pattern=_SAFE_SCOPE_PATTERN)
    items: tuple[ProviderDataCallPublicationManifestSummaryV1, ...] = ()


class ProviderDataCallConfirmationRequestV1(BaseModel):
    """Teacher confirmation bound to the exact disclosure revision and hashes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_hash: str = Field(pattern=_SHA256_PATTERN)
    manifest_hash: str = Field(
        pattern=_SHA256_PATTERN,
        validation_alias=AliasChoices("manifest_hash", "export_manifest_hash"),
    )
    expected_revision: int = Field(ge=1)

    @property
    def export_manifest_hash(self) -> str:
        """Compatibility name used by the provider reservation contract."""

        return self.manifest_hash


# Descriptive aliases keep the contract discoverable to the integration
# window without duplicating any wire shape.
ProviderDataCallV1 = ProviderDataCallDisclosureV1
ProviderDataCallDisclosure = ProviderDataCallDisclosureV1
ProviderDataCallDisclosureResponse = ProviderDataCallDisclosureResponseV1
ProviderDataCallManifestSummary = ProviderDataCallManifestSummaryV1
ProviderDataCallManifestListResponse = ProviderDataCallManifestListResponseV1
ProviderDataCallPublicationManifestSummary = ProviderDataCallPublicationManifestSummaryV1
ProviderDataCallPublicationManifestListResponse = ProviderDataCallPublicationManifestListResponseV1
ProviderDataCallDebateManifestSummary = ProviderDataCallDebateManifestSummaryV1
ProviderDataCallDebateManifestListResponse = ProviderDataCallDebateManifestListResponseV1
ProviderDataCallReportManifestSummary = ProviderDataCallReportManifestSummaryV1
ProviderDataCallReportManifestListResponse = ProviderDataCallReportManifestListResponseV1
# AgentVersion naming aliases keep the dedicated route contract discoverable
# without introducing a second wire shape.
ProviderDataCallAgentVersionManifestSummaryV1 = ProviderDataCallPublicationManifestSummaryV1
ProviderDataCallAgentVersionManifestListResponseV1 = (
    ProviderDataCallPublicationManifestListResponseV1
)
ProviderDataCallConfirmationRequest = ProviderDataCallConfirmationRequestV1


__all__ = [
    "DisclosureFieldClass",
    "ProviderDataCallConfirmationRequest",
    "ProviderDataCallConfirmationRequestV1",
    "ProviderDataCallDisclosure",
    "ProviderDataCallDisclosureResponseV1",
    "ProviderDataCallDisclosureResponse",
    "ProviderDataCallDisclosureV1",
    "ProviderDataCallV1",
    "ProviderDataCallManifestListResponse",
    "ProviderDataCallManifestListResponseV1",
    "ProviderDataCallManifestSummary",
    "ProviderDataCallManifestSummaryV1",
    "ProviderDataCallDebateManifestSummary",
    "ProviderDataCallDebateManifestSummaryV1",
    "ProviderDataCallDebateManifestListResponse",
    "ProviderDataCallDebateManifestListResponseV1",
    "ProviderDataCallReportManifestSummaryV1",
    "ProviderDataCallReportManifestListResponseV1",
    "ProviderDataCallReportManifestSummary",
    "ProviderDataCallReportManifestListResponse",
    "ProviderDataCallPublicationManifestListResponse",
    "ProviderDataCallPublicationManifestListResponseV1",
    "ProviderDataCallPublicationManifestSummary",
    "ProviderDataCallPublicationManifestSummaryV1",
    "ProviderDataCallAgentVersionManifestListResponseV1",
    "ProviderDataCallAgentVersionManifestSummaryV1",
]
