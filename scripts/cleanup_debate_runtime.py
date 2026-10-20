"""Safely remove historical Debate runtime data from one offline SQLite DB.

The default command is a read-only dry run.  ``--apply`` requires both an
explicit database path and ``--offline``; the script never stops a process,
starts a container, deploys code or resets the whole data directory.  It
deletes only rows reachable from the Debate graph (plus the dedicated Demo
acceptance ledger) and exact files referenced by those rows.

SQLite's LLM recovery rows carry an immutable delete trigger.  When such rows
are in the bounded target set, the apply transaction records and validates the
exact trigger definition, drops only that delete guard, deletes the rows,
restores the original SQL before commit, and verifies the trigger again.  All
other delete guards and the final-input/turn-scope triggers from migration
0020 remain active.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import quote

K2A_SCHEMA_HEAD = "0037_knowledge_generation_runs"
K2B1_SCHEMA_HEAD = "0038_knowledge_generation_provider_stage"
K2B2_SCHEMA_HEAD = "0039_knowledge_generation_materialization"
K3A_SCHEMA_HEAD = "0040_teams_publication_grants"
K3B1_SCHEMA_HEAD = "0041_team_conversations"
K3B2_SCHEMA_HEAD = "0042_team_turn_results"
K4A_SCHEMA_HEAD = "0043_learning_evidence"
SCHEMA_HEAD = "0077_real_delete_history_links"
KNOWLEDGE_SETS_SCHEMA_HEAD = "0036_knowledge_sets_assets"
SUPPORTED_SCHEMA_HEADS = {
    "0035_w1_resource_ownership",
    KNOWLEDGE_SETS_SCHEMA_HEAD,
    K2A_SCHEMA_HEAD,
    K2B1_SCHEMA_HEAD,
    K2B2_SCHEMA_HEAD,
    K3A_SCHEMA_HEAD,
    K3B1_SCHEMA_HEAD,
    K3B2_SCHEMA_HEAD,
    K4A_SCHEMA_HEAD,
}
# These additive tables are outside the Debate cleanup's ownership.
V14_PRESERVED_BY_HEAD = {
    "0044_team_provider_stage": (
        "team_provider_calls",
        "team_provider_standing_grants",
        "team_provider_consent_bindings",
    ),
    "0045_assessment_attempts": (
        "assessment_activities",
        "assessment_activity_questions",
        "assessment_attempts",
        "learning_assessment_resource_grants",
        "assessment_attempt_questions",
        "assessment_attempt_events",
        "learning_boundaries",
        "learning_boundary_revisions",
        "learning_boundary_evidence",
        "assessment_course_reports",
        "assessment_course_report_revisions",
        "assessment_course_report_evidence",
        "assessment_course_report_mutations",
    ),
    "0046_chat_withdrawal": (),
    "0047_brainform_markdown": (
        "knowledge_document_versions",
        "knowledge_set_markdown_versions",
    ),
    "0048_runtime_tool_receipts": ("runtime_tool_receipts",),
    "0049_runtime_model_call_stages": ("runtime_model_call_stages",),
    "0050_chat_provider_standing_grants": (
        "chat_provider_standing_grants",
        "chat_provider_consent_bindings",
    ),
    "0051_chat_memory_entry_actions": ("chat_memory_entry_actions",),
    "0052_teacher_courseware": (),
    "0053_user_profile": (),
    "0054_assessment_attempt_question_selection": (),
    "0055_assessment_attempt_submission": (),
    "0056_preset_voice_profiles": (),
    "0057_agent_account_memory": ("agent_account_memories",),
    "0058_card_rooms": ("card_rooms",),
    "0059_chat_titles_pins": (),
    "0060_legacy_data_reset": ("data_reset_rows",),
    "0061_personal_agent_debaters": (),
    "0062_teacher_personal_voices": (),
    "0063_attempt_actor_name": (),
    "0064_active_debate_slot": (),
    "0065_auth_login_admission": ("auth_login_admissions",),
    "0066_postgres_column_widths": (),
    "0067_voice_preview_counter": ("voice_preview_counters",),
    "0068_attempt_activity_index": (),
    "0069_barrage_sequence": (),
    "0070_conversation_attachments": ("conversation_attachments",),
    "0071_chat_reports": ("chat_reports",),
    "0072_attempt_teacher_hidden": (),
    "0073_voice_ready_on_upload": (),
    "0074_interaction_voter_key": (),
    "0077_real_delete_history_links": (),
}
SUPPORTED_SCHEMA_HEADS.update(V14_PRESERVED_BY_HEAD)
AUDIT_SCHEMA_VERSION = "debate_runtime_cleanup_audit_v1"
DELETE_GUARD = "trg_llm_recovery_inputs_immutable_delete"

# These are the runtime tables that the cleanup owns.  ``audit_logs`` has no
# foreign key, so it is handled separately: only rows whose explicit
# ``debate_id`` names a targeted Debate are owned by this cleanup.  Account,
# course and other unscoped audit rows remain preserved.
TARGET_TABLES = (
    "classroom_live_presence",
    "debates",
    "debate_participants",
    "debate_turns",
    "turn_sources",
    "position_history",
    "playback_states",
    "debate_events",
    "classroom_interaction_windows",
    "votes",
    "barrage_messages",
    "interaction_final_vote_counts",
    "interaction_final_barrages",
    "barrage_insight_snapshots",
    "barrage_insight_items",
    "barrage_insight_assignments",
    "civilization_reports",
    "civilization_report_revisions",
    "civilization_report_current_success",
    "jobs",
    "provider_export_confirmations",
    "provider_export_manifests",
    "provider_operations",
    "provider_reservations",
    "provider_scope_budgets",
    "embedding_accepted_stages",
    "embedding_accepted_vectors",
    "llm_accepted_stages",
    "llm_recovery_inputs",
    "demo_acceptance_runs",
    "idempotency_records",
    "file_references",
    "file_operations",
    "stored_files",
)

PRESERVED_TABLES = (
    "agent_conversations",
    "agent_conversation_turns",
    "provider_preferences",
    "user_credentials",
    "teacher_group_access",
    "users",
    "sessions",
    "demo_account_bindings",
    "courses",
    "groups",
    "group_members",
    "course_members",
    "agents",
    "agent_versions",
    "knowledge_documents",
    "knowledge_document_chunks",
    "agent_version_documents",
    "knowledge_snapshots",
    "snapshot_documents",
    "knowledge_chunks",
    "voice_profiles",
    "voice_provider_operations",
    "voice_previews",
    "provider_policy_snapshots",
    "audit_logs",
    "knowledge_sets",
    "knowledge_set_sources",
    "knowledge_assets",
    "knowledge_asset_versions",
    "knowledge_asset_version_sources",
    "agent_knowledge_sets",
    "knowledge_generation_runs",
    "knowledge_generation_target_snapshots",
    "knowledge_generation_accepted_stages",
    "knowledge_generation_source_receipts",
    "knowledge_generation_items",
    "teams",
    "team_versions",
    "team_version_members",
    "team_version_sets",
    "course_team_publications",
    "team_member_invoke_grants",
    "conversation_participants",
    "conversation_participant_sets",
    "conversation_shared_sets",
    "team_turn_results",
    "team_chat_events",
    "learning_records",
    "learning_assessments",
    "learning_assessment_revisions",
    "learning_assessment_mutations",
)
PRESERVED_TABLES += tuple(table for tables in V14_PRESERVED_BY_HEAD.values() for table in tables)
K1_PRESERVED_TABLES = frozenset(
    {
        "knowledge_sets",
        "knowledge_set_sources",
        "knowledge_assets",
        "knowledge_asset_versions",
        "knowledge_asset_version_sources",
        "agent_knowledge_sets",
    }
)
K2_PRESERVED_TABLES = frozenset(
    {"knowledge_generation_runs", "knowledge_generation_accepted_stages"}
)
K2B2_PRESERVED_TABLES = frozenset(
    {
        "knowledge_generation_source_receipts",
        "knowledge_generation_items",
        "knowledge_generation_target_snapshots",
    }
)
K3A_PRESERVED_TABLES = frozenset(
    {
        "teams",
        "team_versions",
        "team_version_members",
        "team_version_sets",
        "course_team_publications",
        "team_member_invoke_grants",
    }
)
K3B1_PRESERVED_TABLES = frozenset(
    {
        "conversation_participants",
        "conversation_participant_sets",
        "conversation_shared_sets",
    }
)
K3B2_PRESERVED_TABLES = frozenset({"team_turn_results", "team_chat_events"})
K4A_PRESERVED_TABLES = frozenset(
    {
        "learning_records",
        "learning_assessments",
        "learning_assessment_revisions",
        "learning_assessment_mutations",
    }
)

IDEMPOTENCY_OPERATIONS = (
    "createDebate",
    "startDebate",
    "retryDebatePreparation",
    "pauseDebate",
    "resumeDebate",
    "finishDebate",
    "releaseDebate",
    "advanceDebatePlayback",
    "replayDebate",
    "interaction.open",
    "interaction.close",
    "report.generate",
)
DEBATE_CLEANUP_OPERATIONS = (
    "debate_cleanup_voice_v1",
    "debate_cleanup_all_v1",
)

_TRIGGER_EXPECTATIONS = {
    "barrage_turn_scope_insert": (
        "CREATE TRIGGER barrage_turn_scope_insert BEFORE INSERT ON barrage_messages "
        "WHEN NEW.turn_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM debate_turns WHERE "
        "id=NEW.turn_id AND debate_id=NEW.debate_id) BEGIN SELECT RAISE(ABORT, "
        "'barrage_turn_scope'); END"
    ),
    "barrage_turn_scope_update": (
        "CREATE TRIGGER barrage_turn_scope_update BEFORE UPDATE ON barrage_messages "
        "WHEN NEW.turn_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM debate_turns WHERE "
        "id=NEW.turn_id AND debate_id=NEW.debate_id) BEGIN SELECT RAISE(ABORT, "
        "'barrage_turn_scope'); END"
    ),
    "debate_final_input_immutable": (
        "CREATE TRIGGER debate_final_input_immutable BEFORE UPDATE ON debates WHEN "
        "OLD.final_input_json IS NOT NULL AND (NEW.final_input_json IS NOT OLD.final_input_json "
        "OR NEW.final_input_hash IS NOT OLD.final_input_hash OR NEW.final_frozen_at IS NOT "
        "OLD.final_frozen_at) "
        "BEGIN SELECT RAISE(ABORT, 'final_input_immutable'); END"
    ),
    "trg_llm_recovery_inputs_immutable_update": (
        "CREATE TRIGGER trg_llm_recovery_inputs_immutable_update BEFORE UPDATE ON "
        "llm_recovery_inputs "
        "BEGIN SELECT RAISE(ABORT, 'llm recovery input is immutable'); END"
    ),
    DELETE_GUARD: (
        "CREATE TRIGGER trg_llm_recovery_inputs_immutable_delete BEFORE DELETE ON "
        "llm_recovery_inputs "
        "BEGIN SELECT RAISE(ABORT, 'llm recovery input is immutable'); END"
    ),
}


class CleanupError(RuntimeError):
    """A cleanup preflight or transaction failed closed."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _normalise_sql(value: str) -> str:
    return " ".join(value.lower().split())


def _safe_relative_file(root: Path, relative_path: str) -> Path:
    """Resolve one exact data file while rejecting traversal and symlinks."""

    if not isinstance(relative_path, str) or not relative_path or "\x00" in relative_path:
        raise CleanupError("stored_file_path_invalid")
    pure = PurePosixPath(relative_path)
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        raise CleanupError("stored_file_path_invalid")
    root = root.resolve(strict=True)
    current = root
    for part in pure.parts:
        current = current / part
        if current.is_symlink():
            raise CleanupError("stored_file_symlink_refused")
    resolved = current.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise CleanupError("stored_file_path_outside_root") from exc
    if current.exists() and not current.is_file():
        raise CleanupError("stored_file_not_regular")
    return current


def _validate_paths(database_path: Path, data_root: Path) -> tuple[Path, Path]:
    """Validate the exact DB and data-root boundary before opening SQLite."""

    supplied_root = data_root.expanduser()
    if supplied_root.is_symlink() or not supplied_root.exists() or not supplied_root.is_dir():
        raise CleanupError("data_root_invalid")
    root = supplied_root.resolve(strict=True)
    supplied_db = database_path.expanduser()
    if not supplied_db.is_absolute():
        supplied_db = root / supplied_db
    if supplied_db.is_symlink() or not supplied_db.exists() or not supplied_db.is_file():
        raise CleanupError("database_path_invalid")
    db = supplied_db.resolve(strict=True)
    try:
        db.relative_to(root)
    except ValueError as exc:
        raise CleanupError("database_outside_data_root") from exc
    return db, root


def _connect(path: Path, *, read_only: bool) -> sqlite3.Connection:
    if read_only:
        uri = f"file:{quote(str(path), safe='/')}?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
    else:
        connection = sqlite3.connect(str(path))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        connection.close()
        raise CleanupError("foreign_keys_unavailable")
    return connection


def _in(values: Iterable[str]) -> tuple[str, tuple[str, ...]]:
    ordered = tuple(dict.fromkeys(str(value) for value in values))
    if not ordered:
        return "NULL", ()
    return ",".join("?" for _ in ordered), ordered


def _select_child_set(
    connection: sqlite3.Connection,
    table: str,
    child_column: str,
    parent_column: str,
    parent_values: Iterable[str],
) -> set[str]:
    """Select child identities by an explicit parent column."""

    clause, params = _in(parent_values)
    if not params:
        return set()
    rows = connection.execute(
        f"SELECT {child_column} FROM {table} WHERE {parent_column} IN ({clause})",
        params,
    )
    return {str(row[0]) for row in rows if row[0] is not None}


def _select_all(connection: sqlite3.Connection, table: str, column: str) -> set[str]:
    rows = connection.execute(f"SELECT {column} FROM {table}")
    return {str(row[0]) for row in rows}


def _select_rows_by_any(
    connection: sqlite3.Connection,
    table: str,
    columns: Sequence[str],
    values: Iterable[str],
) -> list[sqlite3.Row]:
    clause, params = _in(values)
    if not params:
        return []
    predicate = " OR ".join(f"{column} IN ({clause})" for column in columns)
    repeated = params * len(columns)
    return list(connection.execute(f"SELECT * FROM {table} WHERE {predicate}", repeated))


def _count(
    connection: sqlite3.Connection,
    table: str,
    columns: Sequence[str],
    values: Iterable[str],
) -> int:
    clause, params = _in(values)
    if not params:
        return 0
    predicate = " OR ".join(f"{column} IN ({clause})" for column in columns)
    return int(
        connection.execute(
            f"SELECT count(*) FROM {table} WHERE {predicate}", params * len(columns)
        ).fetchone()[0]
    )


def _count_ids(connection: sqlite3.Connection, table: str, ids: Iterable[str]) -> int:
    return _count(connection, table, ("id",), ids)


def _table_names(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    return {str(row[0]) for row in rows}


def _validate_schema(connection: sqlite3.Connection) -> str:
    tables = _table_names(connection)
    if "alembic_version" not in tables:
        raise CleanupError("schema_tables_missing")
    heads = {str(row[0]) for row in connection.execute("SELECT version_num FROM alembic_version")}
    if len(heads) != 1 or not heads.issubset(SUPPORTED_SCHEMA_HEADS):
        raise CleanupError("schema_head_invalid")
    schema_head = next(iter(heads))
    required_preserved = set(PRESERVED_TABLES)
    for introduced_at, additions in V14_PRESERVED_BY_HEAD.items():
        if int(schema_head[:4]) < int(introduced_at[:4]):
            required_preserved.difference_update(additions)
    if schema_head == "0035_w1_resource_ownership":
        required_preserved.difference_update(K1_PRESERVED_TABLES)
        required_preserved.difference_update(K2_PRESERVED_TABLES)
        required_preserved.difference_update(K2B2_PRESERVED_TABLES)
        required_preserved.difference_update(K3A_PRESERVED_TABLES)
        required_preserved.difference_update(K3B1_PRESERVED_TABLES)
        required_preserved.difference_update(K3B2_PRESERVED_TABLES)
        required_preserved.difference_update(K4A_PRESERVED_TABLES)
    elif schema_head == KNOWLEDGE_SETS_SCHEMA_HEAD:
        required_preserved.difference_update(K2_PRESERVED_TABLES)
        required_preserved.difference_update(K2B2_PRESERVED_TABLES)
        required_preserved.difference_update(K3A_PRESERVED_TABLES)
        required_preserved.difference_update(K3B1_PRESERVED_TABLES)
        required_preserved.difference_update(K3B2_PRESERVED_TABLES)
        required_preserved.difference_update(K4A_PRESERVED_TABLES)
    elif schema_head == K2A_SCHEMA_HEAD:
        required_preserved.discard("knowledge_generation_accepted_stages")
        required_preserved.difference_update(K2B2_PRESERVED_TABLES)
        required_preserved.difference_update(K3A_PRESERVED_TABLES)
        required_preserved.difference_update(K3B1_PRESERVED_TABLES)
        required_preserved.difference_update(K3B2_PRESERVED_TABLES)
        required_preserved.difference_update(K4A_PRESERVED_TABLES)
    elif schema_head == K2B1_SCHEMA_HEAD:
        required_preserved.difference_update(K2B2_PRESERVED_TABLES)
        required_preserved.difference_update(K3A_PRESERVED_TABLES)
        required_preserved.difference_update(K3B1_PRESERVED_TABLES)
        required_preserved.difference_update(K3B2_PRESERVED_TABLES)
        required_preserved.difference_update(K4A_PRESERVED_TABLES)
    elif schema_head == K2B2_SCHEMA_HEAD:
        required_preserved.difference_update(K3A_PRESERVED_TABLES)
        required_preserved.difference_update(K3B1_PRESERVED_TABLES)
        required_preserved.difference_update(K3B2_PRESERVED_TABLES)
        required_preserved.difference_update(K4A_PRESERVED_TABLES)
    elif schema_head == K3A_SCHEMA_HEAD:
        required_preserved.difference_update(K3B1_PRESERVED_TABLES)
        required_preserved.difference_update(K3B2_PRESERVED_TABLES)
        required_preserved.difference_update(K4A_PRESERVED_TABLES)
    elif schema_head == K3B1_SCHEMA_HEAD:
        required_preserved.difference_update(K3B2_PRESERVED_TABLES)
        required_preserved.difference_update(K4A_PRESERVED_TABLES)
    elif schema_head == K3B2_SCHEMA_HEAD:
        required_preserved.difference_update(K4A_PRESERVED_TABLES)
    required = set(TARGET_TABLES) | required_preserved | {"alembic_version"}
    if required.difference(tables):
        raise CleanupError("schema_tables_missing")
    if list(connection.execute("PRAGMA foreign_key_check")):
        raise CleanupError("foreign_key_violations_before")
    triggers = {
        str(row[0]): str(row[1])
        for row in connection.execute("SELECT name, sql FROM sqlite_master WHERE type='trigger'")
    }
    for name, expected in _TRIGGER_EXPECTATIONS.items():
        actual = triggers.get(name)
        if actual is None or _normalise_sql(actual) != _normalise_sql(expected):
            raise CleanupError("trigger_definition_unexpected")
    return schema_head


@dataclass(frozen=True)
class CleanupPlan:
    """Opaque target identities plus safe counts for one immutable DB view."""

    debate_ids: frozenset[str]
    participant_ids: frozenset[str]
    turn_ids: frozenset[str]
    window_ids: frozenset[str]
    barrage_ids: frozenset[str]
    report_ids: frozenset[str]
    revision_ids: frozenset[str]
    insight_ids: frozenset[str]
    manifest_ids: frozenset[str]
    manifest_hashes: frozenset[str]
    operation_ids: frozenset[str]
    operation_scopes: frozenset[str]
    run_ids: frozenset[str]
    audit_log_ids: frozenset[str]
    idempotency_ids: frozenset[str]
    file_reference_ids: frozenset[str]
    file_operation_ids: frozenset[str]
    cleanup_journal_ids: frozenset[str]
    stored_file_ids: frozenset[str]
    file_paths: tuple[Path, ...]
    directory_paths: tuple[Path, ...]
    table_counts: Mapping[str, int]
    preserved_counts: Mapping[str, int]
    schema_head: str
    file_bytes: int

    @property
    def file_count(self) -> int:
        return len(self.file_paths)

    @property
    def directory_count(self) -> int:
        return len(self.directory_paths)

    @property
    def has_targets(self) -> bool:
        return (
            any(self.table_counts.values()) or bool(self.file_paths) or bool(self.directory_paths)
        )


def _safe_relative_dir(root: Path, relative_path: str) -> Path:
    """Resolve one exact runtime directory while rejecting traversal/symlinks."""

    if not isinstance(relative_path, str) or not relative_path or "\x00" in relative_path:
        raise CleanupError("runtime_path_invalid")
    pure = PurePosixPath(relative_path)
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        raise CleanupError("runtime_path_invalid")
    root = root.resolve(strict=True)
    current = root
    for part in pure.parts:
        current = current / part
        if current.is_symlink():
            raise CleanupError("runtime_path_symlink_refused")
    resolved = current.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise CleanupError("runtime_path_outside_root") from exc
    if current.exists() and not current.is_dir():
        raise CleanupError("runtime_path_not_directory")
    return current


def _scan_debate_audio_artifacts(
    data_root: Path, debate_course_ids: Mapping[str, str]
) -> tuple[dict[str, Path], tuple[Path, ...], int]:
    """Find exact per-Debate audio files not represented by ``stored_files``.

    The playback contract permits only immediate files in
    ``courses/<course>/current-debate-audio/<debate>``.  We inspect those
    target directories only, refuse symlinks or nested entries, and never
    recurse through an arbitrary data directory.
    """

    if not debate_course_ids:
        return {}, (), 0
    course_root = data_root / "courses"
    if course_root.is_symlink():
        raise CleanupError("runtime_path_symlink_refused")
    if not course_root.exists():
        return {}, (), 0
    if not course_root.is_dir():
        raise CleanupError("runtime_path_not_directory")
    paths: dict[str, Path] = {}
    directories: list[Path] = []
    bytes_total = 0
    for debate_id, course_id in debate_course_ids.items():
        relative_dir = f"courses/{course_id}/current-debate-audio/{debate_id}"
        debate_dir = _safe_relative_dir(data_root, relative_dir)
        if not debate_dir.exists():
            continue
        directories.append(debate_dir)
        for child in debate_dir.iterdir():
            if child.is_symlink():
                raise CleanupError("runtime_path_symlink_refused")
            if not child.is_file():
                raise CleanupError("runtime_path_nested_entry")
            relative_path = child.relative_to(data_root).as_posix()
            path = _safe_relative_file(data_root, relative_path)
            paths.setdefault(relative_path, path)
            bytes_total += max(0, int(path.stat().st_size))
    return paths, tuple(directories), bytes_total


def _collect_owned_path(
    data_root: Path,
    relative_path: str,
    *,
    directory_hint: bool,
    file_paths: dict[str, Path],
    directory_paths: dict[str, Path],
) -> int:
    """Collect one journal path, allowing only a bounded directory shape."""

    if directory_hint:
        directory = _safe_relative_dir(data_root, relative_path)
        directory_paths.setdefault(relative_path, directory)
        if not directory.exists():
            return 0
        bytes_total = 0
        for child in directory.iterdir():
            if child.is_symlink():
                raise CleanupError("runtime_path_symlink_refused")
            if not child.is_file():
                raise CleanupError("runtime_path_nested_entry")
            child_relative = child.relative_to(data_root).as_posix()
            child_path = _safe_relative_file(data_root, child_relative)
            file_paths.setdefault(child_relative, child_path)
            bytes_total += max(0, int(child_path.stat().st_size))
        return bytes_total
    path = _safe_relative_file(data_root, relative_path)
    file_paths.setdefault(relative_path, path)
    return max(0, int(path.stat().st_size)) if path.exists() else 0


def _collect_cleanup_journal_paths(
    data_root: Path,
    rows: Sequence[sqlite3.Row],
    file_paths: dict[str, Path],
    directory_paths: dict[str, Path],
) -> tuple[set[str], set[str], int]:
    """Collect only private quarantine files from online cleanup intents."""

    operation_ids: set[str] = set()
    idempotency_ids: set[str] = set()
    file_bytes = 0
    scanned_staging: set[str] = set()
    for row in rows:
        operation_ids.add(str(row["id"]))
        if row["idempotency_record_id"]:
            idempotency_ids.add(str(row["idempotency_record_id"]))
        staging = row["staging_relative_path"]
        if not isinstance(staging, str) or not staging:
            raise CleanupError("cleanup_journal_invalid")
        if not PurePosixPath(staging).name.startswith(".maya-debate-delete-"):
            raise CleanupError("cleanup_journal_invalid")
        if staging not in scanned_staging:
            file_bytes += _collect_owned_path(
                data_root,
                staging,
                directory_hint=True,
                file_paths=file_paths,
                directory_paths=directory_paths,
            )
            scanned_staging.add(staging)
    return operation_ids, idempotency_ids, file_bytes


def _stored_file_survivor_check(
    connection: sqlite3.Connection,
    *,
    stored_file_ids: set[str],
    file_reference_ids: set[str],
    turn_ids: set[str],
) -> None:
    """Reject a candidate file still referenced by authored/voice data."""

    if not stored_file_ids:
        return
    clause, params = _in(stored_file_ids)
    checks = (
        "knowledge_documents",
        "knowledge_snapshots",
        "snapshot_documents",
        "voice_previews",
    )
    for table in checks:
        column = {
            "knowledge_documents": "stored_file_id",
            "knowledge_snapshots": "combined_file_id",
            "snapshot_documents": "frozen_file_id",
            "voice_previews": "stored_file_id",
        }[table]
        query = f"SELECT 1 FROM {table} WHERE {column} IN ({clause}) LIMIT 1"
        if connection.execute(query, params).fetchone() is not None:
            raise CleanupError("stored_file_shared")
    for table, column, excluded in (
        ("file_references", "stored_file_id", file_reference_ids),
        ("debate_turns", "audio_file_id", turn_ids),
    ):
        excluded_clause, excluded_params = _in(excluded)
        extra_sql = f"id NOT IN ({excluded_clause})" if excluded_params else "1"
        query = f"SELECT 1 FROM {table} WHERE {column} IN ({clause}) AND {extra_sql} LIMIT 1"
        query_params = params + excluded_params
        if connection.execute(query, query_params).fetchone() is not None:
            raise CleanupError("stored_file_shared")


def _build_plan(connection: sqlite3.Connection, data_root: Path, schema_head: str) -> CleanupPlan:
    debate_ids = _select_all(connection, "debates", "id")
    debate_course_ids = {
        str(row["id"]): str(row["course_id"])
        for row in connection.execute("SELECT id, course_id FROM debates")
    }
    participant_ids = _select_child_set(
        connection, "debate_participants", "id", "debate_id", debate_ids
    )
    turn_ids = _select_child_set(connection, "debate_turns", "id", "debate_id", debate_ids)
    window_ids = _select_child_set(
        connection, "classroom_interaction_windows", "id", "debate_id", debate_ids
    )
    barrage_ids = _select_child_set(connection, "barrage_messages", "id", "debate_id", debate_ids)
    report_ids = _select_child_set(
        connection, "civilization_reports", "id", "debate_id", debate_ids
    )
    revision_ids = _select_child_set(
        connection, "civilization_report_revisions", "id", "debate_id", debate_ids
    )
    insight_ids = _select_child_set(
        connection, "barrage_insight_snapshots", "id", "debate_id", debate_ids
    )
    run_ids = _select_all(connection, "demo_acceptance_runs", "id")
    audit_log_rows = _select_rows_by_any(
        connection, "audit_logs", ("debate_id", "request_id"), debate_ids | run_ids
    )
    audit_log_ids = {str(row["id"]) for row in audit_log_rows}
    run_revision_ids = _select_child_set(
        connection, "demo_acceptance_runs", "report_revision_id", "id", run_ids
    )
    revision_ids.update(value for value in run_revision_ids if value)
    report_ids.update(
        _select_child_set(
            connection, "civilization_report_revisions", "report_id", "id", revision_ids
        )
    )
    insight_ids.update(
        _select_child_set(
            connection,
            "civilization_report_revisions",
            "insight_snapshot_id",
            "id",
            revision_ids,
        )
    )

    manifest_rows = _select_rows_by_any(
        connection,
        "provider_export_manifests",
        ("debate_id", "turn_id"),
        debate_ids | turn_ids,
    )
    manifest_ids = {str(row["id"]) for row in manifest_rows}
    manifest_hashes = {str(row["manifest_hash"]) for row in manifest_rows}

    base_owner_ids = (
        debate_ids
        | participant_ids
        | turn_ids
        | window_ids
        | barrage_ids
        | report_ids
        | revision_ids
        | insight_ids
    )
    all_file_operation_rows = _select_rows_by_any(
        connection,
        "file_operations",
        ("entity_id", "old_audio_debate_id", "new_debate_id"),
        base_owner_ids | debate_ids,
    )
    # The online cleanup service leaves one private quarantine intent per
    # moved file.  It deliberately has no Debate FK and therefore survives a
    # Delete All; keep it out of the ordinary graph path scan and handle its
    # private directory below.  A completed/stranded intent may be the only
    # remaining evidence for a Debate that has already been deleted.
    cleanup_rows = list(
        connection.execute(
            "SELECT * FROM file_operations WHERE operation_type IN (?, ?) "
            "AND state IN ('prepared', 'staged', 'promoted', 'committed', "
            "'cleanup_required', 'recovered')",
            DEBATE_CLEANUP_OPERATIONS,
        )
    )
    # Collect the cleanup paths into the same dictionaries used for ordinary
    # runtime files.
    cleanup_file_paths: dict[str, Path] = {}
    cleanup_directory_paths: dict[str, Path] = {}
    cleanup_journal_ids, cleanup_idempotency_ids, cleanup_file_bytes = (
        _collect_cleanup_journal_paths(
            data_root,
            cleanup_rows,
            cleanup_file_paths,
            cleanup_directory_paths,
        )
    )
    file_operation_rows = [
        row
        for row in all_file_operation_rows
        if row["operation_type"] not in DEBATE_CLEANUP_OPERATIONS
    ]
    file_operation_ids = {str(row["id"]) for row in file_operation_rows}
    file_operation_entity_ids = {
        str(row["entity_id"]) for row in file_operation_rows if row["entity_id"]
    }
    owner_ids = base_owner_ids | file_operation_entity_ids | file_operation_ids
    file_reference_rows = _select_rows_by_any(
        connection, "file_references", ("owner_id",), owner_ids
    )
    file_reference_ids = {str(row["id"]) for row in file_reference_rows}
    stored_file_ids = {
        str(row["stored_file_id"]) for row in file_reference_rows if row["stored_file_id"]
    }
    stored_file_ids.update(
        _select_child_set(connection, "debate_turns", "audio_file_id", "debate_id", debate_ids)
    )

    file_paths_by_string: dict[str, Path] = {}
    directory_paths_by_string: dict[str, Path] = {}
    file_paths_by_string.update(cleanup_file_paths)
    directory_paths_by_string.update(cleanup_directory_paths)
    file_bytes = cleanup_file_bytes
    for row in file_operation_rows:
        for column in (
            "source_relative_path",
            "target_relative_path",
            "staging_relative_path",
        ):
            value = row[column]
            if value:
                file_bytes += _collect_owned_path(
                    data_root,
                    str(value),
                    directory_hint=(
                        row["operation_type"] == "debate_audio_swap"
                        and column in {"source_relative_path", "staging_relative_path"}
                    ),
                    file_paths=file_paths_by_string,
                    directory_paths=directory_paths_by_string,
                )
    stored_rows: list[sqlite3.Row] = []
    if stored_file_ids:
        clause, params = _in(stored_file_ids)
        stored_rows = list(
            connection.execute(
                f"SELECT id, relative_path, size FROM stored_files WHERE id IN ({clause})",
                params,
            )
        )
    stored_file_ids.update(str(row["id"]) for row in stored_rows)
    for row in stored_rows:
        relative_path = str(row["relative_path"])
        path = _safe_relative_file(data_root, relative_path)
        file_paths_by_string.setdefault(relative_path, path)
        file_bytes += max(0, int(row["size"] or 0))
    orphan_paths, directory_paths, _orphan_bytes = _scan_debate_audio_artifacts(
        data_root, debate_course_ids
    )
    for relative_path, path in orphan_paths.items():
        file_paths_by_string.setdefault(relative_path, path)
    directory_paths_by_string.update(
        {path.relative_to(data_root).as_posix(): path for path in directory_paths}
    )
    _stored_file_survivor_check(
        connection,
        stored_file_ids=stored_file_ids,
        file_reference_ids=file_reference_ids,
        turn_ids=turn_ids,
    )
    stored_sizes = {str(row["relative_path"]): max(0, int(row["size"] or 0)) for row in stored_rows}
    file_bytes = sum(
        max(0, int(path.stat().st_size)) if path.exists() else stored_sizes.get(relative_path, 0)
        for relative_path, path in file_paths_by_string.items()
    )

    scope_ids = debate_ids | turn_ids | window_ids | report_ids | revision_ids | insight_ids
    operation_rows: list[sqlite3.Row] = []
    predicates: list[str] = []
    params: list[str] = []
    if run_ids:
        clause, values = _in(run_ids)
        predicates.append(
            f"(acceptance_run_id IN ({clause}) AND provider_operation <> 'embedding')"
        )
        params.extend(values)
    if manifest_hashes:
        clause, values = _in(manifest_hashes)
        predicates.append(f"export_manifest_hash IN ({clause})")
        params.extend(values)
    if scope_ids:
        clause, values = _in(scope_ids)
        predicates.append(f"scope_id IN ({clause})")
        params.extend(values)
    if predicates:
        operation_rows = list(
            connection.execute(
                f"SELECT id, scope_id FROM provider_operations WHERE {' OR '.join(predicates)}",
                params,
            )
        )
    operation_ids = {str(row["id"]) for row in operation_rows}
    operation_scopes = {str(row["scope_id"]) for row in operation_rows if row["scope_id"]}
    budget_scopes = scope_ids | operation_scopes
    idempotency_rows: list[sqlite3.Row] = []
    operation_clause, operation_values = _in(IDEMPOTENCY_OPERATIONS)
    idempotency_predicates = [f"operation IN ({operation_clause})"]
    idempotency_params: list[str] = list(operation_values)
    file_idem_ids = {
        str(row["idempotency_record_id"])
        for row in file_operation_rows
        if row["idempotency_record_id"]
    }
    if file_idem_ids:
        clause, values = _in(file_idem_ids)
        idempotency_predicates.append(f"id IN ({clause})")
        idempotency_params.extend(values)
    idempotency_rows = list(
        connection.execute(
            f"SELECT id FROM idempotency_records WHERE {' OR '.join(idempotency_predicates)}",
            idempotency_params,
        )
    )
    idempotency_ids = (
        {str(row["id"]) for row in idempotency_rows} | file_idem_ids | cleanup_idempotency_ids
    )
    cleanup_debate_ids = debate_ids | {
        str(row["entity_id"]) for row in cleanup_rows if row["entity_id"]
    }
    if cleanup_debate_ids:
        operation_clause, operation_values = _in(("deleteVoice", "deleteAll"))
        for cleanup_debate_id in cleanup_debate_ids:
            idempotency_ids.update(
                str(row[0])
                for row in connection.execute(
                    "SELECT id FROM idempotency_records "
                    f"WHERE operation IN ({operation_clause}) "
                    "AND response_json LIKE ?",
                    (*operation_values, f"%{cleanup_debate_id}%"),
                )
            )
    file_operation_ids.update(cleanup_journal_ids)

    target_counts = {
        "debates": _count(connection, "debates", ("id",), debate_ids),
        "debate_participants": _count(
            connection,
            "debate_participants",
            ("id", "debate_id"),
            debate_ids | participant_ids,
        ),
        "debate_turns": _count(
            connection, "debate_turns", ("id", "debate_id"), debate_ids | turn_ids
        ),
        "turn_sources": _count(
            connection,
            "turn_sources",
            ("turn_id", "participant_id"),
            turn_ids | participant_ids,
        ),
        "position_history": _count(
            connection,
            "position_history",
            ("turn_id", "participant_id"),
            turn_ids | participant_ids,
        ),
        "playback_states": _count(connection, "playback_states", ("debate_id",), debate_ids),
        "debate_events": _count(connection, "debate_events", ("debate_id",), debate_ids),
        "classroom_interaction_windows": _count(
            connection,
            "classroom_interaction_windows",
            ("id", "debate_id"),
            window_ids | debate_ids,
        ),
        "votes": _count(
            connection,
            "votes",
            ("window_id", "debate_id", "participant_id"),
            window_ids | debate_ids | participant_ids,
        ),
        "barrage_messages": _count(
            connection,
            "barrage_messages",
            ("id", "window_id", "debate_id", "turn_id"),
            barrage_ids | window_ids | debate_ids | turn_ids,
        ),
        "interaction_final_vote_counts": _count(
            connection,
            "interaction_final_vote_counts",
            ("window_id", "debate_id", "participant_id"),
            window_ids | debate_ids | participant_ids,
        ),
        "interaction_final_barrages": _count(
            connection,
            "interaction_final_barrages",
            ("window_id", "debate_id", "barrage_message_id"),
            window_ids | debate_ids | barrage_ids,
        ),
        "barrage_insight_snapshots": _count(
            connection,
            "barrage_insight_snapshots",
            ("id", "window_id", "debate_id"),
            insight_ids | window_ids | debate_ids,
        ),
        "barrage_insight_items": _count(
            connection,
            "barrage_insight_items",
            ("snapshot_id", "window_id", "debate_id"),
            insight_ids | window_ids | debate_ids,
        ),
        "barrage_insight_assignments": _count(
            connection,
            "barrage_insight_assignments",
            ("snapshot_id", "window_id", "debate_id", "barrage_message_id"),
            insight_ids | window_ids | debate_ids | barrage_ids,
        ),
        "civilization_reports": _count(
            connection,
            "civilization_reports",
            ("id", "debate_id"),
            report_ids | debate_ids,
        ),
        "civilization_report_revisions": _count(
            connection,
            "civilization_report_revisions",
            ("id", "report_id", "debate_id", "insight_snapshot_id"),
            revision_ids | report_ids | debate_ids | insight_ids,
        ),
        "civilization_report_current_success": _count(
            connection,
            "civilization_report_current_success",
            ("report_id", "revision_id", "debate_id"),
            report_ids | revision_ids | debate_ids,
        ),
        "jobs": _count(
            connection,
            "jobs",
            ("debate_id", "turn_id", "insight_snapshot_id", "report_revision_id"),
            debate_ids | turn_ids | insight_ids | revision_ids,
        ),
        "provider_export_confirmations": _count(
            connection, "provider_export_confirmations", ("manifest_id",), manifest_ids
        ),
        "provider_export_manifests": _count(
            connection, "provider_export_manifests", ("id",), manifest_ids
        ),
        "provider_operations": _count(connection, "provider_operations", ("id",), operation_ids),
        "provider_reservations": _count(
            connection, "provider_reservations", ("operation_id",), operation_ids
        ),
        "provider_scope_budgets": _count(
            connection, "provider_scope_budgets", ("scope_id",), budget_scopes
        ),
        "embedding_accepted_stages": _count(
            connection, "embedding_accepted_stages", ("operation_id",), operation_ids
        ),
        "embedding_accepted_vectors": _count(
            connection, "embedding_accepted_vectors", ("operation_id",), operation_ids
        ),
        "llm_accepted_stages": _count(
            connection,
            "llm_accepted_stages",
            ("operation_id", "turn_id"),
            operation_ids | turn_ids,
        ),
        "llm_recovery_inputs": _count(
            connection,
            "llm_recovery_inputs",
            ("operation_id", "turn_id"),
            operation_ids | turn_ids,
        ),
        "demo_acceptance_runs": _count(connection, "demo_acceptance_runs", ("id",), run_ids),
        "audit_logs": _count(connection, "audit_logs", ("id",), audit_log_ids),
        "idempotency_records": _count(connection, "idempotency_records", ("id",), idempotency_ids),
        "file_references": _count(
            connection,
            "file_references",
            ("id", "owner_id"),
            file_reference_ids | owner_ids,
        ),
        "file_operations": _count(
            connection,
            "file_operations",
            ("id", "entity_id"),
            file_operation_ids | owner_ids,
        ),
        "stored_files": _count(connection, "stored_files", ("id",), stored_file_ids),
    }
    preserved_counts = {
        table: int(connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
        for table in PRESERVED_TABLES
        if table in _table_names(connection)
    }
    return CleanupPlan(
        debate_ids=frozenset(debate_ids),
        participant_ids=frozenset(participant_ids),
        turn_ids=frozenset(turn_ids),
        window_ids=frozenset(window_ids),
        barrage_ids=frozenset(barrage_ids),
        report_ids=frozenset(report_ids),
        revision_ids=frozenset(revision_ids),
        insight_ids=frozenset(insight_ids),
        manifest_ids=frozenset(manifest_ids),
        manifest_hashes=frozenset(manifest_hashes),
        operation_ids=frozenset(operation_ids),
        operation_scopes=frozenset(operation_scopes),
        run_ids=frozenset(run_ids),
        audit_log_ids=frozenset(audit_log_ids),
        idempotency_ids=frozenset(idempotency_ids),
        file_reference_ids=frozenset(file_reference_ids),
        file_operation_ids=frozenset(file_operation_ids),
        cleanup_journal_ids=frozenset(cleanup_journal_ids),
        stored_file_ids=frozenset(stored_file_ids),
        file_paths=tuple(file_paths_by_string.values()),
        directory_paths=tuple(directory_paths_by_string.values()),
        table_counts=target_counts,
        preserved_counts=preserved_counts,
        schema_head=schema_head,
        file_bytes=file_bytes,
    )


def inspect_cleanup(database_path: Path, data_root: Path) -> CleanupPlan:
    """Read-only schema/target inspection used by the dry-run CLI and tests."""

    database, root = _validate_paths(database_path, data_root)
    connection = _connect(database, read_only=True)
    try:
        schema_head = _validate_schema(connection)
        return _build_plan(connection, root, schema_head)
    finally:
        connection.close()


def _delete_any(
    connection: sqlite3.Connection,
    table: str,
    columns: Sequence[str],
    values: Iterable[str],
) -> int:
    clause, params = _in(values)
    if not params:
        return 0
    predicate = " OR ".join(f"{column} IN ({clause})" for column in columns)
    cursor = connection.execute(f"DELETE FROM {table} WHERE {predicate}", params * len(columns))
    return max(0, cursor.rowcount)


def _drop_guard_and_get_sql(connection: sqlite3.Connection) -> str:
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?", (DELETE_GUARD,)
    ).fetchone()
    if row is None or not isinstance(row[0], str):
        raise CleanupError("trigger_definition_unexpected")
    original = str(row[0])
    expected = _TRIGGER_EXPECTATIONS[DELETE_GUARD]
    if _normalise_sql(original) != _normalise_sql(expected):
        raise CleanupError("trigger_definition_unexpected")
    connection.execute(f'DROP TRIGGER "{DELETE_GUARD}"')
    return original


def _restore_guard(connection: sqlite3.Connection, original_sql: str) -> None:
    connection.execute(original_sql)
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?", (DELETE_GUARD,)
    ).fetchone()
    if row is None or _normalise_sql(str(row[0])) != _normalise_sql(original_sql):
        raise CleanupError("trigger_restore_failed")


def _remaining_target_counts(connection: sqlite3.Connection, plan: CleanupPlan) -> dict[str, int]:
    values = {
        "debates": (("id",), plan.debate_ids),
        "debate_participants": (
            ("id", "debate_id"),
            plan.participant_ids | plan.debate_ids,
        ),
        "debate_turns": (("id", "debate_id"), plan.turn_ids | plan.debate_ids),
        "turn_sources": (
            ("turn_id", "participant_id"),
            plan.turn_ids | plan.participant_ids,
        ),
        "position_history": (
            ("turn_id", "participant_id"),
            plan.turn_ids | plan.participant_ids,
        ),
        "playback_states": (("debate_id",), plan.debate_ids),
        "debate_events": (("debate_id",), plan.debate_ids),
        "classroom_interaction_windows": (
            ("id", "debate_id"),
            plan.window_ids | plan.debate_ids,
        ),
        "votes": (
            ("window_id", "debate_id", "participant_id"),
            plan.window_ids | plan.debate_ids | plan.participant_ids,
        ),
        "barrage_messages": (
            ("id", "window_id", "debate_id", "turn_id"),
            plan.barrage_ids | plan.window_ids | plan.debate_ids | plan.turn_ids,
        ),
        "interaction_final_vote_counts": (
            ("window_id", "debate_id", "participant_id"),
            plan.window_ids | plan.debate_ids | plan.participant_ids,
        ),
        "interaction_final_barrages": (
            ("window_id", "debate_id", "barrage_message_id"),
            plan.window_ids | plan.debate_ids | plan.barrage_ids,
        ),
        "barrage_insight_snapshots": (
            ("id", "window_id", "debate_id"),
            plan.insight_ids | plan.window_ids | plan.debate_ids,
        ),
        "barrage_insight_items": (
            ("snapshot_id", "window_id", "debate_id"),
            plan.insight_ids | plan.window_ids | plan.debate_ids,
        ),
        "barrage_insight_assignments": (
            ("snapshot_id", "window_id", "debate_id", "barrage_message_id"),
            plan.insight_ids | plan.window_ids | plan.debate_ids | plan.barrage_ids,
        ),
        "civilization_reports": (
            ("id", "debate_id"),
            plan.report_ids | plan.debate_ids,
        ),
        "civilization_report_revisions": (
            ("id", "report_id", "debate_id", "insight_snapshot_id"),
            plan.revision_ids | plan.report_ids | plan.debate_ids | plan.insight_ids,
        ),
        "civilization_report_current_success": (
            ("report_id", "revision_id", "debate_id"),
            plan.report_ids | plan.revision_ids | plan.debate_ids,
        ),
        "jobs": (
            ("debate_id", "turn_id", "insight_snapshot_id", "report_revision_id"),
            plan.debate_ids | plan.turn_ids | plan.insight_ids | plan.revision_ids,
        ),
        "provider_export_confirmations": (("manifest_id",), plan.manifest_ids),
        "provider_export_manifests": (("id",), plan.manifest_ids),
        "provider_operations": (("id",), plan.operation_ids),
        "provider_reservations": (("operation_id",), plan.operation_ids),
        "provider_scope_budgets": (
            ("scope_id",),
            plan.operation_scopes
            | plan.debate_ids
            | plan.turn_ids
            | plan.window_ids
            | plan.report_ids
            | plan.revision_ids
            | plan.insight_ids,
        ),
        "embedding_accepted_stages": (("operation_id",), plan.operation_ids),
        "embedding_accepted_vectors": (("operation_id",), plan.operation_ids),
        "llm_accepted_stages": (
            ("operation_id", "turn_id"),
            plan.operation_ids | plan.turn_ids,
        ),
        "llm_recovery_inputs": (
            ("operation_id", "turn_id"),
            plan.operation_ids | plan.turn_ids,
        ),
        "demo_acceptance_runs": (("id",), plan.run_ids),
        "audit_logs": (("id",), plan.audit_log_ids),
        "idempotency_records": (("id",), plan.idempotency_ids),
        "file_references": (
            ("id", "owner_id"),
            plan.file_reference_ids
            | plan.debate_ids
            | plan.participant_ids
            | plan.turn_ids
            | plan.window_ids
            | plan.barrage_ids
            | plan.report_ids
            | plan.revision_ids
            | plan.insight_ids
            | plan.file_operation_ids,
        ),
        "file_operations": (
            ("id", "entity_id"),
            plan.file_operation_ids
            | plan.debate_ids
            | plan.turn_ids
            | plan.window_ids
            | plan.report_ids
            | plan.revision_ids
            | plan.insight_ids,
        ),
        "stored_files": (("id",), plan.stored_file_ids),
    }
    return {
        table: _count(connection, table, columns, ids)
        for table, (columns, ids) in values.items()
        if _count(connection, table, columns, ids)
    }


def _apply_plan(connection: sqlite3.Connection, plan: CleanupPlan) -> None:
    guard_sql: str | None = None
    try:
        if plan.table_counts.get("llm_recovery_inputs", 0):
            guard_sql = _drop_guard_and_get_sql(connection)

        _delete_any(
            connection,
            "interaction_final_barrages",
            ("window_id", "debate_id", "barrage_message_id"),
            plan.window_ids | plan.debate_ids | plan.barrage_ids,
        )
        _delete_any(
            connection,
            "interaction_final_vote_counts",
            ("window_id", "debate_id", "participant_id"),
            plan.window_ids | plan.debate_ids | plan.participant_ids,
        )
        _delete_any(
            connection,
            "barrage_insight_assignments",
            ("snapshot_id", "window_id", "debate_id", "barrage_message_id"),
            plan.insight_ids | plan.window_ids | plan.debate_ids | plan.barrage_ids,
        )
        _delete_any(
            connection,
            "barrage_insight_items",
            ("snapshot_id", "window_id", "debate_id"),
            plan.insight_ids | plan.window_ids | plan.debate_ids,
        )
        _delete_any(
            connection,
            "jobs",
            ("debate_id", "turn_id", "insight_snapshot_id", "report_revision_id"),
            plan.debate_ids | plan.turn_ids | plan.insight_ids | plan.revision_ids,
        )
        _delete_any(
            connection,
            "llm_accepted_stages",
            ("operation_id", "turn_id"),
            plan.operation_ids | plan.turn_ids,
        )
        _delete_any(
            connection,
            "llm_recovery_inputs",
            ("operation_id", "turn_id"),
            plan.operation_ids | plan.turn_ids,
        )
        _delete_any(
            connection,
            "embedding_accepted_vectors",
            ("operation_id",),
            plan.operation_ids,
        )
        _delete_any(
            connection,
            "embedding_accepted_stages",
            ("operation_id",),
            plan.operation_ids,
        )
        _delete_any(connection, "provider_reservations", ("operation_id",), plan.operation_ids)
        _delete_any(connection, "provider_operations", ("id",), plan.operation_ids)
        if plan.run_ids:
            clause, params = _in(plan.run_ids)
            # Published knowledge retains its embedding provenance even when
            # the temporary acceptance run that first built it is removed.
            connection.execute(
                "UPDATE provider_operations SET acceptance_run_id=NULL, call_no=NULL "
                f"WHERE acceptance_run_id IN ({clause})",
                params,
            )
        # DemoAcceptanceRun.report_revision_id is RESTRICT; remove the run
        # ledger after its provider operations and before its report revision.
        _delete_any(connection, "demo_acceptance_runs", ("id",), plan.run_ids)
        _delete_any(
            connection,
            "civilization_report_current_success",
            ("report_id", "revision_id", "debate_id"),
            plan.report_ids | plan.revision_ids | plan.debate_ids,
        )
        _delete_any(
            connection,
            "civilization_report_revisions",
            ("id", "report_id", "debate_id", "insight_snapshot_id"),
            plan.revision_ids | plan.report_ids | plan.debate_ids | plan.insight_ids,
        )
        _delete_any(
            connection,
            "civilization_reports",
            ("id", "debate_id"),
            plan.report_ids | plan.debate_ids,
        )
        _delete_any(
            connection,
            "barrage_insight_snapshots",
            ("id", "window_id", "debate_id"),
            plan.insight_ids | plan.window_ids | plan.debate_ids,
        )
        _delete_any(
            connection,
            "votes",
            ("window_id", "debate_id", "participant_id"),
            plan.window_ids | plan.debate_ids | plan.participant_ids,
        )
        _delete_any(
            connection,
            "barrage_messages",
            ("id", "window_id", "debate_id", "turn_id"),
            plan.barrage_ids | plan.window_ids | plan.debate_ids | plan.turn_ids,
        )
        _delete_any(
            connection,
            "classroom_interaction_windows",
            ("id", "debate_id"),
            plan.window_ids | plan.debate_ids,
        )
        _delete_any(
            connection,
            "turn_sources",
            ("turn_id", "participant_id"),
            plan.turn_ids | plan.participant_ids,
        )
        _delete_any(
            connection,
            "position_history",
            ("turn_id", "participant_id"),
            plan.turn_ids | plan.participant_ids,
        )
        _delete_any(
            connection,
            "provider_export_confirmations",
            ("manifest_id",),
            plan.manifest_ids,
        )
        _delete_any(connection, "provider_export_manifests", ("id",), plan.manifest_ids)
        _delete_any(
            connection,
            "provider_scope_budgets",
            ("scope_id",),
            plan.operation_scopes
            | plan.debate_ids
            | plan.turn_ids
            | plan.window_ids
            | plan.report_ids
            | plan.revision_ids
            | plan.insight_ids,
        )
        _delete_any(connection, "playback_states", ("debate_id",), plan.debate_ids)
        _delete_any(connection, "debate_events", ("debate_id",), plan.debate_ids)
        _delete_any(
            connection,
            "debate_turns",
            ("id", "debate_id"),
            plan.turn_ids | plan.debate_ids,
        )
        _delete_any(
            connection,
            "debate_participants",
            ("id", "debate_id"),
            plan.participant_ids | plan.debate_ids,
        )
        _delete_any(
            connection,
            "file_references",
            ("id", "owner_id"),
            plan.file_reference_ids
            | plan.debate_ids
            | plan.participant_ids
            | plan.turn_ids
            | plan.window_ids
            | plan.barrage_ids
            | plan.report_ids
            | plan.revision_ids
            | plan.insight_ids
            | plan.file_operation_ids,
        )
        _delete_any(
            connection,
            "file_operations",
            ("id", "entity_id"),
            plan.file_operation_ids
            | plan.debate_ids
            | plan.turn_ids
            | plan.window_ids
            | plan.report_ids
            | plan.revision_ids
            | plan.insight_ids,
        )
        _delete_any(connection, "idempotency_records", ("id",), plan.idempotency_ids)
        # Audit rows have no FK by design.  Remove only the rows whose
        # explicit debate_id was in this plan; account/course audit rows are
        # intentionally preserved.
        _delete_any(connection, "audit_logs", ("id",), plan.audit_log_ids)
        if plan.debate_ids:
            clause, params = _in(plan.debate_ids)
            connection.execute(
                "UPDATE courses SET current_audio_debate_id=NULL "
                f"WHERE current_audio_debate_id IN ({clause})",
                params,
            )
        _delete_any(connection, "debates", ("id",), plan.debate_ids)
        _delete_any(connection, "stored_files", ("id",), plan.stored_file_ids)

        if guard_sql is not None:
            _restore_guard(connection, guard_sql)
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise CleanupError("foreign_key_violations_after")
        remaining = _remaining_target_counts(connection, plan)
        if remaining:
            raise CleanupError("target_rows_remaining")
    except Exception:  # noqa: TRY203
        # The caller rolls the transaction back.  A rolled-back DROP TRIGGER
        # restores the original guard together with every row mutation.
        raise


def _move_files(plan: CleanupPlan, data_root: Path) -> tuple[Path | None, list[tuple[Path, Path]]]:
    existing = [path for path in plan.file_paths if path.exists()]
    if not existing:
        return None, []
    quarantine = Path(tempfile.mkdtemp(prefix=".maya-debate-cleanup-", dir=data_root))
    moved: list[tuple[Path, Path]] = []
    try:
        for index, source in enumerate(existing):
            if source.is_symlink() or not source.is_file():
                raise CleanupError("stored_file_symlink_refused")
            destination = quarantine / f"{index:04d}-{source.name}"
            os.replace(source, destination)
            moved.append((source, destination))
    except Exception:
        for source, destination in reversed(moved):
            if destination.exists():
                os.replace(destination, source)
        quarantine.rmdir()
        raise
    return quarantine, moved


def _finish_file_quarantine(quarantine: Path | None, moved: Sequence[tuple[Path, Path]]) -> None:
    if quarantine is None:
        return
    for _source, destination in moved:
        if destination.exists():
            destination.unlink()
    quarantine.rmdir()


def _remove_empty_debate_directories(paths: Sequence[Path]) -> None:
    """Remove only the exact target audio directories after DB commit."""

    for path in sorted(paths, key=lambda item: len(item.parts), reverse=True):
        if path.is_symlink() or not path.exists():
            continue
        if not path.is_dir():
            continue
        # rmdir never follows children or recursively deletes an unexpected
        # entry.  A concurrent/new artifact therefore remains for a later
        # offline pass instead of widening this cleanup boundary.
        try:
            path.rmdir()
        except OSError:
            continue


def _restore_files(quarantine: Path | None, moved: Sequence[tuple[Path, Path]]) -> None:
    if quarantine is None:
        return
    for source, destination in reversed(moved):
        if destination.exists():
            os.replace(destination, source)
    if quarantine.exists():
        quarantine.rmdir()


def apply_cleanup(database_path: Path, data_root: Path, *, offline: bool = False) -> CleanupPlan:
    """Apply one bounded cleanup transaction after an explicit offline gate."""

    if not offline:
        raise CleanupError("offline_confirmation_required")

    database, root = _validate_paths(database_path, data_root)
    connection = _connect(database, read_only=False)
    quarantine: Path | None = None
    moved: list[tuple[Path, Path]] = []
    try:
        connection.execute("BEGIN IMMEDIATE")
        schema_head = _validate_schema(connection)
        plan = _build_plan(connection, root, schema_head)
        quarantine, moved = _move_files(plan, root)
        try:
            _apply_plan(connection, plan)
            connection.commit()
        except Exception:
            connection.rollback()
            _restore_files(quarantine, moved)
            raise
        _finish_file_quarantine(quarantine, moved)
        _remove_empty_debate_directories(plan.directory_paths)
        # A separate read-only connection proves that the guard survived the
        # commit and that no file cleanup code can hide a trigger mutation.
        verify = _connect(database, read_only=True)
        try:
            _validate_schema(verify)
        finally:
            verify.close()
        return plan
    finally:
        connection.close()


def audit_payload(plan: CleanupPlan, *, mode: str, status: str) -> dict[str, object]:
    return {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "status": status,
        "mode": mode,
        "schema_head": plan.schema_head,
        "app_must_be_stopped": True,
        "debates_seen": len(plan.debate_ids),
        "planned_turns": plan.table_counts.get("debate_turns", 0),
        "planned_classroom_reports": plan.table_counts.get("civilization_reports", 0),
        "target_counts": dict(plan.table_counts),
        "cleanup_journal_count": len(plan.cleanup_journal_ids),
        "preserved_counts_before": dict(plan.preserved_counts),
        "file_count": plan.file_count,
        "directory_count": plan.directory_count,
        "file_bytes": plan.file_bytes,
        "trigger_guard_restored": True,
        "errors": [],
    }


def _error_payload(code: str, *, mode: str) -> dict[str, object]:
    return {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "status": "blocked",
        "mode": mode,
        "app_must_be_stopped": True,
        "trigger_guard_restored": False,
        "errors": [code],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--data-root", type=Path, help="exact runtime data directory")
    parser.add_argument("--database", type=Path, help="SQLite DB path; required with --apply")
    parser.add_argument("--apply", action="store_true", help="apply the bounded cleanup")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="confirm the project app/container is stopped before --apply",
    )
    args = parser.parse_args(argv)
    mode = "apply" if args.apply else "dry_run"
    if args.apply and not args.offline:
        print(
            json.dumps(
                _error_payload("offline_confirmation_required", mode=mode),
                sort_keys=True,
            )
        )
        return 2
    if args.apply and args.database is None:
        print(json.dumps(_error_payload("database_path_required", mode=mode), sort_keys=True))
        return 2
    root = args.root.resolve()
    data_root = args.data_root or root / "data"
    database = args.database or data_root / "maya.sqlite3"
    try:
        if args.apply:
            plan = apply_cleanup(database, data_root, offline=args.offline)
            payload = audit_payload(plan, mode=mode, status="applied")
        else:
            plan = inspect_cleanup(database, data_root)
            payload = audit_payload(
                plan,
                mode=mode,
                status="dry_run" if plan.has_targets else "dry_run_clean",
            )
    except CleanupError as exc:
        print(json.dumps(_error_payload(exc.code, mode=mode), sort_keys=True))
        return 1
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
