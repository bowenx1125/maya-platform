"""Reinstall reviewed provider policies that outlive the runtime database.

A reviewed policy records which supplier documents a person read, when, and at
what content hash. It is operator evidence, not runtime state, but it lived
only in ``data/maya.sqlite3`` — so every runtime reset silently removed it and
the next real turn failed with ``provider_preflight_blocked``, blaming a
missing policy for what was really a wiped database.

The reviewed document is therefore written beside the other private config,
outside ``data/``, and reinstalled here on startup when its row is absent. The
file is the operator's, never the repository's: it is git-ignored, mode 0600,
and this module only reads it.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.providers.control import ProviderPolicySnapshotV1
from app.providers.control_repository import ProviderRepository

LOGGER = logging.getLogger(__name__)

POLICY_DIRECTORY_NAME = "provider-policies"
# Identity fields travel with the document but are not part of the hashed
# policy, so they are dropped before the snapshot is rebuilt.
_NON_POLICY_FIELDS = frozenset({"reviewed", "policy_hash", "provider", "model", "contract_version"})


def policy_directory(config_root: Path) -> Path:
    return config_root / POLICY_DIRECTORY_NAME


def _snapshot_from_document(document: dict[str, Any]) -> ProviderPolicySnapshotV1 | None:
    fields = {key: value for key, value in document.items() if key not in _NON_POLICY_FIELDS}
    try:
        snapshot = ProviderPolicySnapshotV1(**fields)
    except Exception:
        return None
    supplied = document.get("policy_hash")
    # A document whose hash no longer matches its fields was edited by hand.
    # Reinstalling it would let an unreviewed change inherit a reviewed record.
    if isinstance(supplied, str) and supplied and supplied != snapshot.policy_hash:
        return None
    return snapshot


def ensure_reviewed_policies(session: Any, config_root: Path) -> int:
    """Install any reviewed policy whose row is missing. Returns how many."""

    directory = policy_directory(config_root)
    if not directory.is_dir():
        return 0
    repository = ProviderRepository(session, require_export_confirmation=False)
    installed = 0
    for path in sorted(directory.glob("*.json")):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            LOGGER.warning("Skipped an unreadable provider policy file: %s", path.name)
            continue
        if not isinstance(document, dict):
            continue
        snapshot = _snapshot_from_document(document)
        if snapshot is None:
            LOGGER.warning("Skipped a provider policy whose hash does not match: %s", path.name)
            continue
        if repository.get_policy_snapshot(snapshot.policy_hash) is not None:
            continue
        repository.save_policy_snapshot(snapshot)
        installed += 1
        LOGGER.info("Reinstalled reviewed provider policy %s", snapshot.policy_id)
    return installed


__all__ = ["POLICY_DIRECTORY_NAME", "ensure_reviewed_policies", "policy_directory"]
