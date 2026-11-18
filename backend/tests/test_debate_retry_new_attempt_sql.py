"""Real SQL staging path: spent failed turn with accepted bundle → new attempt."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from app.core.db import Database
from app.modules.debates.generation.segments_runtime import SegmentLLMRuntime
from app.providers.control import (
    LLM_DEBATE_TURN_BUCKET,
    ProviderScopeBudgetV1,
)
from app.providers.control_repository import ProviderRepository
from app.providers.llm_adapter import LLMUsageV1
from app.providers.llm_privacy import (
    LLM_SESSION_DISCUSSION_MEMORY_FIELD_CLASS,
    LLMOutboundManifestV1,
)
from app.providers.llm_segments import (
    SegmentAcceptedCandidateV2,
    SegmentLLMAdapter,
    SegmentLLMRequestV2,
)
from sqlalchemy import text

from tests.postgres_db import named_url
from tests.test_four_round_provider import opening_context, snapshot


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _manifest() -> LLMOutboundManifestV1:
    return LLMOutboundManifestV1(
        field_classes=(
            *LLMOutboundManifestV1().field_classes,
            LLM_SESSION_DISCUSSION_MEMORY_FIELD_CLASS,
        )
    )


class OfflineAdapter(SegmentLLMAdapter):
    def __init__(self, outputs: list[dict[str, object]]) -> None:
        super().__init__(
            SimpleNamespace(resolved_endpoint="https://offline.invalid/segments"),
            outbound_manifest=_manifest(),
        )
        self.outputs = outputs
        self.requests: list[SegmentLLMRequestV2] = []

    def send_accepted(self, request: SegmentLLMRequestV2) -> SegmentAcceptedCandidateV2:
        value = self.outputs[len(self.requests)]
        self.requests.append(request)
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"))
        return SegmentAcceptedCandidateV2(
            request=request,
            http_status=200,
            finish_reason="stop",
            usage=LLMUsageV1(1, 0, 1, 2),
            output_json=raw,
            output_hash=hashlib.sha256(raw.encode()).hexdigest(),
            provider_output=value,
        )


def _seed_turn(database: Database, *, debate_id: str, turn_id: str) -> None:
    now = datetime.now(UTC)
    with database.engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.exec_driver_sql("SET LOCAL session_replication_role = 'replica'")
            connection.execute(
                text(
                    "INSERT INTO debates (id,course_id,topic,rule_set_id,rule_snapshot_json,"
                    "output_language,status,"
                    "revision,last_sequence,cancellation_generation,created_by,created_at,updated_at,"
                    "started_at,finished_at,total_duration_seconds,turn_duration_seconds) "
                    "VALUES (:id,'course-retry','topic','rules','{}','en','draft',0,0,0,"
                    "'user-retry',"
                    ":now,:now,NULL,NULL,NULL,NULL)"
                ),
                {"id": debate_id, "now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO debate_turns (id,debate_id,participant_id,knowledge_snapshot_id,"
                    "round_no,"
                    "turn_index,generation_status,publication_status,preparation_stage,speech,"
                    "structured_json,"
                    "predecessor_turn_ids_json,transcript_hash,cutoff_turn_index,retrieval_status,"
                    "grounding_mode,"
                    "retrieval_receipts_json,evidence_trace_json,word_count,attempt,audio_file_id,"
                    "audio_duration_ms,"
                    "actual_tts_voice_kind,actual_tts_voice_profile_id,safe_error_code,"
                    "created_at,updated_at,public_at) "
                    "VALUES (:id,:debate_id,'participant-retry','snapshot-retry',1,0,"
                    "'failed','unpublished','failed',NULL,NULL,'[]',NULL,NULL,NULL,NULL,"
                    "'[]','[]',NULL,2,NULL,NULL,NULL,NULL,'turn_generation_failed',:now,:now,NULL)"
                ),
                {"id": turn_id, "debate_id": debate_id, "now": now},
            )
            transaction.commit()
        except Exception:
            transaction.rollback()
            raise


def _good_speech() -> dict[str, object]:
    return {
        "segments": [
            {
                "text": (
                    "I disagree with the opening claim because classroom attention "
                    "is a scarce resource and distraction lowers practice quality."
                ),
                "source_ids": [],
                "reply_to": None,
                "support_mode": "no_match",
            }
        ]
    }


@pytest.fixture
def sql_runtime(tmp_path: Path):
    database = Database(named_url(f"{tmp_path / 'retry-attempt.sqlite3'}"))
    database.upgrade_schema()
    debate_id = "debate-sql-retry"
    turn_id = "turn-sql-retry"
    _seed_turn(database, debate_id=debate_id, turn_id=turn_id)
    repository = ProviderRepository(database, require_export_confirmation=False)
    repository.save_scope_budget(
        debate_id,
        ProviderScopeBudgetV1(
            max_requests=20,
            max_total_tokens=400_000,
            max_cost_cny=10,
            budget_bucket=LLM_DEBATE_TURN_BUCKET,
        ),
    )
    provider = OfflineAdapter(
        [
            {"segments": []},
            {"segments": []},
            _good_speech(),
            _good_speech(),
            _good_speech(),
            _good_speech(),
        ]
    )
    runtime = SegmentLLMRuntime(
        ledger=repository,
        adapter=provider,
        stage_store=repository,
        defer_publication=True,
    )
    yield database, repository, runtime, provider, debate_id, turn_id
    database.dispose()


def test_sql_retry_after_accepted_bundle_stages_into_new_attempt(sql_runtime) -> None:
    """Reproduce prod: attempt 2 has immutable stage → Retry opens attempt 3."""

    database, repository, runtime, provider, debate_id, turn_id = sql_runtime
    frozen = snapshot()
    policy = _hash("policy")
    manifest = _hash("manifest")
    build = _hash("build")
    prepared = runtime.prepare(
        frozen,
        debate_id=debate_id,
        turn_id=turn_id,
        policy_hash=policy,
        manifest_hash=manifest,
        build_manifest_hash=build,
    )
    first = runtime.run(prepared, context=opening_context(), confirmed=True)
    assert first.status == "succeeded"
    assert first.safe_error_code == "segment_output_salvaged"

    # Locate attempt 2 and confirm its accepted bundle is durable.
    with database.engine.connect() as connection:
        row = (
            connection.execute(
                text(
                    "SELECT id, attempt_no, state FROM provider_operations "
                    "WHERE logical_item_id=:turn ORDER BY attempt_no DESC LIMIT 1"
                ),
                {"turn": turn_id},
            )
            .mappings()
            .one()
        )
        assert int(row["attempt_no"]) == 2
        op_id = str(row["id"])
        stage_count = connection.execute(
            text("SELECT COUNT(*) FROM llm_accepted_stages WHERE operation_id=:id"),
            {"id": op_id},
        ).scalar_one()
        assert int(stage_count) == 1

    # Mark spent failed while keeping the immutable accepted bundle (prod shape).
    with database.engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE provider_operations SET state='failed', "
                "safe_error_code='segment_stage_failed', "
                "request_hash=:stale, staged_response_hash=NULL, updated_at=CURRENT_TIMESTAMP "
                "WHERE id=:id"
            ),
            {"id": op_id, "stale": "e" * 64},
        )

    spent_stage = repository.get_llm_accepted_stage(op_id)
    assert spent_stage is not None

    # Teacher Retry prepares a NEW attempt and stages successfully.
    prepared_again = runtime.prepare(
        frozen,
        debate_id=debate_id,
        turn_id=turn_id,
        policy_hash=policy,
        manifest_hash=manifest,
        build_manifest_hash=build,
    )
    assert prepared_again.attempt_no == 3
    assert prepared_again.operation_id != op_id
    second = runtime.run(prepared_again, context=opening_context(), confirmed=True)
    assert second.status == "succeeded"
    assert second.final_ready is not None
    assert second.final_ready.speech.strip()
    assert "scarce resource" in second.final_ready.speech

    with database.engine.connect() as connection:
        attempts = (
            connection.execute(
                text(
                    "SELECT id, attempt_no, state, charged_request_count, request_count "
                    "FROM provider_operations "
                    "WHERE logical_item_id=:turn ORDER BY attempt_no"
                ),
                {"turn": turn_id},
            )
            .mappings()
            .all()
        )
        assert [int(item["attempt_no"]) for item in attempts] == [1, 2, 3]
        # New attempt 3 is the charged row; spent attempt 2 stays immutable.
        assert attempts[1]["id"] == op_id
        assert int(attempts[2]["charged_request_count"] or 0) >= 1
        assert int(attempts[2]["request_count"] or 0) >= 1
        assert (
            connection.execute(
                text("SELECT COUNT(*) FROM llm_accepted_stages WHERE turn_id=:turn"),
                {"turn": turn_id},
            ).scalar_one()
            >= 2
        )
        # Spent attempt 2 bundle remains.
        assert (
            connection.execute(
                text("SELECT COUNT(*) FROM llm_accepted_stages WHERE operation_id=:id"),
                {"id": op_id},
            ).scalar_one()
            == 1
        )
        # Attempt 2 must not have been rewritten after Retry.
        assert repository.get_llm_accepted_stage(op_id) is not None

    # Three more Retry clicks remain safe (new attempt each time).
    for expected in (4, 5, 6):
        current_id = prepared_again.operation_id
        with database.engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE provider_operations SET state='failed', "
                    "safe_error_code='segment_stage_failed', updated_at=CURRENT_TIMESTAMP "
                    "WHERE logical_item_id=:turn AND attempt_no=:attempt"
                ),
                {"turn": turn_id, "attempt": expected - 1},
            )
        prepared_again = runtime.prepare(
            frozen,
            debate_id=debate_id,
            turn_id=turn_id,
            policy_hash=policy,
            manifest_hash=manifest,
            build_manifest_hash=build,
        )
        assert prepared_again.attempt_no == expected
        assert prepared_again.operation_id != current_id
        outcome = runtime.run(prepared_again, context=opening_context(), confirmed=True)
        assert outcome.status == "succeeded"
        assert outcome.final_ready is not None

    assert len(provider.requests) >= 5


def test_sql_three_rapid_prepares_after_spent_bundle_are_idempotent_or_advance(
    sql_runtime,
) -> None:
    """Three overlapping prepares must not mutate the spent accepted bundle."""

    database, repository, runtime, provider, debate_id, turn_id = sql_runtime
    frozen = snapshot()
    policy = _hash("policy-rapid")
    manifest = _hash("manifest-rapid")
    build = _hash("build-rapid")
    prepared = runtime.prepare(
        frozen,
        debate_id=debate_id,
        turn_id=turn_id,
        policy_hash=policy,
        manifest_hash=manifest,
        build_manifest_hash=build,
    )
    first = runtime.run(prepared, context=opening_context(), confirmed=True)
    assert first.status == "succeeded"

    with database.engine.connect() as connection:
        spent = (
            connection.execute(
                text(
                    "SELECT id FROM provider_operations "
                    "WHERE logical_item_id=:turn ORDER BY attempt_no DESC LIMIT 1"
                ),
                {"turn": turn_id},
            )
            .mappings()
            .one()
        )
        spent_id = str(spent["id"])
    with database.engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE provider_operations SET state='failed', "
                "safe_error_code='segment_stage_failed', "
                "request_hash=:stale, staged_response_hash=NULL, updated_at=CURRENT_TIMESTAMP "
                "WHERE id=:id"
            ),
            {"id": spent_id, "stale": "f" * 64},
        )

    prepared_rows = [
        runtime.prepare(
            frozen,
            debate_id=debate_id,
            turn_id=turn_id,
            policy_hash=policy,
            manifest_hash=manifest,
            build_manifest_hash=build,
        )
        for _ in range(3)
    ]
    assert all(row.attempt_no >= 3 for row in prepared_rows)
    assert all(row.operation_id != spent_id for row in prepared_rows)
    # Either they share the first new attempt (idempotent same identity) or
    # later clicks open later attempts — never rewrite the spent row.
    assert repository.get_llm_accepted_stage(spent_id) is not None
    with database.engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT COUNT(*) FROM llm_accepted_stages WHERE operation_id=:id"),
                {"id": spent_id},
            ).scalar_one()
            == 1
        )
        assert (
            connection.execute(
                text(
                    "SELECT COUNT(*) FROM provider_operations "
                    "WHERE logical_item_id=:turn AND attempt_no >= 3"
                ),
                {"turn": turn_id},
            ).scalar_one()
            >= 1
        )
    # One successful run still stages into a non-spent operation.
    outcome = runtime.run(prepared_rows[0], context=opening_context(), confirmed=True)
    assert outcome.status == "succeeded"
    assert outcome.final_ready is not None
    assert repository.get_llm_accepted_stage(spent_id) is not None
