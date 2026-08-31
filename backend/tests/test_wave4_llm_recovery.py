"""Focused 0015 canonical-input recovery ledger coverage."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from app.core.db import Database
from app.providers.control import (
    LLM_DEBATE_TURN_BUCKET,
    LLM_RECOVERY_INPUT_BYTES_LIMIT,
    LLM_RECOVERY_INPUT_VERSION,
    InMemoryProviderOperationRepository,
    LLMAcceptedStageV1,
    LLMRecoveryInputV1,
    ProviderControlError,
    ProviderReservationRequestV1,
    ProviderScopeBudgetV1,
    canonical_json_bytes,
    sha256_hex,
)
from app.providers.control_repository import ProviderRepository, ProviderRepositoryError
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

_RECOVERY_IDENTITY_KEYS = (
    "request_hash",
    "prompt_hash",
    "prompt_contract_version",
    "schema_hash",
    "tokenizer_id",
    "tokenizer_hash",
    "rule_set_hash",
    "persona_spec_hash",
    "transcript_hash",
    "receipt_hash",
    "policy_hash",
    "export_manifest_hash",
    "build_manifest_hash",
    "repair_policy_hash",
    "generation_fence",
    "model_key",
    "debate_id",
    "turn_id",
    "attempt_no",
)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _assert_stage_equal(actual: LLMAcceptedStageV1, expected: LLMAcceptedStageV1) -> None:
    """Compare the SQL projection while allowing Decimal scale normalization."""

    actual_record = actual.as_record()
    expected_record = expected.as_record()
    for field in (
        "input_price_cny_per_million",
        "cached_input_price_cny_per_million",
        "output_price_cny_per_million",
        "estimated_cost_cny",
        "actual_cost_cny",
    ):
        actual_value = actual_record.pop(field)
        expected_value = expected_record.pop(field)
        if actual_value is None or expected_value is None:
            assert actual_value == expected_value
        else:
            assert Decimal(str(actual_value)) == Decimal(str(expected_value))
    assert actual_record == expected_record


def _request(
    *, debate_id: str = "debate-recovery", turn_id: str = "turn-recovery"
) -> ProviderReservationRequestV1:
    return ProviderReservationRequestV1(
        scope_id=debate_id,
        provider_operation="llm_debate_turn",
        logical_item_id=turn_id,
        attempt_no=1,
        request_hash=_hash("request"),
        max_tokens=20,
        max_cost_cny=0.001,
        policy_hash=_hash("policy"),
        export_manifest_hash=_hash("manifest"),
        build_manifest_hash=_hash("build"),
        model_key="qwen3.7-plus-2026-05-26",
    )


def _stage(operation_id: str, request: ProviderReservationRequestV1) -> LLMAcceptedStageV1:
    output = {"ok": True}
    return LLMAcceptedStageV1(
        operation_id=operation_id,
        turn_id=request.logical_item_id,
        attempt_no=request.attempt_no,
        request_hash=request.request_hash,
        prompt_hash=_hash("prompt"),
        prompt_contract_version="prompt_request_v1",
        schema_hash=_hash("schema"),
        tokenizer_id="pinned-tokenizer",
        tokenizer_hash=_hash("tokenizer"),
        rule_set_hash=_hash("rules"),
        persona_spec_hash=_hash("persona"),
        transcript_hash=_hash("transcript"),
        receipt_hash=_hash("receipts"),
        policy_hash=request.policy_hash,
        export_manifest_hash=request.export_manifest_hash,
        build_manifest_hash=request.build_manifest_hash,
        model_key=request.model_key,
        output_json=json.dumps(output),
        output_hash=sha256_hex(canonical_json_bytes(output)),
        prompt_tokens=4,
        cached_input_tokens=1,
        completion_tokens=2,
        total_tokens=6,
        input_price_cny_per_million="1",
        cached_input_price_cny_per_million="1",
        output_price_cny_per_million="1",
        estimated_cost_cny="0.000006",
    )


def _recovery_input(
    stage: LLMAcceptedStageV1, request: ProviderReservationRequestV1
) -> LLMRecoveryInputV1:
    envelope = {
        "identity": {
            "request_hash": stage.request_hash,
            "prompt_hash": stage.prompt_hash,
            "prompt_contract_version": stage.prompt_contract_version,
            "schema_hash": stage.schema_hash,
            "tokenizer_id": stage.tokenizer_id,
            "tokenizer_hash": stage.tokenizer_hash,
            "rule_set_hash": stage.rule_set_hash,
            "persona_spec_hash": stage.persona_spec_hash,
            "transcript_hash": stage.transcript_hash,
            "receipt_hash": stage.receipt_hash,
            "policy_hash": stage.policy_hash,
            "export_manifest_hash": stage.export_manifest_hash,
            "build_manifest_hash": stage.build_manifest_hash,
            "repair_policy_hash": stage.repair_policy_hash,
            "generation_fence": stage.generation_fence,
            "model_key": stage.model_key,
            "debate_id": request.scope_id,
            "turn_id": stage.turn_id,
            "attempt_no": stage.attempt_no,
        },
        "input": {
            "request_version": "prompt_request_v1",
            "topic": "A safe recovery input.",
        },
    }
    encoded = canonical_json_bytes(envelope).decode("utf-8")
    return LLMRecoveryInputV1(
        operation_id=stage.operation_id,
        turn_id=stage.turn_id,
        attempt_no=stage.attempt_no,
        input_version=LLM_RECOVERY_INPUT_VERSION,
        input_json=encoded,
        input_hash=sha256_hex(encoded),
    )


def _recovery_with_document(
    recovery_input: LLMRecoveryInputV1,
    document: dict[str, object],
) -> LLMRecoveryInputV1:
    encoded = canonical_json_bytes(document).decode("utf-8")
    return replace(
        recovery_input,
        input_json=encoded,
        input_hash=sha256_hex(encoded),
    )


def _recovery_document(recovery_input: LLMRecoveryInputV1) -> dict[str, object]:
    return json.loads(recovery_input.input_json)


def _prepare_in_memory() -> tuple[
    InMemoryProviderOperationRepository,
    ProviderReservationRequestV1,
    LLMAcceptedStageV1,
    LLMRecoveryInputV1,
]:
    repository = InMemoryProviderOperationRepository(
        default_budget=ProviderScopeBudgetV1(
            max_requests=1,
            max_total_tokens=20,
            max_cost_cny=0.01,
            budget_bucket=LLM_DEBATE_TURN_BUCKET,
        )
    )
    request = _request()
    operation = repository.create_prepared(request)
    repository.reserve(operation.id)
    repository.transition(operation.id, expected="reserved", state="sending")
    stage = _stage(operation.id, request)
    recovery_input = _recovery_input(stage, request)
    return repository, request, stage, recovery_input


def _migration_config(database: Database) -> Config:
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[1] / "migrations")
    )
    config.set_main_option("sqlalchemy.url", database.database_url)
    config.attributes["database_url"] = database.database_url
    return config


def _seed_turn(database: Database, *, debate_id: str, turn_id: str) -> None:
    """Add only the parent keys needed by accepted-stage FK checks."""

    now = datetime.now(UTC)
    with database.engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        # PRAGMA execution autobegins a transaction on SQLite.  End that
        # transaction before starting the explicit seed transaction so the
        # parent rows are inserted as one unit.
        connection.commit()
        transaction = connection.begin()
        try:
            connection.execute(
                text(
                    "INSERT INTO debates (id,course_id,topic,rule_set_id,rule_snapshot_json,status,"
                    "revision,last_sequence,cancellation_generation,created_by,created_at,updated_at,"
                    "started_at,finished_at,total_duration_seconds,turn_duration_seconds) "
                    "VALUES (:id,'course-recovery','topic','rules','{}','running',0,0,0,"
                    "'user-recovery',"
                    ":now,:now,NULL,NULL,NULL,NULL)"
                ),
                {"id": debate_id, "now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO debate_turns (id,debate_id,participant_id,knowledge_snapshot_id,"
                    "round_no,"
                    "turn_index,generation_status,publication_status,preparation_stage,speech,structured_json,"
                    "predecessor_turn_ids_json,transcript_hash,cutoff_turn_index,retrieval_status,grounding_mode,"
                    "retrieval_receipts_json,word_count,attempt,audio_file_id,audio_duration_ms,"
                    "actual_tts_voice_kind,actual_tts_voice_profile_id,safe_error_code,"
                    "created_at,updated_at,public_at) "
                    "VALUES (:id,:debate_id,'participant-recovery','snapshot-recovery',1,0,"
                    "'running','unpublished','generation',NULL,NULL,'[]',NULL,NULL,NULL,NULL,"
                    "'[]',NULL,1,NULL,NULL,NULL,NULL,NULL,:now,:now,NULL)"
                ),
                {"id": turn_id, "debate_id": debate_id, "now": now},
            )
            transaction.commit()
        except Exception:
            transaction.rollback()
            raise
        finally:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")


def _prepare_sql(
    tmp_path: Path,
) -> tuple[
    Database,
    ProviderRepository,
    ProviderReservationRequestV1,
    LLMAcceptedStageV1,
    LLMRecoveryInputV1,
]:
    database = Database(f"sqlite:///{tmp_path / 'recovery.sqlite3'}")
    database.upgrade_schema()
    request = _request()
    _seed_turn(database, debate_id=request.scope_id, turn_id=request.logical_item_id)
    repository = ProviderRepository(database, require_export_confirmation=False)
    repository.save_scope_budget(
        request.scope_id,
        ProviderScopeBudgetV1(
            max_requests=1,
            max_total_tokens=20,
            max_cost_cny=0.01,
            budget_bucket=LLM_DEBATE_TURN_BUCKET,
        ),
    )
    operation = repository.create_prepared(request)
    repository.reserve(operation.id)
    repository.transition(operation.id, expected="reserved", state="sending")
    stage = _stage(operation.id, request)
    recovery_input = _recovery_input(stage, request)
    return database, repository, request, stage, recovery_input


def test_recovery_input_is_canonical_closed_and_forbidden_data_free() -> None:
    repository, request, stage, recovery_input = _prepare_in_memory()
    assert recovery_input.input_hash == sha256_hex(recovery_input.input_json)
    assert len(recovery_input.input_json.encode("utf-8")) < LLM_RECOVERY_INPUT_BYTES_LIMIT
    assert repository.stage_llm_accepted_with_recovery(stage, recovery_input) == stage
    bundle = repository.load_llm_accepted_bundle(stage.operation_id)
    assert bundle is not None
    assert bundle.stage == stage
    assert bundle.recovery_input == recovery_input

    with pytest.raises(Exception, match="canonical"):
        LLMRecoveryInputV1(
            operation_id=stage.operation_id,
            turn_id=request.logical_item_id,
            attempt_no=1,
            input_version=LLM_RECOVERY_INPUT_VERSION,
            input_json='{"identity": {}, "input": {}}',
            input_hash=sha256_hex('{"identity": {}, "input": {}}'),
        )
    forbidden = {
        "identity": {
            key: value for key, value in json.loads(recovery_input.input_json)["identity"].items()
        },
        "input": {"teacher_note": "do not persist"},
    }
    forbidden_json = canonical_json_bytes(forbidden).decode("utf-8")
    with pytest.raises(Exception, match="forbidden"):
        LLMRecoveryInputV1(
            operation_id=stage.operation_id,
            turn_id=request.logical_item_id,
            attempt_no=1,
            input_version=LLM_RECOVERY_INPUT_VERSION,
            input_json=forbidden_json,
            input_hash=sha256_hex(forbidden_json),
        )


@pytest.mark.parametrize("identity_key", _RECOVERY_IDENTITY_KEYS)
def test_recovery_input_binds_every_identity_field_to_stage(
    identity_key: str,
) -> None:
    repository, request, stage, recovery_input = _prepare_in_memory()
    document = _recovery_document(recovery_input)
    identity = document["identity"]
    assert isinstance(identity, dict)
    if identity_key.endswith("_hash"):
        identity[identity_key] = _hash(f"tampered-{identity_key}")
    elif identity_key == "attempt_no":
        identity[identity_key] = 2
    elif identity_key == "generation_fence":
        identity[identity_key] = "tampered-generation-fence"
    else:
        identity[identity_key] = f"tampered-{identity_key}"
    tampered = _recovery_with_document(recovery_input, document)

    with pytest.raises(ProviderControlError, match="identity"):
        repository.stage_llm_accepted_with_recovery(stage, tampered)
    assert repository.operation(stage.operation_id).state == "sending"
    assert repository.load_llm_accepted_bundle(stage.operation_id) is None


@pytest.mark.parametrize(
    "forbidden_payload",
    [
        {"raw_agent_md": "private instructions"},
        {"teacher_note": "private note"},
        {"credentials": {"value": "private"}},
        {"header": "Authorization: redacted"},
        {"endpoint": "https://example.invalid"},
        {"nested": {"identity": {"opaque": "private"}}},
        {"safe_text": "authorization: redacted"},
        {"safe_bearer": "Bearer sk-redacted"},
        {"safe_key": "sk-redacted"},
        {"safe_path": "/Users/private/agent.md"},
    ],
)
def test_recovery_input_rejects_forbidden_fields_and_values(
    forbidden_payload: dict[str, object],
) -> None:
    _repository, request, stage, recovery_input = _prepare_in_memory()
    document = _recovery_document(recovery_input)
    nested_input = document["input"]
    assert isinstance(nested_input, dict)
    nested_input.update(forbidden_payload)
    encoded = canonical_json_bytes(document).decode("utf-8")

    with pytest.raises(ProviderControlError, match="forbidden"):
        LLMRecoveryInputV1(
            operation_id=stage.operation_id,
            turn_id=request.logical_item_id,
            attempt_no=1,
            input_version=LLM_RECOVERY_INPUT_VERSION,
            input_json=encoded,
            input_hash=sha256_hex(encoded),
        )


def test_recovery_input_size_limit_counts_utf8_bytes() -> None:
    _repository, request, stage, recovery_input = _prepare_in_memory()
    document = _recovery_document(recovery_input)
    nested_input = document["input"]
    assert isinstance(nested_input, dict)
    nested_input["topic"] = "界" * (LLM_RECOVERY_INPUT_BYTES_LIMIT // 3 + 128)
    encoded = canonical_json_bytes(document).decode("utf-8")
    assert len(encoded.encode("utf-8")) > LLM_RECOVERY_INPUT_BYTES_LIMIT

    with pytest.raises(ProviderControlError) as raised:
        _recovery_with_document(recovery_input, document)
    assert raised.value.code == "llm_recovery_input_size_exceeded"


def test_sql_stage_with_recovery_is_atomic_and_loads_exact_bundle(tmp_path: Path) -> None:
    database, repository, _request_value, stage, recovery_input = _prepare_sql(tmp_path)
    try:
        assert repository.stage_llm_accepted_with_recovery(stage, recovery_input) == stage
        bundle = repository.load_llm_accepted_bundle(stage.operation_id)
        assert bundle is not None
        _assert_stage_equal(bundle.stage, stage)
        assert bundle.recovery_input == recovery_input
        with database.engine.connect() as connection:
            assert (
                connection.execute(text("SELECT state FROM provider_operations")).scalar_one()
                == "accepted"
            )
            assert (
                connection.execute(text("SELECT state FROM provider_reservations")).scalar_one()
                == "accepted"
            )
            assert (
                connection.execute(text("SELECT COUNT(*) FROM llm_accepted_stages")).scalar_one()
                == 1
            )
            assert (
                connection.execute(text("SELECT COUNT(*) FROM llm_recovery_inputs")).scalar_one()
                == 1
            )
    finally:
        database.dispose()


def test_sql_stage_with_recovery_is_idempotent_and_immutable(tmp_path: Path) -> None:
    database, repository, _request_value, stage, recovery_input = _prepare_sql(tmp_path)
    try:
        assert repository.stage_llm_accepted_with_recovery(stage, recovery_input) == stage
        repeated = repository.stage_llm_accepted_with_recovery(stage, recovery_input)
        _assert_stage_equal(repeated, stage)

        changed_document = _recovery_document(recovery_input)
        changed_input = changed_document["input"]
        assert isinstance(changed_input, dict)
        changed_input["topic"] = "A different but still safe recovery input."
        changed_recovery = _recovery_with_document(recovery_input, changed_document)
        with pytest.raises(ProviderRepositoryError, match="immutable"):
            repository.stage_llm_accepted_with_recovery(stage, changed_recovery)
        with database.engine.connect() as connection:
            assert (
                connection.execute(text("SELECT COUNT(*) FROM llm_accepted_stages")).scalar_one()
                == 1
            )
            assert (
                connection.execute(text("SELECT COUNT(*) FROM llm_recovery_inputs")).scalar_one()
                == 1
            )
    finally:
        database.dispose()


def test_sql_atomic_failure_rolls_back_both_rows(tmp_path: Path) -> None:
    database, repository, _request_value, stage, recovery_input = _prepare_sql(tmp_path)
    try:
        with database.engine.begin() as connection:
            connection.execute(
                text("UPDATE provider_reservations SET state='accepted' WHERE operation_id=:id"),
                {"id": stage.operation_id},
            )
        with pytest.raises(ProviderRepositoryError, match="transition"):
            repository.stage_llm_accepted_with_recovery(stage, recovery_input)
        with database.engine.connect() as connection:
            assert (
                connection.execute(text("SELECT COUNT(*) FROM llm_accepted_stages")).scalar_one()
                == 0
            )
            assert (
                connection.execute(text("SELECT COUNT(*) FROM llm_recovery_inputs")).scalar_one()
                == 0
            )
            assert (
                connection.execute(text("SELECT state FROM provider_operations")).scalar_one()
                == "sending"
            )
    finally:
        database.dispose()


def test_sql_recovery_input_trigger_and_tamper_fail_closed(tmp_path: Path) -> None:
    database, repository, _request_value, stage, recovery_input = _prepare_sql(tmp_path)
    try:
        repository.stage_llm_accepted_with_recovery(stage, recovery_input)
        with pytest.raises(IntegrityError):
            with database.engine.begin() as connection:
                connection.execute(
                    text("UPDATE llm_recovery_inputs SET input_hash=:hash WHERE operation_id=:id"),
                    {"hash": _hash("tampered"), "id": stage.operation_id},
                )
        with database.engine.connect() as connection:
            assert (
                connection.execute(text("SELECT input_hash FROM llm_recovery_inputs")).scalar_one()
                == recovery_input.input_hash
            )
    finally:
        database.dispose()


def test_sql_orphan_recovery_input_is_a_partial_bundle_error(tmp_path: Path) -> None:
    database, repository, _request_value, stage, recovery_input = _prepare_sql(tmp_path)
    try:
        with database.engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO llm_recovery_inputs "
                    "(operation_id,turn_id,attempt_no,input_version,input_json,input_hash,"
                    "created_at) "
                    "VALUES (:operation_id,:turn_id,:attempt_no,:input_version,:input_json,"
                    ":input_hash,:created_at)"
                ),
                {
                    **recovery_input.as_record(),
                    "created_at": datetime.now(UTC),
                },
            )
        with pytest.raises(ProviderRepositoryError, match="no accepted stage"):
            repository.load_llm_accepted_bundle(stage.operation_id)
        assert repository.operation(stage.operation_id).state == "sending"
    finally:
        database.dispose()


def test_sqlite_recovery_input_size_check_counts_utf8_bytes(tmp_path: Path) -> None:
    database, _repository, _request_value, stage, recovery_input = _prepare_sql(tmp_path)
    try:
        oversized = "界" * (LLM_RECOVERY_INPUT_BYTES_LIMIT // 3 + 128)
        assert len(oversized.encode("utf-8")) > LLM_RECOVERY_INPUT_BYTES_LIMIT
        with pytest.raises(IntegrityError):
            with database.engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO llm_recovery_inputs "
                        "(operation_id,turn_id,attempt_no,input_version,input_json,input_hash,"
                        "created_at) "
                        "VALUES (:operation_id,:turn_id,:attempt_no,:input_version,:input_json,"
                        ":input_hash,:created_at)"
                    ),
                    {
                        "operation_id": stage.operation_id,
                        "turn_id": recovery_input.turn_id,
                        "attempt_no": recovery_input.attempt_no,
                        "input_version": LLM_RECOVERY_INPUT_VERSION,
                        "input_json": oversized,
                        "input_hash": _hash("oversized"),
                        "created_at": datetime.now(UTC),
                    },
                )
    finally:
        database.dispose()


def test_legacy_accepted_stage_remains_readable_but_not_recoverable(tmp_path: Path) -> None:
    database, repository, _request_value, stage, _recovery_input_value = _prepare_sql(tmp_path)
    try:
        repository.stage_llm_accepted(stage)
        legacy_stage = repository.get_llm_accepted_stage(stage.operation_id)
        assert legacy_stage is not None
        _assert_stage_equal(legacy_stage, stage)
        assert repository.load_llm_accepted_bundle(stage.operation_id) is None
        assert repository.recover_one(stage.operation_id).state == "accepted"
        assert repository.operation(stage.operation_id).state == "accepted"
        with database.engine.connect() as connection:
            assert (
                connection.execute(text("SELECT COUNT(*) FROM llm_recovery_inputs")).scalar_one()
                == 0
            )
    finally:
        database.dispose()


def test_0015_schema_has_no_backfill_and_empty_round_trip(tmp_path: Path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'migration.sqlite3'}")
    config = _migration_config(database)
    try:
        command.upgrade(config, "0014_llm_runtime_budget_buckets")
        assert not inspect(database.engine).has_table("llm_recovery_inputs")
        command.upgrade(config, "head")
        command.upgrade(config, "head")
        inspector = inspect(database.engine)
        assert inspector.has_table("llm_recovery_inputs")
        assert [item["name"] for item in inspector.get_columns("llm_recovery_inputs")] == [
            "operation_id",
            "turn_id",
            "attempt_no",
            "input_version",
            "input_json",
            "input_hash",
            "created_at",
        ]
        assert {item["name"] for item in inspector.get_indexes("llm_recovery_inputs")} == {
            "ix_llm_recovery_inputs_turn"
        }
        with database.engine.connect() as connection:
            assert {
                row[0]
                for row in connection.execute(
                    text(
                        "SELECT name FROM sqlite_master WHERE type='trigger' "
                        "AND tbl_name='llm_recovery_inputs'"
                    )
                ).all()
            } == {
                "trg_llm_recovery_inputs_immutable_update",
                "trg_llm_recovery_inputs_immutable_delete",
            }
        command.downgrade(config, "0014_llm_runtime_budget_buckets")
        assert not inspect(database.engine).has_table("llm_recovery_inputs")
        command.upgrade(config, "head")
        assert inspect(database.engine).has_table("llm_recovery_inputs")
    finally:
        database.dispose()


def test_0014_populated_budget_survives_0015_upgrade_downgrade_and_reupgrade(
    tmp_path: Path,
) -> None:
    database = Database(f"sqlite:///{tmp_path / 'migration-populated.sqlite3'}")
    config = _migration_config(database)
    now = datetime.now(UTC)
    try:
        command.upgrade(config, "0014_llm_runtime_budget_buckets")
        with database.engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO provider_scope_budgets "
                    "(scope_id,budget_bucket,max_requests,max_total_tokens,max_cost_cny,"
                    "allocated_requests,allocated_total_tokens,allocated_cost_cny,"
                    "created_at,updated_at) "
                    "VALUES ('debate-migration','llm_debate_turn',3,30,0.03,1,6,0.006,:now,:now)"
                ),
                {"now": now},
            )
        command.upgrade(config, "head")
        with database.engine.connect() as connection:
            assert connection.execute(
                text(
                    "SELECT budget_bucket,allocated_requests,allocated_total_tokens "
                    "FROM provider_scope_budgets WHERE scope_id='debate-migration'"
                )
            ).one() == ("llm_debate_turn", 1, 6)

        command.downgrade(config, "0014_llm_runtime_budget_buckets")
        assert not inspect(database.engine).has_table("llm_recovery_inputs")
        command.upgrade(config, "head")
        with database.engine.connect() as connection:
            assert connection.execute(
                text(
                    "SELECT budget_bucket,allocated_requests,allocated_total_tokens "
                    "FROM provider_scope_budgets WHERE scope_id='debate-migration'"
                )
            ).one() == ("llm_debate_turn", 1, 6)
    finally:
        database.dispose()


def test_0015_populated_recovery_row_refuses_downgrade(tmp_path: Path) -> None:
    database, repository, _request_value, stage, recovery_input = _prepare_sql(tmp_path)
    config = _migration_config(database)
    try:
        repository.stage_llm_accepted_with_recovery(stage, recovery_input)
        with pytest.raises(RuntimeError, match="retained"):
            command.downgrade(config, "0014_llm_runtime_budget_buckets")
        with database.engine.connect() as connection:
            assert (
                connection.execute(text("SELECT COUNT(*) FROM llm_recovery_inputs")).scalar_one()
                == 1
            )
        assert inspect(database.engine).has_table("llm_recovery_inputs")
    finally:
        database.dispose()
