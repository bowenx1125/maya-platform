"""Raise LLM accepted-stage attempt caps for teacher Preview Retry.

Structure repair stays at attempts 1–2. Teacher Retry of a spent failed turn
must open attempt 3+ into a new provider_operation so an immutable accepted
bundle on the spent row is never overwritten.
"""

from alembic import op

revision = "0095_llm_stage_attempt_cap"
down_revision = "0094_agent_debate_cards"
branch_labels = None
depends_on = None

_NEW = "attempt_no >= 1 AND attempt_no <= 32"
_OLD = "attempt_no >= 1 AND attempt_no <= 2"


def upgrade() -> None:
    op.drop_constraint("ck_llm_stages_attempt", "llm_accepted_stages", type_="check")
    op.create_check_constraint("ck_llm_stages_attempt", "llm_accepted_stages", _NEW)
    op.drop_constraint("ck_llm_recovery_inputs_attempt", "llm_recovery_inputs", type_="check")
    op.create_check_constraint("ck_llm_recovery_inputs_attempt", "llm_recovery_inputs", _NEW)


def downgrade() -> None:
    op.drop_constraint("ck_llm_stages_attempt", "llm_accepted_stages", type_="check")
    op.create_check_constraint("ck_llm_stages_attempt", "llm_accepted_stages", _OLD)
    op.drop_constraint("ck_llm_recovery_inputs_attempt", "llm_recovery_inputs", type_="check")
    op.create_check_constraint("ck_llm_recovery_inputs_attempt", "llm_recovery_inputs", _OLD)
