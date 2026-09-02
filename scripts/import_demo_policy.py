#!/usr/bin/env python3
"""Install unreviewed provider policies so a local Demo can call a real model.

The normal path requires a policy snapshot recording which supplier documents a
person read, when, and at what content hash. That record exists so a school can
audit what left the machine, and `--acknowledge-reviewed` is a human statement
nobody may make on another person's behalf.

A private local Demo run by the person who owns the API key does not need that
archive; it needs the operator to know what is happening. This installs a policy
derived from `.env` alone, marks it `demo-unreviewed`, and the classroom
composition strip then labels those components as unreviewed rather than
letting them pass as audited.

It refuses to run unless DEMO_MODE is true, and it never writes a credential
into the database.

    python scripts/import_demo_policy.py
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

# The endpoints are workspace-scoped and each adapter derives its own. Asking
# the adapters keeps this script from re-deriving a URL that must match exactly.

UNREVIEWED_NOTE = "demo-unreviewed-no-document-was-read"
# A stable, obviously-synthetic digest. The DTO requires a SHA-256 in these
# fields; using the hash of the sentinel keeps the shape valid while making it
# plain to any reader that all three "documents" are the same placeholder and
# none is a real page.
UNREVIEWED_DIGEST = hashlib.sha256(UNREVIEWED_NOTE.encode("utf-8")).hexdigest()
NOT_RETRIEVED = "not-retrieved"


def _backend_on_path() -> None:
    backend = Path(__file__).resolve().parents[1] / "backend"
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))


def _env_values(env_path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        values[key.strip()] = value.strip()
    return values


def _write_env_hashes(env_path: Path, updates: dict[str, str]) -> None:
    lines = env_path.read_text(encoding="utf-8").splitlines(keepends=True)
    remaining = dict(updates)
    for index, line in enumerate(lines):
        key, _, _ = line.partition("=")
        if key.strip() in remaining:
            lines[index] = f"{key.strip()}={remaining.pop(key.strip())}\n"
    for key, value in remaining.items():
        lines.append(f"{key}={value}\n")
    env_path.write_text("".join(lines), encoding="utf-8")


def resolved_endpoints(env: dict[str, str]) -> tuple[str, str]:
    """The exact LLM and embedding endpoints the running adapters would use.

    The values come from the parsed .env rather than Settings: the application
    reads .env relative to the working directory, and this script runs from
    backend/, where it would find nothing.
    """

    from app.modules.knowledge.providers.adapters import DashScopeEmbeddingConfig
    from app.providers.llm_adapter import DashScopeLLMConfig

    api_key = env.get("DASHSCOPE_API_KEY", "")
    workspace = env.get("DASHSCOPE_WORKSPACE_ID", "")
    if not api_key or not workspace:
        raise SystemExit("DASHSCOPE_API_KEY and DASHSCOPE_WORKSPACE_ID must be set in .env")
    llm = DashScopeLLMConfig(api_key=api_key, workspace_id=workspace)
    embedding = DashScopeEmbeddingConfig(api_key=api_key, workspace_id=workspace)
    return llm.resolved_endpoint, embedding.resolved_endpoint


def build_policy(slice_name: str, endpoint: str, region: str) -> object:
    from app.providers.control import (
        DEMO_UNREVIEWED_POLICY_PREFIX,
        ProviderPolicySnapshotV1,
    )

    return ProviderPolicySnapshotV1(
        policy_id=f"{DEMO_UNREVIEWED_POLICY_PREFIX}-{slice_name}",
        supplier="Alibaba Cloud Model Studio",
        region=region,
        account_product="payg_api",
        endpoint=endpoint,
        # Every evidence field states plainly that nothing was reviewed. A
        # placeholder that looked like a real citation would be worse than none.
        privacy_notice_url="https://help.aliyun.com/zh/model-studio/privacy-notice",
        privacy_notice_retrieved_at=NOT_RETRIEVED,
        privacy_notice_sha256=UNREVIEWED_DIGEST,
        service_terms_url="https://help.aliyun.com/zh/model-studio/service-terms",
        service_terms_retrieved_at=NOT_RETRIEVED,
        service_terms_sha256=UNREVIEWED_DIGEST,
        faq_url="https://help.aliyun.com/zh/model-studio/faq",
        faq_retrieved_at=NOT_RETRIEVED,
        faq_sha256=UNREVIEWED_DIGEST,
        no_training_basis=UNREVIEWED_NOTE,
        # The DTO requires these to be asserted true. They are statements about
        # the operator's own supplier account, which is why this script demands
        # --accept-unreviewed rather than asserting them by itself.
        prompt_response_logging_disabled=True,
        inference_log_backflow_disabled=True,
        optional_content_logging_disabled=True,
        service_improvement_disabled=True,
        storage_disclosed=True,
        retention_setting=NOT_RETRIEVED,
        snapshot_revision=1,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument(
        "--accept-unreviewed",
        action="store_true",
        help=(
            "state that this is your own supplier account on your own machine, "
            "that you accept running without a reviewed policy, and that the "
            "account's logging and retention settings are yours to answer for"
        ),
    )
    args = parser.parse_args()
    if not args.accept_unreviewed:
        raise SystemExit(
            "refusing: pass --accept-unreviewed.\n"
            "It records that a person, not this script, accepts running a real "
            "provider without a reviewed policy."
        )

    root = args.root.resolve()
    env_path = root / ".env"
    if not env_path.exists():
        raise SystemExit("no .env; run `pnpm bootstrap:local` first")
    env = _env_values(env_path)
    if env.get("DEMO_MODE", "").lower() != "true":
        raise SystemExit("refusing: DEMO_MODE is not true; use the reviewed importers")

    region = env.get("DASHSCOPE_REGION") or "cn-beijing"
    _backend_on_path()
    from app.core.db import Database
    from app.providers.control_repository import ProviderRepository

    database = Database(f"sqlite:///{root / 'data' / 'maya.sqlite3'}")
    database.upgrade_schema()
    # Alembic leaves its connection pooled; the writer fence below opens
    # BEGIN IMMEDIATE and would block on it.
    database.dispose()

    llm_endpoint, embedding_endpoint = resolved_endpoints(env)
    llm = build_policy("llm", llm_endpoint, region)
    embedding = build_policy("embedding", embedding_endpoint, region)
    from app.core.models import ProviderPolicySnapshot
    from app.providers.control import DEMO_UNREVIEWED_POLICY_PREFIX

    # Two separate transactions on purpose. save_policy_snapshot opens its own
    # BEGIN IMMEDIATE writer fence, so holding an ORM transaction across the
    # call deadlocks against it.
    with database.session() as session:
        # Re-running must be able to correct a row this script wrote earlier —
        # a changed workspace changes the endpoint. Only rows this script owns
        # are removed; a reviewed policy is never touched.
        stale = (
            session.query(ProviderPolicySnapshot)
            .filter(ProviderPolicySnapshot.policy_id.startswith(DEMO_UNREVIEWED_POLICY_PREFIX))
            .all()
        )
        replaced = len(stale)
        for row in stale:
            session.delete(row)
        session.commit()

    with database.session() as session:
        repository = ProviderRepository(session, require_export_confirmation=False)
        for policy in (llm, embedding):
            if repository.get_policy_snapshot(policy.policy_hash) is None:
                repository.save_policy_snapshot(policy)
        session.commit()
    if replaced:
        print(f"replaced {replaced} earlier demo-unreviewed policies")

    _write_env_hashes(
        env_path,
        {
            "LLM_PROVIDER_POLICY_HASH": llm.policy_hash,
            "REPORT_PROVIDER_POLICY_HASH": llm.policy_hash,
            "EMBEDDING_PROVIDER_POLICY_HASH": embedding.policy_hash,
        },
    )
    print(f"installed two demo-unreviewed policies in {region}")
    print("updated LLM/REPORT/EMBEDDING policy hashes in .env")
    print("these are NOT reviewed; the composition strip labels them so")


if __name__ == "__main__":
    main()
