"""One immutable classroom cutoff shared by every final-round speaker."""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict, deque
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import conflict
from app.modules.debates.models import Debate, DebateParticipant, DebateTurn, PlaybackState
from app.modules.debates.round_count import (
    debate_round_count,
    preview_turn_count,
    uses_segment_protocol,
)
from app.modules.interactions.models import BarrageMessage
from app.providers.llm_privacy import LLMOutboundPrivacyError, validate_anonymous_barrage_text


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _history_hash(turns: Sequence[DebateTurn]) -> str:
    return hashlib.sha256(
        _canonical([{"id": row.id, "speech": row.speech} for row in turns]).encode()
    ).hexdigest()


def _anonymous_text(value: str, identity_tokens: Sequence[str]) -> str | None:
    for token in sorted(set(identity_tokens), key=len, reverse=True):
        if not token.strip():
            continue
        pattern = re.escape(token)
        if token.isascii():
            pattern = r"(?<!\w)" + pattern + r"(?!\w)"
        value = re.sub(pattern, "[redacted]", value, flags=re.IGNORECASE)
    value = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[redacted]", value)
    value = re.sub(r"(?<!\d)(?:\+?86[ -]?)?1[3-9]\d{9}(?!\d)", "[redacted]", value)
    if not value.replace("[redacted]", "").strip():
        return None
    try:
        validate_anonymous_barrage_text(value, identity_tokens=identity_tokens)
    except LLMOutboundPrivacyError:
        return None
    return value


def select_final_barrages(
    rows: Sequence[BarrageMessage], *, identity_tokens: Sequence[str] = ()
) -> tuple[list[dict[str, str]], list[str]]:
    """Deduplicate and balance candidates across turns before model selection."""

    tokens = (*identity_tokens, *(row.nickname for row in rows))
    by_turn: dict[str, deque[tuple[str, str]]] = defaultdict(deque)
    seen: set[str] = set()
    for row in sorted(rows, key=lambda row: row.sequence):
        if row.turn_id is None:
            continue
        text = _anonymous_text(row.raw_text, tokens)
        if text is None:
            continue
        key = " ".join(text.split()).casefold()
        if key in seen:
            continue
        seen.add(key)
        by_turn[row.turn_id].append((row.id, text))
    candidates: list[dict[str, str]] = []
    message_ids: list[str] = []
    while len(candidates) < 12 and any(by_turn.values()):
        for queue in by_turn.values():
            if not queue:
                continue
            message_id, text = queue.popleft()
            message_ids.append(message_id)
            candidates.append({"id": f"B{len(candidates) + 1}", "text": text})
            if len(candidates) == 12:
                break
    return candidates, message_ids


def read_final_input(debate: Debate) -> Mapping[str, Any] | None:
    if debate.final_input_json is None:
        return None
    if hashlib.sha256(debate.final_input_json.encode()).hexdigest() != debate.final_input_hash:
        raise conflict("final_input_changed", "The saved final input is invalid.")
    value = json.loads(debate.final_input_json)
    if (
        not isinstance(value, dict)
        or value.get("version") != "final_input_v1"
        # Completed classroom inputs remain immutable when a later replay is
        # released. Live generation still requires the exact cancellation fence.
        or (
            getattr(debate, "status", None) not in {"debate_finished", "completed"}
            and value.get("generation") != debate.cancellation_generation
        )
        or value.get("language") != debate.output_language
    ):
        raise conflict("final_input_changed", "The saved final input is stale.")
    return value


def final_barrages_for_generation(
    debate: Debate, predecessors: Sequence[DebateTurn]
) -> tuple[Mapping[str, object], ...]:
    value = read_final_input(debate)
    if value is None:
        raise conflict("final_input_required", "Press Final to prepare the last round.")
    if value.get("history_hash") != _history_hash(predecessors):
        raise conflict("final_input_changed", "The saved classroom history changed.")
    return tuple(value["barrages"])


def freeze_final_input(
    session: Session,
    debate: Debate,
    *,
    expected_control_version: int,
    identity_tokens: Sequence[str] = (),
) -> Mapping[str, Any]:
    """Caller holds the teacher-scoped BEGIN IMMEDIATE writer transaction."""

    if not uses_segment_protocol(debate):
        raise conflict("final_input_unavailable", "This lesson uses the earlier protocol.")
    saved = read_final_input(debate)
    if saved is not None:
        return saved
    playback = session.scalar(select(PlaybackState).where(PlaybackState.debate_id == debate.id))
    if (
        debate.status != "running"
        or playback is None
        or playback.mode != "live"
        or playback.status != "waiting_next"
        or playback.control_version != expected_control_version
    ):
        raise conflict("final_input_not_ready", "Finish the prepared rounds before Final.")
    participants = session.scalars(
        select(DebateParticipant).where(DebateParticipant.debate_id == debate.id)
    ).all()
    turns = session.scalars(
        select(DebateTurn)
        .where(
            DebateTurn.debate_id == debate.id,
            DebateTurn.round_no < debate_round_count(debate),
        )
        .order_by(DebateTurn.turn_index)
    ).all()
    expected = preview_turn_count(debate, len(participants))
    final_turns = session.scalars(
        select(DebateTurn).where(
            DebateTurn.debate_id == debate.id,
            DebateTurn.round_no == debate_round_count(debate),
        )
    ).all()
    if (
        not turns
        or len(final_turns) != len(participants)
        or any(row.speech or row.publication_status == "public" for row in final_turns)
        or len(turns) != expected
        or [row.turn_index for row in turns] != list(range(expected))
        or playback.current_turn_id != turns[-1].id
        or any(
            row.publication_status != "public"
            or row.generation_status != "final_ready"
            or not row.speech
            for row in turns
        )
    ):
        raise conflict("final_input_not_ready", "Every prepared turn must finish playback first.")
    messages = session.scalars(
        select(BarrageMessage)
        .where(BarrageMessage.debate_id == debate.id)
        .order_by(BarrageMessage.sequence)
    ).all()
    turn_ids = {row.id for row in turns}
    eligible = [row for row in messages if row.turn_id in turn_ids]
    candidates, message_ids = select_final_barrages(eligible, identity_tokens=identity_tokens)
    value = {
        "version": "final_input_v1",
        "generation": debate.cancellation_generation,
        "language": debate.output_language,
        "cutoff_sequence": max((row.sequence for row in messages), default=0),
        "history_hash": _history_hash(turns),
        "barrages": candidates,
        "message_ids": message_ids,
    }
    debate.final_input_json = _canonical(value)
    debate.final_input_hash = hashlib.sha256(debate.final_input_json.encode()).hexdigest()
    debate.final_frozen_at = datetime.now(UTC)
    session.flush()
    return value
