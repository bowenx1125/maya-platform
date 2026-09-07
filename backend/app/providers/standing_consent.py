"""Demo-only standing consent for exact provider export manifests."""

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

    The operator flag is deliberately narrow: both Demo switches must be on,
    and the same manifest/policy validation used by an explicit teacher action
    still runs before the confirmation row is written. Callers re-run
    ``require_exact_confirmation`` with their owner scope after this helper
    returns so a standing consent can never bypass the course/group/version
    binding.
    """

    if not getattr(settings, "demo_mode", False):
        return False
    if not getattr(settings, "demo_auto_confirm_provider", False):
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
        "Provider disclosure confirmed by standing Demo consent manifest=%s",
        manifest.manifest_hash,
    )
    return True


__all__ = ["apply_standing_provider_consent"]
