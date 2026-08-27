"""In-memory CAS semantics for generation workers.

M10/M12 can map these operations to their SQL claim rows.  Keeping the
policy here gives the pure M11 tests a concrete adversarial model for stop,
late-result, stale-token and current+one-next preparation behavior without
touching the shared ORM models.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field, replace
from typing import Literal

ClaimStage = Literal["retrieval", "generation", "tts"]
ClaimState = Literal["running", "final_ready", "public", "interrupted", "discarded"]


class GenerationFenceError(RuntimeError):
    """A fence operation has invalid input; stale completion is not an error."""


@dataclass(frozen=True, slots=True)
class TurnClaim:
    debate_id: str
    turn_id: str
    turn_index: int
    stage: ClaimStage
    attempt: Literal[1, 2]
    claim_token: str
    cancellation_generation: int
    predecessor_turn_ids: tuple[str, ...]
    transcript_hash: str
    state: ClaimState = "running"

    def __post_init__(self) -> None:
        if not self.debate_id or not self.turn_id or not self.claim_token:
            raise ValueError("a generation claim needs debate, turn and token identities")
        if self.turn_index < 0 or self.cancellation_generation < 0:
            raise ValueError("generation claim indexes must be non-negative")


@dataclass(slots=True)
class PreparationCap:
    """A pure current+one-next claim window.

    ``current_final_ready`` is intentionally separate from TTS/public state:
    once the current text is final-ready, exactly one immediate successor may
    prepare, but that successor cannot recursively claim another turn.
    """

    current_turn_index: int
    total_turns: int
    current_final_ready: bool = False
    claimed_indices: set[int] = field(default_factory=set)

    def can_claim(self, turn_index: int) -> bool:
        if not 0 <= turn_index < self.total_turns:
            return False
        if turn_index in self.claimed_indices:
            return False
        if turn_index == self.current_turn_index:
            return True
        return (
            turn_index == self.current_turn_index + 1
            and self.current_final_ready
            and turn_index < self.total_turns
            and not any(index > self.current_turn_index + 1 for index in self.claimed_indices)
        )

    def claim(self, turn_index: int) -> bool:
        if not self.can_claim(turn_index):
            return False
        self.claimed_indices.add(turn_index)
        return True

    def mark_current_final_ready(self) -> None:
        self.current_final_ready = True

    def advance(self) -> None:
        """Move the planned window after the current turn becomes public."""

        if self.current_turn_index in self.claimed_indices:
            self.claimed_indices.remove(self.current_turn_index)
        self.current_turn_index += 1
        self.current_final_ready = self.current_turn_index in self.claimed_indices

    @property
    def prepared_indices(self) -> tuple[int, ...]:
        return tuple(sorted(self.claimed_indices))


def can_claim_turn(
    *,
    current_turn_index: int,
    candidate_turn_index: int,
    current_final_ready: bool,
    claimed_indices: set[int] | frozenset[int] = frozenset(),
    total_turns: int | None = None,
) -> bool:
    """Check the current + immediate successor policy without mutation."""

    if candidate_turn_index in claimed_indices or candidate_turn_index < 0:
        return False
    if total_turns is not None and candidate_turn_index >= total_turns:
        return False
    if candidate_turn_index == current_turn_index:
        return True
    return candidate_turn_index == current_turn_index + 1 and current_final_ready


@dataclass(slots=True)
class _DebateFence:
    status: Literal["running", "stopped", "failed", "completed"]
    cancellation_generation: int
    cap: PreparationCap
    claims: dict[tuple[str, str], TurnClaim] = field(default_factory=dict)
    final_ready: dict[str, TurnClaim] = field(default_factory=dict)
    public_turn_ids: set[str] = field(default_factory=set)


class GenerationFence:
    """A small executable model of claim-token/cancellation CAS behavior."""

    def __init__(self) -> None:
        self._debates: dict[str, _DebateFence] = {}

    def register(
        self,
        debate_id: str,
        *,
        total_turns: int,
        current_turn_index: int = 0,
        cancellation_generation: int = 0,
    ) -> None:
        if not debate_id or total_turns < 1 or not 0 <= current_turn_index < total_turns:
            raise GenerationFenceError("invalid debate fence registration")
        if debate_id in self._debates:
            raise GenerationFenceError("debate fence is already registered")
        self._debates[debate_id] = _DebateFence(
            status="running",
            cancellation_generation=cancellation_generation,
            cap=PreparationCap(current_turn_index, total_turns),
        )

    def claim_turn(
        self,
        debate_id: str,
        *,
        turn_id: str,
        turn_index: int,
        stage: ClaimStage = "generation",
        attempt: int = 1,
        predecessor_turn_ids: tuple[str, ...] = (),
        transcript_hash: str = "",
        claim_token: str | None = None,
    ) -> TurnClaim | None:
        fence = self._require(debate_id)
        if fence.status != "running" or attempt not in {1, 2}:
            return None
        if not fence.cap.claim(turn_index):
            return None
        token = claim_token or secrets.token_urlsafe(32)
        claim = TurnClaim(
            debate_id=debate_id,
            turn_id=turn_id,
            turn_index=turn_index,
            stage=stage,
            attempt=attempt,  # type: ignore[arg-type]
            claim_token=token,
            cancellation_generation=fence.cancellation_generation,
            predecessor_turn_ids=tuple(predecessor_turn_ids),
            transcript_hash=transcript_hash,
        )
        fence.claims[(turn_id, stage)] = claim
        return claim

    def complete(
        self,
        claim: TurnClaim,
        *,
        stage: ClaimStage | None = None,
        attempt: int | None = None,
        predecessor_turn_ids: tuple[str, ...] | None = None,
        transcript_hash: str | None = None,
    ) -> bool:
        """CAS-complete a claim; stale/late results are safely discarded."""

        fence = self._debates.get(claim.debate_id)
        if fence is None or fence.status != "running":
            return False
        current = fence.claims.get((claim.turn_id, claim.stage))
        if current is None:
            return False
        if current.claim_token != claim.claim_token:
            return False
        if current.state != "running":
            return False
        if current.cancellation_generation != fence.cancellation_generation:
            return False
        if stage is not None and stage != current.stage:
            return False
        if attempt is not None and attempt != current.attempt:
            return False
        if (
            predecessor_turn_ids is not None
            and tuple(predecessor_turn_ids) != current.predecessor_turn_ids
        ):
            return False
        if transcript_hash is not None and transcript_hash != current.transcript_hash:
            return False
        finished = replace(current, state="final_ready")
        fence.claims[(claim.turn_id, claim.stage)] = finished
        fence.final_ready[claim.turn_id] = finished
        if claim.turn_index == fence.cap.current_turn_index:
            fence.cap.mark_current_final_ready()
        return True

    def release(self, claim: TurnClaim) -> bool:
        """Release an owned failed-attempt claim for a safe retry.

        Release is a compare-and-swap on the exact claim token.  A stale
        worker cannot release a replacement worker's claim, and a final-ready
        or public claim cannot be rolled back by this retry seam.
        """

        fence = self._debates.get(claim.debate_id)
        if fence is None or fence.status != "running":
            return False
        current = fence.claims.get((claim.turn_id, claim.stage))
        if current is None or current.claim_token != claim.claim_token:
            return False
        if current.state != "running":
            return False
        del fence.claims[(claim.turn_id, claim.stage)]
        fence.cap.claimed_indices.discard(claim.turn_index)
        return True

    def publish(self, turn_id: str, *, predecessor_turn_ids: tuple[str, ...]) -> bool:
        """Mark a final-ready turn public only after its complete prefix is public."""

        for fence in self._debates.values():
            claim = fence.final_ready.get(turn_id)
            if claim is None:
                continue
            if any(item not in fence.public_turn_ids for item in predecessor_turn_ids):
                return False
            if tuple(predecessor_turn_ids) != claim.predecessor_turn_ids:
                return False
            public_claim = replace(claim, state="public")
            fence.final_ready[turn_id] = public_claim
            fence.public_turn_ids.add(turn_id)
            if claim.turn_index == fence.cap.current_turn_index:
                fence.cap.advance()
            return True
        return False

    def stop(self, debate_id: str) -> int:
        fence = self._require(debate_id)
        if fence.status in {"stopped", "failed", "completed"}:
            return fence.cancellation_generation
        fence.status = "stopped"
        fence.cancellation_generation += 1
        for key, claim in tuple(fence.claims.items()):
            if claim.state == "running":
                fence.claims[key] = replace(claim, state="interrupted")
        fence.cap.claimed_indices.clear()
        return fence.cancellation_generation

    def fail(self, debate_id: str) -> int:
        fence = self._require(debate_id)
        fence.status = "failed"
        fence.cancellation_generation += 1
        fence.cap.claimed_indices.clear()
        return fence.cancellation_generation

    def current_generation(self, debate_id: str) -> int:
        return self._require(debate_id).cancellation_generation

    def prepared_indices(self, debate_id: str) -> tuple[int, ...]:
        return self._require(debate_id).cap.prepared_indices

    def _require(self, debate_id: str) -> _DebateFence:
        try:
            return self._debates[debate_id]
        except KeyError as exc:
            raise GenerationFenceError("unknown debate fence") from exc


__all__ = [
    "GenerationFence",
    "GenerationFenceError",
    "PreparationCap",
    "TurnClaim",
    "can_claim_turn",
]
