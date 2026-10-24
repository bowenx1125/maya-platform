"""Unlink stored files only after the deleting transaction has committed.

A hard delete removes rows and their files together. Unlinking inside the
transaction lost 841 production files: the cleanup rolled back, the rows came
back and their files did not. A path queued here is unlinked once the
outermost transaction commits, and dropped when the transaction (or the
savepoint it was queued in) rolls back. A failed unlink is logged and never
touches the database.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from sqlalchemy import event
from sqlalchemy.orm import Session, SessionTransaction

from app.modules.knowledge.files import contained_path

LOGGER = logging.getLogger(__name__)

_KEY = "maya_unlink_after_commit"


def unlink_after_commit(db: Session, data_root: Path | None, relative_path: str | None) -> None:
    if data_root is None or not relative_path:
        return
    transaction = db.get_nested_transaction() or db.get_transaction()
    db.info.setdefault(_KEY, []).append((transaction, data_root, relative_path))


def pending_unlinks(db: Session) -> list[str]:
    return [relative for _transaction, _root, relative in db.info.get(_KEY, [])]


def _inside(transaction: Any, ended: SessionTransaction) -> bool:
    current = transaction
    while current is not None:
        if current is ended:
            return True
        current = current.parent
    return False


@event.listens_for(Session, "after_soft_rollback")
def _drop_rolled_back(session: Session, previous_transaction: SessionTransaction) -> None:
    queued = session.info.get(_KEY)
    if queued:
        session.info[_KEY] = [
            entry for entry in queued if not _inside(entry[0], previous_transaction)
        ]


@event.listens_for(Session, "after_commit")
def _unlink_committed(session: Session) -> None:
    queued = session.info.pop(_KEY, None)
    for _transaction, data_root, relative in queued or ():
        try:
            path = contained_path(data_root, relative)
            if path.is_file() or path.is_symlink():
                path.unlink()
        except (OSError, ValueError):
            LOGGER.warning("stored_file_unlink_failed")
