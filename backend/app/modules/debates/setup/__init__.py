"""Teacher-facing Debate draft setup and deterministic rule helpers."""

from .audio_swap import (
    AudioSwapRecovery,
    AudioSwapRequest,
    AudioSwapState,
    create_audio_swap_journal,
    prepare_audio_swap_journal,
    recover_audio_swap,
    transition_audio_swap,
)
from .rules import (
    RuleViolation,
    assert_plan_shape,
    build_turn_plan,
    canonical_rule_snapshot_json,
    normalize_participant_ids,
    plan_turns,
    rule_snapshot,
)
from .service import (
    claim_debate_job,
    commit_start_plan,
    create_debate_draft,
    get_debate,
    list_debates,
    require_teacher_course,
    update_debate_draft,
)

__all__ = [
    "AudioSwapRecovery",
    "AudioSwapRequest",
    "AudioSwapState",
    "RuleViolation",
    "assert_plan_shape",
    "build_turn_plan",
    "canonical_rule_snapshot_json",
    "claim_debate_job",
    "commit_start_plan",
    "create_audio_swap_journal",
    "create_debate_draft",
    "get_debate",
    "list_debates",
    "normalize_participant_ids",
    "plan_turns",
    "prepare_audio_swap_journal",
    "recover_audio_swap",
    "require_teacher_course",
    "rule_snapshot",
    "transition_audio_swap",
    "update_debate_draft",
]
