"""Safety and idempotence tests for the reviewed Real Embedding policy importer."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from scripts.import_provider_policy import (
    EMBEDDING_ENDPOINT_PATH,
    PolicyImportError,
    import_reviewed_policy,
    load_policy_file,
    main,
    validate_reviewed_policy,
)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _document() -> dict[str, Any]:
    endpoint = "https://fixture.cn-beijing.maas.aliyuncs.com" + EMBEDDING_ENDPOINT_PATH
    document: dict[str, Any] = {
        "reviewed": True,
        "provider": "dashscope",
        "model": "text-embedding-v4",
        "dimension": 1024,
        "region": "cn-beijing",
        "embedding_policy_version": "w4-embed-v1",
        "contract_version": "ProviderDataCallV1",
        "policy_hash": "0" * 64,
        "policy_id": "real-embed-demo-policy",
        "supplier": "Alibaba Cloud Model Studio",
        "account_product": "payg_api",
        "endpoint": endpoint,
        "privacy_notice_url": "https://help.aliyun.com/zh/model-studio/privacy-notice",
        "privacy_notice_retrieved_at": "2026-08-31T00:00:00Z",
        "privacy_notice_sha256": _digest("privacy-review"),
        "service_terms_url": "https://help.aliyun.com/zh/model-studio/service-terms",
        "service_terms_retrieved_at": "2026-08-31T00:00:00Z",
        "service_terms_sha256": _digest("terms-review"),
        "faq_url": "https://help.aliyun.com/zh/model-studio/faq",
        "faq_retrieved_at": "2026-08-31T00:00:00Z",
        "faq_sha256": _digest("faq-review"),
        "no_training_basis": "payg-api-terms-reviewed",
        "prompt_response_logging_disabled": True,
        "inference_log_backflow_disabled": True,
        "optional_content_logging_disabled": True,
        "service_improvement_disabled": True,
        "storage_disclosed": True,
        "retention_setting": "unknown",
        "snapshot_revision": 1,
    }
    from app.providers.control import ProviderPolicySnapshotV1

    policy_values = {
        key: value
        for key, value in document.items()
        if key
        not in {
            "reviewed",
            "provider",
            "model",
            "dimension",
            "embedding_policy_version",
            "contract_version",
            "policy_hash",
        }
    }
    document["policy_hash"] = ProviderPolicySnapshotV1(**policy_values).policy_hash
    return document


def test_empty_sqlite_import_is_idempotent_and_only_stores_policy(tmp_path: Path) -> None:
    document = _document()
    database_url = f"sqlite:///{tmp_path / 'policy.sqlite3'}"

    first = import_reviewed_policy(
        document,
        database_url=database_url,
        acknowledge_reviewed=True,
    )
    second = import_reviewed_policy(
        document,
        database_url=database_url,
        acknowledge_reviewed=True,
    )

    assert first.status == "created"
    assert second.status == "already_present"
    assert first.policy_hash == second.policy_hash == document["policy_hash"]

    from app.core.db import ALEMBIC_HEAD, Database
    from app.core.models import ProviderPolicySnapshot
    from app.providers.control_repository import ProviderRepository
    from sqlalchemy import func, select, text

    database = Database(database_url)
    try:
        row = ProviderRepository(database).get_policy_snapshot(document["policy_hash"])
        assert row is not None
        assert database.check_ready()
        with database.engine.connect() as connection:
            assert connection.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).scalar_one() == ALEMBIC_HEAD
            assert connection.execute(select(func.count()).select_from(ProviderPolicySnapshot)).scalar_one() == 1
    finally:
        database.dispose()


def test_reviewed_acknowledgement_is_required_before_database_access(tmp_path: Path) -> None:
    with pytest.raises(PolicyImportError, match="acknowledgement"):
        import_reviewed_policy(
            _document(),
            database_url=f"sqlite:///{tmp_path / 'never-created.sqlite3'}",
            acknowledge_reviewed=False,
        )
    assert not (tmp_path / "never-created.sqlite3").exists()


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("provider", "openai"),
        ("model", "text-embedding-v3"),
        ("dimension", 256),
        ("region", "us-east-1"),
        ("embedding_policy_version", "latest"),
        ("endpoint", "https://example.invalid/api"),
        ("retention_setting", None),
        ("prompt_response_logging_disabled", False),
        ("inference_log_backflow_disabled", False),
        ("optional_content_logging_disabled", False),
        ("service_improvement_disabled", False),
        ("storage_disclosed", False),
        ("no_training_basis", "unknown"),
        ("retention_setting", "pending"),
        ("policy_hash", "not-a-hash"),
    ),
)
def test_identity_and_policy_controls_fail_closed(field: str, value: object) -> None:
    document = _document()
    document[field] = value
    with pytest.raises(PolicyImportError):
        validate_reviewed_policy(document, acknowledge_reviewed=True)


def test_missing_and_unknown_secret_fields_fail_without_persisting() -> None:
    document = _document()
    missing = copy.deepcopy(document)
    del missing["faq_sha256"]
    with pytest.raises(PolicyImportError):
        validate_reviewed_policy(missing, acknowledge_reviewed=True)

    secret_field = copy.deepcopy(document)
    secret_field["api_key"] = "fixture-value-must-not-be-accepted"
    with pytest.raises(PolicyImportError, match="forbidden"):
        validate_reviewed_policy(secret_field, acknowledge_reviewed=True)


def test_file_loader_requires_explicit_json_and_never_accepts_env_name(tmp_path: Path) -> None:
    document_path = tmp_path / "reviewed-policy.json"
    document_path.write_text(json.dumps(_document()), encoding="utf-8")
    assert load_policy_file(document_path)["reviewed"] is True

    env_path = tmp_path / ".env"
    env_path.write_text("DASHSCOPE_API_KEY=fixture-value", encoding="utf-8")
    with pytest.raises(PolicyImportError):
        load_policy_file(env_path)


def test_policy_endpoint_path_is_fixed() -> None:
    document = _document()
    document["endpoint"] = "https://fixture.cn-beijing.maas.aliyuncs.com/wrong"
    with pytest.raises(PolicyImportError):
        validate_reviewed_policy(document, acknowledge_reviewed=True)


def test_cli_summary_is_hash_only_and_requires_explicit_ack(tmp_path: Path, capsys: Any) -> None:
    document_path = tmp_path / "reviewed-policy.json"
    document_path.write_text(json.dumps(_document()), encoding="utf-8")
    database_url = f"sqlite:///{tmp_path / 'cli.sqlite3'}"

    with pytest.raises(SystemExit) as missing_ack:
        main(
            [
                "--policy-file",
                str(document_path),
                "--database-url",
                database_url,
            ]
        )
    assert missing_ack.value.code == 2
    assert capsys.readouterr().err

    assert (
        main(
            [
                "--policy-file",
                str(document_path),
                "--database-url",
                database_url,
                "--acknowledge-reviewed",
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert document_path.read_text(encoding="utf-8") not in output
    assert json.loads(output) == {
        "status": "created",
        "policy_hash": _document()["policy_hash"],
    }
    assert "fixture.cn-beijing" not in output


def test_workspace_and_secret_fields_are_rejected() -> None:
    document = _document()
    document["workspace_id"] = "fixture"
    with pytest.raises(PolicyImportError, match="forbidden"):
        validate_reviewed_policy(document, acknowledge_reviewed=True)
