"""Validate that a turn cites only its own knowledge snapshot."""

from __future__ import annotations

from collections.abc import Mapping

from sqlalchemy.orm import Session


def _value(value: object, name: str, default: object = None) -> object:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def receipt_scope_is_valid(db: Session, turn: object, receipt: object) -> bool:
    """A turn may cite only its own knowledge snapshot.

    Other Agents' public speeches are visible as history. Their knowledge
    receipts and Persona are not.
    """

    snapshot_id = str(_value(receipt, "snapshot_id", ""))
    return bool(snapshot_id) and snapshot_id == str(_value(turn, "knowledge_snapshot_id", ""))
