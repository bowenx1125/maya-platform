"""Migration and ORM coverage for the immutable embedding identity boundary."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from app.core.db import Database
from app.core.models import EmbeddingAcceptedStage, EmbeddingAcceptedVector, KnowledgeSnapshot
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

REVISION = "0013_embedding_identity_stage"
PREVIOUS_REVISION = "0012_persona_activation"


def test_orm_identity_is_on_snapshot_and_stage_chunk_id_is_build_opaque() -> None:
    snapshot = KnowledgeSnapshot(
        id="snapshot-orm",
        agent_version_id="version-orm",
        stored_file_id="file-orm",
        content_hash="a" * 64,
        total_char_count=1,
        embedding_key="mock",
        embedding_provider="mock",
        embedding_region="local",
        embedding_dimension=256,
        embedding_policy_version="w4-mock-v1",
        chunking_json="{}",
        created_at=datetime.now(UTC),
    )
    assert snapshot.embedding_key == "mock-sha256-v1"
    assert snapshot.embedding_model_key == "mock-sha256-v1"
    assert snapshot.embedding_model == "mock-sha256-v1"
    assert snapshot.provider == "mock"
    assert snapshot.region == "local"
    assert snapshot.dimension == 256
    assert snapshot.policy_version == "w4-mock-v1"
    assert {
        "embedding_provider",
        "embedding_model_key",
        "embedding_region",
        "embedding_dimension",
        "embedding_policy_version",
    } <= {str(column.name) for column in KnowledgeSnapshot.__table__.columns}
    assert not EmbeddingAcceptedVector.__table__.c.chunk_id.foreign_keys
    assert "operation_id" in {
        str(column.name) for column in EmbeddingAcceptedStage.__table__.columns
    }


def _config(database_url: str) -> Config:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).parents[1] / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    config.attributes["database_url"] = database_url
    return config


def _database_url(path: Path) -> str:
    return f"sqlite:///{path}"


def _upgrade(path: Path, revision: str = REVISION) -> None:
    command.upgrade(_config(_database_url(path)), revision)


def _downgrade(path: Path, revision: str = PREVIOUS_REVISION) -> None:
    command.downgrade(_config(_database_url(path)), revision)


def _revision(path: Path) -> str:
    database = Database(_database_url(path))
    try:
        with database.engine.connect() as connection:
            return str(connection.execute(text("SELECT version_num FROM alembic_version")).scalar())
    finally:
        database.dispose()


def _seed_populated_legacy(path: Path) -> dict[str, str]:
    """Build one 0012 database using raw SQL, as a real legacy DB would."""

    _upgrade(path, PREVIOUS_REVISION)
    database = Database(_database_url(path))
    now = datetime.now(UTC)
    timestamp = now.isoformat()
    digest = "a" * 64
    try:
        with database.engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO courses "
                    "(id,code,name,current_audio_debate_id,created_at) "
                    "VALUES ('course-identity','identity-course','Identity Course',NULL,:now)"
                ),
                {"now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO groups (id,course_id,name,created_at) "
                    "VALUES ('group-identity','course-identity','Identity Group',:now)"
                ),
                {"now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO stored_files "
                    "(id,kind,relative_path,sha256,size,state,created_at,updated_at) "
                    "VALUES ('file-identity','markdown','identity/source.md',:hash,9,'active',"
                    ":now,:now)"
                ),
                {"hash": digest, "now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO agents "
                    "(id,group_id,name,description,metadata_revision,status,"
                    "current_published_version_id,created_at,updated_at) "
                    "VALUES ('agent-identity','group-identity','Identity Agent','',0,'active',"
                    "'version-identity',:now,:now)"
                ),
                {"now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO agent_versions "
                    "(id,agent_id,version_seq,state,revision,agent_md,avatar_config_json,"
                    "voice_profile_id,knowledge_snapshot_id,published_at,created_at,updated_at,"
                    "persona_required) VALUES ('version-identity','agent-identity',0,'published',"
                    "1,'# Identity Agent','{}',NULL,'snapshot-identity',:now,:now,:now,0)"
                ),
                {"now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO knowledge_snapshots "
                    "(id,agent_version_id,combined_file_id,content_hash,total_char_count,"
                    "embedding_model_key,chunking_config_json,created_at) VALUES "
                    "('snapshot-identity','version-identity','file-identity',:hash,11,"
                    "'legacy-mock-key','{}',:now)"
                ),
                {"hash": "b" * 64, "now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO knowledge_documents "
                    "(id,group_id,source_filename,stored_file_id,char_count,index_status,"
                    "index_revision,workspace_state,content_hash,created_at,updated_at) VALUES "
                    "('document-identity','group-identity','source.md','file-identity',11,'ready',"
                    "1,'active',:hash,:now,:now)"
                ),
                {"hash": "c" * 64, "now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO snapshot_documents "
                    "(id,snapshot_id,document_id,frozen_file_id,source_filename,char_count,"
                    "order_index) "
                    "VALUES ('snapshot-document-identity','snapshot-identity','document-identity',"
                    "'file-identity','source.md',11,0)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO knowledge_chunks "
                    "(id,snapshot_id,snapshot_document_id,document_id,chunk_index,text,start_offset,"
                    "end_offset,embedding_blob,embedding_dimension,embedding_key) VALUES "
                    "('chunk-identity','snapshot-identity','snapshot-document-identity',"
                    "'document-identity',0,'legacy vector',0,12,:blob,256,'mock')"
                ),
                {"blob": b"legacy-vector", "now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO provider_policy_snapshots "
                    "(id,policy_id,contract_version,supplier,region,account_product,endpoint,"
                    "privacy_notice_url,privacy_notice_retrieved_at,privacy_notice_sha256,"
                    "service_terms_url,service_terms_retrieved_at,service_terms_sha256,"
                    "faq_url,faq_retrieved_at,faq_sha256,no_training_basis,"
                    "prompt_response_logging_disabled,inference_log_backflow_disabled,"
                    "optional_content_logging_disabled,service_improvement_disabled,"
                    "storage_disclosed,retention_setting,snapshot_revision,policy_hash,created_at) "
                    "VALUES ('policy-identity','policy-identity','ProviderDataCallV1',"
                    "'Alibaba Cloud Model Studio','cn-beijing','payg_api','https://example.invalid',"
                    "'https://example.invalid/privacy',:stamp,:hash,'https://example.invalid/terms',"
                    ":stamp,:hash,'https://example.invalid/faq',:stamp,:hash,'payg terms',1,1,1,1,"
                    "1,"
                    "'unknown',1,:hash,:now)"
                ),
                {"stamp": timestamp, "hash": digest, "now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO provider_export_manifests "
                    "(id,policy_snapshot_id,scope_id,provider_operation,model_key,policy_hash,"
                    "build_manifest_hash,persona_spec_hash,fields_json,operation_revision,"
                    "contains_secret,contains_identity,contains_private_audio,contains_teacher_note,"
                    "manifest_hash,created_at) VALUES ('manifest-identity','policy-identity',"
                    "'snapshot-identity','embedding','text-embedding-v4',:hash,:hash,:hash,'[]',1,0,0,0,0,"
                    ":hash,:now)"
                ),
                {"hash": digest, "now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO provider_export_confirmations "
                    "(id,manifest_id,policy_snapshot_id,manifest_hash,policy_hash,confirmed_at,"
                    "confirmation_revision,created_at) VALUES ('confirmation-identity',"
                    "'manifest-identity','policy-identity',:hash,:hash,:stamp,1,:now)"
                ),
                {"stamp": timestamp, "hash": digest, "now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO provider_operations "
                    "(id,scope_id,provider_operation,logical_item_id,attempt_no,request_hash,"
                    "max_tokens,max_cost_cny,policy_hash,export_manifest_hash,build_manifest_hash,"
                    "model_key,state,request_count,charged_request_count,staged_response_hash,"
                    "safe_error_code,created_at,updated_at) VALUES ('operation-identity',"
                    "'snapshot-identity','embedding','batch-0',1,:hash,1,0.01,:hash,:hash,:hash,"
                    "'text-embedding-v4','accepted',1,1,:hash,NULL,:now,:now)"
                ),
                {"hash": digest, "now": now},
            )
    finally:
        database.dispose()
    return {
        "snapshot_id": "snapshot-identity",
        "chunk_id": "chunk-identity",
        "operation_id": "operation-identity",
        "manifest_id": "manifest-identity",
        "course_id": "course-identity",
        "group_id": "group-identity",
        "agent_version_id": "version-identity",
    }


def _columns(path: Path, table: str) -> set[str]:
    database = Database(_database_url(path))
    try:
        return {str(item["name"]) for item in inspect(database.engine).get_columns(table)}
    finally:
        database.dispose()


def test_0013_fresh_and_repeat_create_identity_and_stage_tables(tmp_path: Path) -> None:
    path = tmp_path / "fresh.sqlite3"
    _upgrade(path)
    _upgrade(path)

    assert _revision(path) == REVISION
    assert {
        "embedding_provider",
        "embedding_region",
        "embedding_dimension",
        "embedding_policy_version",
    } <= _columns(path, "knowledge_snapshots")
    assert {"course_id", "group_id", "agent_version_id"} <= _columns(
        path, "provider_export_manifests"
    )
    assert {
        "embedding_accepted_stages",
        "embedding_accepted_vectors",
    } <= set(_table_names(path))
    assert "embedding_blob" in _columns(path, "embedding_accepted_vectors")
    forbidden = {
        "raw_response",
        "response_json",
        "api_key",
        "endpoint",
        "workspace_id",
    }
    assert not forbidden & _columns(path, "embedding_accepted_stages")

    database = Database(_database_url(path))
    try:
        with database.engine.connect() as connection:
            foreign_keys = connection.execute(
                text("PRAGMA foreign_key_list('embedding_accepted_stages')")
            ).all()
            assert any(row[2] == "provider_operations" for row in foreign_keys)
            vector_foreign_keys = connection.execute(
                text("PRAGMA foreign_key_list('embedding_accepted_vectors')")
            ).all()
            assert {row[2] for row in vector_foreign_keys} == {
                "embedding_accepted_stages",
            }
    finally:
        database.dispose()


def _table_names(path: Path) -> list[str]:
    database = Database(_database_url(path))
    try:
        return [str(value) for value in inspect(database.engine).get_table_names()]
    finally:
        database.dispose()


def test_0013_backfills_legacy_mock_without_changing_snapshot_or_vector_bytes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "populated.sqlite3"
    fixture = _seed_populated_legacy(path)
    database = Database(_database_url(path))
    try:
        with database.engine.connect() as connection:
            before = connection.execute(
                text("SELECT id, embedding_blob FROM knowledge_chunks WHERE id=:chunk_id"),
                fixture,
            ).one()
            before_snapshot_id = connection.execute(
                text("SELECT id FROM knowledge_snapshots WHERE id=:snapshot_id"), fixture
            ).scalar_one()
    finally:
        database.dispose()

    _upgrade(path)
    database = Database(_database_url(path))
    try:
        with database.engine.connect() as connection:
            identity = connection.execute(
                text(
                    "SELECT embedding_provider, embedding_model_key, embedding_region, "
                    "embedding_dimension, embedding_policy_version FROM knowledge_snapshots "
                    "WHERE id=:snapshot_id"
                ),
                fixture,
            ).one()
            assert tuple(identity) == (
                "mock",
                "mock-sha256-v1",
                "local",
                256,
                "w4-mock-v1",
            )
            after = connection.execute(
                text("SELECT id, embedding_blob FROM knowledge_chunks WHERE id=:chunk_id"),
                fixture,
            ).one()
            assert after == before
            assert connection.execute(
                text(
                    "SELECT course_id, group_id, agent_version_id FROM provider_export_manifests "
                    "WHERE id=:manifest_id"
                ),
                fixture,
            ).one() == (None, None, None)
            assert (
                connection.execute(
                    text(
                        "SELECT id FROM provider_export_confirmations "
                        "WHERE id='confirmation-identity'"
                    )
                ).scalar_one()
                == "confirmation-identity"
            )
            assert (
                connection.execute(
                    text(
                        "SELECT operation_id, build_id, batch_index FROM embedding_accepted_stages "
                        "WHERE operation_id=:operation_id"
                    ),
                    fixture,
                ).first()
                is None
            )
    finally:
        database.dispose()
    assert before_snapshot_id == fixture["snapshot_id"]


def test_0013_snapshot_identity_check_accepts_only_frozen_combinations(
    tmp_path: Path,
) -> None:
    path = tmp_path / "identity-check.sqlite3"
    fixture = _seed_populated_legacy(path)
    _upgrade(path)
    database = Database(_database_url(path))
    try:
        with database.engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE knowledge_snapshots SET embedding_provider='dashscope', "
                    "embedding_model_key='text-embedding-v4', embedding_region='cn-beijing', "
                    "embedding_dimension=1024, embedding_policy_version='w4-embed-v1' "
                    "WHERE id=:snapshot_id"
                ),
                fixture,
            )
        with pytest.raises(IntegrityError):
            with database.engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE knowledge_snapshots SET embedding_dimension=256 "
                        "WHERE id=:snapshot_id"
                    ),
                    fixture,
                )
        with database.engine.connect() as connection:
            identity = connection.execute(
                text(
                    "SELECT embedding_provider, embedding_model_key, embedding_region, "
                    "embedding_dimension, embedding_policy_version FROM knowledge_snapshots "
                    "WHERE id=:snapshot_id"
                ),
                fixture,
            ).one()
            assert tuple(identity) == (
                "dashscope",
                "text-embedding-v4",
                "cn-beijing",
                1024,
                "w4-embed-v1",
            )
    finally:
        database.dispose()


def test_0013_stage_is_durable_ordered_and_database_bound(tmp_path: Path) -> None:
    path = tmp_path / "stage.sqlite3"
    fixture = _seed_populated_legacy(path)
    _upgrade(path)
    database = Database(_database_url(path))
    try:
        with database.engine.begin() as connection:
            values = {
                **fixture,
                "build_id": "build-identity",
                "build_hash": "b" * 64,
                "response_hash": "c" * 64,
            }
            connection.execute(
                text(
                    "INSERT INTO embedding_accepted_stages "
                    "(operation_id,build_id,build_manifest_hash,batch_index,model_key,"
                    "embedding_provider,embedding_region,dimension,policy_version,response_hash,"
                    "created_at) VALUES (:operation_id,:build_id,:build_hash,0,"
                    "'text-embedding-v4','dashscope','cn-beijing',1024,'w4-embed-v1',"
                    ":response_hash,:now)"
                ),
                {**values, "now": datetime.now(UTC)},
            )
            # Staging precedes snapshot publication: this build-local chunk ID
            # deliberately has no KnowledgeChunk row yet.
            connection.execute(
                text(
                    "INSERT INTO embedding_accepted_vectors "
                    "(operation_id,item_index,chunk_id,embedding_blob) VALUES "
                    "(:operation_id,0,'build-chunk-before-publish',:blob)"
                ),
                {"operation_id": fixture["operation_id"], "blob": b"staged-before-publish"},
            )
            connection.execute(
                text(
                    "INSERT INTO knowledge_chunks "
                    "(id,snapshot_id,snapshot_document_id,document_id,chunk_index,text,"
                    "start_offset,end_offset,embedding_blob,embedding_dimension,embedding_key) "
                    "SELECT 'chunk-identity-2',snapshot_id,snapshot_document_id,document_id,"
                    "1,'second vector',0,12,:blob,256,'mock' FROM knowledge_chunks "
                    "WHERE id='chunk-identity'"
                ),
                {"blob": b"second-vector"},
            )
            for item_index, chunk_id in ((1, "chunk-identity-2"), (2, "chunk-identity")):
                connection.execute(
                    text(
                        "INSERT INTO embedding_accepted_vectors "
                        "(operation_id,item_index,chunk_id,embedding_blob) VALUES "
                        "(:operation_id,:item_index,:chunk_id,:blob)"
                    ),
                    {
                        "operation_id": fixture["operation_id"],
                        "item_index": item_index,
                        "chunk_id": chunk_id,
                        "blob": bytes([item_index + 1]),
                    },
                )
            ordered = connection.execute(
                text(
                    "SELECT item_index, chunk_id FROM embedding_accepted_vectors "
                    "WHERE operation_id=:operation_id ORDER BY item_index"
                ),
                fixture,
            ).all()
            assert [tuple(value) for value in ordered] == [
                (0, "build-chunk-before-publish"),
                (1, "chunk-identity-2"),
                (2, "chunk-identity"),
            ]
            with pytest.raises(IntegrityError):
                connection.execute(
                    text(
                        "INSERT INTO embedding_accepted_vectors "
                        "(operation_id,item_index,chunk_id,embedding_blob) VALUES "
                        "(:operation_id,0,:chunk_id,:blob)"
                    ),
                    {
                        "operation_id": fixture["operation_id"],
                        "chunk_id": fixture["chunk_id"],
                        "blob": b"duplicate",
                    },
                )
    finally:
        database.dispose()


def test_0013_downgrade_only_legacy_mock_is_lossless_and_reupgradeable(tmp_path: Path) -> None:
    path = tmp_path / "downgrade.sqlite3"
    fixture = _seed_populated_legacy(path)
    _upgrade(path)
    _downgrade(path)
    assert _revision(path) == PREVIOUS_REVISION
    assert "embedding_provider" not in _columns(path, "knowledge_snapshots")
    assert "embedding_accepted_stages" not in _table_names(path)
    assert "embedding_accepted_vectors" not in _table_names(path)
    assert {"course_id", "group_id", "agent_version_id"} - _columns(
        path, "provider_export_manifests"
    ) == {"course_id", "group_id", "agent_version_id"}
    database = Database(_database_url(path))
    try:
        with database.engine.connect() as connection:
            assert (
                connection.execute(
                    text("SELECT id FROM knowledge_snapshots WHERE id=:snapshot_id"), fixture
                ).scalar_one()
                == fixture["snapshot_id"]
            )
            assert (
                connection.execute(
                    text("SELECT embedding_blob FROM knowledge_chunks WHERE id=:chunk_id"), fixture
                ).scalar_one()
                == b"legacy-vector"
            )
    finally:
        database.dispose()
    _upgrade(path)
    assert _revision(path) == REVISION


def test_0013_real_identity_or_accepted_stage_refuses_lossy_downgrade(tmp_path: Path) -> None:
    real_path = tmp_path / "real.sqlite3"
    fixture = _seed_populated_legacy(real_path)
    _upgrade(real_path)
    database = Database(_database_url(real_path))
    try:
        with database.engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE knowledge_snapshots SET embedding_provider='dashscope', "
                    "embedding_model_key='text-embedding-v4', embedding_region='cn-beijing', "
                    "embedding_dimension=1024, embedding_policy_version='w4-embed-v1' "
                    "WHERE id=:snapshot_id"
                ),
                fixture,
            )
    finally:
        database.dispose()
    with pytest.raises(RuntimeError, match="real or invalid embedding identity"):
        _downgrade(real_path)
    assert _revision(real_path) == REVISION

    stage_path = tmp_path / "stage-refusal.sqlite3"
    stage_fixture = _seed_populated_legacy(stage_path)
    _upgrade(stage_path)
    database = Database(_database_url(stage_path))
    try:
        with database.engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO embedding_accepted_stages "
                    "(operation_id,build_id,build_manifest_hash,batch_index,model_key,"
                    "embedding_provider,embedding_region,dimension,policy_version,response_hash,"
                    "created_at) VALUES (:operation_id,'build-stage',:hash,0,"
                    "'text-embedding-v4','dashscope','cn-beijing',1024,'w4-embed-v1',:hash,:now)"
                ),
                {**stage_fixture, "hash": "d" * 64, "now": datetime.now(UTC)},
            )
    finally:
        database.dispose()
    with pytest.raises(RuntimeError, match="accepted embedding stages"):
        _downgrade(stage_path)
    assert _revision(stage_path) == REVISION


def test_0013_manifest_owner_foreign_keys_and_legacy_nulls(tmp_path: Path) -> None:
    path = tmp_path / "owners.sqlite3"
    fixture = _seed_populated_legacy(path)
    _upgrade(path)
    database = Database(_database_url(path))
    try:
        with database.engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE provider_export_manifests SET course_id=:course_id, "
                    "group_id=:group_id, "
                    "agent_version_id=:agent_version_id WHERE id=:manifest_id"
                ),
                fixture,
            )
            with pytest.raises(IntegrityError):
                connection.execute(
                    text(
                        "INSERT INTO provider_export_manifests "
                        "(id,policy_snapshot_id,scope_id,provider_operation,model_key,policy_hash,"
                        "build_manifest_hash,persona_spec_hash,fields_json,operation_revision,"
                        "contains_secret,contains_identity,contains_private_audio,contains_teacher_note,"
                        "manifest_hash,created_at,course_id) SELECT 'manifest-bad',"
                        "policy_snapshot_id,"
                        "scope_id,provider_operation,model_key,policy_hash,build_manifest_hash,"
                        "persona_spec_hash,fields_json,operation_revision,contains_secret,contains_identity,"
                        "contains_private_audio,contains_teacher_note,manifest_hash,created_at,"
                        "'missing' "
                        "FROM provider_export_manifests WHERE id=:manifest_id"
                    ),
                    fixture,
                )
    finally:
        database.dispose()
