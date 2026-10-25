"""Import one reviewed, non-secret ProviderDataCall policy into an empty DB.

This entry point is intentionally separate from Provider selection.  It reads a
JSON policy supplied by the operator, validates the fixed Real Embedding
identity and policy controls, and persists only the existing
``ProviderPolicySnapshotV1`` through ``ProviderRepository``.  It never reads
environment settings, constructs a Provider, or sends a request.

The file format is deliberately explicit.  It contains the policy fields plus
the fixed resource declaration (``provider``, ``model``, ``dimension``,
``region``, ``embedding_policy_version`` and ``contract_version``), a caller-
computed ``policy_hash``, and ``reviewed: true``.  The CLI additionally
requires ``--acknowledge-reviewed`` so a copied or incomplete file cannot be
accepted accidentally.
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
from typing import Any
from urllib.parse import urlsplit

REAL_PROVIDER = "dashscope"
REAL_MODEL = "text-embedding-v4"
REAL_DIMENSION = 1024
REAL_REGION = "cn-beijing"
REAL_POLICY_VERSION = "w4-embed-v1"
PROVIDER_DATA_CALL_VERSION = "ProviderDataCallV1"
REAL_SUPPLIER = "Alibaba Cloud Model Studio"
EMBEDDING_ENDPOINT_PATH = "/api/v1/services/embeddings/text-embedding/text-embedding"

_ALLOWED_ACCOUNT_PRODUCTS = frozenset(
    {
        "payg_api",
        "pay-as-you-go api",
        "pay-as-you-go API",
        "token_plan_team",
        "Token Plan Team",
    }
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,120}$")
_SAFE_WORKSPACE_RE = re.compile(r"^[A-Za-z0-9-]+$")
_SECRET_KEY_RE = re.compile(
    r"(?:api[_-]?key|authorization|bearer|credential|password|secret|token|private[_-]?key|"
    r"workspace[_-]?id)",
    re.IGNORECASE,
)
_SECRET_VALUE_RE = re.compile(
    r"(?:api[_-]?key|authorization|bearer|credential(?:s)?|password|secret)\s*[:=]"
    r"|\bbearer\s+[A-Za-z0-9._~+/=-]{8,}\b"
    r"|\bsk-[A-Za-z0-9][A-Za-z0-9_-]{7,}\b",
    re.IGNORECASE,
)
_UNREVIEWED_VALUES = frozenset(
    {
        "unknown",
        "unverified",
        "not verified",
        "pending",
        "todo",
        "tbd",
        "example",
        "example.invalid",
    }
)
_POLICY_FIELDS = frozenset(
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
_IDENTITY_FIELDS = frozenset(
    {
        "provider",
        "model",
        "dimension",
        "region",
        "embedding_policy_version",
        "endpoint",
        "contract_version",
    }
)
_REQUIRED_FIELDS = frozenset(
    {
        "reviewed",
        "policy_hash",
        *_IDENTITY_FIELDS,
        *_POLICY_FIELDS,
    }
)
_ALLOWED_FIELDS = _REQUIRED_FIELDS


class PolicyImportError(ValueError):
    """A policy cannot be accepted without exposing its source values."""


@dataclass(frozen=True, slots=True)
class PolicyImportResult:
    """Sanitized import result suitable for a terminal summary."""

    status: str
    policy_hash: str


def _fail(message: str) -> PolicyImportError:
    # Keep all errors value-free: callers may safely print this exception.
    return PolicyImportError(message)


def _ensure_backend_import_path() -> None:
    backend = Path(__file__).resolve().parents[1] / "backend"
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise _fail("policy document must be a JSON object")
    return value


def _safe_string(value: object, field: str, *, max_length: int = 500) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > max_length:
        raise _fail(f"policy field {field} is missing or invalid")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise _fail(f"policy field {field} is missing or invalid")
    if _SECRET_VALUE_RE.search(value):
        raise _fail("policy contains a forbidden secret-shaped value")
    return value


def _sha256(value: object, field: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise _fail(f"policy field {field} is not a SHA-256 digest")
    return value


def _https_url(value: object, field: str) -> str:
    text = _safe_string(value, field)
    try:
        parsed = urlsplit(text)
        port = parsed.port
    except ValueError as exc:
        raise _fail(f"policy field {field} is an invalid URL") from exc
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
        raise _fail(f"policy field {field} is an invalid URL")
    return text


def _embedding_endpoint(value: object) -> str:
    text = _https_url(value, "endpoint")
    parsed = urlsplit(text)
    host = (parsed.hostname or "").casefold()
    suffix = ".cn-beijing.maas.aliyuncs.com"
    workspace = host[: -len(suffix)] if host.endswith(suffix) else ""
    if (
        not workspace
        or _SAFE_WORKSPACE_RE.fullmatch(workspace) is None
        or parsed.path != EMBEDDING_ENDPOINT_PATH
    ):
        raise _fail("policy endpoint is not the fixed Beijing Embedding resource")
    return text


def _timestamp(value: object, field: str) -> str:
    text = _safe_string(value, field, max_length=64)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _fail(f"policy field {field} is not a reviewed timestamp") from exc
    if parsed.tzinfo is None:
        raise _fail(f"policy field {field} is not a reviewed timestamp")
    return text


def _required_bool(value: object, field: str) -> bool:
    if value is not True:
        raise _fail(f"policy control {field} must be explicitly true")
    return True


def _required_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise _fail(f"policy field {field} is invalid")
    return value


def _reject_secret_keys(document: Mapping[str, object]) -> None:
    for key in document:
        if _SECRET_KEY_RE.search(key):
            raise _fail("policy contains a forbidden secret-bearing field")


def _policy_values(document: Mapping[str, object]) -> dict[str, object]:
    _reject_secret_keys(document)
    missing = _REQUIRED_FIELDS - document.keys()
    unknown = document.keys() - _ALLOWED_FIELDS
    if missing:
        raise _fail("policy document is missing required reviewed fields")
    if unknown:
        raise _fail("policy document contains an unknown field")
    if document["reviewed"] is not True:
        raise _fail("policy requires reviewed=true")
    if document["provider"] != REAL_PROVIDER or document["model"] != REAL_MODEL:
        raise _fail("policy resource identity is not the fixed Embedding resource")
    if document["dimension"] != REAL_DIMENSION:
        raise _fail("policy resource dimension is not 1024")
    if document["region"] != REAL_REGION or document["embedding_policy_version"] != REAL_POLICY_VERSION:
        raise _fail("policy resource region or policy version is not fixed")
    if document["contract_version"] != PROVIDER_DATA_CALL_VERSION:
        raise _fail("policy contract version is not ProviderDataCallV1")

    policy_id = _safe_string(document["policy_id"], "policy_id", max_length=120)
    if _SAFE_ID_RE.fullmatch(policy_id) is None:
        raise _fail("policy field policy_id is invalid")
    supplier = _safe_string(document["supplier"], "supplier", max_length=160)
    if supplier != REAL_SUPPLIER:
        raise _fail("policy supplier is not the fixed Model Studio supplier")
    account_product = _safe_string(document["account_product"], "account_product", max_length=64)
    if account_product not in _ALLOWED_ACCOUNT_PRODUCTS:
        raise _fail("policy account product is not authorized")
    endpoint = _embedding_endpoint(document["endpoint"])
    if document["region"] != REAL_REGION:
        raise _fail("policy region is not cn-beijing")

    url_values = {
        field: _https_url(document[field], field)
        for field in ("privacy_notice_url", "service_terms_url", "faq_url")
    }
    hash_values = {
        field: _sha256(document[field], field)
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
    no_training_basis = _safe_string(document["no_training_basis"], "no_training_basis", max_length=240)
    if no_training_basis.casefold() in _UNREVIEWED_VALUES:
        raise _fail("policy no-training basis is not reviewed")
    retention = _safe_string(document["retention_setting"], "retention_setting", max_length=160)
    if retention.casefold() in _UNREVIEWED_VALUES - {"unknown"}:
        raise _fail("policy retention setting is not reviewed")
    if retention.casefold() not in {"unknown", "not disclosed"} and len(retention) < 2:
        raise _fail("policy retention setting is invalid")
    controls = {
        field: _required_bool(document[field], field)
        for field in (
            "prompt_response_logging_disabled",
            "inference_log_backflow_disabled",
            "optional_content_logging_disabled",
            "service_improvement_disabled",
            "storage_disclosed",
        )
    }
    snapshot_revision = _required_int(document["snapshot_revision"], "snapshot_revision")
    supplied_hash = _sha256(document["policy_hash"], "policy_hash")
    return {
        "policy_id": policy_id,
        "supplier": supplier,
        "region": REAL_REGION,
        "account_product": account_product,
        "endpoint": endpoint,
        **url_values,
        **timestamps,
        **hash_values,
        "no_training_basis": no_training_basis,
        **controls,
        "retention_setting": retention,
        "snapshot_revision": snapshot_revision,
        "supplied_policy_hash": supplied_hash,
    }


def validate_reviewed_policy(
    document: Mapping[str, object],
    *,
    acknowledge_reviewed: bool,
) -> Any:
    """Validate a reviewed JSON mapping and return the existing policy DTO."""

    if acknowledge_reviewed is not True:
        raise _fail("manual reviewed acknowledgement is required")
    values = _policy_values(_mapping(document))
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
    """Read one explicit JSON policy file without consulting environment state."""

    resolved = path.resolve()
    if resolved.name.startswith(".env") or resolved.suffix.casefold() != ".json":
        raise _fail("policy input must be an explicit JSON file")
    try:
        raw = resolved.read_bytes()
        document = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _fail("policy input is not readable strict UTF-8 JSON") from exc
    return _mapping(document)


def import_reviewed_policy(
    document: Mapping[str, object],
    *,
    database_url: str,
    acknowledge_reviewed: bool,
) -> PolicyImportResult:
    """Validate then idempotently persist policy data through the domain seam."""

    if not isinstance(database_url, str) or not database_url.startswith("postgresql"):
        raise _fail("an explicit PostgreSQL database URL is required")
    policy = validate_reviewed_policy(
        document,
        acknowledge_reviewed=acknowledge_reviewed,
    )
    _ensure_backend_import_path()
    from app.core.db import Database
    from app.providers.control_repository import ProviderRepository

    database = Database(database_url)
    try:
        # The importer is also the empty runtime entry point: use the checked
        # Alembic head so policy rows are created in the same traceable schema
        # as the application.  Migrations are local schema work and never
        # select or invoke a Provider.
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
            # A concurrent importer may have won the unique policy/revision
            # race.  Re-read only through the repository and accept that exact
            # immutable value; all other conflicts fail closed.
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
        "--policy-file",
        "--policy-json",
        dest="policy_file",
        type=Path,
        required=True,
        help="explicit non-secret reviewed policy JSON file",
    )
    parser.add_argument(
        "--database-url",
        required=True,
        help="explicit isolated SQLite URL; never read from DATABASE_URL",
    )
    parser.add_argument(
        "--acknowledge-reviewed",
        "--reviewed",
        dest="acknowledge_reviewed",
        action="store_true",
        required=True,
        help="acknowledge that the policy/account controls were manually reviewed",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = import_reviewed_policy(
            load_policy_file(args.policy_file),
            database_url=args.database_url,
            acknowledge_reviewed=args.acknowledge_reviewed,
        )
    except PolicyImportError as exc:
        print(f"provider policy import failed: {exc}", file=sys.stderr)
        return 2
    # Hash and status are safe operator metadata; endpoint, policy values and
    # any transport material are intentionally absent from output.  Keep the
    # success line machine-readable for the next explicit configuration step.
    print(json.dumps({"status": result.status, "policy_hash": result.policy_hash}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
