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
    "public_predecessor_speech",
    "current_evidence_excerpt",
    "opaque_local_id",
    "current_tts_speech",
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
]
