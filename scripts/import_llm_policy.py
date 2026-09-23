"""Import the one reviewed, non-secret Real-Core LLM policy.

This is deliberately a fixed LLM entry point, separate from the Embedding
importer.  It accepts one exact DashScope resource and persists only the
existing ``ProviderPolicySnapshotV1`` control row.  It never reads credentials,
selects a Provider, or sends a network request.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlsplit

REAL_PROVIDER: Final = "dashscope"
REAL_REGION: Final = "cn-beijing"
PROVIDER_DATA_CALL_VERSION: Final = "ProviderDataCallV1"
REAL_SUPPLIER: Final = "Alibaba Cloud Model Studio"
LLM_ENDPOINT_PATH: Final = "/compatible-mode/v1/chat/completions"

ACCOUNT_PRODUCTS: Final = frozenset(
    {
        "payg_api",
        "pay-as-you-go api",
        "pay-as-you-go API",
        "token_plan_team",
        "Token Plan Team",
    }
)
POLICY_FIELDS: Final = frozenset(
    {
        "policy_id",
        "supplier",
        "account_product",
        "privacy_notice_url",
        "privacy_notice_retrieved_at",
        "privacy_notice_sha256",
        "service_terms_url",
        "service_terms_retrieved_at",
        "service_terms_sha256",
        "faq_url",
        "faq_retrieved_at",
        "faq_sha256",
        "no_training_basis",
        "prompt_response_logging_disabled",
        "inference_log_backflow_disabled",
        "optional_content_logging_disabled",
        "service_improvement_disabled",
        "storage_disclosed",
        "retention_setting",
        "snapshot_revision",
        "endpoint",
        "region",
    }
)
IDENTITY_FIELDS: Final = frozenset({"provider", "model", "region", "endpoint", "contract_version"})
REQUIRED_FIELDS: Final = frozenset({"reviewed", "policy_hash", *POLICY_FIELDS, *IDENTITY_FIELDS})
SHA256_RE: Final = re.compile(r"^[0-9a-f]{64}$")
SAFE_ID_RE: Final = re.compile(r"^[A-Za-z0-9_.:-]{1,120}$")
SAFE_WORKSPACE_RE: Final = re.compile(r"^[A-Za-z0-9-]+$")
SECRET_KEY_RE: Final = re.compile(
    r"(?:api[_-]?key|authorization|bearer|credential|password|secret|token|"
    r"private[_-]?key|workspace[_-]?id)",
    re.IGNORECASE,
)
SECRET_VALUE_RE: Final = re.compile(
    r"(?:api[_-]?key|authorization|bearer|credential(?:s)?|password|secret)\s*[:=]"
    r"|\bbearer\s+[A-Za-z0-9._~+/=-]{8,}\b"
    r"|\bsk-[A-Za-z0-9][A-Za-z0-9_-]{7,}\b",
    re.IGNORECASE,
)
UNREVIEWED_VALUES: Final = frozenset(
    {"unreviewed", "unverified", "not verified", "pending", "todo", "tbd", "example"}
)


class PolicyImportError(ValueError):
    """A fixed LLM policy cannot cross the import boundary."""


@dataclass(frozen=True, slots=True)
class PolicyImportResult:
    """Safe terminal metadata; no policy value is returned."""

    status: str
    policy_hash: str


def _fail(message: str) -> PolicyImportError:
    # Every message is value-free so it is safe for a caller to report.
    return PolicyImportError(message)


def _ensure_backend_import_path() -> None:
    backend = Path(__file__).resolve().parents[1] / "backend"
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise _fail("policy document must be a JSON object")
    return value


def _text(value: object, field: str, *, limit: int = 500) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise _fail(f"policy field {field} is invalid")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise _fail(f"policy field {field} is invalid")
    if SECRET_VALUE_RE.search(value):
        raise _fail("policy contains a forbidden secret-shaped value")
    return value


def _sha(value: object, field: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise _fail(f"policy field {field} is not a SHA-256 digest")
    return value


def _url(value: object, field: str) -> str:
    text = _text(value, field)
    try:
        parsed = urlsplit(text)
        port = parsed.port
    except ValueError as exc:
        raise _fail(f"policy field {field} is invalid") from exc
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.query
        or parsed.fragment
        or parsed.hostname.casefold() == "example.invalid"
    ):
        raise _fail(f"policy field {field} is invalid")
    return text


def _llm_endpoint(value: object) -> str:
    text = _url(value, "endpoint")
    parsed = urlsplit(text)
    host = (parsed.hostname or "").casefold()
    suffix = ".cn-beijing.maas.aliyuncs.com"
    workspace = host[: -len(suffix)] if host.endswith(suffix) else ""
    if (
        not workspace
        or SAFE_WORKSPACE_RE.fullmatch(workspace) is None
        or parsed.path != LLM_ENDPOINT_PATH
    ):
        raise _fail("policy endpoint is not the fixed Beijing LLM resource")
    return text


def _timestamp(value: object, field: str) -> str:
    text = _text(value, field, limit=64)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _fail(f"policy field {field} is not a reviewed timestamp") from exc
    if parsed.tzinfo is None:
        raise _fail(f"policy field {field} is not a reviewed timestamp")
    return text


def _checked_document(document: Mapping[str, object]) -> dict[str, object]:
    if not all(isinstance(key, str) for key in document):
        raise _fail("policy document keys are invalid")
    if any(SECRET_KEY_RE.search(key) for key in document):
        raise _fail("policy contains a forbidden secret-bearing field")
    missing = REQUIRED_FIELDS - document.keys()
    if missing or document.keys() - REQUIRED_FIELDS:
        raise _fail("policy document fields are incomplete or unsupported")
    if document["reviewed"] is not True:
        raise _fail("policy requires reviewed=true")
    model = document["model"]
    if (
        document["provider"] != REAL_PROVIDER
        or not isinstance(model, str)
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", model) is None
    ):
        raise _fail("policy resource identity is not a DashScope LLM resource")
    if document["region"] != REAL_REGION:
        raise _fail("policy resource region is not fixed")
    if document["contract_version"] != PROVIDER_DATA_CALL_VERSION:
        raise _fail("policy contract version is not ProviderDataCallV1")

    policy_id = _text(document["policy_id"], "policy_id", limit=120)
    if SAFE_ID_RE.fullmatch(policy_id) is None:
        raise _fail("policy field policy_id is invalid")
    supplier = _text(document["supplier"], "supplier", limit=160)
    if supplier != REAL_SUPPLIER:
        raise _fail("policy supplier is not the fixed Model Studio supplier")
    account_product = _text(document["account_product"], "account_product", limit=64)
    if account_product not in ACCOUNT_PRODUCTS:
        raise _fail("policy account product is not authorized")

    endpoint = _llm_endpoint(document["endpoint"])
    urls = {
        field: _url(document[field], field)
        for field in ("privacy_notice_url", "service_terms_url", "faq_url")
    }
    hashes = {
        field: _sha(document[field], field)
        for field in ("privacy_notice_sha256", "service_terms_sha256", "faq_sha256")
    }
    timestamps = {
        field: _timestamp(document[field], field)
        for field in (
            "privacy_notice_retrieved_at",
            "service_terms_retrieved_at",
            "faq_retrieved_at",
        )
    }
    no_training = _text(document["no_training_basis"], "no_training_basis", limit=240)
    retention = _text(document["retention_setting"], "retention_setting", limit=160)
    if no_training.casefold() in UNREVIEWED_VALUES:
        raise _fail("policy no-training basis is not reviewed")
    if retention.casefold() in UNREVIEWED_VALUES:
        raise _fail("policy retention setting is not reviewed")
    for field in (
        "prompt_response_logging_disabled",
        "inference_log_backflow_disabled",
        "optional_content_logging_disabled",
        "service_improvement_disabled",
        "storage_disclosed",
    ):
        if document[field] is not True:
            raise _fail(f"policy control {field} must be explicitly true")
    revision = document["snapshot_revision"]
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise _fail("policy snapshot revision is invalid")
    supplied_hash = _sha(document["policy_hash"], "policy_hash")
    return {
        "policy_id": policy_id,
        "supplier": supplier,
        "region": REAL_REGION,
        "account_product": account_product,
        "endpoint": endpoint,
        **urls,
        **timestamps,
        **hashes,
        "no_training_basis": no_training,
        "prompt_response_logging_disabled": True,
        "inference_log_backflow_disabled": True,
        "optional_content_logging_disabled": True,
        "service_improvement_disabled": True,
        "storage_disclosed": True,
        "retention_setting": retention,
        "snapshot_revision": revision,
        "supplied_policy_hash": supplied_hash,
    }


def validate_reviewed_policy(document: Mapping[str, object], *, acknowledge_reviewed: bool) -> Any:
    """Validate fixed identity and return the existing server-side policy DTO."""

    if acknowledge_reviewed is not True:
        raise _fail("manual reviewed acknowledgement is required")
    values = _checked_document(_mapping(document))
    supplied_hash = str(values.pop("supplied_policy_hash"))
    _ensure_backend_import_path()
    from app.providers.control import ProviderPolicySnapshotV1

    try:
        policy = ProviderPolicySnapshotV1(**values)
    except Exception as exc:
        raise _fail("provider policy controls are invalid") from exc
    if policy.policy_hash != supplied_hash:
        raise _fail("policy_hash does not match the reviewed policy fields")
    return policy


def load_policy_file(path: Path) -> Mapping[str, object]:
    """Load one explicitly named JSON file; environment files are forbidden."""

    resolved = path.resolve()
    if resolved.name.startswith(".env") or resolved.suffix.casefold() != ".json":
        raise _fail("policy input must be an explicit JSON file")
    try:
        value = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _fail("policy input is not readable strict UTF-8 JSON") from exc
    return _mapping(value)


def import_reviewed_policy(
    document: Mapping[str, object], *, database_url: str, acknowledge_reviewed: bool
) -> PolicyImportResult:
    """Validate and idempotently persist the exact LLM policy row."""

    if not isinstance(database_url, str) or not database_url.startswith("sqlite:"):
        raise _fail("an explicit SQLite database URL is required")
    policy = validate_reviewed_policy(document, acknowledge_reviewed=acknowledge_reviewed)
    _ensure_backend_import_path()
    from app.core.db import Database
    from app.providers.control_repository import ProviderRepository

    database = Database(database_url)
    try:
        database.upgrade_schema()
        repository = ProviderRepository(database)
        existing = repository.get_policy_snapshot(policy.policy_hash)
        if existing is not None:
            if existing != policy:
                raise _fail("persisted policy hash resolves to different controls")
            return PolicyImportResult("already_present", policy.policy_hash)
        try:
            repository.save_policy_snapshot(policy)
        except Exception as exc:
            current = repository.get_policy_snapshot(policy.policy_hash)
            if current is None or current != policy:
                raise _fail("provider policy persistence conflicted") from exc
            return PolicyImportResult("already_present", policy.policy_hash)
        return PolicyImportResult("created", policy.policy_hash)
    except PolicyImportError:
        raise
    except Exception as exc:
        raise _fail("provider policy persistence failed") from exc
    finally:
        database.dispose()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--policy-file", "--policy-json", dest="policy_file", type=Path, required=True
    )
    parser.add_argument("--database-url", required=True)
    parser.add_argument(
        "--acknowledge-reviewed",
        "--reviewed",
        dest="acknowledge_reviewed",
        action="store_true",
        required=True,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = import_reviewed_policy(
            load_policy_file(args.policy_file),
            database_url=args.database_url,
            acknowledge_reviewed=args.acknowledge_reviewed,
        )
    except PolicyImportError as exc:
        print(f"LLM policy import failed: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {"status": result.status, "policy_hash": result.policy_hash}, separators=(",", ":")
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
