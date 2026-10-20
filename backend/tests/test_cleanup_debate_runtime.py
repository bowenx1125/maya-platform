"""Disposable-DB acceptance tests for the offline Debate runtime cleanup."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from app.core.db import Database
from app.core.identity import group_name_key, username_key
from app.core.models import (
    Base,
    FileReference,
    Job,
    KnowledgeDocument,
    ProviderOperation,
    StoredFile,
)
from app.modules.auth.models import DemoAccountBinding
from app.modules.debates import cleanup as online_cleanup
from app.modules.debates import models as _debate_models
from app.modules.interactions import models as _interaction_models
from app.modules.knowledge.recovery import recover_file_operations
from app.modules.knowledge_sets.models import (
    AgentKnowledgeSet,
    KnowledgeAsset,
    KnowledgeAssetVersion,
    KnowledgeAssetVersionSource,
    KnowledgeGenerationAcceptedStage,
    KnowledgeGenerationRun,
    KnowledgeGenerationTargetSnapshot,
    KnowledgeSet,
    KnowledgeSetSource,
)
from app.modules.learning.models import AssessmentActivity, AssessmentAttempt
from app.modules.reports import models as _report_models
from app.modules.teams.models import (
    CourseTeamPublication,
    Team,
    TeamMemberInvokeGrant,
    TeamVersion,
    TeamVersionMember,
    TeamVersionSet,
)
from app.modules.workspace.models import Conversation
from sqlalchemy import text

del DemoAccountBinding, _debate_models, _interaction_models, _report_models

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import cleanup_debate_runtime as cleanup  # noqa: E402


def _uid(number: int) -> str:
    return f"00000000-0000-4000-8000-{number:012d}"


def _alembic_config(database_path: Path) -> Config:
    backend_root = Path(__file__).resolve().parents[1]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "migrations"))
    database_url = f"sqlite:///{database_path}"
    config.set_main_option("sqlalchemy.url", database_url)
    config.attributes["database_url"] = database_url
    return config


def _hash(letter: str = "a") -> str:
    return letter * 64


def _table_rows(
    database_path: Path, tables: tuple[str, ...]
) -> dict[str, list[tuple[object, ...]]]:
    import sqlite3

    with sqlite3.connect(database_path) as connection:
        return {
            table: connection.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall()
            for table in tables
        }


def _add(session, table_name: str, **values: object) -> None:
    if table_name == "users":
        values["username_key"] = username_key(str(values["username"]))
    elif table_name == "groups":
        values["name_key"] = group_name_key(str(values["name"]))
    session.execute(Base.metadata.tables[table_name].insert().values(**values))


@pytest.fixture
def migrated_database(tmp_path: Path):
    database_path = tmp_path / "maya.sqlite3"
    database = Database(f"sqlite:///{database_path}", tmp_path)
    database.upgrade_schema()
    _seed_runtime_graph(database, tmp_path)
    try:
        yield database_path, tmp_path
    finally:
        database.dispose()


def _seed_runtime_graph(database: Database, data_root: Path) -> dict[str, str]:
    """Create one authored graph plus one complete disposable runtime graph."""

    ids = {
        "user": _uid(1),
        "teacher": _uid(2),
        "course": _uid(10),
        "group": _uid(11),
        "agent": _uid(12),
        "version": _uid(13),
        "snapshot": _uid(14),
        "source_file": _uid(15),
        "document": _uid(16),
        "document_chunk": _uid(17),
        "snapshot_document": _uid(18),
        "chunk": _uid(19),
        "debate": _uid(20),
        "participant": _uid(21),
        "turn": _uid(22),
        "audio_file": _uid(23),
        "turn_source": _uid(24),
        "position": _uid(25),
        "playback": _uid(26),
        "event": _uid(27),
        "window": _uid(28),
        "vote": _uid(29),
        "barrage": _uid(30),
        "insight": _uid(31),
        "insight_item": _uid(32),
        "report": _uid(33),
        "revision": _uid(34),
        "job_insight": _uid(35),
        "job_report": _uid(36),
        "policy": _uid(37),
        "manifest": _uid(38),
        "manifest_shared": _uid(39),
        "confirmation": _uid(40),
        "operation": _uid(41),
        "operation_shared": _uid(42),
        "reservation": _uid(43),
        "run": _uid(44),
        "idempotency": _uid(45),
        "idempotency_keep": _uid(46),
        "file_reference": _uid(47),
        "file_operation": _uid(48),
        "embedding_stage": _uid(49),
        "llm_stage": _uid(50),
        "recovery": _uid(51),
        "audit": _uid(52),
        "audit_keep": _uid(53),
    }
    now = datetime.now(UTC)
    source_relative = f"groups/{ids['group']}/knowledge/authored.md"
    source_bytes = b"Authored knowledge that must survive runtime cleanup.\n"
    source_path = data_root / source_relative
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_bytes(source_bytes)

    with database.session() as session:
        _add(
            session,
            "users",
            id=ids["user"],
            username="authored-student",
            display_name="Authored Student",
            status="active",
            created_at=now,
        )
        _add(
            session,
            "users",
            id=ids["teacher"],
            username="authored-teacher",
            display_name="Authored Teacher",
            status="active",
            created_at=now,
        )
        _add(
            session,
            "sessions",
            id_hash=_hash("b"),
            user_id=ids["user"],
            csrf_hash=_hash("c"),
            expires_at=now + timedelta(days=1),
            created_at=now,
        )
        _add(
            session,
            "demo_account_bindings",
            account_key="authored-account",
            user_id=ids["user"],
            material_fingerprint=_hash("d"),
            active=True,
            created_at=now,
            updated_at=now,
        )
        _add(
            session,
            "courses",
            id=ids["course"],
            code="AUTHORED-COURSE",
            name="Authored Course",
            current_audio_debate_id=None,
            created_at=now,
        )
        _add(
            session,
            "course_members",
            course_id=ids["course"],
            user_id=ids["teacher"],
            role="teacher",
            created_at=now,
        )
        _add(
            session,
            "course_members",
            course_id=ids["course"],
            user_id=ids["user"],
            role="student",
            created_at=now,
        )
        _add(
            session,
            "groups",
            id=ids["group"],
            course_id=ids["course"],
            name="Authored Group",
            created_at=now,
        )
        _add(
            session,
            "group_members",
            group_id=ids["group"],
            user_id=ids["teacher"],
            role="leader",
            created_at=now,
        )
        _add(
            session,
            "agents",
            id=ids["agent"],
            group_id=ids["group"],
            name="Authored Agent",
            description="Preserve this authored catalog record.",
            metadata_revision=0,
            status="active",
            created_at=now,
            updated_at=now,
        )
        _add(
            session,
            "agent_versions",
            id=ids["version"],
            agent_id=ids["agent"],
            version_seq=1,
            state="published",
            revision=0,
            agent_md="# Authored Agent\n",
            avatar_config_json="{}",
            knowledge_snapshot_id=ids["snapshot"],
            published_at=now,
            created_at=now,
            updated_at=now,
        )
        _add(
            session,
            "stored_files",
            id=ids["source_file"],
            kind="markdown",
            relative_path=source_relative,
            sha256=_hash("e"),
            size=len(source_bytes),
            state="active",
            created_at=now,
            updated_at=now,
        )
        _add(
            session,
            "knowledge_documents",
            id=ids["document"],
            group_id=ids["group"],
            source_filename="authored.md",
            stored_file_id=ids["source_file"],
            char_count=52,
            index_status="ready",
            index_revision=1,
            workspace_state="active",
            content_hash=_hash("f"),
            created_at=now,
            updated_at=now,
        )
        _add(
            session,
            "knowledge_document_chunks",
            id=ids["document_chunk"],
            document_id=ids["document"],
            chunk_index=0,
            text="Authored knowledge chunk.",
            start_offset=0,
            end_offset=25,
            embedding_blob=b"document-vector",
            embedding_dimension=256,
            embedding_key="mock-sha256-v1",
        )
        _add(
            session,
            "agent_version_documents",
            agent_version_id=ids["version"],
            document_id=ids["document"],
            enabled=True,
            order_index=0,
        )
        _add(
            session,
            "knowledge_snapshots",
            id=ids["snapshot"],
            agent_version_id=ids["version"],
            combined_file_id=ids["source_file"],
            content_hash=_hash("1"),
            total_char_count=52,
            embedding_model_key="mock-sha256-v1",
            embedding_provider="mock",
            embedding_region="local",
            embedding_dimension=256,
            embedding_policy_version="w4-mock-v1",
            chunking_config_json="{}",
            created_at=now,
        )
        _add(
            session,
            "snapshot_documents",
            id=ids["snapshot_document"],
            snapshot_id=ids["snapshot"],
            document_id=ids["document"],
            frozen_file_id=ids["source_file"],
            source_filename="authored.md",
            char_count=52,
            order_index=0,
        )
        _add(
            session,
            "knowledge_chunks",
            id=ids["chunk"],
            snapshot_id=ids["snapshot"],
            snapshot_document_id=ids["snapshot_document"],
            document_id=ids["document"],
            chunk_index=0,
            text="Authored snapshot chunk.",
            start_offset=0,
            end_offset=25,
            embedding_blob=b"snapshot-vector",
            embedding_dimension=256,
            embedding_key="mock-sha256-v1",
        )
        _add(
            session,
            "debates",
            id=ids["debate"],
            course_id=ids["course"],
            topic="Disposable historical runtime debate",
            rule_set_id="maya_demo_v1",
            rule_snapshot_json="{}",
            output_language="en",
            final_input_json='{"round": 3}',
            final_input_hash=_hash("2"),
            final_frozen_at=now,
            status="completed",
            revision=1,
            last_sequence=1,
            cancellation_generation=0,
            created_by=ids["teacher"],
            created_at=now,
            updated_at=now,
            started_at=now,
            finished_at=now,
        )
        _add(
            session,
            "debate_participants",
            id=ids["participant"],
            debate_id=ids["debate"],
            course_id=ids["course"],
            group_id=ids["group"],
            agent_id=ids["agent"],
            agent_version_id=ids["version"],
            knowledge_snapshot_id=ids["snapshot"],
            slot="A",
            order_index=0,
            agent_name="Authored Agent",
            version_label="v1",
            avatar_config_json="{}",
            effective_voice_kind="mock_sentinel",
            voice_fallback_active=False,
            stance_mode="assigned",
            initial_stance="support",
            current_stance="support",
            teacher_note="",
            initial_position_summary="Initial",
            current_position_summary="Current",
            created_at=now,
            updated_at=now,
        )
        session.execute(
            text("UPDATE courses SET current_audio_debate_id=:debate_id WHERE id=:course_id"),
            {"debate_id": ids["debate"], "course_id": ids["course"]},
        )
        audio_relative = (
            f"courses/{ids['course']}/current-debate-audio/{ids['debate']}/{ids['turn']}.wav"
        )
        audio_bytes = b"target-audio"
        audio_path = data_root / audio_relative
        audio_path.parent.mkdir(parents=True, exist_ok=True)
        audio_path.write_bytes(audio_bytes)
        _add(
            session,
            "stored_files",
            id=ids["audio_file"],
            kind="debate_audio",
            relative_path=audio_relative,
            sha256=_hash("3"),
            size=len(audio_bytes),
            state="active",
            created_at=now,
            updated_at=now,
        )
        # This is a real orphan from the playback directory and must be
        # removed by the bounded scanner even though it has no DB row.
        (audio_path.parent / "orphan-runtime.wav").write_bytes(b"orphan")
        _add(
            session,
            "debate_turns",
            id=ids["turn"],
            debate_id=ids["debate"],
            participant_id=ids["participant"],
            knowledge_snapshot_id=ids["snapshot"],
            round_no=1,
            turn_index=0,
            generation_status="failed",
            publication_status="unpublished",
            preparation_stage="failed",
            predecessor_turn_ids_json="[]",
            retrieval_receipts_json="[]",
            evidence_trace_json="[]",
            attempt=1,
            audio_file_id=ids["audio_file"],
            audio_duration_ms=10,
            actual_tts_voice_kind="mock_sentinel",
            safe_error_code="synthetic_failure",
            created_at=now,
            updated_at=now,
        )
        _add(
            session,
            "turn_sources",
            id=ids["turn_source"],
            turn_id=ids["turn"],
            participant_id=ids["participant"],
            snapshot_id=ids["snapshot"],
            chunk_id=ids["chunk"],
            evidence_id="authored-evidence",
            source_filename="authored.md",
            rank=1,
            score=0.9,
            created_at=now,
        )
        _add(
            session,
            "position_history",
            id=ids["position"],
            participant_id=ids["participant"],
            turn_id=ids["turn"],
            before_summary="Initial",
            after_summary="Current",
            update_type="refined",
            reason="Synthetic runtime row",
            influencing_evidence_ids_json="[]",
            created_at=now,
        )
        _add(
            session,
            "playback_states",
            id=ids["playback"],
            debate_id=ids["debate"],
            status="completed",
            mode="live",
            current_turn_id=None,
            cursor_ms=0,
            playback_rate=1.0,
            control_version=1,
            audio_duration_ms=10,
            created_at=now,
            updated_at=now,
        )
        _add(
            session,
            "debate_events",
            id=ids["event"],
            debate_id=ids["debate"],
            sequence=1,
            event_type="debate.completed",
            event_version=1,
            payload_json="{}",
            occurred_at=now,
        )
        _add(
            session,
            "classroom_interaction_windows",
            id=ids["window"],
            debate_id=ids["debate"],
            course_id=ids["course"],
            status="closed",
            revision=0,
            created_at=now,
            updated_at=now,
        )
        _add(
            session,
            "votes",
            id=ids["vote"],
            window_id=ids["window"],
            debate_id=ids["debate"],
            participant_id=ids["participant"],
            client_submission_id=_uid(60),
            submitted_at=now,
        )
        _add(
            session,
            "barrage_messages",
            id=ids["barrage"],
            window_id=ids["window"],
            debate_id=ids["debate"],
            turn_id=ids["turn"],
            nickname="student",
            raw_text="Synthetic runtime message",
            client_submission_id=_uid(61),
            sequence=1,
            submitted_at=now,
        )
        _add(
            session,
            "interaction_final_vote_counts",
            window_id=ids["window"],
            debate_id=ids["debate"],
            participant_id=ids["participant"],
            count=1,
        )
        _add(
            session,
            "interaction_final_barrages",
            window_id=ids["window"],
            debate_id=ids["debate"],
            barrage_message_id=ids["barrage"],
            sequence=1,
        )
        _add(
            session,
            "barrage_insight_snapshots",
            id=ids["insight"],
            window_id=ids["window"],
            debate_id=ids["debate"],
            revision_no=1,
            policy_key="mock_barrage_insight_v1",
            status="ready",
            attempt=1,
            input_hash=_hash("4"),
            included_count=0,
            filtered_count=0,
            created_at=now,
            updated_at=now,
        )
        _add(
            session,
            "barrage_insight_items",
            id=ids["insight_item"],
            snapshot_id=ids["insight"],
            window_id=ids["window"],
            debate_id=ids["debate"],
            order_index=0,
            category="support",
            summary="Synthetic insight",
        )
        _add(
            session,
            "civilization_reports",
            id=ids["report"],
            debate_id=ids["debate"],
            generation_status="ready",
            latest_attempt_status="ready",
            policy_key="mock_maya_report_v1",
            created_at=now,
            updated_at=now,
        )
        _add(
            session,
            "civilization_report_revisions",
            id=ids["revision"],
            report_id=ids["report"],
            debate_id=ids["debate"],
            insight_snapshot_id=ids["insight"],
            revision_no=1,
            status="ready",
            attempt=1,
            input_manifest_json="{}",
            input_manifest_hash=_hash("5"),
            english_markdown="word " * 600,
            word_count=600,
            trigger="automatic",
            requested_by=ids["teacher"],
            created_at=now,
            updated_at=now,
        )
        _add(
            session,
            "civilization_report_current_success",
            report_id=ids["report"],
            revision_id=ids["revision"],
            debate_id=ids["debate"],
            revision_status="ready",
        )
        _add(
            session,
            "jobs",
            id=ids["job_insight"],
            operation="barrage_insight.generate",
            state="completed",
            attempt=1,
            created_at=now,
            updated_at=now,
            debate_id=ids["debate"],
            turn_id=ids["turn"],
            insight_snapshot_id=ids["insight"],
        )
        _add(
            session,
            "jobs",
            id=ids["job_report"],
            operation="report.generate",
            state="completed",
            attempt=1,
            created_at=now,
            updated_at=now,
            debate_id=ids["debate"],
            report_revision_id=ids["revision"],
        )
        _add(
            session,
            "provider_policy_snapshots",
            id=ids["policy"],
            policy_id="synthetic-policy",
            contract_version="ProviderDataCallV1",
            supplier="Synthetic Provider",
            region="cn-beijing",
            account_product="payg_api",
            endpoint="https://synthetic.invalid",
            privacy_notice_url="https://synthetic.invalid/privacy",
            privacy_notice_retrieved_at="2026-01-01T00:00:00Z",
            privacy_notice_sha256=_hash("6"),
            service_terms_url="https://synthetic.invalid/terms",
            service_terms_retrieved_at="2026-01-01T00:00:00Z",
            service_terms_sha256=_hash("7"),
            faq_url="https://synthetic.invalid/faq",
            faq_retrieved_at="2026-01-01T00:00:00Z",
            faq_sha256=_hash("8"),
            no_training_basis="synthetic",
            prompt_response_logging_disabled=True,
            inference_log_backflow_disabled=True,
            optional_content_logging_disabled=True,
            service_improvement_disabled=True,
            storage_disclosed=True,
            retention_setting="none",
            snapshot_revision=1,
            policy_hash=_hash("9"),
            created_at=now,
        )
        manifest_common = {
            "policy_snapshot_id": ids["policy"],
            "policy_hash": _hash("9"),
            "build_manifest_hash": _hash("a"),
            "persona_spec_hash": _hash("b"),
            "fields_json": "[]",
            "operation_revision": 1,
            "contains_secret": False,
            "contains_identity": False,
            "contains_private_audio": False,
            "contains_teacher_note": False,
            "max_attempts": 1,
            "max_total_tokens": 10,
            "max_cost_cny": 0.001,
            "created_at": now,
        }
        _add(
            session,
            "provider_export_manifests",
            id=ids["manifest"],
            scope_id=ids["debate"],
            provider_operation="llm_debate_turn",
            model_key="synthetic-llm",
            manifest_hash=_hash("c"),
            course_id=ids["course"],
            group_id=ids["group"],
            agent_version_id=ids["version"],
            debate_id=ids["debate"],
            turn_id=ids["turn"],
            **manifest_common,
        )
        _add(
            session,
            "provider_export_manifests",
            id=ids["manifest_shared"],
            scope_id=ids["version"],
            provider_operation="embedding",
            model_key="synthetic-embedding",
            manifest_hash=_hash("d"),
            course_id=ids["course"],
            group_id=ids["group"],
            agent_version_id=ids["version"],
            **manifest_common,
        )
        _add(
            session,
            "provider_export_confirmations",
            id=ids["confirmation"],
            manifest_id=ids["manifest"],
            policy_snapshot_id=ids["policy"],
            manifest_hash=_hash("c"),
            policy_hash=_hash("9"),
            confirmed_at="2026-01-01T00:00:00Z",
            confirmation_revision=1,
            created_at=now,
        )
        _add(
            session,
            "demo_acceptance_runs",
            id=ids["run"],
            plan_version="real_core_demo_v2",
            fixture_hash=_hash("e"),
            baseline_agent_id=ids["agent"],
            baseline_version_id=ids["version"],
            baseline_snapshot_id=ids["snapshot"],
            target_agent_id=ids["agent"],
            target_version_id=ids["version"],
            debate_id=ids["debate"],
            report_revision_id=ids["revision"],
            state="executed",
            starting_charged_requests=0,
            created_at=now,
            updated_at=now,
        )
        operation_common = {
            "attempt_no": 1,
            "request_hash": _hash("f"),
            "max_tokens": 10,
            "max_cost_cny": 0.001,
            "policy_hash": _hash("9"),
            "build_manifest_hash": _hash("a"),
            "state": "succeeded",
            "request_count": 1,
            "charged_request_count": 1,
            "created_at": now,
            "updated_at": now,
        }
        _add(
            session,
            "provider_operations",
            id=ids["operation"],
            scope_id=ids["debate"],
            provider_operation="llm_debate_turn",
            logical_item_id=ids["turn"],
            export_manifest_hash=_hash("c"),
            model_key="synthetic-llm",
            acceptance_run_id=ids["run"],
            call_no=1,
            **operation_common,
        )
        _add(
            session,
            "provider_operations",
            id=ids["operation_shared"],
            scope_id=ids["version"],
            acceptance_run_id=ids["run"],
            call_no=2,
            provider_operation="embedding",
            logical_item_id=ids["chunk"],
            export_manifest_hash=_hash("d"),
            model_key="synthetic-embedding",
            **operation_common,
        )
        _add(
            session,
            "provider_reservations",
            id=ids["reservation"],
            operation_id=ids["operation"],
            scope_id=ids["debate"],
            provider_operation="llm_debate_turn",
            logical_item_id=ids["turn"],
            attempt_no=1,
            max_tokens=10,
            max_cost_cny=0.001,
            state="succeeded",
            created_at=now,
            updated_at=now,
        )
        _add(
            session,
            "provider_scope_budgets",
            scope_id=ids["debate"],
            budget_bucket="llm_debate_turn",
            max_requests=2,
            max_total_tokens=100,
            max_cost_cny=1,
            allocated_requests=1,
            allocated_total_tokens=10,
            allocated_cost_cny=0.001,
            created_at=now,
            updated_at=now,
        )
        _add(
            session,
            "provider_scope_budgets",
            scope_id=ids["version"],
            budget_bucket="embedding_snapshot",
            max_requests=2,
            max_total_tokens=100,
            max_cost_cny=1,
            allocated_requests=1,
            allocated_total_tokens=10,
            allocated_cost_cny=0.001,
            created_at=now,
            updated_at=now,
        )
        _add(
            session,
            "embedding_accepted_stages",
            operation_id=ids["operation_shared"],
            build_id="synthetic-build",
            build_manifest_hash=_hash("a"),
            batch_index=0,
            model_key="mock-sha256-v1",
            embedding_provider="mock",
            embedding_region="local",
            dimension=256,
            policy_version="w4-mock-v1",
            response_hash=_hash("0"),
            created_at=now,
        )
        _add(
            session,
            "embedding_accepted_vectors",
            operation_id=ids["operation_shared"],
            item_index=0,
            chunk_id=ids["chunk"],
            embedding_blob=b"accepted-vector",
        )
        _add(
            session,
            "llm_accepted_stages",
            operation_id=ids["operation"],
            turn_id=ids["turn"],
            attempt_no=1,
            request_hash=_hash("f"),
            prompt_hash=_hash("1"),
            prompt_contract_version="synthetic-v1",
            schema_hash=_hash("2"),
            tokenizer_id="synthetic-tokenizer",
            tokenizer_hash=_hash("3"),
            rule_set_hash=_hash("4"),
            persona_spec_hash=_hash("5"),
            transcript_hash=_hash("6"),
            receipt_hash=_hash("7"),
            policy_hash=_hash("9"),
            export_manifest_hash=_hash("c"),
            build_manifest_hash=_hash("a"),
            generation_fence="synthetic-fence",
            model_key="synthetic-llm",
            output_json="{}",
            output_hash=_hash("8"),
            prompt_tokens=0,
            cached_input_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            price_card_version="synthetic",
            input_price_cny_per_million=0,
            cached_input_price_cny_per_million=0,
            output_price_cny_per_million=0,
            estimated_cost_cny=0,
            actual_cost_cny=0,
            retrieval_reused=False,
            created_at=now,
        )
        _add(
            session,
            "llm_recovery_inputs",
            operation_id=ids["operation"],
            turn_id=ids["turn"],
            attempt_no=1,
            input_version="llm_recovery_input_v1",
            input_json="{}",
            input_hash=_hash("a"),
            created_at=now,
        )
        _add(
            session,
            "idempotency_records",
            id=ids["idempotency"],
            actor_user_id=ids["teacher"],
            operation="createDebate",
            key="synthetic-target",
            request_hash=_hash("b"),
            state="completed",
            claim_token=_hash("c"),
            lease_expires_at=now + timedelta(days=1),
            status_code=201,
            response_json="{}",
            created_at=now,
            updated_at=now,
        )
        _add(
            session,
            "idempotency_records",
            id=ids["idempotency_keep"],
            actor_user_id=ids["teacher"],
            operation="knowledge.upload",
            key="synthetic-authored",
            request_hash=_hash("d"),
            state="completed",
            claim_token=_hash("e"),
            lease_expires_at=now + timedelta(days=1),
            status_code=200,
            response_json="{}",
            created_at=now,
            updated_at=now,
        )
        _add(
            session,
            "file_references",
            id=ids["file_reference"],
            stored_file_id=ids["audio_file"],
            owner_type="debate_turn",
            owner_id=ids["turn"],
            purpose="audio",
            created_at=now,
        )
        staging_relative = f"staging/audio-swap/{ids['course']}/request/{ids['debate']}"
        staging_path = data_root / staging_relative
        staging_path.mkdir(parents=True, exist_ok=True)
        (staging_path / "staged.wav").write_bytes(b"staged")
        _add(
            session,
            "file_operations",
            id=ids["file_operation"],
            idempotency_record_id=ids["idempotency"],
            operation_type="debate_audio_swap",
            entity_id=ids["debate"],
            request_id=_uid(62),
            source_relative_path=(f"courses/{ids['course']}/current-debate-audio/{ids['debate']}"),
            staging_relative_path=staging_relative,
            old_audio_debate_id=ids["debate"],
            new_debate_id=ids["debate"],
            expected_old_debate_id=ids["debate"],
            state="cleanup_required",
            created_at=now,
            updated_at=now,
        )
        _add(
            session,
            "audit_logs",
            id=ids["audit"],
            event_type="debate.completed",
            actor_kind="teacher",
            actor_id=ids["teacher"],
            course_id=ids["course"],
            debate_id=ids["debate"],
            request_id=None,
            details_json="{}",
            created_at=now,
        )
        _add(
            session,
            "audit_logs",
            id=ids["audit_keep"],
            event_type="account.login",
            actor_kind="teacher",
            actor_id=ids["teacher"],
            course_id=None,
            debate_id=None,
            request_id=None,
            details_json="{}",
            created_at=now,
        )
    return ids


def _count(database_path: Path, table: str) -> int:
    import sqlite3

    connection = sqlite3.connect(database_path)
    try:
        return int(connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
    finally:
        connection.close()


def test_dry_run_is_read_only_and_machine_audit_is_sanitized(migrated_database):
    database_path, data_root = migrated_database
    before_debates = _count(database_path, "debates")
    plan = cleanup.inspect_cleanup(database_path, data_root)
    payload = cleanup.audit_payload(plan, mode="dry_run", status="dry_run")

    assert plan.has_targets
    assert plan.table_counts["debates"] == 1
    assert plan.table_counts["audit_logs"] == 1
    assert plan.file_count >= 3  # audio, orphan audio, and staged audio
    assert plan.directory_count >= 2
    assert _count(database_path, "debates") == before_debates
    encoded = json.dumps(payload, ensure_ascii=False)
    assert "00000000-0000-4000-8000-000000000020" not in encoded
    assert "Authored knowledge" not in encoded
    assert payload["app_must_be_stopped"] is True


def test_cleanup_accepts_known_0035_data_after_additive_0036_downgrade(migrated_database):
    database_path, data_root = migrated_database
    command.downgrade(_alembic_config(database_path), "0035_w1_resource_ownership")

    plan = cleanup.inspect_cleanup(database_path, data_root)
    payload = cleanup.audit_payload(plan, mode="dry_run", status="dry_run")
    assert plan.schema_head == "0035_w1_resource_ownership"
    assert plan.table_counts["debates"] == 1
    assert payload["schema_head"] == "0035_w1_resource_ownership"


def test_cleanup_preserves_knowledge_set_and_all_references(migrated_database):
    database_path, data_root = migrated_database
    database = Database(f"sqlite:///{database_path}", data_root)
    set_id = _uid(110)
    binding_id = _uid(111)
    asset_id = _uid(112)
    version_id = _uid(113)
    version_source_id = _uid(114)
    file_reference_id = _uid(115)
    job_id = _uid(116)
    generation_run_id = _uid(117)
    provider_operation_id = _uid(118)
    now = datetime.now(UTC)
    content_json = json.dumps(
        {"kind": "note", "title": "Kept source", "body": "Authored evidence."},
        sort_keys=True,
        separators=(",", ":"),
    )
    content_hash = hashlib.sha256(content_json.encode("utf-8")).hexdigest()
    location_json = "{}"
    location_hash = hashlib.sha256(location_json.encode("utf-8")).hexdigest()
    accepted_stage_json = '{"assets":[]}'
    accepted_stage_hash = hashlib.sha256(accepted_stage_json.encode("utf-8")).hexdigest()
    try:
        with database.session() as session:
            document = session.get(KnowledgeDocument, _uid(16))
            stored = session.get(StoredFile, _uid(15))
            assert document is not None and stored is not None
            agent_version_id = session.scalar(
                text("SELECT id FROM agent_versions WHERE agent_id = :agent_id LIMIT 1"),
                {"agent_id": _uid(12)},
            )
            assert agent_version_id is not None
            session.add(
                KnowledgeSet(
                    id=set_id,
                    owner_user_id=_uid(1),
                    course_id=_uid(10),
                    group_id=_uid(11),
                    ownership_scope="group",
                    visibility="public",
                    display_name="Kept Set",
                    metadata_revision=1,
                    content_revision=1,
                    authorization_epoch=1,
                    created_at=now,
                    updated_at=now,
                )
            )
            session.flush()
            session.add(
                KnowledgeSetSource(
                    id=binding_id,
                    knowledge_set_id=set_id,
                    document_id=document.id,
                    stored_file_id=stored.id,
                    source_content_hash=document.content_hash,
                    source_file_sha256=stored.sha256,
                    source_authorization_epoch=document.authorization_epoch,
                    source_index_revision=document.index_revision,
                    source_filename=document.source_filename,
                    order_index=0,
                    is_active=True,
                    created_by_user_id=_uid(1),
                    created_at=now,
                )
            )
            session.add(
                KnowledgeAsset(
                    id=asset_id,
                    knowledge_set_id=set_id,
                    kind="note",
                    current_version_seq=1,
                    created_by_user_id=_uid(1),
                    created_at=now,
                    updated_at=now,
                )
            )
            session.flush()
            session.add(
                KnowledgeAssetVersion(
                    id=version_id,
                    asset_id=asset_id,
                    version_seq=1,
                    content_json=content_json,
                    content_hash=content_hash,
                    source_dependency_hash=_hash("5"),
                    dependency_authorization_epoch=1,
                    set_authorization_epoch=1,
                    origin="manual",
                    created_by_user_id=_uid(1),
                    generator_agent_version_id=None,
                    generation_job_id=None,
                    created_at=now,
                )
            )
            session.add(
                KnowledgeAssetVersionSource(
                    id=version_source_id,
                    asset_version_id=version_id,
                    source_binding_id=binding_id,
                    document_id=document.id,
                    stored_file_id=stored.id,
                    source_content_hash=document.content_hash,
                    source_file_sha256=stored.sha256,
                    source_authorization_epoch=document.authorization_epoch,
                    source_location_json=location_json,
                    source_location_hash=location_hash,
                    created_at=now,
                )
            )
            session.add(
                FileReference(
                    id=file_reference_id,
                    stored_file_id=stored.id,
                    owner_type="knowledge_asset_version_source",
                    owner_id=version_source_id,
                    purpose="source",
                    created_at=now,
                )
            )
            session.add(
                AgentKnowledgeSet(
                    agent_id=_uid(12),
                    knowledge_set_id=set_id,
                    order_index=0,
                    created_by_user_id=_uid(1),
                    created_at=now,
                )
            )
            session.add(
                Team(
                    id=_uid(130),
                    owner_user_id=_uid(2),
                    course_id=_uid(10),
                    group_id=None,
                    ownership_scope="personal",
                    display_name="Preserved Team",
                    visibility="public",
                    metadata_revision=0,
                    authorization_epoch=0,
                    current_version_seq=1,
                    deleted_at=None,
                    created_at=now,
                    updated_at=now,
                )
            )
            session.flush()
            session.add(
                TeamVersion(
                    id=_uid(131),
                    team_id=_uid(130),
                    version_seq=1,
                    display_name="Preserved Team",
                    visibility="public",
                    authorization_epoch=0,
                    created_by_user_id=_uid(2),
                    created_at=now,
                )
            )
            session.flush()
            session.add(
                TeamVersionMember(
                    id=_uid(132),
                    team_version_id=_uid(131),
                    agent_id=_uid(12),
                    agent_version_id=str(agent_version_id),
                    position=0,
                    is_leader=True,
                    display_name="Preserved Agent",
                    avatar_config_json="{}",
                    own_knowledge_set_snapshots_json="[]",
                    raw_source_fences_json="[]",
                    created_at=now,
                )
            )
            session.add(
                TeamVersionSet(
                    id=_uid(133),
                    team_version_id=_uid(131),
                    knowledge_set_id=set_id,
                    authorization_epoch=1,
                    position=0,
                    created_at=now,
                )
            )
            session.flush()
            session.add(
                CourseTeamPublication(
                    id=_uid(134),
                    course_id=_uid(10),
                    team_id=_uid(130),
                    team_version_id=_uid(131),
                    publisher_user_id=_uid(2),
                    authorization_epoch=0,
                    state="published",
                    published_at=now,
                    revoked_at=None,
                )
            )
            session.flush()
            session.add(
                TeamMemberInvokeGrant(
                    id=_uid(135),
                    publication_id=_uid(134),
                    team_version_id=_uid(131),
                    team_member_id=_uid(132),
                    agent_id=_uid(12),
                    agent_version_id=str(agent_version_id),
                    authorization_epoch=0,
                    created_at=now,
                )
            )
            session.flush()
            session.add(
                Conversation(
                    id=_uid(137),
                    user_id=_uid(1),
                    course_id=_uid(10),
                    agent_version_id=None,
                    snapshot_id=None,
                    agent_name_snapshot="",
                    agent_authorization_epoch=0,
                    entry_kind="maya_team",
                    chat_visibility="private",
                    origin="published_course_team",
                    team_id=_uid(130),
                    team_version_id=_uid(131),
                    team_owner_user_id=_uid(2),
                    team_name_snapshot="Preserved Team",
                    team_authorization_epoch=0,
                    publication_id=_uid(134),
                    publication_epoch=0,
                    revision=0,
                    active_request_id=None,
                    withdrawn_at=None,
                    created_at=now,
                )
            )
            session.add(
                AssessmentActivity(
                    id=_uid(136),
                    course_id=_uid(10),
                    team_id=_uid(130),
                    team_version_id=_uid(131),
                    publication_id=_uid(134),
                    recipe_id="mayaform.cleanup.test",
                    recipe_version_id=str(agent_version_id),
                    evaluator_team_member_id=_uid(132),
                    evaluator_agent_version_id=str(agent_version_id),
                    boundary_team_member_id=_uid(132),
                    boundary_agent_version_id=str(agent_version_id),
                    publisher_user_id=_uid(2),
                    questions_hash=_hash("m"),
                    question_selection_revision=2,
                    created_at=now,
                )
            )
            session.flush()
            session.add(
                AssessmentAttempt(
                    id=_uid(138),
                    activity_id=_uid(136),
                    team_id=_uid(130),
                    recipe_id="mayaform.cleanup.test",
                    actor_user_id=_uid(1),
                    source_conversation_id=_uid(137),
                    chat_visibility="private",
                    status="in_progress",
                    revision=3,
                    question_selection_revision=2,
                    started_at=now,
                    updated_at=now,
                    completed_at=None,
                    abandoned_at=None,
                    abandonment_reason=None,
                )
            )
            session.add(
                Job(
                    id=job_id,
                    operation="knowledge_set.generate",
                    state="pending",
                    idempotency_key=_hash("7"),
                    claim_token=None,
                    attempt=0,
                    safe_error_code=None,
                    created_at=now,
                    updated_at=now,
                )
            )
            session.add(
                ProviderOperation(
                    id=provider_operation_id,
                    scope_id=generation_run_id,
                    provider_operation="llm_knowledge_generate",
                    logical_item_id=generation_run_id,
                    attempt_no=1,
                    request_hash=_hash("p"),
                    max_tokens=0,
                    max_cost_cny=0,
                    policy_hash=_hash("q"),
                    export_manifest_hash=_hash("r"),
                    build_manifest_hash=_hash("s"),
                    model_key="qwen3.8-max-2026-09-02",
                    state="accepted",
                    request_count=1,
                    charged_request_count=1,
                    staged_response_hash=accepted_stage_hash,
                    safe_error_code=None,
                    created_at=now,
                    updated_at=now,
                )
            )
            session.flush()
            session.add(
                KnowledgeGenerationRun(
                    id=generation_run_id,
                    job_id=job_id,
                    input_key=_hash("8"),
                    owner_user_id=_uid(1),
                    course_id=_uid(10),
                    agent_id=_uid(12),
                    agent_version_id=str(agent_version_id),
                    knowledge_set_id=set_id,
                    provider_operation_id=provider_operation_id,
                    provider_manifest_hash=_hash("r"),
                    request_hash=_hash("p"),
                    agent_md_hash=_hash("9"),
                    agent_authorization_epoch=0,
                    set_authorization_epoch=1,
                    source_manifest_json="[]",
                    source_manifest_hash=_hash("6"),
                    state="pending",
                    safe_error_code=None,
                    claim_token=None,
                    lease_expires_at=None,
                    created_at=now,
                    updated_at=now,
                )
            )
            session.flush()
            session.add(
                KnowledgeGenerationTargetSnapshot(
                    run_id=generation_run_id,
                    asset_heads_json="[]",
                    created_at=now,
                )
            )
            session.flush()
            session.add(
                KnowledgeGenerationAcceptedStage(
                    run_id=generation_run_id,
                    operation_id=provider_operation_id,
                    request_hash=_hash("p"),
                    manifest_hash=_hash("r"),
                    policy_hash=_hash("q"),
                    model_key="qwen3.8-max-2026-09-02",
                    schema_hash=_hash("u"),
                    canonical_stage_json=accepted_stage_json,
                    canonical_stage_hash=accepted_stage_hash,
                    item_count=0,
                    usage_json=None,
                    safe_error_code=None,
                    accepted_at=now,
                    created_at=now,
                )
            )
        preserved_tables = (
            "knowledge_sets",
            "knowledge_set_sources",
            "knowledge_assets",
            "knowledge_asset_versions",
            "knowledge_asset_version_sources",
            "agent_knowledge_sets",
            "knowledge_generation_runs",
            "knowledge_generation_target_snapshots",
            "knowledge_generation_accepted_stages",
            "teams",
            "team_versions",
            "team_version_members",
            "team_version_sets",
            "course_team_publications",
            "team_member_invoke_grants",
            "assessment_activities",
            "assessment_attempts",
        )
        before = _table_rows(database_path, preserved_tables)
        with sqlite3.connect(database_path) as connection:
            file_reference_before = connection.execute(
                "SELECT * FROM file_references WHERE id=?", (file_reference_id,)
            ).fetchone()
        assert file_reference_before is not None
        plan = cleanup.inspect_cleanup(database_path, data_root)
        assert provider_operation_id not in plan.operation_ids, plan.operation_ids
        for table in preserved_tables:
            assert plan.preserved_counts[table] == 1

        cleanup.apply_cleanup(database_path, data_root, offline=True)

        assert _table_rows(database_path, preserved_tables) == before
        with sqlite3.connect(database_path) as connection:
            assert connection.execute(
                "SELECT question_selection_revision FROM assessment_attempts WHERE id=?",
                (_uid(138),),
            ).fetchone() == (2,)
        with sqlite3.connect(database_path) as connection:
            file_reference_after = connection.execute(
                "SELECT * FROM file_references WHERE id=?", (file_reference_id,)
            ).fetchone()
            assert file_reference_after == file_reference_before
            assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        database.dispose()


def test_cleanup_accepts_current_0054_schema_head(migrated_database):
    database_path, data_root = migrated_database
    with sqlite3.connect(database_path) as connection:
        version = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    assert version == ("0075_agent_editor_audit",)
    assert cleanup.SCHEMA_HEAD == version[0]
    assert version[0] in cleanup.SUPPORTED_SCHEMA_HEADS

    plan = cleanup.inspect_cleanup(database_path, data_root)
    assert plan.schema_head == version[0]


def test_cleanup_rejects_unknown_schema_head(migrated_database):
    import sqlite3

    database_path, data_root = migrated_database
    with sqlite3.connect(database_path) as connection:
        connection.execute("UPDATE alembic_version SET version_num='unknown-head'")

    with pytest.raises(cleanup.CleanupError, match="schema_head_invalid"):
        cleanup.inspect_cleanup(database_path, data_root)


def test_apply_removes_runtime_graph_preserves_authored_graph_and_is_idempotent(
    migrated_database,
):
    database_path, data_root = migrated_database
    target_ids = _uid
    plan = cleanup.apply_cleanup(database_path, data_root, offline=True)

    assert plan.table_counts["debates"] == 1
    assert plan.table_counts["demo_acceptance_runs"] == 1
    assert plan.table_counts["llm_recovery_inputs"] == 1
    assert plan.table_counts["audit_logs"] == 1
    assert not (
        data_root / "courses" / target_ids(10) / "current-debate-audio" / target_ids(20)
    ).exists()
    assert not any((data_root / "staging" / "audio-swap").rglob("*.wav"))

    connection = __import__("sqlite3").connect(database_path)
    connection.row_factory = __import__("sqlite3").Row
    try:
        assert connection.execute("PRAGMA foreign_key_check").fetchone() is None
        assert connection.execute("SELECT count(*) FROM debates").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM debate_turns").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM llm_recovery_inputs").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM demo_acceptance_runs").fetchone()[0] == 0
        assert (
            connection.execute(
                "SELECT count(*) FROM audit_logs WHERE debate_id IS NOT NULL"
            ).fetchone()[0]
            == 0
        )
        assert (
            connection.execute(
                "SELECT count(*) FROM audit_logs WHERE debate_id IS NULL"
            ).fetchone()[0]
            == 1
        )
        assert connection.execute("SELECT count(*) FROM users").fetchone()[0] == 2
        assert connection.execute("SELECT count(*) FROM knowledge_snapshots").fetchone()[0] == 1
        assert (
            connection.execute("SELECT count(*) FROM provider_policy_snapshots").fetchone()[0] == 1
        )
        assert (
            connection.execute("SELECT count(*) FROM provider_export_manifests").fetchone()[0] == 1
        )
        assert connection.execute("SELECT count(*) FROM provider_operations").fetchone()[0] == 1
        assert (
            connection.execute("SELECT count(*) FROM embedding_accepted_stages").fetchone()[0] == 1
        )
        assert connection.execute("SELECT count(*) FROM idempotency_records").fetchone()[0] == 1
        assert (
            connection.execute("SELECT current_audio_debate_id FROM courses").fetchone()[0] is None
        )
        triggers = {
            row[0]: row[1]
            for row in connection.execute(
                "SELECT name, sql FROM sqlite_master WHERE type='trigger'"
            )
        }
        assert cleanup.DELETE_GUARD in triggers
        assert "trg_llm_recovery_inputs_immutable_update" in triggers
        assert "debate_final_input_immutable" in triggers
    finally:
        connection.close()

    # A second offline pass sees no debate/runtime rows and does not disturb
    # the authored catalog or the account audit row.
    second = cleanup.apply_cleanup(database_path, data_root, offline=True)
    assert not second.has_targets
    assert _count(database_path, "users") == 2
    assert _count(database_path, "audit_logs") == 1


def test_path_guards_and_cli_apply_boundary(tmp_path: Path, capsys):
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    root = tmp_path / "data"
    root.mkdir()
    (root / "safe.txt").write_text("safe", encoding="utf-8")
    (root / "link").symlink_to(outside)

    with pytest.raises(cleanup.CleanupError, match="stored_file_symlink_refused"):
        cleanup._safe_relative_file(root, "link")
    with pytest.raises(cleanup.CleanupError, match="stored_file_path_invalid"):
        cleanup._safe_relative_file(root, "../outside.txt")

    assert cleanup.main(["--apply", "--database", str(tmp_path / "missing.sqlite3")]) == 2
    assert "offline_confirmation_required" in capsys.readouterr().out


def test_generic_recovery_skips_cleanup_intent_and_special_resumer_only_drains_quarantine(
    migrated_database,
):
    """The generic upload recovery must never delete a cleanup source path."""

    database_path, data_root = migrated_database
    source_relative = "groups/00000000-0000-4000-8000-000000000011/knowledge/authored.md"
    quarantine_relative = ".maya-debate-delete-regression"
    quarantine_path = data_root / quarantine_relative
    quarantine_path.mkdir()
    (quarantine_path / "quarantine.wav").write_bytes(b"private-quarantine")
    operation_id = _uid(75)
    target_debate_id = _uid(20)
    now = datetime.now(UTC)
    database = Database(f"sqlite:///{database_path}", data_root)
    try:
        with database.session() as session:
            _add(
                session,
                "file_operations",
                id=operation_id,
                idempotency_record_id=None,
                operation_type="debate_cleanup_all_v1",
                entity_id=target_debate_id,
                request_id=_uid(76),
                source_relative_path=source_relative,
                target_relative_path=f"{quarantine_relative}/quarantine.wav",
                staging_relative_path=quarantine_relative,
                old_audio_debate_id=None,
                new_debate_id=None,
                expected_old_debate_id=None,
                state="cleanup_required",
                safe_error_code=None,
                created_at=now,
                updated_at=now,
            )
        with database.session() as session:
            recover_file_operations(session, data_root)
        source_path = data_root / source_relative
        assert source_path.exists()
        assert (quarantine_path / "quarantine.wav").exists()
        with database.session() as session:
            result = online_cleanup.resume_cleanup_journals(
                session,
                data_root,
                debate_id=target_debate_id,
            )
        assert result["deleted_file_count"] == 1
        assert source_path.exists()
        assert not (quarantine_path / "quarantine.wav").exists()
        assert not quarantine_path.exists()
        with database.session() as session:
            assert (
                session.execute(
                    text("SELECT state FROM file_operations WHERE id=:id"),
                    {"id": operation_id},
                ).scalar_one()
                == "recovered"
            )
    finally:
        database.dispose()


def test_offline_cleanup_retires_orphaned_online_journals_after_debate_delete(
    migrated_database,
):
    """Bulk cleanup handles private receipts after the Debate row is gone."""

    database_path, data_root = migrated_database
    runtime_db = Database(f"sqlite:///{database_path}", data_root)
    target_debate_id = _uid(20)
    try:
        with runtime_db.session() as session:
            asyncio.run(
                online_cleanup.delete_all(
                    session,
                    actor_user_id=_uid(2),
                    debate_id=target_debate_id,
                    expected_revision=1,
                    expected_control_version=1,
                    data_root=data_root,
                )
            )
        orphan_dir = data_root / ".maya-debate-delete-offline"
        orphan_dir.mkdir()
        (orphan_dir / "orphan.bin").write_bytes(b"orphan-quarantine")
        now = datetime.now(UTC)
        with runtime_db.session() as session:
            _add(
                session,
                "idempotency_records",
                id=_uid(78),
                actor_user_id=_uid(2),
                operation="deleteAll",
                key="cleanup-orphan-journal-001",
                request_hash=_hash("7"),
                state="completed",
                claim_token=_hash("8"),
                lease_expires_at=now,
                status_code=200,
                response_json=json.dumps({"debate_id": target_debate_id}),
                created_at=now,
                updated_at=now,
            )
            _add(
                session,
                "file_operations",
                id=_uid(79),
                idempotency_record_id=_uid(78),
                operation_type="debate_cleanup_all_v1",
                entity_id=target_debate_id,
                request_id=_uid(80),
                source_relative_path=(
                    "groups/00000000-0000-4000-8000-000000000011/knowledge/authored.md"
                ),
                target_relative_path=".maya-debate-delete-offline/orphan.bin",
                staging_relative_path=".maya-debate-delete-offline",
                old_audio_debate_id=None,
                new_debate_id=None,
                expected_old_debate_id=None,
                state="cleanup_required",
                safe_error_code=None,
                created_at=now,
                updated_at=now,
            )
    finally:
        runtime_db.dispose()

    plan = cleanup.inspect_cleanup(database_path, data_root)
    assert not plan.debate_ids
    assert plan.cleanup_journal_ids
    assert _uid(79) in plan.cleanup_journal_ids
    assert _uid(78) in plan.idempotency_ids
    assert plan.file_count >= 1
    cleanup.apply_cleanup(database_path, data_root, offline=True)

    assert not orphan_dir.exists()
    import sqlite3

    connection = sqlite3.connect(database_path)
    try:
        assert (
            connection.execute(
                "SELECT count(*) FROM file_operations WHERE operation_type LIKE 'debate_cleanup_%'"
            ).fetchone()[0]
            == 0
        )
        assert (
            connection.execute(
                "SELECT count(*) FROM idempotency_records WHERE id=?", (_uid(78),)
            ).fetchone()[0]
            == 0
        )
        assert connection.execute("SELECT count(*) FROM users").fetchone()[0] == 2
        assert connection.execute("SELECT count(*) FROM knowledge_snapshots").fetchone()[0] == 1
    finally:
        connection.close()
