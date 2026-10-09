"""Operator standing consent for exact provider export manifests."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from app.providers.control import (
    ExportConfirmationV1,
    ExportManifestV1,
    ProviderPolicySnapshotV1,
    confirm_export_manifest,
)
from app.providers.control_repository import ProviderRepository

LOGGER = logging.getLogger(__name__)


def apply_standing_provider_consent(
    repository: ProviderRepository,
    manifest: ExportManifestV1,
    policy: ProviderPolicySnapshotV1,
    settings: object,
) -> bool:
    """Record standing consent for one exact, owner-bound manifest.

    The operator decision is explicit configuration, and the same
    manifest/policy validation used by an explicit teacher action still runs
    before the confirmation row is written. Callers re-run
    ``require_exact_confirmation`` with their owner scope after this helper
    returns so a standing consent can never bypass the course/group/version
    binding.
    """

    if not standing_consent_enabled(settings):
        return False
    try:
        revision = int(manifest.operation_revision)
        confirmation = confirm_export_manifest(
            manifest,
            policy,
            confirmed_at=datetime.now(UTC).isoformat(),
            expected_manifest_hash=manifest.manifest_hash,
            expected_policy_hash=policy.policy_hash,
        )
        identifier = repository.get_export_manifest_id(manifest.manifest_hash)
        if identifier is None:
            return False
        repository.save_export_confirmation(
            identifier,
            ExportConfirmationV1(
                manifest_hash=confirmation.manifest_hash,
                policy_hash=confirmation.policy_hash,
                confirmed_at=confirmation.confirmed_at,
                confirmation_revision=revision,
            ),
        )
    except Exception:
        return False
    LOGGER.warning(
        "Provider disclosure confirmed by standing operator consent manifest=%s",
        manifest.manifest_hash,
    )
    return True


def standing_consent_enabled(settings: object) -> bool:
    if getattr(settings, "provider_standing_consent", False) is True:
        return True
    return (
        getattr(settings, "demo_mode", False) is True
        and getattr(settings, "demo_auto_confirm_provider", False) is True
    )


__all__ = ["apply_standing_provider_consent", "standing_consent_enabled"]
