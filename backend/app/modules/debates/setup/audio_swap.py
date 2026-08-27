"""Typed, recoverable audio swap journal primitives for Debate start.

M12 owns the physical atomic rename.  M10 owns the durable intent and state
contract so a crash can never be mistaken for the older generic delete-both
recovery path.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Literal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import invalid_state, validation_failure
from app.core.models import FileOperation


class AudioSwapState(StrEnum):
    PREPARED = "prepared"
    STAGED = "staged"
    COMMITTED = "committed"
    CLEANUP_REQUIRED = "cleanup_required"
    RECOVERED = "recovered"


@dataclass(frozen=True)
class AudioSwapRequest:
    course_id: str
    request_id: str
    old_debate_id: str | None
    source_relative_path: str | None
    staging_relative_path: str
    new_debate_id: str
    expected_old_debate_id: str | None
    idempotency_record_id: str | None = None


@dataclass(frozen=True)
class AudioSwapRecovery:
    action: Literal["restore_old", "delete_staging", "nothing"]
    old_debate_id: str | None
    new_debate_id: str | None
    staging_relative_path: str | None = None


def _validate_relative_path(value: str | None, *, nullable: bool = True) -> None:
    if value is None and nullable:
        return
    if not value:
        raise validation_failure(
            "Audio swap paths must not be empty.", code="file_operation_failed"
        )
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "?" in value or "#" in value:
        raise validation_failure(
            "Audio swap paths must be relative and contained.", code="file_operation_failed"
        )


def prepare_audio_swap_journal(db: Session, request: AudioSwapRequest) -> FileOperation:
    """Persist ``debate_audio_swap/prepared`` before any rename."""

    _validate_relative_path(request.source_relative_path)
    _validate_relative_path(request.staging_relative_path, nullable=False)
    timestamp = datetime.now(UTC)
    row = FileOperation(
        id=str(uuid4()),
        idempotency_record_id=request.idempotency_record_id,
        operation_kind="debate_audio_swap",
        entity_id=request.new_debate_id,
        request_id=request.request_id,
        source_relative_path=request.source_relative_path,
        target_relative_path=None,
        expected_sha256=None,
        old_audio_debate_id=request.old_debate_id,
        staging_relative_path=request.staging_relative_path,
        new_debate_id=request.new_debate_id,
        expected_old_debate_id=request.expected_old_debate_id,
        state=AudioSwapState.PREPARED.value,
        safe_error_code=None,
        created_at=timestamp,
        updated_at=timestamp,
    )
    db.add(row)
    db.flush()
    return row


_TRANSITIONS: dict[str, set[str]] = {
    AudioSwapState.PREPARED.value: {
        AudioSwapState.STAGED.value,
        AudioSwapState.RECOVERED.value,
    },
    AudioSwapState.STAGED.value: {
        AudioSwapState.COMMITTED.value,
        AudioSwapState.RECOVERED.value,
    },
    AudioSwapState.COMMITTED.value: {
        AudioSwapState.CLEANUP_REQUIRED.value,
        AudioSwapState.RECOVERED.value,
    },
    AudioSwapState.CLEANUP_REQUIRED.value: {AudioSwapState.RECOVERED.value},
    AudioSwapState.RECOVERED.value: set(),
}


def transition_audio_swap(
    db: Session,
    operation_id: str,
    *,
    expected_state: AudioSwapState | str,
    target_state: AudioSwapState | str,
) -> FileOperation:
    """Perform a validated journal state transition."""

    row = db.scalar(select(FileOperation).where(FileOperation.id == operation_id))
    if row is None or row.operation_kind != "debate_audio_swap":
        raise invalid_state("The Debate audio-swap journal was not found.")
    expected = (
        expected_state.value if isinstance(expected_state, AudioSwapState) else expected_state
    )
    target = target_state.value if isinstance(target_state, AudioSwapState) else target_state
    if row.state != expected:
        raise invalid_state("The Debate audio-swap journal state is stale.")
    if target not in _TRANSITIONS.get(expected, set()):
        raise invalid_state("The Debate audio-swap transition is not valid.")
    row.state = target
    row.updated_at = datetime.now(UTC)
    db.flush()
    return row


def recover_audio_swap(
    db: Session,
    operation_id: str,
    *,
    current_audio_debate_id: str | None,
) -> AudioSwapRecovery:
    """Choose restore-versus-delete solely from committed DB state.

    A committed journal with the new course pointer means the database won;
    only staging cleanup is needed.  Any earlier state restores the old
    pointer/directory when one existed.  No generic delete-both operation is
    invoked.
    """

    row = db.scalar(select(FileOperation).where(FileOperation.id == operation_id))
    if row is None or row.operation_kind != "debate_audio_swap":
        raise invalid_state("The Debate audio-swap journal was not found.")
    if (
        row.state in {AudioSwapState.COMMITTED.value, AudioSwapState.CLEANUP_REQUIRED.value}
        and current_audio_debate_id == row.new_debate_id
    ):
        if row.state == AudioSwapState.COMMITTED.value:
            row.state = AudioSwapState.CLEANUP_REQUIRED.value
        row.state = AudioSwapState.RECOVERED.value
        row.updated_at = datetime.now(UTC)
        db.flush()
        return AudioSwapRecovery(
            "delete_staging",
            row.old_audio_debate_id,
            row.new_debate_id,
            row.staging_relative_path,
        )
    if row.state != AudioSwapState.RECOVERED.value:
        row.state = AudioSwapState.RECOVERED.value
        row.updated_at = datetime.now(UTC)
        db.flush()
    return AudioSwapRecovery(
        "restore_old",
        row.old_audio_debate_id,
        row.new_debate_id,
        row.staging_relative_path,
    )


def audio_swap_journals_for_idempotency(
    db: Session,
    idempotency_record_id: str,
) -> list[FileOperation]:
    """Return recoverable typed swaps belonging to one start claim.

    Start idempotency takeover must inspect the audio journal before issuing a
    replacement claim.  Generic Wave 1 file recovery intentionally excludes
    ``debate_audio_swap`` rows because restore-versus-delete depends on the
    committed course pointer.  This helper provides the narrow query for the
    shared claim/recovery path; callers perform the physical move/delete using
    ``staging_relative_path`` and then call :func:`recover_audio_swap` with
    that course's current audio pointer.
    """

    return list(
        db.scalars(
            select(FileOperation)
            .where(
                FileOperation.idempotency_record_id == idempotency_record_id,
                FileOperation.operation_kind == "debate_audio_swap",
                FileOperation.state.in_(
                    (
                        AudioSwapState.PREPARED.value,
                        AudioSwapState.STAGED.value,
                        AudioSwapState.COMMITTED.value,
                        AudioSwapState.CLEANUP_REQUIRED.value,
                    )
                ),
            )
            .order_by(FileOperation.created_at, FileOperation.id)
        ).all()
    )


# Intuitive names for downstream playback integration.
create_audio_swap_journal = prepare_audio_swap_journal
recover_debate_audio_swap = recover_audio_swap


__all__ = [
    "AudioSwapRecovery",
    "AudioSwapRequest",
    "AudioSwapState",
    "audio_swap_journals_for_idempotency",
    "create_audio_swap_journal",
    "prepare_audio_swap_journal",
    "recover_audio_swap",
    "recover_debate_audio_swap",
    "transition_audio_swap",
]
