"""Small server-only bridge between LLM-A and playback SQL.

The provider/ledger worker owns accepted-stage and recovery-input DTOs.  This
module only adapts those ports to the playback Session and supplies the final
CAS fallback for older ledger implementations.  It never owns transport or
provider output parsing.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.providers.control import LLMRecoveryInputV1
from app.providers.llm_segments import SegmentRecoveryInputV2


def _now() -> datetime:
    return datetime.now(UTC)


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _method(value: object, *names: str) -> Callable[..., object] | None:
    for name in names:
        candidate = getattr(value, name, None)
        if callable(candidate):
            return cast(Callable[..., object], candidate)
    return None


def _read(value: object, name: str, default: object = None) -> object:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _as_int(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, (str, float)):
        try:
            return int(value)
        except (TypeError, ValueError, OverflowError):
            return default
    return default


def _items(value: object) -> Sequence[object]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return value
    return ()


class SqlLLMPublication:
    """Session-bound stage/recovery/publication port for production playback."""

    def __init__(self, db: Session, *, ledger: object | None = None) -> None:
        self.db = db
        self.ledger = ledger

    def stage_accepted_with_recovery(self, stage: object, recovery_input: object) -> object:
        if isinstance(recovery_input, SegmentRecoveryInputV2):
            return self.stage_segment_accepted_with_recovery(stage, recovery_input)
        method = _method(
            self.ledger,
            "stage_llm_accepted_with_recovery",
            "stage_accepted_with_recovery",
        )
        if method is None:
            raise RuntimeError("the accepted-stage recovery port is unavailable")
        if not isinstance(recovery_input, LLMRecoveryInputV1):
            raise RuntimeError("LLM publication recovery input has the wrong domain type")
        return method(stage, recovery_input)

    stage_llm_accepted_with_recovery = stage_accepted_with_recovery

    def stage_segment_accepted_with_recovery(
        self, stage: object, recovery_input: SegmentRecoveryInputV2
    ) -> object:
        """Persist the explicit segments_v2 stage/input pair atomically."""

        if not isinstance(recovery_input, SegmentRecoveryInputV2):
            raise RuntimeError("segment recovery input has the wrong domain type")
        method = _method(
            self.ledger,
            "stage_segment_accepted_with_recovery",
            "stage_segments_accepted_with_recovery",
        )
        if method is None:
            raise RuntimeError("the segment accepted-stage recovery port is unavailable")
        return method(stage, recovery_input)

    stage_segments_accepted_with_recovery = stage_segment_accepted_with_recovery

    def get_llm_accepted_stage(self, operation_id: str) -> object | None:
        method = _method(self.ledger, "get_llm_accepted_stage", "get_accepted_llm_stage")
        return method(operation_id) if method is not None else None

    def load_accepted_bundle(self, operation_id: str) -> object | None:
        method = _method(
            self.ledger,
            "load_llm_accepted_bundle",
            "load_accepted_bundle",
            "get_llm_accepted_bundle",
        )
        if method is None:
            return None
        try:
            return method(operation_id, db=self.db)
        except TypeError:
            return method(operation_id)

    load_llm_accepted_bundle = load_accepted_bundle

    def commit_llm_turn_success(self, **kwargs: object) -> object:
        """Promote accepted operation/reservation in the caller's Session.

        The turn, sources, evidence and job have already been staged by
        ``SqlPlaybackRepository.mark_turn_ready`` on this same Session.  A
        failed CAS raises so the caller's transaction rolls every write back.
        """

        if isinstance(kwargs.get("recovery_input"), SegmentRecoveryInputV2):
            return self.commit_segment_turn_success(**kwargs)

        operation_id = kwargs.get("operation_id")
        turn_id = kwargs.get("turn_id")
        request_hash = kwargs.get("request_hash")
        if not isinstance(operation_id, str) or not operation_id:
            raise RuntimeError("LLM publication operation identity is missing")
        if not isinstance(turn_id, str) or not turn_id:
            raise RuntimeError("LLM publication turn identity is missing")
        if not isinstance(request_hash, str) or not request_hash:
            raise RuntimeError("LLM publication request identity is missing")
        stage = kwargs.get("stage")
        stage_operation_id = _read(stage, "operation_id")
        stage_turn_id = _read(stage, "turn_id")
        stage_request_hash = _read(stage, "request_hash")
        output_hash = _read(stage, "output_hash", _read(stage, "stage_hash"))
        if (
            str(stage_operation_id) != operation_id
            or str(stage_turn_id) != turn_id
            or str(stage_request_hash) != request_hash
            or not isinstance(output_hash, str)
            or len(output_hash) != 64
        ):
            raise RuntimeError("LLM publication stage identity is stale")
        operation_row = (
            self.db.execute(
                text(
                    "SELECT state, provider_operation, logical_item_id, request_hash, "
                    "staged_response_hash FROM provider_operations WHERE id=:operation_id"
                ),
                {"operation_id": operation_id},
            )
            .mappings()
            .first()
        )
        if operation_row is None:
            raise RuntimeError("LLM publication operation is unavailable")
        if (
            str(operation_row["provider_operation"]) != "llm_debate_turn"
            or str(operation_row["logical_item_id"]) != turn_id
            or str(operation_row["request_hash"]) != request_hash
            or str(operation_row["staged_response_hash"] or "") not in {"", output_hash}
        ):
            raise RuntimeError("LLM publication operation identity is stale")
        stage_row = (
            self.db.execute(
                text(
                    "SELECT output_hash, turn_id, request_hash FROM llm_accepted_stages "
                    "WHERE operation_id=:operation_id"
                ),
                {"operation_id": operation_id},
            )
            .mappings()
            .first()
        )
        if stage_row is None or (
            str(stage_row["output_hash"]) != output_hash
            or str(stage_row["turn_id"]) != turn_id
            or str(stage_row["request_hash"]) != request_hash
        ):
            raise RuntimeError("LLM publication accepted stage is unavailable")
        recovery_input = kwargs.get("recovery_input")
        if not isinstance(recovery_input, LLMRecoveryInputV1):
            raise RuntimeError("LLM publication recovery input is unavailable")
        input_json = recovery_input.input_json
        input_hash = recovery_input.input_hash
        try:
            recovery_input.identity()
            recovery_value = json.loads(input_json)
            if not isinstance(recovery_value, Mapping):
                raise ValueError("recovery envelope is not an object")
            if hashlib.sha256(input_json.encode("utf-8")).hexdigest() != input_hash:
                raise ValueError("recovery input hash is stale")
            identity_value = recovery_value.get("identity")
            input_value = recovery_value.get("input")
            request_value = input_value.get("request") if isinstance(input_value, Mapping) else None
            fence_value = input_value.get("fence") if isinstance(input_value, Mapping) else None
            if (
                not isinstance(identity_value, Mapping)
                or not isinstance(request_value, Mapping)
                or not isinstance(fence_value, Mapping)
            ):
                raise ValueError("recovery envelope is incomplete")
            prompt_hash = hashlib.sha256(_canonical(request_value).encode("utf-8")).hexdigest()
            fence_hash = hashlib.sha256(_canonical(fence_value).encode("utf-8")).hexdigest()
        except Exception as exc:
            raise RuntimeError("LLM publication recovery input is invalid") from exc
        if (
            recovery_input.operation_id != operation_id
            or recovery_input.turn_id != turn_id
            or str(recovery_input.attempt_no)
            != str(stage_row.get("attempt_no", getattr(stage, "attempt_no", "")))
            or str(request_value.get("turn_id", "")) != turn_id
            or str(request_value.get("request_version", "")) != "prompt_request_v1"
            or prompt_hash != str(stage_row.get("prompt_hash", getattr(stage, "prompt_hash", "")))
            or fence_hash != str(getattr(stage, "generation_fence", ""))
            or str(identity_value.get("request_hash", "")) != request_hash
            or str(identity_value.get("prompt_hash", "")) != str(getattr(stage, "prompt_hash", ""))
            or str(identity_value.get("turn_id", "")) != turn_id
            or _as_int(identity_value.get("attempt_no", 0), 0)
            != _as_int(getattr(stage, "attempt_no", 0), 0)
        ):
            raise RuntimeError("LLM publication recovery identity is stale")
        for name in (
            "prompt_contract_version",
            "schema_hash",
            "tokenizer_id",
            "tokenizer_hash",
            "rule_set_hash",
            "persona_spec_hash",
            "transcript_hash",
            "receipt_hash",
            "policy_hash",
            "export_manifest_hash",
            "build_manifest_hash",
            "generation_fence",
            "model_key",
        ):
            if str(identity_value.get(name, "")) != str(getattr(stage, name, "")):
                raise RuntimeError("LLM publication recovery identity is stale")
        if identity_value.get("repair_policy_hash") != getattr(stage, "repair_policy_hash", None):
            raise RuntimeError("LLM publication recovery identity is stale")
        recovery_row = (
            self.db.execute(
                text(
                    "SELECT input_hash, input_json, input_version, "
                    "operation_id, turn_id, attempt_no "
                    "FROM llm_recovery_inputs "
                    "WHERE operation_id=:operation_id"
                ),
                {"operation_id": operation_id},
            )
            .mappings()
            .first()
        )
        if recovery_row is None or (
            str(recovery_row["input_hash"]) != input_hash
            or str(recovery_row["input_json"]) != input_json
            or str(recovery_row["input_version"]) != "llm_recovery_input_v1"
            or str(recovery_row["operation_id"]) != operation_id
            or str(recovery_row["turn_id"]) != turn_id
        ):
            raise RuntimeError("LLM publication recovery row is unavailable")
        turn_row = (
            self.db.execute(
                text(
                    "SELECT t.generation_status, t.structured_json, t.evidence_trace_json, "
                    "t.debate_id, t.participant_id, t.knowledge_snapshot_id, "
                    "t.predecessor_turn_ids_json, t.transcript_hash, t.cutoff_turn_index, "
                    "d.cancellation_generation "
                    "FROM debate_turns AS t JOIN debates AS d ON d.id=t.debate_id "
                    "WHERE t.id=:turn_id"
                ),
                {"turn_id": turn_id},
            )
            .mappings()
            .first()
        )
        if turn_row is None or str(turn_row["generation_status"]) != "final_ready":
            raise RuntimeError("LLM publication turn is not final-ready")
        if not str(turn_row["structured_json"] or ""):
            raise RuntimeError("LLM publication structured result is missing")
        if turn_row["evidence_trace_json"] is None:
            raise RuntimeError("LLM publication evidence trace is missing")
        if str(identity_value.get("debate_id", "")) != str(turn_row["debate_id"]):
            raise RuntimeError("LLM publication recovery identity is stale")
        try:
            recovery_generation = int(fence_value.get("generation", -1))
            current_generation = int(turn_row["cancellation_generation"])
        except (TypeError, ValueError):
            raise RuntimeError("LLM publication turn fence is invalid") from None
        if recovery_generation != current_generation:
            raise RuntimeError("LLM publication turn fence is stale")
        if str(request_value.get("debate_id", "")) != str(turn_row["debate_id"]):
            raise RuntimeError("LLM publication recovery identity is stale")
        if str(request_value.get("turn_id", "")) != turn_id:
            raise RuntimeError("LLM publication recovery identity is stale")
        if str(request_value.get("transcript_hash", "")) != str(turn_row["transcript_hash"] or ""):
            raise RuntimeError("LLM publication transcript fence is stale")
        final_ready = kwargs.get("final_ready")
        recovery_receipts = (
            input_value.get("receipts", []) if isinstance(input_value, Mapping) else []
        )
        if not isinstance(recovery_receipts, list):
            raise RuntimeError("LLM publication recovery receipts are invalid")
        for receipt in recovery_receipts:
            if not isinstance(receipt, Mapping):
                raise RuntimeError("LLM publication recovery receipt is invalid")
            chunk_id = receipt.get("chunk_id")
            snapshot_id = receipt.get("snapshot_id")
            receipt_text = receipt.get("text")
            if not isinstance(chunk_id, str) or not isinstance(snapshot_id, str):
                raise RuntimeError("LLM publication recovery receipt is invalid")
            chunk = self.db.execute(
                text("SELECT snapshot_id, text FROM knowledge_chunks WHERE id=:chunk_id"),
                {"chunk_id": chunk_id},
            ).first()
            if (
                chunk is None
                or str(chunk[0]) != str(turn_row["knowledge_snapshot_id"])
                or snapshot_id != str(turn_row["knowledge_snapshot_id"])
                or str(chunk[1]) != str(receipt_text or "")
            ):
                raise RuntimeError("LLM publication receipt crossed its snapshot")
        if final_ready is not None:
            if (
                str(_read(final_ready, "turn_id", "")) != turn_id
                or str(_read(final_ready, "debate_id", turn_row["debate_id"]))
                != str(turn_row["debate_id"])
                or str(_read(final_ready, "participant_id", "")) != str(turn_row["participant_id"])
                or str(_read(final_ready, "snapshot_id", ""))
                != str(turn_row["knowledge_snapshot_id"])
                or str(_read(final_ready, "transcript_hash", ""))
                != str(turn_row["transcript_hash"])
                or _as_int(_read(final_ready, "cutoff_turn_index", -1), -1)
                != int(turn_row["cutoff_turn_index"])
            ):
                raise RuntimeError("LLM publication turn fence is stale")
            expected_predecessors = _read(final_ready, "predecessor_turn_ids", ()) or ()
            try:
                persisted_predecessors = json.loads(str(turn_row["predecessor_turn_ids_json"]))
            except (TypeError, ValueError):
                raise RuntimeError("LLM publication predecessor fence is invalid") from None
            if list(str(item) for item in _items(expected_predecessors)) != persisted_predecessors:
                raise RuntimeError("LLM publication predecessor fence is stale")
            for receipt in _items(_read(final_ready, "used_receipts", ())):
                snapshot_id = _read(receipt, "snapshot_id", "")
                chunk_id = _read(receipt, "chunk_id", "")
                chunk = self.db.execute(
                    text("SELECT snapshot_id, text FROM knowledge_chunks WHERE id=:chunk_id"),
                    {"chunk_id": str(chunk_id)},
                ).first()
                if (
                    chunk is None
                    or str(chunk[0]) != str(turn_row["knowledge_snapshot_id"])
                    or str(snapshot_id) != str(turn_row["knowledge_snapshot_id"])
                    or str(chunk[1]) != str(_read(receipt, "text", ""))
                ):
                    raise RuntimeError("LLM publication receipt crossed its snapshot")
        manifest_row = (
            self.db.execute(
                text(
                    "SELECT scope_id, provider_operation, model_key, policy_hash, "
                    "build_manifest_hash, debate_id, turn_id, max_attempts, "
                    "max_total_tokens, max_cost_cny, repair_policy_version, repair_policy_hash "
                    "FROM provider_export_manifests WHERE manifest_hash=:manifest_hash"
                ),
                {"manifest_hash": str(getattr(stage, "export_manifest_hash", ""))},
            )
            .mappings()
            .first()
        )
        if manifest_row is None or (
            str(manifest_row["scope_id"]) != str(turn_row["debate_id"])
            or str(manifest_row["provider_operation"]) != "llm_debate_turn"
            or str(manifest_row["model_key"]) != str(getattr(stage, "model_key", ""))
            or str(manifest_row["policy_hash"]) != str(getattr(stage, "policy_hash", ""))
            or str(manifest_row["build_manifest_hash"])
            != str(getattr(stage, "build_manifest_hash", ""))
            or str(manifest_row["repair_policy_version"] or "")
            != str(getattr(stage, "repair_policy_version", "") or "")
            or str(manifest_row["repair_policy_hash"] or "")
            != str(getattr(stage, "repair_policy_hash", "") or "")
            or str(manifest_row["debate_id"]) != str(turn_row["debate_id"])
            or str(manifest_row["turn_id"]) != turn_id
            or int(manifest_row["max_attempts"]) != 2
        ):
            raise RuntimeError("LLM publication export manifest is stale")
        state = str(operation_row["state"])
        if state == "succeeded":
            reservation = self.db.execute(
                text("SELECT state FROM provider_reservations WHERE operation_id=:operation_id"),
                {"operation_id": operation_id},
            ).scalar_one_or_none()
            if str(reservation) != "succeeded":
                raise RuntimeError("LLM publication reservation state is inconsistent")
            return operation_row
        if state != "accepted":
            raise RuntimeError("LLM publication operation is not accepted")
        changed = self.db.execute(
            text(
                "UPDATE provider_operations SET state='succeeded', "
                "updated_at=:updated_at WHERE id=:operation_id AND "
                "state='accepted' AND staged_response_hash=:output_hash"
            ),
            {
                "updated_at": _now(),
                "operation_id": operation_id,
                "output_hash": output_hash,
            },
        )
        if int(getattr(changed, "rowcount", 0)) != 1:
            raise RuntimeError("LLM publication operation CAS failed")
        reservation = self.db.execute(
            text(
                "UPDATE provider_reservations SET state='succeeded', updated_at=:updated_at "
                "WHERE operation_id=:operation_id AND state='accepted'"
            ),
            {"updated_at": _now(), "operation_id": operation_id},
        )
        if int(getattr(reservation, "rowcount", 0)) != 1:
            raise RuntimeError("LLM publication reservation CAS failed")
        return {"operation_id": operation_id, "state": "succeeded"}

    def commit_segment_turn_success(self, **kwargs: object) -> object:
        """Finalize a staged segments_v2 turn without invoking the provider."""

        from app.modules.debates.generation.segments import (
            SegmentTurnResult,
            StoredSegmentTurnResult,
            load_stored_segment_turn_result,
        )

        recovery_input = kwargs.get("recovery_input")
        if not isinstance(recovery_input, SegmentRecoveryInputV2):
            raise RuntimeError("segment recovery input is unavailable")
        recovery_input.__post_init__()
        operation_id = kwargs.get("operation_id")
        turn_id = kwargs.get("turn_id")
        request_hash = kwargs.get("request_hash")
        if not isinstance(operation_id, str) or not operation_id:
            raise RuntimeError("LLM publication operation identity is missing")
        if not isinstance(turn_id, str) or not turn_id:
            raise RuntimeError("LLM publication turn identity is missing")
        if not isinstance(request_hash, str) or not request_hash:
            raise RuntimeError("LLM publication request identity is missing")
        stage = kwargs.get("stage")
        output_hash = _read(stage, "output_hash", _read(stage, "stage_hash"))
        if (
            str(_read(stage, "operation_id")) != operation_id
            or str(_read(stage, "turn_id")) != turn_id
            or str(_read(stage, "request_hash")) != request_hash
            or not isinstance(output_hash, str)
            or len(output_hash) != 64
        ):
            raise RuntimeError("LLM publication stage identity is stale")
        operation_row = (
            self.db.execute(
                text(
                    "SELECT state, provider_operation, logical_item_id, attempt_no, request_hash, "
                    "policy_hash, export_manifest_hash, build_manifest_hash, model_key, "
                    "staged_response_hash, scope_id FROM provider_operations "
                    "WHERE id=:operation_id"
                ),
                {"operation_id": operation_id},
            )
            .mappings()
            .first()
        )
        if operation_row is None:
            raise RuntimeError("LLM publication operation is unavailable")
        frozen = recovery_input.frozen_request
        if (
            str(operation_row["provider_operation"]) != "llm_debate_turn"
            or str(operation_row["scope_id"]) != frozen.debate_id
            or str(operation_row["logical_item_id"]) != turn_id
            or int(operation_row["attempt_no"]) != frozen.attempt_no
            or str(operation_row["request_hash"]) != request_hash
            or str(operation_row["request_hash"]) != frozen.request_hash
            or str(operation_row["policy_hash"]) != frozen.policy_hash
            or str(operation_row["export_manifest_hash"]) != frozen.export_manifest_hash
            or str(operation_row["build_manifest_hash"]) != frozen.build_manifest_hash
            or str(operation_row["model_key"]) != str(_read(stage, "model_key", ""))
            or str(operation_row["staged_response_hash"] or "") != output_hash
        ):
            raise RuntimeError("LLM publication operation identity is stale")
        try:
            recovery_input.assert_stage_identity(stage)
        except Exception as exc:
            raise RuntimeError("LLM publication recovery identity is stale") from exc
        stage_row = (
            self.db.execute(
                text(
                    "SELECT output_hash, turn_id, attempt_no, request_hash "
                    "FROM llm_accepted_stages "
                    "WHERE operation_id=:operation_id"
                ),
                {"operation_id": operation_id},
            )
            .mappings()
            .first()
        )
        if stage_row is None or (
            str(stage_row["output_hash"]) != output_hash
            or str(stage_row["turn_id"]) != turn_id
            or int(stage_row["attempt_no"]) != frozen.attempt_no
            or str(stage_row["request_hash"]) != request_hash
        ):
            raise RuntimeError("LLM publication accepted stage is unavailable")
        recovery_row = (
            self.db.execute(
                text(
                    "SELECT input_version, input_json, input_hash, operation_id, turn_id, "
                    "attempt_no "
                    "FROM llm_recovery_inputs WHERE operation_id=:operation_id"
                ),
                {"operation_id": operation_id},
            )
            .mappings()
            .first()
        )
        if recovery_row is None or (
            str(recovery_row["input_version"]) != "segment_recovery_input_v2"
            or str(recovery_row["input_json"]) != recovery_input.input_json
            or str(recovery_row["input_hash"]) != recovery_input.input_hash
            or str(recovery_row["operation_id"]) != operation_id
            or str(recovery_row["turn_id"]) != turn_id
            or int(recovery_row["attempt_no"]) != frozen.attempt_no
        ):
            raise RuntimeError("LLM publication recovery input is unavailable")
        turn_row = (
            self.db.execute(
                text(
                    "SELECT t.generation_status, t.structured_json, t.retrieval_receipts_json, "
                    "t.debate_id, t.participant_id, t.knowledge_snapshot_id, "
                    "t.predecessor_turn_ids_json, t.transcript_hash, t.cutoff_turn_index, "
                    "d.cancellation_generation FROM debate_turns AS t "
                    "JOIN debates AS d ON d.id=t.debate_id WHERE t.id=:turn_id"
                ),
                {"turn_id": turn_id},
            )
            .mappings()
            .first()
        )
        if turn_row is None or str(turn_row["generation_status"]) != "final_ready":
            raise RuntimeError("LLM publication turn is not final-ready")
        if str(turn_row["debate_id"]) != frozen.debate_id or str(
            turn_row["knowledge_snapshot_id"]
        ) != str(frozen.snapshot.snapshot_id):
            raise RuntimeError("LLM publication recovery identity is stale")
        try:
            predecessor_ids = json.loads(str(turn_row["predecessor_turn_ids_json"]))
            if not isinstance(predecessor_ids, list) or not all(
                isinstance(item, str) and item for item in predecessor_ids
            ):
                raise ValueError("predecessor fence is invalid")
            fence_value = {
                "predecessor_turn_ids": predecessor_ids,
                "transcript_hash": str(turn_row["transcript_hash"] or ""),
                "cutoff_turn_index": int(turn_row["cutoff_turn_index"]),
                "generation": int(turn_row["cancellation_generation"]),
            }
            fence_hash = hashlib.sha256(_canonical(fence_value).encode("utf-8")).hexdigest()
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError("LLM publication generation fence is invalid") from exc
        if (
            frozen.generation_fence != fence_hash
            or str(_read(stage, "generation_fence", "")) != fence_hash
            or str(_read(stage, "transcript_hash", "")) != str(turn_row["transcript_hash"] or "")
            or str(_read(stage, "receipt_hash", "")) != frozen.snapshot.receipt_hash
        ):
            raise RuntimeError("LLM publication generation fence is stale")
        for receipt in frozen.snapshot.receipts:
            from app.modules.debates.models import DebateTurn
            from app.modules.debates.source_lineage import receipt_scope_is_valid

            source_turn = self.db.get(DebateTurn, turn_id)
            chunk = self.db.execute(
                text("SELECT snapshot_id, text FROM knowledge_chunks WHERE id=:chunk_id"),
                {"chunk_id": receipt.chunk_id},
            ).first()
            if (
                chunk is None
                or str(chunk[0]) != receipt.snapshot_id
                or str(chunk[1]) != receipt.text
                or source_turn is None
                or not receipt_scope_is_valid(self.db, source_turn, receipt)
            ):
                raise RuntimeError("LLM publication recovery receipt crossed its snapshot")
        stored_value = _read(kwargs.get("final_ready"), "structured")
        if isinstance(stored_value, SegmentTurnResult):
            stored_payload = stored_value.as_stored_payload()
        elif isinstance(stored_value, StoredSegmentTurnResult):
            stored_payload = stored_value.as_payload()
        elif isinstance(stored_value, Mapping):
            stored_payload = dict(stored_value)
        else:
            raise RuntimeError("LLM publication segment result is unavailable")
        stored = load_stored_segment_turn_result(stored_payload)
        stored_hash = hashlib.sha256(_canonical(stored.as_payload()).encode("utf-8")).hexdigest()
        if stored_hash != output_hash:
            raise RuntimeError("LLM publication segment output hash is stale")
        try:
            persisted_structured = json.loads(str(turn_row["structured_json"]))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError("LLM publication structured result is invalid") from exc
        if persisted_structured != stored.as_payload():
            raise RuntimeError("LLM publication structured result is stale")
        try:
            persisted_receipts = json.loads(str(turn_row["retrieval_receipts_json"] or "[]"))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError("LLM publication receipts are invalid") from exc
        if not isinstance(persisted_receipts, list):
            raise RuntimeError("LLM publication receipts are invalid")
        persisted_ids = tuple(
            str(item.get("evidence_id"))
            for item in persisted_receipts
            if isinstance(item, Mapping) and item.get("evidence_id")
        )
        if persisted_ids != stored.used_evidence_ids:
            raise RuntimeError("LLM publication receipts do not match segment references")
        final_ready = kwargs.get("final_ready")
        if (
            str(_read(final_ready, "turn_id", "")) != turn_id
            or str(_read(final_ready, "participant_id", "")) != str(turn_row["participant_id"])
            or str(_read(final_ready, "snapshot_id", "")) != str(turn_row["knowledge_snapshot_id"])
            or str(_read(final_ready, "transcript_hash", "")) != str(turn_row["transcript_hash"])
            or _as_int(_read(final_ready, "cutoff_turn_index", -1), -1)
            != int(turn_row["cutoff_turn_index"])
            or tuple(_items(_read(final_ready, "predecessor_turn_ids", ())))
            != tuple(predecessor_ids)
        ):
            raise RuntimeError("LLM publication turn fence is stale")
        manifest_row = (
            self.db.execute(
                text(
                    "SELECT scope_id, provider_operation, model_key, policy_hash, "
                    "build_manifest_hash, debate_id, turn_id, max_attempts, repair_policy_hash "
                    "FROM provider_export_manifests WHERE manifest_hash=:manifest_hash"
                ),
                {"manifest_hash": str(_read(stage, "export_manifest_hash", ""))},
            )
            .mappings()
            .first()
        )
        expected_attempts = 2 if _read(stage, "repair_policy_hash") else 1
        if manifest_row is None or (
            str(manifest_row["scope_id"]) != frozen.debate_id
            or str(manifest_row["provider_operation"]) != "llm_debate_turn"
            or str(manifest_row["model_key"]) != str(_read(stage, "model_key", ""))
            or str(manifest_row["policy_hash"]) != frozen.policy_hash
            or str(manifest_row["build_manifest_hash"]) != frozen.build_manifest_hash
            or str(manifest_row["debate_id"]) != frozen.debate_id
            or str(manifest_row["turn_id"]) != turn_id
            or int(manifest_row["max_attempts"]) != expected_attempts
            or str(manifest_row["repair_policy_hash"] or "")
            != str(_read(stage, "repair_policy_hash", "") or "")
        ):
            raise RuntimeError("LLM publication export manifest is stale")
        state = str(operation_row["state"])
        if state == "succeeded":
            reservation_state = self.db.execute(
                text("SELECT state FROM provider_reservations WHERE operation_id=:operation_id"),
                {"operation_id": operation_id},
            ).scalar_one_or_none()
            if str(reservation_state) != "succeeded":
                raise RuntimeError("LLM publication reservation state is inconsistent")
            return operation_row
        if state != "accepted":
            raise RuntimeError("LLM publication operation is not accepted")
        changed = self.db.execute(
            text(
                "UPDATE provider_operations SET state='succeeded', updated_at=:updated_at "
                "WHERE id=:operation_id AND state='accepted' AND staged_response_hash=:output_hash"
            ),
            {"updated_at": _now(), "operation_id": operation_id, "output_hash": output_hash},
        )
        if int(getattr(changed, "rowcount", 0)) != 1:
            raise RuntimeError("LLM publication operation CAS failed")
        reservation = self.db.execute(
            text(
                "UPDATE provider_reservations SET state='succeeded', updated_at=:updated_at "
                "WHERE operation_id=:operation_id AND state='accepted'"
            ),
            {"updated_at": _now(), "operation_id": operation_id},
        )
        if int(getattr(reservation, "rowcount", 0)) != 1:
            raise RuntimeError("LLM publication reservation CAS failed")
        return {"operation_id": operation_id, "state": "succeeded"}


__all__ = ["SqlLLMPublication"]
