"""Focused coverage for the bounded Real-Core Demo acceptance-run ledger."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from app.core.db import Database
from app.core.errors import PlatformError
from app.core.models import (
    Agent,
    AgentVersion,
    KnowledgeSnapshot,
    StoredFile,
)
from app.modules.demo_acceptance.schemas import (
    DemoAcceptanceCallRequest,
    DemoAcceptanceRunCreateRequest,
)
from app.modules.demo_acceptance.service import (
    attach_acceptance_call,
    create_acceptance_run,
    get_acceptance_run,
)
from app.modules.demo_baseline.service import (
    BASELINE_AGENT_ID,
    BASELINE_SNAPSHOT_ID,
    BASELINE_VERSION_ID,
    ensure_demo_baseline,
)
from app.providers.control import ProviderReservationRequestV1
from app.providers.control_repository import ProviderRepository
from app.seed import GROUP_BOWEN_ID, TEACHER_ID, seed_demo_data
from pydantic import ValidationError
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

TARGET_AGENT_ID = "11111111-1111-4111-8111-111111111111"
TARGET_VERSION_ID = "22222222-2222-4222-8222-222222222222"
TARGET_SNAPSHOT_ID = "33333333-3333-4333-8333-333333333333"
TARGET_FILE_ID = "44444444-4444-4444-8444-444444444444"
FIXTURE_HASH = hashlib.sha256(b"real-core-demo-fixture").hexdigest()
HASH_A = "a" * 64
HASH_B = "b" * 64


def _manifest_hash(item: str) -> str:
    return hashlib.sha256(f"manifest:{item}".encode()).hexdigest()


def _migration_config(database_url: str) -> Config:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).parents[1] / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    config.attributes["database_url"] = database_url
    return config


def _now() -> datetime:
    return datetime.now(UTC)


def _database(tmp_path: Path) -> Database:
    database = Database(f"sqlite:///{tmp_path / 'ledger.sqlite3'}", tmp_path)
    database.initialize_schema()
    with database.session() as session:
        seed_demo_data(session)
        ensure_demo_baseline(session, tmp_path)
        now = _now()
        session.add(
            Agent(
                id=TARGET_AGENT_ID,
                group_id=GROUP_BOWEN_ID,
                name="Target Guide",
                description="Target fixture",
                status="active",
                current_published_version_id=None,
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            StoredFile(
                id=TARGET_FILE_ID,
                kind="snapshot_rag",
                relative_path="groups/target/rag.md",
                sha256=HASH_A,
                size_bytes=1,
                state="active",
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            AgentVersion(
                id=TARGET_VERSION_ID,
                agent_id=TARGET_AGENT_ID,
                version_seq=0,
                state="draft",
                revision=0,
                agent_md="# Target Guide",
                avatar_config_json="{}",
                knowledge_snapshot_id=TARGET_SNAPSHOT_ID,
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            KnowledgeSnapshot(
                id=TARGET_SNAPSHOT_ID,
                agent_version_id=TARGET_VERSION_ID,
                stored_file_id=TARGET_FILE_ID,
                content_hash=HASH_B,
                total_char_count=1,
                embedding_key="mock-sha256-v1",
                embedding_provider="mock",
                embedding_region="local",
                embedding_dimension=256,
                embedding_policy_version="w4-mock-v1",
                chunking_json="{}",
                created_at=now,
            )
        )
    return database


def _create_run(database: Database, *, fixture_hash: str = FIXTURE_HASH) -> str:
    with database.session() as session:
        result = create_acceptance_run(
            session,
            actor_user_id=TEACHER_ID,
            request=DemoAcceptanceRunCreateRequest(
                fixture_hash=fixture_hash,
                target_agent_id=UUID(TARGET_AGENT_ID),
                target_version_id=UUID(TARGET_VERSION_ID),
            ),
        )
        return str(result.id)


def _provider_operation(
    database: Database,
    *,
    item: str,
    purpose: str = "embedding",
    manifest_hash: str | None = None,
    scope_id: str = TARGET_VERSION_ID,
) -> str:
    request = ProviderReservationRequestV1(
        scope_id=scope_id,
        provider_operation=purpose,
        logical_item_id=item,
        attempt_no=1,
        request_hash=HASH_A,
        max_tokens=1,
        max_cost_cny=0.001,
        policy_hash=HASH_A,
        export_manifest_hash=manifest_hash or _manifest_hash(item),
    )
    return (
        ProviderRepository(database, require_export_confirmation=False).create_prepared(request).id
    )


def test_empty_db_migration_adds_null_legacy_bindings_and_preserves_downgrade(
    tmp_path: Path,
) -> None:
    path = tmp_path / "legacy.sqlite3"
    database_url = f"sqlite:///{path}"
    config = _migration_config(database_url)
    command.upgrade(config, "0015_llm_recovery_input")
    now = _now()
    with Database(database_url).engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO provider_operations "
                "(id,scope_id,provider_operation,logical_item_id,attempt_no,request_hash,"
                "max_tokens,max_cost_cny,policy_hash,export_manifest_hash,build_manifest_hash,"
                "model_key,state,request_count,charged_request_count,created_at,updated_at) "
                "VALUES (:id,'legacy','embedding','legacy-item',1,:hash,1,0,:hash,:hash,'',"
                "'','prepared',0,0,:now,:now)"
            ),
            {"id": "legacy-operation", "hash": HASH_A, "now": now},
        )
    command.upgrade(config, "head")
    with Database(database_url).engine.connect() as connection:
        assert connection.execute(
            text(
                "SELECT acceptance_run_id,call_no,request_count,charged_request_count "
                "FROM provider_operations WHERE id='legacy-operation'"
            )
        ).one() == (None, None, 0, 0)
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == (
            "0016_real_core_acceptance_run"
        )
    command.downgrade(config, "0015_llm_recovery_input")
    inspector = inspect(Database(database_url).engine)
    assert "demo_acceptance_runs" not in inspector.get_table_names()
    assert "acceptance_run_id" not in {
        str(column["name"]) for column in inspector.get_columns("provider_operations")
    }
    with Database(database_url).engine.connect() as connection:
        assert connection.execute(
            text("SELECT request_count,charged_request_count FROM provider_operations")
        ).one() == (0, 0)


def test_ledger_model_constraints_enforce_plan_initial_zero_pair_and_ordinal(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    try:
        now = _now()
        with pytest.raises(IntegrityError):
            with database.engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO demo_acceptance_runs "
                        "(id,plan_version,fixture_hash,baseline_agent_id,baseline_version_id,"
                        "baseline_snapshot_id,target_agent_id,target_version_id,state,"
                        "starting_charged_requests,created_at,updated_at) VALUES "
                        "(:id,'wrong',:hash,:ba,:bv,:bs,:ta,:tv,'prepared',0,:now,:now)"
                    ),
                    {
                        "id": str(uuid4()),
                        "hash": FIXTURE_HASH,
                        "ba": BASELINE_AGENT_ID,
                        "bv": BASELINE_VERSION_ID,
                        "bs": BASELINE_SNAPSHOT_ID,
                        "ta": TARGET_AGENT_ID,
                        "tv": TARGET_VERSION_ID,
                        "now": now,
                    },
                )
        run_id = _create_run(database)
        operation_id = _provider_operation(database, item="constraint-item")
        with pytest.raises(IntegrityError):
            with database.engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE provider_operations SET acceptance_run_id=:run_id "
                        "WHERE id=:operation_id"
                    ),
                    {"run_id": run_id, "operation_id": operation_id},
                )
    finally:
        database.dispose()


def test_create_is_exactly_idempotent_and_rejects_conflicting_or_historical_target(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    try:
        with database.session() as session:
            request = DemoAcceptanceRunCreateRequest(
                fixture_hash=FIXTURE_HASH,
                target_agent_id=UUID(TARGET_AGENT_ID),
                target_version_id=UUID(TARGET_VERSION_ID),
            )
            first = create_acceptance_run(session, actor_user_id=TEACHER_ID, request=request)
            second = create_acceptance_run(session, actor_user_id=TEACHER_ID, request=request)
            assert first.id == second.id
            assert first.starting_charged_requests == 0
            assert second.call_count == second.charged_request_count == 0
            with pytest.raises(PlatformError, match="target already belongs"):
                create_acceptance_run(
                    session,
                    actor_user_id=TEACHER_ID,
                    request=request.model_copy(update={"fixture_hash": "c" * 64}),
                )
        historical_database = _database(tmp_path / "historical")
        try:
            _provider_operation(historical_database, item="historical-item")
            with historical_database.session() as session:
                with pytest.raises(PlatformError, match="already has provider history"):
                    create_acceptance_run(
                        session,
                        actor_user_id=TEACHER_ID,
                        request=DemoAcceptanceRunCreateRequest(
                            fixture_hash="d" * 64,
                            target_agent_id=UUID(TARGET_AGENT_ID),
                            target_version_id=UUID(TARGET_VERSION_ID),
                        ),
                    )
        finally:
            historical_database.dispose()
    finally:
        database.dispose()


def test_attach_calls_one_to_seven_is_atomic_and_summary_counts_charges(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    try:
        run_id = _create_run(database)
        manifest_hashes = [_manifest_hash(f"call-{index}") for index in range(1, 8)]
        for call_no, manifest_hash in enumerate(manifest_hashes, start=1):
            operation_id = _provider_operation(
                database,
                item=f"call-{call_no}",
                manifest_hash=manifest_hash,
            )
            with database.session() as session:
                response = attach_acceptance_call(
                    session,
                    actor_user_id=TEACHER_ID,
                    run_id=run_id,
                    request=DemoAcceptanceCallRequest(
                        manifest_hash=manifest_hash,
                        call_no=call_no,
                    ),
                )
                assert response.call_count == call_no
                assert response.charged_request_count == 0
            with database.engine.connect() as connection:
                assert connection.execute(
                    text(
                        "SELECT acceptance_run_id,call_no,provider_operation "
                        "FROM provider_operations WHERE id=:operation_id"
                    ),
                    {"operation_id": operation_id},
                ).one() == (run_id, call_no, "embedding")
        with database.engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE provider_operations SET state='succeeded',request_count=1,"
                    "charged_request_count=1 WHERE acceptance_run_id=:run_id"
                ),
                {"run_id": run_id},
            )
        with database.session() as session:
            summary = get_acceptance_run(session, actor_user_id=TEACHER_ID, run_id=run_id)
            assert summary.call_count == 7
            assert summary.charged_request_count == 7
            assert summary.starting_charged_requests == 0
            assert "calls" not in summary.model_dump()
    finally:
        database.dispose()


def test_attach_manifest_resolution_fails_closed_for_missing_cross_run_and_multiple_operations(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    try:
        run_id = _create_run(database)
        with database.session() as session:
            with pytest.raises(PlatformError, match="does not identify exactly one"):
                attach_acceptance_call(
                    session,
                    actor_user_id=TEACHER_ID,
                    run_id=run_id,
                    request=DemoAcceptanceCallRequest(
                        manifest_hash="c" * 64,
                        call_no=1,
                    ),
                )

        cross_run_manifest = _manifest_hash("cross-run")
        _provider_operation(
            database,
            item="cross-run",
            manifest_hash=cross_run_manifest,
            scope_id="another-run-target",
        )
        with database.session() as session:
            with pytest.raises(PlatformError, match="does not belong"):
                attach_acceptance_call(
                    session,
                    actor_user_id=TEACHER_ID,
                    run_id=run_id,
                    request=DemoAcceptanceCallRequest(
                        manifest_hash=cross_run_manifest,
                        call_no=1,
                    ),
                )

        ambiguous_manifest = _manifest_hash("ambiguous")
        _provider_operation(
            database,
            item="ambiguous-1",
            manifest_hash=ambiguous_manifest,
        )
        _provider_operation(
            database,
            item="ambiguous-2",
            manifest_hash=ambiguous_manifest,
        )
        with database.session() as session:
            with pytest.raises(PlatformError, match="does not identify exactly one"):
                attach_acceptance_call(
                    session,
                    actor_user_id=TEACHER_ID,
                    run_id=run_id,
                    request=DemoAcceptanceCallRequest(
                        manifest_hash=ambiguous_manifest,
                        call_no=1,
                    ),
                )
    finally:
        database.dispose()


def test_attach_accepts_explainable_eighth_but_rejects_ninth_and_duplicate(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    try:
        run_id = _create_run(database)
        first_manifest = _manifest_hash("duplicate-first")
        second_manifest = _manifest_hash("duplicate-second")
        _provider_operation(
            database,
            item="duplicate-first",
            manifest_hash=first_manifest,
        )
        second = _provider_operation(
            database,
            item="duplicate-second",
            manifest_hash=second_manifest,
        )
        with database.session() as session:
            attach_acceptance_call(
                session,
                actor_user_id=TEACHER_ID,
                run_id=run_id,
                request=DemoAcceptanceCallRequest(manifest_hash=first_manifest, call_no=1),
            )
            with pytest.raises(PlatformError, match="could not be attached"):
                attach_acceptance_call(
                    session,
                    actor_user_id=TEACHER_ID,
                    run_id=run_id,
                    request=DemoAcceptanceCallRequest(manifest_hash=second_manifest, call_no=1),
                )
        _provider_operation(
            database,
            item="semantic-extra-query",
            purpose="embedding_query",
        )
        with database.session() as session:
            response = attach_acceptance_call(
                session,
                actor_user_id=TEACHER_ID,
                run_id=run_id,
                request=DemoAcceptanceCallRequest(
                    manifest_hash=_manifest_hash("semantic-extra-query"),
                    call_no=8,
                ),
            )
            assert response.call_count == 2
            assert response.charged_request_count == 0
            assert "calls" not in response.model_dump()
        with pytest.raises(ValidationError):
            DemoAcceptanceCallRequest(manifest_hash=second_manifest, call_no=9)
        with database.engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE provider_operations SET state='reserved',request_count=1 WHERE id=:id"
                ),
                {"id": second},
            )
        with database.session() as session:
            with pytest.raises(PlatformError, match="could not be attached"):
                attach_acceptance_call(
                    session,
                    actor_user_id=TEACHER_ID,
                    run_id=run_id,
                    request=DemoAcceptanceCallRequest(manifest_hash=second_manifest, call_no=2),
                )
    finally:
        database.dispose()


def test_api_safe_response_and_student_authorization(app_factory: Any) -> None:
    # The direct service assertions above exercise SQL transaction fences.  A
    # separate app fixture proves the route is teacher-only and exposes only
    # opaque IDs, plan/hash, state and counters.
    app, database, settings = app_factory()
    from fastapi.testclient import TestClient

    with pytest.raises(ValidationError):
        DemoAcceptanceCallRequest(
            operation_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
            call_no=1,
        )

    with TestClient(app) as client:
        with database.session() as session:
            ensure_demo_baseline(session, settings.resolved_data_root)
            now = _now()
            session.add(
                Agent(
                    id=TARGET_AGENT_ID,
                    group_id=GROUP_BOWEN_ID,
                    name="Target Guide",
                    description="Target fixture",
                    status="active",
                    created_at=now,
                    updated_at=now,
                )
            )
            session.add(
                AgentVersion(
                    id=TARGET_VERSION_ID,
                    agent_id=TARGET_AGENT_ID,
                    version_seq=0,
                    state="draft",
                    revision=0,
                    agent_md="# Target Guide",
                    avatar_config_json="{}",
                    created_at=now,
                    updated_at=now,
                )
            )
        teacher_login = client.post(
            "/api/v1/auth/login",
            json={"username": "teacher-demo", "password": "demo-password"},
        )
        assert teacher_login.status_code == 200, teacher_login.text
        csrf = teacher_login.json()["csrf_token"]
        response = client.post(
            "/api/v1/demo/acceptance-runs",
            headers={"X-CSRF-Token": csrf, "Origin": "http://testserver"},
            json={
                "fixture_hash": FIXTURE_HASH,
                "target_agent_id": TARGET_AGENT_ID,
                "target_version_id": TARGET_VERSION_ID,
            },
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["starting_charged_requests"] == 0
        assert body["call_count"] == body["charged_request_count"] == 0
        assert {
            "calls",
            "operation_id",
            "call_no",
            "purpose",
            "request_count",
        }.isdisjoint(body)
        # ``state`` is the run lifecycle state; no per-call state object is
        # present because the response no longer contains a calls collection.
        assert body["state"] == "prepared"
        assert not any(
            forbidden in response.text.casefold()
            for forbidden in ("provider", "model", "endpoint", "api_key", "workspace", "key")
        )
        student_login = client.post(
            "/api/v1/auth/login",
            json={"username": "student-bowen-1", "password": "demo-password"},
        )
        student_csrf = student_login.json()["csrf_token"]
        denied = client.get(
            f"/api/v1/demo/acceptance-runs/{body['id']}",
            headers={"Origin": "http://testserver", "X-CSRF-Token": student_csrf},
        )
        assert denied.status_code == 403
    database.dispose()
