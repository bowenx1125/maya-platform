"""Allow repair_feedback_v2 on LLM turn export manifests."""

from collections.abc import Sequence

from alembic import op

revision: str = "0092_repair_feedback_v2"
down_revision: str | Sequence[str] | None = "0091_quiz_show_results"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_V1_HASH = "d5b81d460ecd713f4b3d52b5732efc935b63455c2a29b5a5ab2471b17d00050b"
_V2_HASH = "22ccaa931e2b17aa8b4ec6dd485ccbc864c0af37c47b32dcd070fe8cb3102ac1"

_OLD = (
    "provider_operation <> 'llm_debate_turn' OR "
    "(max_attempts = 2 AND repair_policy_version = 'repair_feedback_v1' "
    "AND repair_policy_hash = '" + _V1_HASH + "') OR "
    "(max_attempts = 1 AND repair_policy_version IS NULL "
    "AND repair_policy_hash IS NULL)"
)
_NEW = (
    "provider_operation <> 'llm_debate_turn' OR "
    "(max_attempts = 2 AND repair_policy_version = 'repair_feedback_v1' "
    "AND repair_policy_hash = '" + _V1_HASH + "') OR "
    "(max_attempts = 2 AND repair_policy_version = 'repair_feedback_v2' "
    "AND repair_policy_hash = '" + _V2_HASH + "') OR "
    "(max_attempts = 1 AND repair_policy_version IS NULL "
    "AND repair_policy_hash IS NULL)"
)


def upgrade() -> None:
    op.drop_constraint(
        "ck_provider_export_manifests_llm_retry_policy",
        "provider_export_manifests",
        type_="check",
    )
    op.create_check_constraint(
        "ck_provider_export_manifests_llm_retry_policy",
        "provider_export_manifests",
        _NEW,
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_provider_export_manifests_llm_retry_policy",
        "provider_export_manifests",
        type_="check",
    )
    op.create_check_constraint(
        "ck_provider_export_manifests_llm_retry_policy",
        "provider_export_manifests",
        _OLD,
    )
