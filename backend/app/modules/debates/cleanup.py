"""Teacher-scoped cleanup of Debate media and runtime rows.

This module is deliberately smaller than the offline historical cleanup
command.  It is the online boundary for the two teacher actions that need to
operate on one Debate at a time:

* ``delete_voice`` removes retained audio while leaving the validated text,
  retrieval receipts, source rows, paragraph fences and final-input snapshot
  untouched.  The Debate cancellation generation is intentionally unchanged;
  revision and playback control version are the media fences.
* ``delete_all`` cancels and removes one Debate graph regardless of playback
  state or a stale list revision. The SQLite writer transaction fences scoped
  deletion and trigger restoration while other classrooms remain untouched.

The service owns its short transaction because physical files are staged in a
private quarantine before the transaction commits.  A failed transaction puts
the files back.  A successful commit finalises the quarantine and removes
only exact paths in the Debate audio, audio-swap staging, or Debate report
output locations.  No provider response, student message, nickname, or raw
path is returned in a result.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import logging
import os
import re
import secrets
import shutil
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import delete, false, select, text, true, update
from sqlalchemy.orm import Session
from sqlalchemy.schema import Table

from app.core.errors import PlatformError, conflict, idempotency_conflict, invalid_state, not_found
from app.core.models import (
    Base,
    FileOperation,
    FileReference,
    IdempotencyRecord,
    Job,
    StoredFile,
)
from app.core.sqlutil import foreign_keys_ok
from app.modules.debates import models as _debate_models
from app.modules.debates.models import Debate, DebateTurn, PlaybackState
from app.modules.debates.setup.service import require_teacher_course
from app.modules.interactions import models as _interaction_models
from app.modules.reports import models as _report_models

del _debate_models, _interaction_models, _report_models

LOGGER = logging.getLogger(__name__)

_UUID_COMPONENT = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_RECOVERY_DELETE_TRIGGER = "trg_llm_recovery_inputs_immutable_delete"
_RECOVERY_UPDATE_TRIGGER = "trg_llm_recovery_inputs_immutable_update"
_CLEANUP_VOICE_OPERATION = "debate_cleanup_voice_v1"
_CLEANUP_ALL_OPERATION = "debate_cleanup_all_v1"
_CLEANUP_OPERATIONS = frozenset({_CLEANUP_VOICE_OPERATION, _CLEANUP_ALL_OPERATION})
_EXPECTED_RECOVERY_DELETE_TRIGGER_SQL = (
    "CREATE TRIGGER trg_llm_recovery_inputs_immutable_delete BEFORE DELETE ON "
    "llm_recovery_inputs BEGIN SELECT RAISE(ABORT, 'llm recovery input is immutable'); END"
)
_ACTIVE_PROVIDER_STATES = frozenset(
    {"prepared", "reserved", "sending", "accepted", "acceptance_unknown"}
)
_DEBATE_IDEMPOTENCY_OPERATIONS = frozenset(
    {
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
        "deleteVoice",
        "deleteAll",
        "rebirthDebate",
        "remakeDebate",
    }
)


class DebateCleanupError(PlatformError):
    """Internal cleanup error for unsafe paths or incomplete setup."""

    def __init__(self, code: str) -> None:
        super().__init__(
            code,
            "The Debate cleanup could not be completed safely.",
            409,
        )
        self.code = code
        self.args = (code,)


@dataclass(frozen=True)
class DeleteVoiceResult:
    """Sanitised outcome of one media-only deletion."""

    debate_id: str
    revision: int
    control_version: int
    cancellation_generation: int
    cleared_turn_count: int
    interrupted_job_count: int
    deleted_file_count: int
    missing_file_count: int
    pending_file_count: int
    regenerable_turn_ids: tuple[str, ...]
    retained_public_turn_count: int
    runtime_cancelled: bool

    @property
    def cleanup_status(self) -> str:
        return "complete" if self.pending_file_count == 0 and self.runtime_cancelled else "pending"

    def to_public_dict(self) -> dict[str, Any]:
        """Return a wire-safe summary with no source/provider content."""

        return {
            "debate_id": self.debate_id,
            "revision": self.revision,
            "control_version": self.control_version,
            "cancellation_generation": self.cancellation_generation,
            "cleared_turn_count": self.cleared_turn_count,
            "interrupted_job_count": self.interrupted_job_count,
            "deleted_file_count": self.deleted_file_count,
            "missing_file_count": self.missing_file_count,
            "pending_file_count": self.pending_file_count,
            "regenerable_turn_ids": list(self.regenerable_turn_ids),
            "retained_public_turn_count": self.retained_public_turn_count,
            "runtime_cancelled": self.runtime_cancelled,
            "cleanup_status": self.cleanup_status,
        }

    @classmethod
    def from_public_dict(cls, value: Mapping[str, Any]) -> DeleteVoiceResult:
        try:
            return cls(
                debate_id=str(value["debate_id"]),
                revision=int(value["revision"]),
                control_version=int(value["control_version"]),
                cancellation_generation=int(value["cancellation_generation"]),
                cleared_turn_count=int(value["cleared_turn_count"]),
                interrupted_job_count=int(value["interrupted_job_count"]),
                deleted_file_count=int(value["deleted_file_count"]),
                missing_file_count=int(value["missing_file_count"]),
                pending_file_count=int(value["pending_file_count"]),
                regenerable_turn_ids=tuple(str(item) for item in value["regenerable_turn_ids"]),
                retained_public_turn_count=int(value["retained_public_turn_count"]),
                runtime_cancelled=bool(value["runtime_cancelled"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise invalid_state("The Debate cleanup idempotency receipt is invalid.") from exc


@dataclass(frozen=True)
class DeleteAllResult:
    """Sanitised outcome of one Debate graph deletion."""

    debate_id: str
    revision: int
    control_version: int
    cancellation_generation: int
    interrupted_job_count: int
    deleted_rows: Mapping[str, int]
    deleted_file_count: int
    missing_file_count: int
    pending_file_count: int
    runtime_cancelled: bool

    @property
    def cleanup_status(self) -> str:
        return "complete" if self.pending_file_count == 0 and self.runtime_cancelled else "pending"

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "debate_id": self.debate_id,
            "revision": self.revision,
            "control_version": self.control_version,
            "cancellation_generation": self.cancellation_generation,
            "interrupted_job_count": self.interrupted_job_count,
            "deleted_rows": dict(self.deleted_rows),
            "deleted_file_count": self.deleted_file_count,
            "missing_file_count": self.missing_file_count,
            "pending_file_count": self.pending_file_count,
            "runtime_cancelled": self.runtime_cancelled,
            "cleanup_status": self.cleanup_status,
        }

    @classmethod
    def from_public_dict(cls, value: Mapping[str, Any]) -> DeleteAllResult:
        try:
            rows = value["deleted_rows"]
            if not isinstance(rows, Mapping):
                raise TypeError("deleted_rows must be a mapping")
            return cls(
                debate_id=str(value["debate_id"]),
                revision=int(value["revision"]),
                control_version=int(value["control_version"]),
                cancellation_generation=int(value["cancellation_generation"]),
                interrupted_job_count=int(value["interrupted_job_count"]),
                deleted_rows={str(key): int(item) for key, item in rows.items()},
                deleted_file_count=int(value["deleted_file_count"]),
                missing_file_count=int(value["missing_file_count"]),
                pending_file_count=int(value["pending_file_count"]),
                runtime_cancelled=bool(value["runtime_cancelled"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise invalid_state("The Debate cleanup idempotency receipt is invalid.") from exc


@dataclass
class _DebateGraph:
    debate_id: str
    course_id: str
    participant_ids: set[str] = field(default_factory=set)
    turn_ids: set[str] = field(default_factory=set)
    window_ids: set[str] = field(default_factory=set)
    barrage_ids: set[str] = field(default_factory=set)
    insight_ids: set[str] = field(default_factory=set)
    insight_item_ids: set[str] = field(default_factory=set)
    report_ids: set[str] = field(default_factory=set)
    revision_ids: set[str] = field(default_factory=set)
    manifest_ids: set[str] = field(default_factory=set)
    manifest_hashes: set[str] = field(default_factory=set)
    run_ids: set[str] = field(default_factory=set)
    operation_ids: set[str] = field(default_factory=set)
    operation_scopes: set[str] = field(default_factory=set)
    file_reference_ids: set[str] = field(default_factory=set)
    file_operation_ids: set[str] = field(default_factory=set)
    stored_file_ids: set[str] = field(default_factory=set)
    idempotency_ids: set[str] = field(default_factory=set)
    audit_log_ids: set[str] = field(default_factory=set)
    file_paths: dict[str, Path] = field(default_factory=dict)
    directory_paths: dict[str, Path] = field(default_factory=dict)

    @property
    def owner_ids(self) -> set[str]:
        return (
            {self.debate_id}
            | self.participant_ids
            | self.turn_ids
            | self.window_ids
            | self.barrage_ids
            | self.insight_ids
            | self.insight_item_ids
            | self.report_ids
            | self.revision_ids
            | self.manifest_ids
            | self.file_operation_ids
        )

    @property
    def scope_ids(self) -> set[str]:
        return (
            {self.debate_id}
            | self.participant_ids
            | self.turn_ids
            | self.window_ids
            | self.barrage_ids
            | self.insight_ids
            | self.report_ids
            | self.revision_ids
        )


@dataclass
class _FileQuarantine:
    root: Path
    quarantine: Path | None
    moved: list[tuple[Path, Path]]
    directory_paths: tuple[Path, ...]
    missing_count: int = 0
    journal_ids: tuple[str, ...] = ()

    @property
    def moved_count(self) -> int:
        return len(self.moved)

    @property
    def quarantine_relative_path(self) -> str | None:
        if self.quarantine is None:
            return None
        return self.quarantine.relative_to(self.root).as_posix()


def _table(name: str) -> Table:
    table = Base.metadata.tables.get(name)
    if table is None:  # pragma: no cover - migration/schema preflight catches this
        raise DebateCleanupError("cleanup_schema_unavailable")
    return table


def _values(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(value) for value in values if value is not None))


def _ids(db: Session, table_name: str, column_name: str, values: Iterable[str]) -> set[str]:
    values_tuple = _values(values)
    if not values_tuple:
        return set()
    table = _table(table_name)
    column = table.c[column_name]
    return {
        str(value)
        for value in db.scalars(select(column).where(column.in_(values_tuple))).all()
        if value is not None
    }


def _children(
    db: Session,
    table_name: str,
    child_column: str,
    parent_column: str,
    parent_values: Iterable[str],
) -> set[str]:
    """Select child identities by a separate parent column."""

    values_tuple = _values(parent_values)
    if not values_tuple:
        return set()
    table = _table(table_name)
    return {
        str(value)
        for value in db.scalars(
            select(table.c[child_column]).where(table.c[parent_column].in_(values_tuple))
        ).all()
        if value is not None
    }


def _rows(db: Session, table_name: str, *predicates: Any) -> list[Any]:
    table = _table(table_name)
    return list(db.execute(select(table).where(*predicates)).mappings().all())


def _count(db: Session, table_name: str) -> int:
    table = _table(table_name)
    value = db.execute(select(text("count(*)")).select_from(table)).scalar_one()
    return int(value or 0)


def _safe_component(value: str, label: str) -> str:
    if not isinstance(value, str) or not _UUID_COMPONENT.fullmatch(value):
        raise DebateCleanupError(f"{label}_invalid")
    return value


def _safe_root(data_root: Path | str | None) -> Path:
    if data_root is None:
        raise DebateCleanupError("data_root_required")
    root = Path(data_root).expanduser()
    if root.is_symlink() or not root.exists() or not root.is_dir():
        raise DebateCleanupError("data_root_invalid")
    return root.resolve(strict=True)


def _safe_path(root: Path, relative_path: str, *, directory: bool = False) -> Path:
    """Resolve one lexical path and refuse traversal, links, and type drift."""

    root = root.resolve(strict=True)
    if (
        not isinstance(relative_path, str)
        or not relative_path
        or "\x00" in relative_path
        or "\\" in relative_path
    ):
        raise DebateCleanupError("cleanup_path_invalid")
    pure = PurePosixPath(relative_path)
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        raise DebateCleanupError("cleanup_path_invalid")
    current = root
    for part in pure.parts:
        current = current / part
        if current.is_symlink():
            raise DebateCleanupError("cleanup_path_symlink_refused")
    resolved = current.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise DebateCleanupError("cleanup_path_outside_root") from exc
    if current.exists():
        if directory and not current.is_dir():
            raise DebateCleanupError("cleanup_path_not_directory")
        if not directory and not current.is_file():
            raise DebateCleanupError("cleanup_path_not_regular")
    return current


def _allowed_audio_prefix(course_id: str, debate_id: str) -> str:
    return f"courses/{course_id}/current-debate-audio/{debate_id}/"


def _allowed_staging_prefix(course_id: str, debate_id: str) -> str:
    return f"staging/audio-swap/{course_id}/request/{debate_id}/"


def _path_is_allowed(
    relative_path: str,
    *,
    course_id: str,
    debate_id: str,
    directory: bool,
) -> bool:
    """Keep file cleanup within paths created by Debate playback/reporting."""

    audio = _allowed_audio_prefix(course_id, debate_id)
    staging = _allowed_staging_prefix(course_id, debate_id)
    audio_directory = audio[:-1]
    staging_directory = staging[:-1]
    if (
        relative_path.startswith(audio)
        or relative_path.startswith(staging)
        or (directory and relative_path in {audio_directory, staging_directory})
    ):
        return True
    parts = PurePosixPath(relative_path).parts
    if (
        not directory
        and len(parts) == 6
        and parts[:4] == ("staging", "debate-turn-tts", course_id, debate_id)
        and PurePosixPath(parts[5]).suffix == ".wav"
    ):
        try:
            UUID(parts[4])
            UUID(PurePosixPath(parts[5]).stem)
        except ValueError:
            return False
        return True
    # Reports are currently returned as bytes, but older runtime journals may
    # have materialised one exact Debate-named file.  Permit that file shape
    # without opening the whole reports tree.
    if not directory and len(parts) == 2 and parts[0] == "reports":
        return debate_id in parts[1]
    return False


def _collect_file_path(
    graph: _DebateGraph,
    root: Path,
    relative_path: str,
    *,
    directory: bool,
) -> None:
    if not _path_is_allowed(
        relative_path,
        course_id=graph.course_id,
        debate_id=graph.debate_id,
        directory=directory,
    ):
        raise DebateCleanupError("cleanup_path_not_debate_owned")
    path = _safe_path(root, relative_path, directory=directory)
    if directory:
        graph.directory_paths.setdefault(relative_path, path)
        if not path.exists():
            return
        for child in path.iterdir():
            if child.is_symlink():
                raise DebateCleanupError("cleanup_path_symlink_refused")
            if not child.is_file():
                raise DebateCleanupError("cleanup_path_nested_entry")
            child_relative = child.relative_to(root).as_posix()
            child_path = _safe_path(root, child_relative)
            graph.file_paths.setdefault(child_relative, child_path)
        return
    graph.file_paths.setdefault(relative_path, path)
    if relative_path.startswith(f"staging/debate-turn-tts/{graph.course_id}/{graph.debate_id}/"):
        parts = PurePosixPath(relative_path).parts
        for depth in (5, 4):
            parent = str(PurePosixPath(*parts[:depth]))
            graph.directory_paths.setdefault(parent, _safe_path(root, parent, directory=True))


def _collect_audio_directory(graph: _DebateGraph, root: Path) -> None:
    relative = f"courses/{graph.course_id}/current-debate-audio/{graph.debate_id}"
    _collect_file_path(graph, root, relative, directory=True)


def _narrow_media_graph(db: Session, graph: _DebateGraph, root: Path) -> None:
    """Reduce a full graph to audio rows for Delete Voice."""

    file_operations = _table("file_operations")
    media_operation_rows = (
        db.execute(
            select(file_operations).where(
                file_operations.c.id.in_(tuple(graph.file_operation_ids))
                if graph.file_operation_ids
                else false(),
                file_operations.c.operation_type == "debate_audio_swap",
            )
        )
        .mappings()
        .all()
    )
    graph.file_operation_ids = {str(row["id"]) for row in media_operation_rows}
    refs = _table("file_references")
    media_owner_ids = {graph.debate_id} | graph.turn_ids
    media_ref_rows = (
        db.execute(
            select(refs).where(
                refs.c.owner_id.in_(tuple(media_owner_ids)),
                refs.c.purpose.in_(("audio", "debate_audio", "audio_output")),
            )
        )
        .mappings()
        .all()
    )
    graph.file_reference_ids = {str(row["id"]) for row in media_ref_rows}
    graph.stored_file_ids = {
        str(row["stored_file_id"]) for row in media_ref_rows if row["stored_file_id"] is not None
    }
    if graph.turn_ids:
        turn_table = _table("debate_turns")
        graph.stored_file_ids.update(
            str(value)
            for value in db.scalars(
                select(turn_table.c.audio_file_id).where(turn_table.c.id.in_(tuple(graph.turn_ids)))
            ).all()
            if value is not None
        )
    graph.file_paths.clear()
    graph.directory_paths.clear()
    stored_table = _table("stored_files")
    if graph.stored_file_ids:
        stored_rows = db.execute(
            select(stored_table.c.relative_path).where(
                stored_table.c.id.in_(tuple(graph.stored_file_ids))
            )
        ).all()
        for stored_path_row in stored_rows:
            _collect_file_path(graph, root, str(stored_path_row[0]), directory=False)
    for operation_row in media_operation_rows:
        for column in ("source_relative_path", "target_relative_path", "staging_relative_path"):
            value = operation_row[column]
            if not value:
                continue
            directory = column in {"source_relative_path", "staging_relative_path"}
            _collect_file_path(graph, root, str(value), directory=directory)
    _collect_audio_directory(graph, root)


def _build_graph(
    db: Session,
    debate: Debate,
    root: Path,
    *,
    collect_files: bool = True,
) -> _DebateGraph:
    graph = _DebateGraph(str(debate.id), str(debate.course_id))
    graph.participant_ids = _children(
        db, "debate_participants", "id", "debate_id", {graph.debate_id}
    )
    graph.turn_ids = _children(db, "debate_turns", "id", "debate_id", {graph.debate_id})
    graph.window_ids = _children(
        db, "classroom_interaction_windows", "id", "debate_id", {graph.debate_id}
    )
    graph.barrage_ids = _children(db, "barrage_messages", "id", "debate_id", {graph.debate_id})
    graph.insight_ids = _children(
        db, "barrage_insight_snapshots", "id", "debate_id", {graph.debate_id}
    )
    graph.insight_item_ids = _children(
        db, "barrage_insight_items", "id", "debate_id", {graph.debate_id}
    )
    graph.report_ids = _children(db, "civilization_reports", "id", "debate_id", {graph.debate_id})
    graph.revision_ids = _children(
        db, "civilization_report_revisions", "id", "debate_id", {graph.debate_id}
    )
    if graph.report_ids:
        graph.revision_ids.update(
            _children(db, "civilization_report_revisions", "id", "report_id", graph.report_ids)
        )
    graph.insight_ids.update(
        _children(
            db,
            "civilization_report_revisions",
            "insight_snapshot_id",
            "id",
            graph.revision_ids,
        )
    )
    if graph.insight_ids:
        graph.insight_item_ids.update(
            _children(db, "barrage_insight_items", "id", "snapshot_id", graph.insight_ids)
        )

    manifest_table = _table("provider_export_manifests")
    manifest_predicates = [manifest_table.c.debate_id == graph.debate_id]
    if graph.turn_ids:
        manifest_predicates.append(manifest_table.c.turn_id.in_(tuple(graph.turn_ids)))
    manifest_rows = (
        db.execute(select(manifest_table).where(_or_all(manifest_predicates))).mappings().all()
    )
    graph.manifest_ids = {str(row["id"]) for row in manifest_rows}
    graph.manifest_hashes = {str(row["manifest_hash"]) for row in manifest_rows}

    run_table = _table("demo_acceptance_runs")
    run_predicates = [run_table.c.debate_id == graph.debate_id]
    if graph.revision_ids:
        run_predicates.append(run_table.c.report_revision_id.in_(tuple(graph.revision_ids)))
    graph.run_ids = {
        str(value)
        for value in db.scalars(select(run_table.c.id).where(_or_all(run_predicates))).all()
        if value is not None
    }

    owner_ids = graph.owner_ids
    file_operation_table = _table("file_operations")
    file_operation_predicates: list[Any] = [
        file_operation_table.c.entity_id.in_(tuple(owner_ids)) if owner_ids else false(),
        file_operation_table.c.old_audio_debate_id == graph.debate_id,
        file_operation_table.c.new_debate_id == graph.debate_id,
    ]
    file_operation_rows = (
        db.execute(
            select(file_operation_table).where(
                (
                    file_operation_predicates[0]
                    | file_operation_predicates[1]
                    | file_operation_predicates[2]
                ),
                file_operation_table.c.operation_type.not_in(tuple(_CLEANUP_OPERATIONS)),
            )
        )
        .mappings()
        .all()
    )
    graph.file_operation_ids = {str(row["id"]) for row in file_operation_rows}

    file_reference_table = _table("file_references")
    file_reference_predicates = [
        file_reference_table.c.owner_id.in_(tuple(owner_ids)) if owner_ids else false(),
    ]
    if graph.file_operation_ids:
        file_reference_predicates.append(
            file_reference_table.c.owner_id.in_(tuple(graph.file_operation_ids))
        )
    file_reference_rows = (
        db.execute(select(file_reference_table).where(_or_all(file_reference_predicates)))
        .mappings()
        .all()
    )
    graph.file_reference_ids = {str(row["id"]) for row in file_reference_rows}
    graph.stored_file_ids.update(
        str(row["stored_file_id"])
        for row in file_reference_rows
        if row["stored_file_id"] is not None
    )
    turn_table = _table("debate_turns")
    graph.stored_file_ids.update(
        str(value)
        for value in db.scalars(
            select(turn_table.c.audio_file_id).where(
                turn_table.c.id.in_(tuple(graph.turn_ids)) if graph.turn_ids else false()
            )
        ).all()
        if value is not None
    )

    # Provider operations are selected by durable Debate scopes, turn/report
    # identities, or Debate-owned manifests.  Acceptance-run ownership alone
    # is insufficient: a shared embedding operation may be included in a
    # DemoAcceptanceRun and must survive with its run association detached.
    operation_table = _table("provider_operations")
    operation_predicates: list[Any] = []
    if graph.scope_ids:
        operation_predicates.append(operation_table.c.scope_id.in_(tuple(graph.scope_ids)))
        operation_predicates.append(operation_table.c.logical_item_id.in_(tuple(graph.scope_ids)))
    if graph.manifest_hashes:
        operation_predicates.append(
            operation_table.c.export_manifest_hash.in_(tuple(graph.manifest_hashes))
        )
    if graph.run_ids:
        run_operation_predicate = operation_table.c.acceptance_run_id.in_(tuple(graph.run_ids))
        # A run can carry a shared snapshot embedding operation.  Only the
        # target-scope/manifest rows above are owned by this Debate.
        if operation_predicates:
            operation_predicates.append(
                run_operation_predicate
                & (
                    operation_table.c.scope_id.in_(tuple(graph.scope_ids))
                    | operation_table.c.logical_item_id.in_(tuple(graph.scope_ids))
                    | (
                        operation_table.c.export_manifest_hash.in_(tuple(graph.manifest_hashes))
                        if graph.manifest_hashes
                        else false()
                    )
                )
            )
    if operation_predicates:
        operation_rows = (
            db.execute(
                select(operation_table).where(
                    operation_predicates[0] | operation_predicates[1]
                    if len(operation_predicates) == 2
                    else _or_all(operation_predicates)
                )
            )
            .mappings()
            .all()
        )
    else:
        operation_rows = []
    graph.operation_ids = {str(row["id"]) for row in operation_rows}
    graph.operation_scopes = {
        str(row["scope_id"]) for row in operation_rows if row["scope_id"] is not None
    }

    idem_table = _table("idempotency_records")
    if graph.file_operation_ids:
        graph.idempotency_ids.update(
            str(value)
            for value in db.scalars(
                select(file_operation_table.c.idempotency_record_id).where(
                    file_operation_table.c.id.in_(tuple(graph.file_operation_ids))
                )
            ).all()
            if value is not None
        )
    # The exact Debate UUID in the sanitized response is the only acceptable
    # way to associate an unlinked idempotency row.  We do not table-scan all
    # records or delete a teacher's unrelated account/knowledge claims.
    if graph.debate_id:
        graph.idempotency_ids.update(
            str(value)
            for value in db.scalars(
                select(idem_table.c.id).where(
                    idem_table.c.operation.in_(tuple(_DEBATE_IDEMPOTENCY_OPERATIONS)),
                    idem_table.c.response_json.contains(graph.debate_id),
                )
            ).all()
            if value is not None
        )

    audit_table = _table("audit_logs")
    request_ids = {
        str(row["request_id"]) for row in file_operation_rows if row["request_id"] is not None
    }
    audit_predicates = [audit_table.c.debate_id == graph.debate_id]
    if request_ids:
        audit_predicates.append(audit_table.c.request_id.in_(tuple(request_ids)))
    graph.audit_log_ids = {
        str(value)
        for value in db.scalars(select(audit_table.c.id).where(_or_all(audit_predicates))).all()
        if value is not None
    }

    if collect_files:
        stored_table = _table("stored_files")
        if graph.stored_file_ids:
            stored_rows = (
                db.execute(
                    select(stored_table.c.id, stored_table.c.relative_path).where(
                        stored_table.c.id.in_(tuple(graph.stored_file_ids))
                    )
                )
                .mappings()
                .all()
            )
            # A stored file selected through a target reference is still
            # required to have a runtime-owned path.  Refuse a bad
            # owner/path combination instead of risking a knowledge or voice
            # file.
            for row in stored_rows:
                _collect_file_path(graph, root, str(row["relative_path"]), directory=False)

        for row in file_operation_rows:
            operation_type = str(row["operation_type"] or "")
            for column in (
                "source_relative_path",
                "target_relative_path",
                "staging_relative_path",
            ):
                value = row[column]
                if not value:
                    continue
                relative = str(value)
                directory = operation_type == "debate_audio_swap" and column in {
                    "source_relative_path",
                    "staging_relative_path",
                }
                _collect_file_path(graph, root, relative, directory=directory)

        # The directory is authoritative for orphaned audio files.  This
        # catches files left after a worker crashed between the filesystem move
        # and the DB journal update, without recursing through any other
        # course/debate.
        _collect_audio_directory(graph, root)
    return graph


def _or_all(predicates: Sequence[Any]) -> Any:
    if not predicates:
        return false()
    expression = predicates[0]
    for predicate in predicates[1:]:
        expression = expression | predicate
    return expression


def _load_debate(db: Session, debate_id: str, actor_user_id: str) -> Debate:
    debate = db.get(Debate, str(debate_id))
    if debate is None:
        raise not_found()
    require_teacher_course(db, str(actor_user_id), str(debate.course_id))
    return debate


def _begin_immediate(db: Session) -> None:
    """Take SQLite's writer lock before reading the cleanup graph.

    ``get_db`` normally starts a deferred transaction for authentication and
    route setup.  Cleanup cannot use that snapshot: another writer could
    replace an audio pointer between graph inspection and the CAS.  Rolling
    back the request's read snapshot is safe here because this service is the
    transaction owner, then ``BEGIN IMMEDIATE`` fences the complete read/write
    sequence.  Non-SQLite test engines simply retain their normal transaction.
    """

    db.rollback()
    bind = db.get_bind()
    if getattr(bind.dialect, "name", "") == "sqlite":
        try:
            db.connection().exec_driver_sql("BEGIN IMMEDIATE")
        except Exception as exc:
            raise conflict(
                "cleanup_busy",
                "The Debate cleanup could not acquire its write boundary.",
            ) from exc


def _cleanup_request_hash(
    operation: str,
    actor_user_id: str,
    debate_id: str,
    expected_revision: int,
    expected_control_version: int,
) -> str:
    payload = json.dumps(
        [
            operation,
            str(actor_user_id),
            [str(debate_id)],
            {
                "mode": operation,
                "debate_id": str(debate_id),
                "expected_revision": int(expected_revision),
                "expected_control_version": int(expected_control_version),
            },
        ],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class _IdempotencyClaim:
    record: IdempotencyRecord | None
    request_hash: str
    replay: DeleteVoiceResult | DeleteAllResult | None = None


def _claim_cleanup_idempotency(
    db: Session,
    *,
    operation: str,
    actor_user_id: str,
    debate_id: str,
    expected_revision: int,
    expected_control_version: int,
    key: str | None,
) -> _IdempotencyClaim:
    """Claim/replay one cleanup request inside the writer transaction."""

    request_hash = _cleanup_request_hash(
        operation,
        actor_user_id,
        debate_id,
        expected_revision,
        expected_control_version,
    )
    if key is None:
        return _IdempotencyClaim(None, request_hash)
    if len(key) < 16:
        raise conflict(
            "idempotency_conflict",
            "Idempotency-Key must contain at least 16 characters.",
        )
    record = db.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.actor_user_id == str(actor_user_id),
            IdempotencyRecord.operation == operation,
            IdempotencyRecord.key == key,
        )
    )
    if record is None:
        now = datetime.now(UTC)
        record = IdempotencyRecord(
            id=str(uuid4()),
            actor_user_id=str(actor_user_id),
            operation=operation,
            key=key,
            request_hash=request_hash,
            state="pending",
            claim_token=secrets.token_urlsafe(32),
            lease_expires_at=now + timedelta(seconds=10),
            created_at=now,
            updated_at=now,
        )
        db.add(record)
        db.flush()
        return _IdempotencyClaim(record, request_hash)
    if record.request_hash != request_hash:
        raise idempotency_conflict()
    if record.state == "completed" and record.response_json:
        try:
            payload = json.loads(record.response_json)
        except (TypeError, ValueError) as exc:
            raise invalid_state("The Debate cleanup idempotency receipt is invalid.") from exc
        if not isinstance(payload, Mapping):
            raise invalid_state("The Debate cleanup idempotency receipt is invalid.")
        replay: DeleteVoiceResult | DeleteAllResult
        if operation == "deleteVoice":
            replay = DeleteVoiceResult.from_public_dict(payload)
        else:
            replay = DeleteAllResult.from_public_dict(payload)
        # There is no reason to hold the writer lock for a pure replay.  The
        # caller's normal session dependency may commit again harmlessly.
        db.rollback()
        return _IdempotencyClaim(record, request_hash, replay)
    now = datetime.now(UTC)
    if record.state == "pending" and record.lease_expires_at is not None:
        expiry = record.lease_expires_at
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=UTC)
        if expiry > now:
            raise conflict(
                "idempotency_in_progress",
                "An identical Debate cleanup request is already in progress.",
            )
    if record.state not in {"pending", "abandoned"}:
        raise invalid_state("The Debate cleanup idempotency record is invalid.")
    record.state = "pending"
    record.claim_token = secrets.token_urlsafe(32)
    record.lease_expires_at = now + timedelta(seconds=10)
    record.status_code = None
    record.response_json = None
    record.updated_at = now
    db.flush()
    return _IdempotencyClaim(record, request_hash)


def _persist_cleanup_receipt(
    db: Session,
    record: IdempotencyRecord | None,
    result: DeleteVoiceResult | DeleteAllResult,
) -> None:
    if record is None:
        return
    payload = json.dumps(result.to_public_dict(), sort_keys=True, separators=(",", ":"))
    record.state = "completed"
    record.status_code = 200
    record.response_json = payload
    record.updated_at = datetime.now(UTC)
    db.flush()


def _revise_cleanup_receipt(
    db: Session,
    record: IdempotencyRecord | None,
    request_hash: str,
    result: DeleteVoiceResult | DeleteAllResult,
) -> None:
    """CAS the post-commit filesystem/cancellation status into the receipt."""

    if record is None:
        return
    payload = json.dumps(result.to_public_dict(), sort_keys=True, separators=(",", ":"))
    try:
        changed = db.execute(
            update(IdempotencyRecord)
            .where(
                IdempotencyRecord.id == record.id,
                IdempotencyRecord.actor_user_id == record.actor_user_id,
                IdempotencyRecord.operation == record.operation,
                IdempotencyRecord.key == record.key,
                IdempotencyRecord.request_hash == request_hash,
                IdempotencyRecord.state == "completed",
            )
            .values(response_json=payload, updated_at=datetime.now(UTC))
        )
        if int(getattr(changed, "rowcount", 0) or 0) != 1:
            db.rollback()
            return
        db.commit()
    except Exception as exc:  # pragma: no cover - lock/fault leaves safe base receipt
        db.rollback()
        LOGGER.error("Debate cleanup receipt revision failed error_type=%s", type(exc).__name__)


def _load_playback(db: Session, debate_id: str) -> PlaybackState:
    playback = db.scalar(select(PlaybackState).where(PlaybackState.debate_id == debate_id))
    if playback is None:
        debate = db.get(Debate, debate_id)
        if debate is None:
            raise conflict(
                "playback_state_unavailable", "The Debate playback state is unavailable."
            )
        # Older/incomplete records may expose a virtual version-zero snapshot.
        # Materialize it inside this writer transaction for scoped cleanup.
        now = datetime.now(UTC)
        playback = PlaybackState(
            id=str(uuid4()),
            debate_id=debate_id,
            status="preparing",
            mode="live",
            control_version=0,
            cursor_ms=0,
            playback_rate=1.0,
            created_at=now,
            updated_at=now,
        )
        db.add(playback)
        db.flush()
    return playback


def _fence_debate(
    db: Session,
    debate: Debate,
    playback: PlaybackState,
    *,
    expected_revision: int,
    expected_control_version: int,
    delete_all: bool,
    advance_revision: bool = True,
) -> tuple[int, int, int]:
    """CAS both rows and return the new revision/control/generation."""

    current_revision = int(debate.revision)
    current_control = int(playback.control_version)
    if current_revision != int(expected_revision):
        raise conflict(
            "stale_revision",
            "The Debate revision is stale.",
            {"current_revision": current_revision},
        )
    if current_control != int(expected_control_version):
        raise conflict(
            "stale_control_version",
            "The playback control version is stale.",
            {"current_control_version": current_control},
        )
    now = datetime.now(UTC)
    new_revision = current_revision + int(advance_revision)
    new_control = current_control + 1
    new_generation = int(debate.cancellation_generation or 0) + (1 if delete_all else 0)
    debate_values: dict[str, Any] = {"revision": new_revision, "updated_at": now}
    if delete_all:
        debate_values["cancellation_generation"] = new_generation
    changed = db.execute(
        update(Debate)
        .where(Debate.id == debate.id, Debate.revision == current_revision)
        .values(**debate_values)
    )
    if int(getattr(changed, "rowcount", 0) or 0) != 1:
        raise conflict("stale_revision", "The Debate changed before cleanup was committed.")
    playback_values: dict[str, Any] = {
        "control_version": new_control,
        "pending_action": None,
        "pending_ticket_hash": None,
        "pending_media_command_id": None,
        "audio_duration_ms": 0,
        "controller_epoch": None,
        "controller_owner_connection": None,
        "updated_at": now,
    }
    if delete_all:
        playback_values.update(
            {
                "status": "stopped",
                "current_turn_id": None,
                "mode": "live",
                "replay_scope": None,
                "replay_index": None,
                "replay_turn_ids_json": None,
                "cursor_ms": 0,
            }
        )
    elif playback.status in {"playing", "preparing", "ready", "waiting_next"}:
        # A media deletion parks the lesson until text-only TTS recovery has
        # rebuilt the selected audio.  Keeping current_turn_id and the public
        # turn rows is what makes the recovery scope explicit.
        playback_values["status"] = "paused"
    changed = db.execute(
        update(PlaybackState)
        .where(
            PlaybackState.debate_id == debate.id,
            PlaybackState.control_version == current_control,
        )
        .values(**playback_values)
    )
    if int(getattr(changed, "rowcount", 0) or 0) != 1:
        raise conflict(
            "stale_control_version",
            "The playback state changed before cleanup was committed.",
        )
    # Keep the loaded objects coherent for result construction and any caller
    # that inspects them before the enclosing request dependency returns.
    debate.revision = new_revision
    if delete_all:
        debate.cancellation_generation = new_generation
    playback.control_version = new_control
    return new_revision, new_control, new_generation


def _interrupt_jobs(
    db: Session,
    debate_id: str,
    code: str,
    *,
    turn_ids: Iterable[str] | None = None,
    include_report_jobs: bool = True,
) -> int:
    predicates: list[Any] = [
        Job.debate_id == debate_id,
        Job.state.in_(("pending", "running")),
    ]
    if not include_report_jobs:
        # Delete Voice fences only speech/TTS work.  Insight/report jobs may
        # share the Debate and sometimes even retain a turn_id for provenance;
        # they are independent outputs and must continue untouched.
        predicates.append(Job.operation.not_in(("barrage_insight.generate", "report.generate")))
        values = _values(turn_ids or ())
        predicates.append(Job.turn_id.in_(values) if values else false())
    changed = db.execute(
        update(Job)
        .where(*predicates)
        .values(state="interrupted", safe_error_code=code, updated_at=datetime.now(UTC))
    )
    return max(0, int(getattr(changed, "rowcount", 0) or 0))


def _capture_recovery_triggers(db: Session) -> dict[str, str]:
    names = (_RECOVERY_DELETE_TRIGGER,)
    rows = (
        db.execute(
            text("SELECT name, sql FROM sqlite_master WHERE type='trigger' AND name=:delete_name"),
            {"delete_name": _RECOVERY_DELETE_TRIGGER},
        )
        .mappings()
        .all()
    )
    captured = {str(row["name"]): str(row["sql"]) for row in rows if row["sql"]}
    if set(captured) != set(names):
        raise DebateCleanupError("recovery_trigger_unavailable")
    expected = " ".join(_EXPECTED_RECOVERY_DELETE_TRIGGER_SQL.lower().split())
    for name, sql in captured.items():
        lowered = " ".join(sql.lower().split())
        if name != _RECOVERY_DELETE_TRIGGER or lowered != expected:
            raise DebateCleanupError("recovery_trigger_definition_unexpected")
    return captured


def _drop_recovery_triggers(db: Session, captured: Mapping[str, str]) -> None:
    if _RECOVERY_DELETE_TRIGGER not in captured:
        raise DebateCleanupError("recovery_trigger_definition_unexpected")
    db.execute(text(f'DROP TRIGGER "{_RECOVERY_DELETE_TRIGGER}"'))


def _restore_recovery_triggers(db: Session, captured: Mapping[str, str]) -> None:
    name = _RECOVERY_DELETE_TRIGGER
    sql = captured.get(name)
    if not sql:
        raise DebateCleanupError("recovery_trigger_restore_failed")
    db.execute(text(sql))
    row = db.execute(
        text("SELECT sql FROM sqlite_master WHERE type='trigger' AND name=:name"),
        {"name": name},
    ).scalar_one_or_none()
    if row is None or " ".join(str(row).lower().split()) != " ".join(sql.lower().split()):
        raise DebateCleanupError("recovery_trigger_restore_failed")


def _delete_recovery_inputs(db: Session, column_name: str, values: Iterable[str]) -> int:
    """Delete scoped LLM recovery inputs on either supported database.

    SQLite migrations guard the table with an immutability trigger, so the
    scoped delete briefly drops and restores it inside the caller's writer
    transaction.  PostgreSQL has no such trigger (``sqlite_master`` does not
    exist there); the rows are deleted under foreign keys alone.  Skipping the
    delete on PostgreSQL left ``provider_operations`` rows referenced and made
    Delete All fail with a foreign key violation.
    """

    values_tuple = _values(values)
    if not values_tuple:
        return 0
    if db.get_bind().dialect.name != "sqlite":
        return _delete_rows(db, "llm_recovery_inputs", column_name, values_tuple)
    table = _table("llm_recovery_inputs")
    present = db.scalar(
        select(text("count(*)")).select_from(table).where(table.c[column_name].in_(values_tuple))
    )
    if not int(present or 0):
        return 0
    triggers = _capture_recovery_triggers(db)
    _drop_recovery_triggers(db, triggers)
    count = _delete_rows(db, "llm_recovery_inputs", column_name, values_tuple)
    _restore_recovery_triggers(db, triggers)
    return count


def _stored_file_survivor_check(db: Session, graph: _DebateGraph) -> None:
    if not graph.stored_file_ids:
        return
    stored_ids = tuple(graph.stored_file_ids)
    # Authored knowledge and voice rows are a hard boundary.  A shared file
    # remains in place and its target reference is removed only when all other
    # references are absent.
    for table_name, column_name in (
        ("knowledge_documents", "stored_file_id"),
        ("knowledge_snapshots", "combined_file_id"),
        ("snapshot_documents", "frozen_file_id"),
        ("voice_previews", "stored_file_id"),
    ):
        table = _table(table_name)
        shared = db.execute(
            select(table.c.id).where(table.c[column_name].in_(stored_ids)).limit(1)
        ).first()
        if shared:
            raise DebateCleanupError("stored_file_shared")
    refs = _table("file_references")
    if db.execute(
        select(refs.c.id)
        .where(
            refs.c.stored_file_id.in_(stored_ids),
            ~refs.c.id.in_(tuple(graph.file_reference_ids)) if graph.file_reference_ids else true(),
        )
        .limit(1)
    ).first():
        raise DebateCleanupError("stored_file_shared")
    turns = _table("debate_turns")
    if db.execute(
        select(turns.c.id)
        .where(
            turns.c.audio_file_id.in_(stored_ids),
            ~turns.c.id.in_(tuple(graph.turn_ids)) if graph.turn_ids else true(),
        )
        .limit(1)
    ).first():
        raise DebateCleanupError("stored_file_shared")


def _stage_files(graph: _DebateGraph, root: Path) -> _FileQuarantine:
    paths = list(graph.file_paths.values())
    existing: list[Path] = []
    missing = 0
    for path in paths:
        if path.is_symlink():
            raise DebateCleanupError("cleanup_path_symlink_refused")
        if path.exists():
            if not path.is_file():
                raise DebateCleanupError("cleanup_path_not_regular")
            existing.append(path)
        else:
            missing += 1
    if not existing:
        return _FileQuarantine(root, None, [], tuple(graph.directory_paths.values()), missing)
    quarantine = Path(tempfile.mkdtemp(prefix=".maya-debate-delete-", dir=root))
    moved: list[tuple[Path, Path]] = []
    try:
        for index, source in enumerate(existing):
            destination = quarantine / f"{index:08d}-{source.name}"
            os.replace(source, destination)
            moved.append((source, destination))
    except Exception:
        for source, destination in reversed(moved):
            if destination.exists():
                os.replace(destination, source)
        shutil.rmtree(quarantine, ignore_errors=True)
        raise
    return _FileQuarantine(root, quarantine, moved, tuple(graph.directory_paths.values()), missing)


def _journal_quarantine(
    db: Session,
    quarantine: _FileQuarantine,
    *,
    operation_type: str,
    debate_id: str,
    idempotency_record_id: str | None,
) -> _FileQuarantine:
    """Persist one generic journal row per moved file before DB commit.

    ``FileOperation`` is intentionally used as a storage-only recovery
    journal.  ``old_audio_debate_id`` and ``new_debate_id`` remain NULL so a
    Delete All can remove the Debate row without violating its RESTRICT FKs;
    ``entity_id`` is an opaque selector and is excluded from the Debate graph
    when ``operation_type`` is one of the two private cleanup values.
    """

    if quarantine.quarantine_relative_path is None:
        return quarantine
    journal_ids: list[str] = []
    now = datetime.now(UTC)
    for source, destination in quarantine.moved:
        source_relative = source.relative_to(quarantine.root).as_posix()
        destination_relative = destination.relative_to(quarantine.root).as_posix()
        row = FileOperation(
            id=str(uuid4()),
            idempotency_record_id=idempotency_record_id,
            operation_kind=operation_type,
            entity_id=str(debate_id),
            request_id=str(uuid4()),
            source_relative_path=source_relative,
            target_relative_path=destination_relative,
            staging_relative_path=quarantine.quarantine_relative_path,
            expected_sha256=None,
            old_audio_debate_id=None,
            new_debate_id=None,
            expected_old_debate_id=None,
            state="cleanup_required",
            safe_error_code=None,
            created_at=now,
            updated_at=now,
        )
        db.add(row)
        journal_ids.append(row.id)
    db.flush()
    quarantine.journal_ids = tuple(journal_ids)
    return quarantine


def _resume_cleanup_journal_rows(
    db: Session,
    root: Path,
    *,
    debate_id: str | None = None,
    idempotency_record_id: str | None = None,
) -> tuple[int, int, int, tuple[str, ...]]:
    """Finish committed quarantine files without touching semantic DB rows.

    The recovery boundary deliberately does not consult or recreate Debate or
    Turn rows.  A missing quarantine file is already physically complete; an
    unexpected file/symlink leaves the journal in ``cleanup_required`` and
    raises a safe error so an operator can inspect the private directory.
    """

    clauses: list[Any] = [
        FileOperation.operation_kind.in_(tuple(_CLEANUP_OPERATIONS)),
        FileOperation.state == "cleanup_required",
    ]
    if debate_id is not None:
        clauses.append(FileOperation.entity_id == str(debate_id))
    if idempotency_record_id is not None:
        clauses.append(FileOperation.idempotency_record_id == str(idempotency_record_id))
    rows = list(db.scalars(select(FileOperation).where(*clauses)).all())
    if not rows:
        return 0, 0, 0, ()
    grouped: dict[tuple[str, str], list[FileOperation]] = {}
    for row in rows:
        staging = row.staging_relative_path
        target = row.target_relative_path
        if not staging or not target:
            raise DebateCleanupError("cleanup_journal_invalid")
        grouped.setdefault((str(row.entity_id), str(staging)), []).append(row)

    deleted = 0
    missing = 0
    pending = 0
    recovered_ids: list[str] = []
    for (_owner, staging_relative), group in grouped.items():
        staging_path = _safe_path(root, staging_relative, directory=True)
        # A cleanup directory is private and cannot be an arbitrary path from
        # a legacy journal row.  This prefix also prevents a row from naming a
        # real course/staging directory during recovery.
        if not PurePosixPath(staging_relative).name.startswith(".maya-debate-delete-"):
            raise DebateCleanupError("cleanup_journal_invalid")
        if staging_path.exists() and staging_path.is_symlink():
            raise DebateCleanupError("cleanup_path_symlink_refused")
        group_pending = False
        for row in group:
            target_relative = str(row.target_relative_path)
            target_path = _safe_path(root, target_relative, directory=False)
            target_parent = PurePosixPath(target_relative).parent.as_posix()
            if target_parent != PurePosixPath(staging_relative).as_posix():
                raise DebateCleanupError("cleanup_journal_invalid")
            if not target_path.exists():
                missing += 1
                continue
            if target_path.is_symlink() or not target_path.is_file():
                raise DebateCleanupError("cleanup_path_symlink_refused")
            try:
                target_path.unlink()
                deleted += 1
            except OSError:
                group_pending = True
        if staging_path.exists():
            try:
                staging_path.rmdir()
            except OSError:
                group_pending = True
        if group_pending:
            pending += 1
            continue
        for row in group:
            row.state = "recovered"
            row.updated_at = datetime.now(UTC)
            recovered_ids.append(str(row.id))
    db.flush()
    if recovered_ids:
        db.commit()
    return deleted, missing, pending, tuple(recovered_ids)


def resume_cleanup_journals(
    db: Session,
    data_root: Path | str,
    *,
    debate_id: str | None = None,
    idempotency_record_id: str | None = None,
) -> dict[str, int]:
    """Resume committed file cleanup at startup or after an idempotent retry."""

    root = _safe_root(data_root)
    try:
        deleted, missing, pending, recovered = _resume_cleanup_journal_rows(
            db,
            root,
            debate_id=debate_id,
            idempotency_record_id=idempotency_record_id,
        )
    except Exception:
        db.rollback()
        raise
    return {
        "deleted_file_count": deleted,
        "missing_file_count": missing,
        "pending_file_count": pending,
        "recovered_journal_count": len(recovered),
    }


def _recovered_cleanup_file_count(
    db: Session,
    *,
    debate_id: str,
    idempotency_record_id: str,
) -> int:
    return int(
        db.scalar(
            select(text("count(*)"))
            .select_from(_table("file_operations"))
            .where(
                _table("file_operations").c.entity_id == str(debate_id),
                _table("file_operations").c.idempotency_record_id == str(idempotency_record_id),
                _table("file_operations").c.operation_type.in_(tuple(_CLEANUP_OPERATIONS)),
                _table("file_operations").c.state == "recovered",
            )
        )
        or 0
    )


def _restore_files(quarantine: _FileQuarantine) -> None:
    for source, destination in reversed(quarantine.moved):
        if destination.exists():
            source.parent.mkdir(parents=True, exist_ok=True)
            os.replace(destination, source)
    if quarantine.quarantine is not None:
        shutil.rmtree(quarantine.quarantine, ignore_errors=True)


def _finish_files(quarantine: _FileQuarantine) -> tuple[int, int]:
    deleted = 0
    pending = 0
    if quarantine.quarantine is not None:
        for _source, destination in quarantine.moved:
            try:
                if destination.exists():
                    destination.unlink()
                deleted += 1
            except OSError:
                pending += 1
        try:
            quarantine.quarantine.rmdir()
        except OSError:
            pending += 1
    for directory in sorted(
        quarantine.directory_paths, key=lambda item: len(item.parts), reverse=True
    ):
        if directory.is_symlink():
            pending += 1
            continue
        if not directory.exists():
            continue
        try:
            directory.rmdir()
        except OSError:
            # A concurrent artifact is left for a later bounded cleanup pass.
            pending += 1
    return deleted, pending


def _mark_cleanup_journal_recovered(
    db: Session,
    quarantine: _FileQuarantine,
    *,
    file_pending: int,
) -> None:
    """Close file intents after their quarantine has been fully drained."""

    if not quarantine.journal_ids or file_pending:
        return
    try:
        changed = db.execute(
            update(FileOperation)
            .where(
                FileOperation.id.in_(quarantine.journal_ids),
                FileOperation.state == "cleanup_required",
            )
            .values(state="recovered", updated_at=datetime.now(UTC))
        )
        if int(getattr(changed, "rowcount", 0) or 0):
            db.commit()
    except Exception as exc:  # pragma: no cover - leaves an idempotent recovery row
        db.rollback()
        LOGGER.error("Debate cleanup journal close failed error_type=%s", type(exc).__name__)


async def _cancel_runtime(
    debate_id: str,
    *,
    playback_service: Any | None = None,
    task_manager: Any | None = None,
    ticket_store: Any | None = None,
    report_task_manager: Any | None = None,
    wait_for_workers: bool = True,
) -> None:
    """Interrupt process-local work after DB rows have been fenced."""

    if playback_service is not None:
        task_manager = task_manager or getattr(playback_service, "task_manager", None)
        ticket_store = ticket_store or getattr(playback_service, "ticket_store", None)
    cancel = getattr(task_manager, "request_cancel_debate", None) if not wait_for_workers else None
    cancel = cancel or getattr(task_manager, "cancel_debate", None)
    if callable(cancel):
        value = cancel(str(debate_id))
        if inspect.isawaitable(value):
            await value
    revoke = getattr(ticket_store, "revoke_debate", None)
    if callable(revoke):
        value = revoke(str(debate_id))
        if inspect.isawaitable(value):
            await value
    cancel_reports = (
        getattr(report_task_manager, "request_cancel_debate", None)
        if not wait_for_workers
        else None
    )
    cancel_reports = cancel_reports or getattr(report_task_manager, "cancel_debate", None)
    if callable(cancel_reports):
        value = cancel_reports(str(debate_id))
        if inspect.isawaitable(value):
            await value


async def _resume_replayed_cleanup(
    db: Session,
    claim: _IdempotencyClaim,
    *,
    data_root: Path | str | None,
    playback_service: Any | None,
    task_manager: Any | None,
    ticket_store: Any | None,
    report_task_manager: Any | None,
) -> DeleteVoiceResult | DeleteAllResult:
    """Complete a committed receipt's private quarantine on a retry."""

    replay = claim.replay
    if replay is None or data_root is None or claim.record is None:
        return replay  # type: ignore[return-value]
    # Journal rows count distinct quarantined files. The receipt may already
    # count some missing targets from a partially completed deletion, so a
    # retry reconciles totals rather than adding the same files again.
    recovered_before = _recovered_cleanup_file_count(
        db,
        debate_id=replay.debate_id,
        idempotency_record_id=claim.record.id,
    )
    stats = resume_cleanup_journals(
        # The replay claim rolls back its writer snapshot before entering this
        # helper, so this Session is free to update only journal/receipt rows.
        db,
        data_root,
        debate_id=replay.debate_id,
        idempotency_record_id=claim.record.id,
    )
    runtime_cancelled = replay.runtime_cancelled
    if not runtime_cancelled or stats["recovered_journal_count"]:
        runtime_cancelled = True
        try:
            await _cancel_runtime(
                replay.debate_id,
                playback_service=playback_service,
                task_manager=task_manager,
                ticket_store=ticket_store,
                report_task_manager=report_task_manager,
            )
        except Exception as exc:
            runtime_cancelled = False
            LOGGER.error(
                "Replayed Debate cleanup cancellation failed error_type=%s",
                type(exc).__name__,
            )
    deleted_file_count = max(
        replay.deleted_file_count,
        recovered_before + stats["deleted_file_count"] + stats["missing_file_count"],
    )
    pending_file_count = stats["pending_file_count"] + (0 if runtime_cancelled else 1)
    if isinstance(replay, DeleteVoiceResult):
        result: DeleteVoiceResult | DeleteAllResult = replace(
            replay,
            deleted_file_count=deleted_file_count,
            missing_file_count=replay.missing_file_count,
            pending_file_count=pending_file_count,
            runtime_cancelled=runtime_cancelled,
        )
    else:
        result = replace(
            replay,
            deleted_file_count=deleted_file_count,
            missing_file_count=replay.missing_file_count,
            pending_file_count=pending_file_count,
            runtime_cancelled=runtime_cancelled,
        )
    _revise_cleanup_receipt(db, claim.record, claim.request_hash, result)
    return result


def _clear_turn_audio(db: Session, graph: _DebateGraph) -> tuple[int, tuple[str, ...], int]:
    if not graph.turn_ids:
        return 0, (), 0
    turns = (
        db.execute(select(DebateTurn).where(DebateTurn.id.in_(tuple(graph.turn_ids))))
        .scalars()
        .all()
    )
    regenerable: list[str] = []
    retained_public = 0
    audio_ids: set[str] = set()
    for turn in turns:
        if turn.audio_file_id:
            audio_ids.add(str(turn.audio_file_id))
        if (
            turn.speech is not None
            and turn.structured_json is not None
            and turn.transcript_hash is not None
        ):
            regenerable.append(str(turn.id))
        if turn.publication_status == "public":
            retained_public += 1
        # A worker that was only generating text cannot publish a late result
        # after this request fences its Job.  Validated text stays untouched.
        if turn.generation_status == "running" and str(turn.id) not in regenerable:
            turn.generation_status = "failed"
            turn.preparation_stage = "failed"
            turn.safe_error_code = "debate_media_deleted"
        turn.audio_file_id = None
        turn.audio_duration_ms = None
        turn.actual_tts_voice_kind = None
        turn.actual_tts_voice_profile_id = None
        turn.updated_at = datetime.now(UTC)
    # File references owned by the target turn/debate and files selected from
    # those pointers are the only media rows removed by Delete Voice.
    refs = _table("file_references")
    ref_rows = (
        db.execute(
            select(refs.c.id, refs.c.stored_file_id).where(
                refs.c.id.in_(tuple(graph.file_reference_ids))
                if graph.file_reference_ids
                else false()
            )
        )
        .mappings()
        .all()
    )
    audio_ref_ids = {str(row["id"]) for row in ref_rows if str(row["stored_file_id"]) in audio_ids}
    if audio_ref_ids:
        db.execute(delete(FileReference).where(FileReference.id.in_(tuple(audio_ref_ids))))
    # Only delete files no longer referenced by any authored/shared row.  The
    # survivor check raises if a selected file is unexpectedly shared, so a
    # misclassified knowledge/voice file cannot be lost.
    graph.stored_file_ids = audio_ids
    graph.file_reference_ids = audio_ref_ids
    _stored_file_survivor_check(db, graph)
    db.flush()
    if audio_ids:
        db.execute(delete(StoredFile).where(StoredFile.id.in_(tuple(audio_ids))))
    return len(turns), tuple(sorted(regenerable)), retained_public


def _delete_rows(db: Session, table_name: str, column_name: str, values: Iterable[str]) -> int:
    values_tuple = _values(values)
    if not values_tuple:
        return 0
    table = _table(table_name)
    result = db.execute(delete(table).where(table.c[column_name].in_(values_tuple)))
    return max(0, int(getattr(result, "rowcount", 0) or 0))


def _delete_graph(
    db: Session,
    graph: _DebateGraph,
    captured_triggers: Mapping[str, str] | None,
) -> dict[str, int]:
    """Delete one graph in explicit FK-safe order."""

    counts: dict[str, int] = {}

    def remove(table: str, column: str, values: Iterable[str]) -> None:
        count = _delete_rows(db, table, column, values)
        if count:
            counts[table] = counts.get(table, 0) + count

    # Final interaction/report/provider children first.
    remove("interaction_final_barrages", "debate_id", {graph.debate_id})
    remove("interaction_final_vote_counts", "debate_id", {graph.debate_id})
    remove("barrage_insight_assignments", "debate_id", {graph.debate_id})
    remove("barrage_insight_items", "debate_id", {graph.debate_id})
    remove("jobs", "debate_id", {graph.debate_id})
    if graph.operation_ids:
        remove("llm_accepted_stages", "operation_id", graph.operation_ids)
        remove("embedding_accepted_vectors", "operation_id", graph.operation_ids)
        remove("embedding_accepted_stages", "operation_id", graph.operation_ids)
        remove("provider_reservations", "operation_id", graph.operation_ids)
    if graph.turn_ids:
        remove("llm_accepted_stages", "turn_id", graph.turn_ids)
    # Recovery inputs restrict both provider_operations and debate_turns. They
    # must go on every dialect; only SQLite needs its trigger lifted (done by
    # the caller, which passes captured_triggers when it did so).
    if graph.turn_ids:
        remove("llm_recovery_inputs", "turn_id", graph.turn_ids)
    if graph.operation_ids:
        remove("llm_recovery_inputs", "operation_id", graph.operation_ids)
    remove("provider_operations", "id", graph.operation_ids)
    remove("demo_acceptance_runs", "id", graph.run_ids)
    # Export manifests retain RESTRICT references to both Debate and turn;
    # remove their confirmations/manifests before either semantic row.
    remove("provider_export_confirmations", "manifest_id", graph.manifest_ids)
    remove("provider_export_manifests", "id", graph.manifest_ids)
    remove("civilization_report_current_success", "debate_id", {graph.debate_id})
    remove("civilization_report_revisions", "debate_id", {graph.debate_id})
    remove("civilization_reports", "debate_id", {graph.debate_id})
    remove("barrage_insight_snapshots", "debate_id", {graph.debate_id})
    remove("votes", "debate_id", {graph.debate_id})
    remove("barrage_messages", "debate_id", {graph.debate_id})
    remove("classroom_interaction_windows", "debate_id", {graph.debate_id})
    remove("turn_sources", "turn_id", graph.turn_ids)
    remove("position_history", "turn_id", graph.turn_ids)
    remove("playback_states", "debate_id", {graph.debate_id})
    remove("debate_events", "debate_id", {graph.debate_id})
    remove("debate_turns", "id", graph.turn_ids)
    remove("debate_participants", "id", graph.participant_ids)
    remove("provider_scope_budgets", "scope_id", graph.operation_scopes | graph.scope_ids)
    remove("file_references", "id", graph.file_reference_ids)
    remove("file_operations", "id", graph.file_operation_ids)
    remove("idempotency_records", "id", graph.idempotency_ids)
    remove("audit_logs", "id", graph.audit_log_ids)
    # The Course remains authored.  Only clear its current audio pointer if it
    # still names this Debate, then remove the Debate itself.
    course_table = _table("courses")
    db.execute(
        update(course_table)
        .where(course_table.c.current_audio_debate_id == graph.debate_id)
        .values(current_audio_debate_id=None)
    )
    remove("debates", "id", {graph.debate_id})
    remove("stored_files", "id", graph.stored_file_ids)

    if captured_triggers is not None:
        _restore_recovery_triggers(db, captured_triggers)
    if not foreign_keys_ok(db):
        raise DebateCleanupError("foreign_key_violations_after")
    return counts


def _detach_surviving_run_operations(db: Session, graph: _DebateGraph) -> None:
    """Keep shared embedding metadata valid when its run ledger is deleted."""

    if not graph.run_ids:
        return
    operation_table = _table("provider_operations")
    db.execute(
        update(operation_table)
        .where(
            operation_table.c.acceptance_run_id.in_(tuple(graph.run_ids)),
            ~operation_table.c.id.in_(tuple(graph.operation_ids))
            if graph.operation_ids
            else true(),
        )
        .values(acceptance_run_id=None, call_no=None, updated_at=datetime.now(UTC))
    )


async def delete_voice(
    db: Session,
    *,
    actor_user_id: str,
    debate_id: str,
    expected_revision: int,
    expected_control_version: int,
    data_root: Path | str | None = None,
    idempotency_key: str | None = None,
    playback_service: Any | None = None,
    task_manager: Any | None = None,
    ticket_store: Any | None = None,
    report_task_manager: Any | None = None,
) -> DeleteVoiceResult:
    """Delete one Debate's audio while retaining validated semantic rows.

    The service commits the fenced transaction before returning.  It is safe
    for the normal ``get_db`` dependency to call ``commit`` again.
    """

    _begin_immediate(db)
    quarantine: _FileQuarantine | None = None
    claim: _IdempotencyClaim | None = None
    try:
        claim = _claim_cleanup_idempotency(
            db,
            operation="deleteVoice",
            actor_user_id=actor_user_id,
            debate_id=debate_id,
            expected_revision=expected_revision,
            expected_control_version=expected_control_version,
            key=idempotency_key,
        )
        if claim.replay is not None:
            return await _resume_replayed_cleanup(
                db,
                claim,
                data_root=data_root,
                playback_service=playback_service,
                task_manager=task_manager,
                ticket_store=ticket_store,
                report_task_manager=report_task_manager,
            )  # type: ignore[return-value]
        root = _safe_root(data_root)
        debate = _load_debate(db, debate_id, actor_user_id)
        playback = _load_playback(db, debate_id)
        graph = _build_graph(db, debate, root, collect_files=False)
        _narrow_media_graph(db, graph, root)
        _fence_debate(
            db,
            debate,
            playback,
            expected_revision=expected_revision,
            expected_control_version=expected_control_version,
            delete_all=False,
        )
        interrupted_jobs = _interrupt_jobs(
            db,
            debate_id,
            "debate_media_deleted",
            turn_ids=graph.turn_ids,
            include_report_jobs=False,
        )
        cleared_count, regenerable_ids, retained_public_count = _clear_turn_audio(db, graph)
        _delete_rows(db, "file_operations", "id", graph.file_operation_ids)
        quarantine = _stage_files(graph, root)
        _journal_quarantine(
            db,
            quarantine,
            operation_type=_CLEANUP_VOICE_OPERATION,
            debate_id=debate_id,
            idempotency_record_id=claim.record.id if claim and claim.record else None,
        )
        base_result = DeleteVoiceResult(
            debate_id=str(debate_id),
            revision=int(debate.revision),
            control_version=int(playback.control_version),
            cancellation_generation=int(debate.cancellation_generation),
            cleared_turn_count=cleared_count,
            interrupted_job_count=interrupted_jobs,
            deleted_file_count=0,
            missing_file_count=quarantine.missing_count,
            pending_file_count=quarantine.moved_count,
            regenerable_turn_ids=regenerable_ids,
            retained_public_turn_count=retained_public_count,
            runtime_cancelled=False,
        )
        _persist_cleanup_receipt(db, claim.record if claim is not None else None, base_result)
        # The durable Job state and both CAS values are committed before any
        # potentially slow asyncio cancellation.  A late worker sees the
        # interrupted claim even if its local task takes time to unwind.
        db.commit()
    except Exception:
        db.rollback()
        if quarantine is not None:
            _restore_files(quarantine)
        raise
    runtime_cancelled = True
    try:
        await _cancel_runtime(
            debate_id,
            playback_service=playback_service,
            task_manager=task_manager,
            ticket_store=ticket_store,
            report_task_manager=None,
        )
    except Exception as exc:
        runtime_cancelled = False
        LOGGER.error(
            "Debate media cancellation did not complete debate_id=%s error_type=%s",
            debate_id,
            type(exc).__name__,
        )
    assert quarantine is not None
    deleted_files, pending_files = _finish_files(quarantine)
    _mark_cleanup_journal_recovered(db, quarantine, file_pending=pending_files)
    if not runtime_cancelled:
        pending_files += 1
    result = DeleteVoiceResult(
        debate_id=str(debate_id),
        revision=int(debate.revision),
        control_version=int(playback.control_version),
        cancellation_generation=int(debate.cancellation_generation),
        cleared_turn_count=cleared_count,
        interrupted_job_count=interrupted_jobs,
        deleted_file_count=deleted_files,
        missing_file_count=quarantine.missing_count,
        pending_file_count=pending_files,
        regenerable_turn_ids=regenerable_ids,
        retained_public_turn_count=retained_public_count,
        runtime_cancelled=runtime_cancelled,
    )
    _revise_cleanup_receipt(
        db,
        claim.record if claim is not None else None,
        claim.request_hash if claim else "",
        result,
    )
    return result


async def delete_all(
    db: Session,
    *,
    actor_user_id: str,
    debate_id: str,
    expected_revision: int,
    expected_control_version: int,
    data_root: Path | str | None = None,
    idempotency_key: str | None = None,
    playback_service: Any | None = None,
    task_manager: Any | None = None,
    ticket_store: Any | None = None,
    report_task_manager: Any | None = None,
) -> DeleteAllResult:
    """Cancel and remove one Debate graph and its bounded runtime files."""

    _begin_immediate(db)
    quarantine: _FileQuarantine | None = None
    captured_triggers: dict[str, str] | None = None
    claim: _IdempotencyClaim | None = None
    try:
        claim = _claim_cleanup_idempotency(
            db,
            operation="deleteAll",
            actor_user_id=actor_user_id,
            debate_id=debate_id,
            expected_revision=expected_revision,
            expected_control_version=expected_control_version,
            key=idempotency_key,
        )
        if claim.replay is not None:
            return await _resume_replayed_cleanup(
                db,
                claim,
                data_root=data_root,
                playback_service=playback_service,
                task_manager=task_manager,
                ticket_store=ticket_store,
                report_task_manager=report_task_manager,
            )  # type: ignore[return-value]
        root = _safe_root(data_root)
        debate = _load_debate(db, debate_id, actor_user_id)
        playback = _load_playback(db, debate_id)
        graph = _build_graph(db, debate, root)
        # BEGIN IMMEDIATE holds the writer boundary through scoped deletion
        # and trigger restoration. Another classroom need not be stopped.
        _fence_debate(
            db,
            debate,
            playback,
            expected_revision=int(debate.revision),
            expected_control_version=int(playback.control_version),
            delete_all=True,
        )
        interrupted_jobs = _interrupt_jobs(db, debate_id, "debate_deleted")
        # Mark every unvalidated running turn as failed before deleting the
        # graph; this makes the in-transaction state safe for a worker that was
        # already holding an object reference when the request arrived.
        db.execute(
            update(DebateTurn)
            .where(
                DebateTurn.debate_id == debate_id,
                DebateTurn.generation_status == "running",
            )
            .values(
                generation_status="failed",
                preparation_stage="failed",
                safe_error_code="debate_deleted",
                updated_at=datetime.now(UTC),
            )
        )
        quarantine = _stage_files(graph, root)
        _journal_quarantine(
            db,
            quarantine,
            operation_type=_CLEANUP_ALL_OPERATION,
            debate_id=debate_id,
            idempotency_record_id=claim.record.id if claim and claim.record else None,
        )
        recovery_table = _table("llm_recovery_inputs")
        recovery_predicate: Any = (
            recovery_table.c.turn_id.in_(tuple(graph.turn_ids)) if graph.turn_ids else false()
        )
        if graph.operation_ids:
            recovery_predicate = recovery_predicate | recovery_table.c.operation_id.in_(
                tuple(graph.operation_ids)
            )
        recovery_count = db.scalar(
            select(text("count(*)")).select_from(recovery_table).where(recovery_predicate)
        )
        if int(recovery_count or 0) and db.get_bind().dialect.name == "sqlite":
            # The immutability trigger is created by the SQLite migrations.
            # PostgreSQL schema bootstrap has no equivalent trigger, so the
            # scoped delete proceeds under foreign keys alone.
            captured_triggers = _capture_recovery_triggers(db)
            _drop_recovery_triggers(db, captured_triggers)
        _detach_surviving_run_operations(db, graph)
        _stored_file_survivor_check(db, graph)
        deleted_rows = _delete_graph(db, graph, captured_triggers)
        base_result = DeleteAllResult(
            debate_id=str(debate_id),
            revision=int(debate.revision),
            control_version=int(playback.control_version),
            cancellation_generation=int(debate.cancellation_generation),
            interrupted_job_count=interrupted_jobs,
            deleted_rows=deleted_rows,
            deleted_file_count=0,
            missing_file_count=quarantine.missing_count,
            pending_file_count=quarantine.moved_count,
            runtime_cancelled=False,
        )
        _persist_cleanup_receipt(db, claim.record if claim is not None else None, base_result)
        # Job interruption and cancellation_generation are now in the same
        # committed deletion transaction; local cancellation may safely occur
        # after this commit without borrowing a provider worker Session.
        db.commit()
    except Exception:
        db.rollback()
        if quarantine is not None:
            _restore_files(quarantine)
        raise
    runtime_cancelled = True
    try:
        await _cancel_runtime(
            debate_id,
            playback_service=playback_service,
            task_manager=task_manager,
            ticket_store=ticket_store,
            report_task_manager=report_task_manager,
            wait_for_workers=False,
        )
    except Exception as exc:
        runtime_cancelled = False
        LOGGER.error(
            "Debate runtime cancellation did not complete debate_id=%s error_type=%s",
            debate_id,
            type(exc).__name__,
        )
    assert quarantine is not None
    deleted_files, pending_files = _finish_files(quarantine)
    _mark_cleanup_journal_recovered(db, quarantine, file_pending=pending_files)
    if not runtime_cancelled:
        pending_files += 1
    result = DeleteAllResult(
        debate_id=str(debate_id),
        revision=int(debate.revision),
        control_version=int(playback.control_version),
        cancellation_generation=int(debate.cancellation_generation),
        interrupted_job_count=interrupted_jobs,
        deleted_rows=deleted_rows,
        deleted_file_count=deleted_files,
        missing_file_count=quarantine.missing_count,
        pending_file_count=pending_files,
        runtime_cancelled=runtime_cancelled,
    )
    _revise_cleanup_receipt(
        db,
        claim.record if claim is not None else None,
        claim.request_hash if claim else "",
        result,
    )
    return result


__all__ = [
    "DebateCleanupError",
    "DeleteAllResult",
    "DeleteVoiceResult",
    "delete_all",
    "delete_voice",
    "resume_cleanup_journals",
]
