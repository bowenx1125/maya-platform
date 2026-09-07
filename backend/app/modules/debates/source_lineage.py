"""Validate reused classroom evidence against its original completed turn."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session


def _value(value: object, name: str, default: object = None) -> object:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _receipt_payload(receipt: object) -> dict[str, object]:
    if isinstance(receipt, Mapping):
        payload = dict(receipt)
    elif is_dataclass(receipt) and not isinstance(receipt, type):
        payload = asdict(receipt)
    else:
        return {}
    resolver = getattr(receipt, "resolved_evidence_id", None)
    if callable(resolver):
        payload["evidence_id"] = resolver()
    return {key: value for key, value in payload.items() if value is not None}


def receipt_scope_is_valid(db: Session, turn: object, receipt: object) -> bool:
    """Foreign receipts require the exact original, visible own-KB publication.

    A matching chunk alone is insufficient: the original source must have been
    selected and cited by a completed predecessor in this Debate. Legacy turns
    retain their original participant-snapshot restriction.
    """

    snapshot_id = str(_value(receipt, "snapshot_id", ""))
    if snapshot_id == str(_value(turn, "knowledge_snapshot_id", "")):
        return True
    debate_id = str(_value(turn, "debate_id", ""))
    rule_json = db.execute(
        text("SELECT rule_snapshot_json FROM debates WHERE id=:id"), {"id": debate_id}
    ).scalar_one_or_none()
    try:
        rule = json.loads(str(rule_json or "{}"))
        predecessor_ids = json.loads(str(_value(turn, "predecessor_turn_ids_json", "[]")))
    except (TypeError, ValueError):
        return False
    if (
        not isinstance(rule, Mapping)
        or rule.get("teaching_protocol") != "four_round_v1"
        or not isinstance(predecessor_ids, list)
    ):
        return False
    candidate = _receipt_payload(receipt)
    evidence_id = candidate.get("evidence_id")
    chunk_id = candidate.get("chunk_id")
    if not evidence_id or not chunk_id:
        return False
    rows = db.execute(
        text(
            "SELECT t.id, t.structured_json, t.retrieval_receipts_json "
            "FROM debate_turns AS t JOIN turn_sources AS s ON s.turn_id=t.id "
            "WHERE t.debate_id=:debate_id AND t.turn_index<:turn_index "
            "AND t.generation_status='final_ready' AND t.preparation_stage='ready' "
            "AND t.knowledge_snapshot_id=:snapshot_id "
            "AND s.snapshot_id=:snapshot_id AND s.chunk_id=:chunk_id "
            "AND s.evidence_id=:evidence_id AND s.participant_id=t.participant_id"
        ),
        {
            "debate_id": debate_id,
            "turn_index": _value(turn, "turn_index", -1),
            "snapshot_id": snapshot_id,
            "chunk_id": chunk_id,
            "evidence_id": evidence_id,
        },
    ).mappings()
    for origin in rows:
        if str(origin["id"]) not in predecessor_ids:
            continue
        try:
            structured = json.loads(str(origin["structured_json"]))
            receipts = json.loads(str(origin["retrieval_receipts_json"]))
            segments = structured.get("segments", [])
            cited = any(evidence_id in item.get("source_ids", []) for item in segments)
        except (TypeError, ValueError, AttributeError):
            continue
        if (
            cited
            and isinstance(receipts, list)
            and any(
                isinstance(item, Mapping) and _receipt_payload(item) == candidate
                for item in receipts
            )
        ):
            return True
    return False
