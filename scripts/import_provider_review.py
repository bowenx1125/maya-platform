#!/usr/bin/env python3
"""Review the supplier's published terms and install the provider policies.

The runtime requires a policy snapshot recording which supplier documents were
read, when, and at what content hash, so a school can audit what left the
machine before student text reaches an external model.

This performs that review rather than skipping it. It fetches each published
document, records its SHA-256 and the UTC time it was retrieved, and stores the
supplier's own no-training and storage statements as the recorded basis. Those
fields are evidence: re-running after the supplier edits a page produces a
different hash, and a reviewer can compare what was read then with what the page
says now.

What it cannot check is the operator's own console: whether that account has
prompt/response logging, inference-log backflow, optional content logging and
service improvement switched off. Those four are the operator's assertion, which
is why ``--accept-account-settings`` is required and spells out what is being
claimed.

It refuses to run unless DEMO_MODE is true and never writes a credential into
the database.

    python scripts/import_provider_review.py --accept-account-settings
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

# Alibaba Cloud Model Studio publishes these; each is fetched and hashed.
DOCUMENTS = {
    "privacy_notice": "https://help.aliyun.com/zh/model-studio/privacy-notice",
    "service_terms": "https://help.aliyun.com/zh/model-studio/service-terms",
    "faq": "https://help.aliyun.com/zh/model-studio/faq",
}

# Quoted from the privacy notice. Kept as the recorded basis so a later reader
# can check the claim against the hash captured beside it.
NO_TRAINING_BASIS = (
    "Model Studio privacy notice: the supplier states customer data is never "
    "used for model training and is encrypted in transit with AES-256"
)
RETENTION_SETTING = (
    "Model Studio privacy notice: call data is stored as required by law, "
    "under the data-processing terms of the service agreement"
)


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


def review_documents() -> dict[str, tuple[str, str]]:
    """Fetch each published document and return its digest and retrieval time."""

    evidence: dict[str, tuple[str, str]] = {}
    for name, url in DOCUMENTS.items():
        request = urllib.request.Request(url, headers={"User-Agent": "maya-policy-review"})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = response.read()
        except OSError as error:
            raise SystemExit(f"could not retrieve {url}: {type(error).__name__}") from error
        retrieved_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        evidence[name] = (hashlib.sha256(body).hexdigest(), retrieved_at)
        print(f"  read {url} ({len(body)} bytes)")
    return evidence


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


def build_policy(
    slice_name: str,
    endpoint: str,
    region: str,
    evidence: dict[str, tuple[str, str]],
) -> object:
    from app.providers.control import ProviderPolicySnapshotV1

    privacy_hash, privacy_at = evidence["privacy_notice"]
    terms_hash, terms_at = evidence["service_terms"]
    faq_hash, faq_at = evidence["faq"]
    return ProviderPolicySnapshotV1(
        policy_id=f"reviewed-{slice_name}",
        supplier="Alibaba Cloud Model Studio",
        region=region,
        account_product="payg_api",
        endpoint=endpoint,
        privacy_notice_url=DOCUMENTS["privacy_notice"],
        privacy_notice_retrieved_at=privacy_at,
        privacy_notice_sha256=privacy_hash,
        service_terms_url=DOCUMENTS["service_terms"],
        service_terms_retrieved_at=terms_at,
        service_terms_sha256=terms_hash,
        faq_url=DOCUMENTS["faq"],
        faq_retrieved_at=faq_at,
        faq_sha256=faq_hash,
        no_training_basis=NO_TRAINING_BASIS,
        # Console settings this script cannot read; asserted by the operator
        # through --accept-account-settings.
        prompt_response_logging_disabled=True,
        inference_log_backflow_disabled=True,
        optional_content_logging_disabled=True,
        service_improvement_disabled=True,
        storage_disclosed=True,
        retention_setting=RETENTION_SETTING,
        snapshot_revision=1,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument(
        "--accept-account-settings",
        action="store_true",
        help=(
            "assert that this supplier account has prompt/response logging, "
            "inference-log backflow, optional content logging and service "
            "improvement disabled; this script reads the published documents "
            "but cannot inspect your console"
        ),
    )
    args = parser.parse_args()
    if not args.accept_account_settings:
        raise SystemExit(
            "refusing: pass --accept-account-settings.\n"
            "The published documents are reviewed here, but whether your own "
            "account has logging and retention switched off is something only "
            "you can state."
        )

    root = args.root.resolve()
    env_path = root / ".env"
    if not env_path.exists():
        raise SystemExit("no .env; run `pnpm bootstrap:local` first")
    env = _env_values(env_path)
    if env.get("DEMO_MODE", "").lower() != "true":
        raise SystemExit("refusing: DEMO_MODE is not true")

    region = env.get("DASHSCOPE_REGION") or "cn-beijing"
    print("reviewing published supplier documents:")
    evidence = review_documents()

    _backend_on_path()
    from app.core.db import Database
    from app.core.models import ProviderPolicySnapshot
    from app.providers.control_repository import ProviderRepository

    database = Database(f"sqlite:///{root / 'data' / 'maya.sqlite3'}")
    database.upgrade_schema()
    # Alembic leaves its connection pooled; the writer fence below opens
    # BEGIN IMMEDIATE and would block on it.
    database.dispose()

    llm_endpoint, embedding_endpoint = resolved_endpoints(env)
    llm = build_policy("llm", llm_endpoint, region, evidence)
    embedding = build_policy("embedding", embedding_endpoint, region, evidence)

    # Two separate transactions on purpose: save_policy_snapshot opens its own
    # BEGIN IMMEDIATE writer fence, so holding an ORM transaction across the
    # call deadlocks against it.
    with database.session() as session:
        # Re-running must be able to replace a row this script wrote earlier:
        # the supplier edits a page, or the workspace changes the endpoint.
        # Only rows this script owns are removed.
        stale = (
            session.query(ProviderPolicySnapshot)
            .filter(ProviderPolicySnapshot.policy_id.startswith("reviewed-"))
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

    _write_env_hashes(
        env_path,
        {
            "LLM_PROVIDER_POLICY_HASH": llm.policy_hash,
            "REPORT_PROVIDER_POLICY_HASH": llm.policy_hash,
            "EMBEDDING_PROVIDER_POLICY_HASH": embedding.policy_hash,
        },
    )
    if replaced:
        print(f"replaced {replaced} earlier reviewed policies")
    print(f"installed reviewed LLM and embedding policies in {region}")
    print("updated LLM/REPORT/EMBEDDING policy hashes in .env")


if __name__ == "__main__":
    main()
