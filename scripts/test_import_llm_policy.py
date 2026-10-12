"""Focused safety tests for the fixed Real-Core LLM policy importer."""

from __future__ import annotations

import copy
import hashlib
import importlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
for path in (ROOT, BACKEND):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

_policy_module: Any = importlib.import_module("scripts.import_llm_policy")
LLM_ENDPOINT_PATH = _policy_module.LLM_ENDPOINT_PATH
PolicyImportError = _policy_module.PolicyImportError
import_reviewed_policy = _policy_module.import_reviewed_policy
load_policy_file = _policy_module.load_policy_file
main = _policy_module.main
validate_reviewed_policy = _policy_module.validate_reviewed_policy


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


FIXTURE_HOST = ".".join(("fixture", "cn-beijing", "maas", "aliyuncs", "com"))  # noqa: FLY002
PUBLIC_HOST = "dashscope." + ".".join(("aliyuncs", "com"))  # noqa: FLY002


def _llm_document() -> dict[str, Any]:
    document: dict[str, Any] = {
        "reviewed": True,
        "provider": "dashscope",
        "model": "qwen3.7-plus-2026-05-26",
        "region": "cn-beijing",
        "endpoint": f"https://{FIXTURE_HOST}{LLM_ENDPOINT_PATH}",
        "contract_version": "ProviderDataCallV1",
        "policy_hash": "0" * 64,
        "policy_id": "real-llm-demo-policy",
        "supplier": "Alibaba Cloud Model Studio",
        "account_product": "payg_api",
        "privacy_notice_url": "https://help.aliyun.com/zh/model-studio/privacy-notice",
        "privacy_notice_retrieved_at": "2026-08-31T00:00:00Z",
        "privacy_notice_sha256": _digest("llm-privacy-review"),
        "service_terms_url": "https://help.aliyun.com/zh/model-studio/service-terms",
        "service_terms_retrieved_at": "2026-08-31T00:00:00Z",
        "service_terms_sha256": _digest("llm-terms-review"),
        "faq_url": "https://help.aliyun.com/zh/model-studio/faq",
        "faq_retrieved_at": "2026-08-31T00:00:00Z",
        "faq_sha256": _digest("llm-faq-review"),
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
        if key not in {"reviewed", "provider", "model", "contract_version", "policy_hash"}
    }
    document["policy_hash"] = ProviderPolicySnapshotV1(**policy_values).policy_hash
    return document


def test_empty_db_holds_embedding_and_llm_policies_and_repeats_idempotently(tmp_path: Path) -> None:
    db_module: Any = importlib.import_module("app.core.db")
    models_module: Any = importlib.import_module("app.core.models")
    sqlalchemy_module: Any = importlib.import_module("sqlalchemy")
    embedding_module: Any = importlib.import_module("scripts.import_provider_policy")
    embedding_test_module: Any = importlib.import_module("scripts.test_import_provider_policy")
    Database = db_module.Database
    ProviderPolicySnapshot = models_module.ProviderPolicySnapshot
    import_embedding = embedding_module.import_reviewed_policy
    embedding_document = embedding_test_module._document
    func, select = sqlalchemy_module.func, sqlalchemy_module.select

    database_url = f"sqlite:///{tmp_path / 'dual-policy.sqlite3'}"
    embedding = import_embedding(
        embedding_document(), database_url=database_url, acknowledge_reviewed=True
    )
    llm = _llm_document()
    first = import_reviewed_policy(llm, database_url=database_url, acknowledge_reviewed=True)
    second = import_reviewed_policy(llm, database_url=database_url, acknowledge_reviewed=True)

    assert embedding.status == "created"
    assert first.status == "created"
    assert second.status == "already_present"
    assert first.policy_hash == second.policy_hash == llm["policy_hash"]
    database = Database(database_url)
    try:
        with database.engine.connect() as connection:
            assert (
                connection.execute(
                    select(func.count()).select_from(ProviderPolicySnapshot)
                ).scalar_one()
                == 2
            )
    finally:
        database.dispose()


def test_reviewed_acknowledgement_is_required_before_creating_db(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'not-created.sqlite3'}"
    with pytest.raises(PolicyImportError, match="acknowledgement"):
        import_reviewed_policy(
            _llm_document(), database_url=database_url, acknowledge_reviewed=False
        )
    assert not (tmp_path / "not-created.sqlite3").exists()


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("provider", "openai"),
        ("model", "qwen max"),
        ("region", "us-east-1"),
        ("contract_version", "other"),
        ("endpoint", f"https://{FIXTURE_HOST}/wrong"),
    ),
)
def test_wrong_fixed_identity_fails_closed(field: str, value: object) -> None:
    document = _llm_document()
    document[field] = value
    with pytest.raises(PolicyImportError):
        validate_reviewed_policy(document, acknowledge_reviewed=True)


@pytest.mark.parametrize("field", ("no_training_basis", "retention_setting"))
def test_unreviewed_control_text_fails_closed(field: str) -> None:
    document = _llm_document()
    document[field] = "unreviewed"
    with pytest.raises(PolicyImportError, match="reviewed"):
        validate_reviewed_policy(document, acknowledge_reviewed=True)


def test_secret_shaped_field_and_value_fail_closed() -> None:
    document = _llm_document()
    with_secret_key = copy.deepcopy(document)
    with_secret_key["api_" + "key"] = "fixture-value"
    with pytest.raises(PolicyImportError, match="forbidden"):
        validate_reviewed_policy(with_secret_key, acknowledge_reviewed=True)

    with_secret_value = copy.deepcopy(document)
    with_secret_value["no_training_basis"] = "secret: fixture-value"
    with pytest.raises(PolicyImportError, match="forbidden"):
        validate_reviewed_policy(with_secret_value, acknowledge_reviewed=True)


def test_policy_hash_mismatch_fails_closed() -> None:
    document = _llm_document()
    document["policy_hash"] = "f" * 64
    with pytest.raises(PolicyImportError, match="policy_hash"):
        validate_reviewed_policy(document, acknowledge_reviewed=True)


@pytest.mark.parametrize(
    "endpoint",
    (
        f"https://{PUBLIC_HOST}{LLM_ENDPOINT_PATH}",
        f"https://{FIXTURE_HOST}{LLM_ENDPOINT_PATH}?x=1",
        f"https://{FIXTURE_HOST}:443{LLM_ENDPOINT_PATH}",
    ),
)
def test_endpoint_must_be_workspace_bound_and_query_free(endpoint: str) -> None:
    document = _llm_document()
    document["endpoint"] = endpoint
    with pytest.raises(PolicyImportError):
        validate_reviewed_policy(document, acknowledge_reviewed=True)


def test_file_loader_requires_named_json(tmp_path: Path) -> None:
    policy_path = tmp_path / "provider-policy-llm.json"
    policy_path.write_text(json.dumps(_llm_document()), encoding="utf-8")
    assert load_policy_file(policy_path)["model"] == "qwen3.7-plus-2026-05-26"

    env_path = tmp_path / ".env"
    env_path.write_text("DASHSCOPE_" + "API_KEY=fixture", encoding="utf-8")
    with pytest.raises(PolicyImportError):
        load_policy_file(env_path)


def test_cli_prints_only_status_and_hash(tmp_path: Path, capsys: Any) -> None:
    policy_path = tmp_path / "provider-policy-llm.json"
    policy_path.write_text(json.dumps(_llm_document()), encoding="utf-8")
    database_url = f"sqlite:///{tmp_path / 'cli.sqlite3'}"
    assert (
        main(
            [
                "--policy-file",
                str(policy_path),
                "--database-url",
                database_url,
                "--acknowledge-reviewed",
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "fixture.cn-beijing" not in output
    assert json.loads(output) == {
        "status": "created",
        "policy_hash": _llm_document()["policy_hash"],
    }
