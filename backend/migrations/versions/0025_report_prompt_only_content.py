"""Keep report length as metadata rather than a publication condition."""

from importlib import import_module

import sqlalchemy as sa
from alembic import op

revision = "0025_report_prompt_only_content"
down_revision = "0024_shared_discussion_evidence"
branch_labels = None
depends_on = None


def _replace_check(condition: str) -> None:
    with op.batch_alter_table("civilization_report_revisions", recreate="always") as batch:
        batch.drop_constraint("ck_civilization_report_revisions_ready_shape", type_="check")
        batch.create_check_constraint("ck_civilization_report_revisions_ready_shape", condition)


def upgrade() -> None:
    fence = import_module("migrations.versions.0023_segment_report_wordcount")._fenced
    fence(
        lambda: _replace_check(
            "status != 'ready' OR (english_markdown IS NOT NULL AND word_count IS NOT NULL "
            "AND word_count >= 0 AND safe_error_code IS NULL)"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    incompatible = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM civilization_report_revisions WHERE status='ready' AND "
            "(word_count < 1 OR word_count > 900 OR (word_count < 600 AND "
            "COALESCE(json_extract(input_manifest_json, '$.manifest_version'), '') "
            "<> 'report_input_manifest_v2'))"
        )
    ).scalar_one()
    if incompatible:
        raise RuntimeError("Cannot restore obsolete length checks while reports need preservation")
    fence = import_module("migrations.versions.0023_segment_report_wordcount")._fenced
    fence(
        lambda: _replace_check(
            "status != 'ready' OR (english_markdown IS NOT NULL AND word_count >= 1 "
            "AND (word_count >= 600 OR COALESCE(json_extract(input_manifest_json, "
            "'$.manifest_version'), '') = 'report_input_manifest_v2') "
            "AND word_count <= 900 AND safe_error_code IS NULL)"
        )
    )
