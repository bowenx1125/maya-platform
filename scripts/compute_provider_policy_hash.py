#!/usr/bin/env python3
"""Fill in ``policy_hash`` for a reviewed provider policy document.

The importers refuse a document whose ``policy_hash`` does not match its own
fields, which is what stops a hand-edited policy from reaching the database.
That check is only usable if the author can compute the hash for the values
they actually reviewed, so this prints it and can write it back.

It reviews nothing. It reads no credential, selects no provider and sends no
request. ``--acknowledge-reviewed`` on the importer remains a human statement
that a person read the supplier documents this file names.

    python scripts/compute_provider_policy_hash.py my-llm-policy.json --write
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# The document carries identity fields the snapshot itself does not hash.
NON_POLICY_FIELDS = frozenset({"reviewed", "policy_hash", "provider", "model", "contract_version"})


def _snapshot_class() -> type:
    backend = Path(__file__).resolve().parents[1] / "backend"
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))
    from app.providers.control import ProviderPolicySnapshotV1

    return ProviderPolicySnapshotV1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("policy_file", type=Path)
    parser.add_argument(
        "--write",
        action="store_true",
        help="write the computed hash back into the file's policy_hash field",
    )
    args = parser.parse_args()

    document = json.loads(args.policy_file.read_text(encoding="utf-8"))
    fields = {key: value for key, value in document.items() if key not in NON_POLICY_FIELDS}
    snapshot = _snapshot_class()(**fields)
    digest = snapshot.policy_hash

    print(digest)
    if args.write:
        document["policy_hash"] = digest
        args.policy_file.write_text(
            json.dumps(document, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"wrote policy_hash into {args.policy_file}", file=sys.stderr)


if __name__ == "__main__":
    main()
