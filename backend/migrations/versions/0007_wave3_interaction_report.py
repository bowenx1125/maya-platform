# ruff: noqa: E501
"""wave3_interaction_report

Revision ID: 0007_wave3_interaction_report
Revises: 0006_pre_wave3_polish
Frozen for Wave 3: 2026-08-29

"""

from collections.abc import Sequence
from uuid import NAMESPACE_URL, uuid5

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007_wave3_interaction_report"
down_revision: str | Sequence[str] | None = "0006_pre_wave3_polish"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_WAVE3_OPERATIONS = (
    "interaction.open",
    "interaction.close",
    "report.generate",
    "translation.generate",
)


def _backfill_interaction_windows() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT id, course_id, created_at, updated_at FROM debates ORDER BY created_at, id")
    ).mappings()
    interaction_windows = sa.table(
        "classroom_interaction_windows",
        sa.column("id", sa.String(36)),
        sa.column("debate_id", sa.String(36)),
        sa.column("course_id", sa.String(36)),
        sa.column("status", sa.String(16)),
        sa.column("token_nonce", sa.LargeBinary(32)),
        sa.column("revision", sa.Integer()),
        sa.column("opened_by", sa.String(36)),
        sa.column("opened_at", sa.DateTime(timezone=True)),
        sa.column("finalized_by", sa.String(36)),
        sa.column("finalized_at", sa.DateTime(timezone=True)),
        sa.column("frozen_barrage_ids_json", sa.Text()),
        sa.column("frozen_barrage_input_hash", sa.String(64)),
        sa.column("frozen_vote_totals_json", sa.Text()),
        sa.column("frozen_vote_input_hash", sa.String(64)),
        sa.column("frozen_barrage_count", sa.Integer()),
        sa.column("frozen_vote_count", sa.Integer()),
        # SQLite's historical DateTime adapter returns text for raw migration
        # SELECTs.  Bind these two values as text so their exact representation
        # is preserved instead of passing them through the DateTime processor.
        sa.column("created_at", sa.String()),
        sa.column("updated_at", sa.String()),
    )
    payload = [
        {
            "id": str(uuid5(NAMESPACE_URL, f"maya:interaction:{row['id']}")),
            "debate_id": row["id"],
            "course_id": row["course_id"],
            "status": "closed",
            "token_nonce": None,
            "revision": 0,
            "opened_by": None,
            "opened_at": None,
            "finalized_by": None,
            "finalized_at": None,
            "frozen_barrage_ids_json": None,
            "frozen_barrage_input_hash": None,
            "frozen_vote_totals_json": None,
            "frozen_vote_input_hash": None,
            "frozen_barrage_count": None,
            "frozen_vote_count": None,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]
    if payload:
        op.bulk_insert(interaction_windows, payload)


def _upgrade_jobs() -> None:
    with op.batch_alter_table("jobs", recreate="always") as batch:
        batch.add_column(sa.Column("insight_snapshot_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("report_revision_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("translation_batch_id", sa.String(36), nullable=True))
        batch.create_foreign_key(
            "fk_jobs_insight_snapshot",
            "barrage_insight_snapshots",
            ["insight_snapshot_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.create_foreign_key(
            "fk_jobs_report_revision",
            "civilization_report_revisions",
            ["report_revision_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.create_foreign_key(
            "fk_jobs_translation_batch",
            "translation_batches",
            ["translation_batch_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.create_check_constraint(
            "ck_jobs_wave3_typed_owner",
            "(operation = 'barrage_insight.generate' AND insight_snapshot_id IS NOT NULL "
            "AND report_revision_id IS NULL AND translation_batch_id IS NULL) OR "
            "(operation = 'report.generate' AND insight_snapshot_id IS NULL "
            "AND report_revision_id IS NOT NULL AND translation_batch_id IS NULL) OR "
            "(operation = 'translation.generate' AND insight_snapshot_id IS NULL "
            "AND report_revision_id IS NULL AND translation_batch_id IS NOT NULL) OR "
            "(operation NOT IN ('barrage_insight.generate', 'report.generate', "
            "'translation.generate') AND insight_snapshot_id IS NULL "
            "AND report_revision_id IS NULL AND translation_batch_id IS NULL)",
        )
        batch.create_index(
            "uq_jobs_insight_snapshot",
            ["insight_snapshot_id"],
            unique=True,
            sqlite_where=sa.text("insight_snapshot_id IS NOT NULL"),
        )
        batch.create_index(
            "uq_jobs_report_revision",
            ["report_revision_id"],
            unique=True,
            sqlite_where=sa.text("report_revision_id IS NOT NULL"),
        )
        batch.create_index(
            "uq_jobs_translation_batch",
            ["translation_batch_id"],
            unique=True,
            sqlite_where=sa.text("translation_batch_id IS NOT NULL"),
        )


def _downgrade_jobs() -> None:
    with op.batch_alter_table("jobs", recreate="always") as batch:
        batch.drop_index("uq_jobs_translation_batch")
        batch.drop_index("uq_jobs_report_revision")
        batch.drop_index("uq_jobs_insight_snapshot")
        batch.drop_constraint("ck_jobs_wave3_typed_owner", type_="check")
        batch.drop_constraint("fk_jobs_translation_batch", type_="foreignkey")
        batch.drop_constraint("fk_jobs_report_revision", type_="foreignkey")
        batch.drop_constraint("fk_jobs_insight_snapshot", type_="foreignkey")
        batch.drop_column("translation_batch_id")
        batch.drop_column("report_revision_id")
        batch.drop_column("insight_snapshot_id")


def upgrade() -> None:
    """Upgrade schema."""
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "civilization_reports",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("debate_id", sa.String(length=36), nullable=False),
        sa.Column("generation_status", sa.String(length=16), nullable=False),
        sa.Column("latest_attempt_status", sa.String(length=16), nullable=False),
        sa.Column("policy_key", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "generation_status IN ('not_started', 'generating', 'ready', 'failed')",
            name="ck_civilization_reports_generation_status",
        ),
        sa.CheckConstraint(
            "latest_attempt_status IN ('not_started', 'generating', 'ready', 'failed')",
            name="ck_civilization_reports_latest_status",
        ),
        sa.ForeignKeyConstraint(["debate_id"], ["debates.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("debate_id"),
        sa.UniqueConstraint("id", "debate_id", name="uq_civilization_reports_id_debate"),
    )
    op.create_index(
        "ix_civilization_reports_debate", "civilization_reports", ["debate_id"], unique=True
    )
    op.create_table(
        "classroom_interaction_windows",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("debate_id", sa.String(length=36), nullable=False),
        sa.Column("course_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("token_nonce", sa.LargeBinary(length=32), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("opened_by", sa.String(length=36), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finalized_by", sa.String(length=36), nullable=True),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("frozen_barrage_ids_json", sa.Text(), nullable=True),
        sa.Column("frozen_barrage_input_hash", sa.String(length=64), nullable=True),
        sa.Column("frozen_vote_totals_json", sa.Text(), nullable=True),
        sa.Column("frozen_vote_input_hash", sa.String(length=64), nullable=True),
        sa.Column("frozen_barrage_count", sa.Integer(), nullable=True),
        sa.Column("frozen_vote_count", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status <> 'closed' OR (token_nonce IS NULL AND opened_by IS NULL AND opened_at IS NULL AND finalized_by IS NULL AND finalized_at IS NULL AND frozen_barrage_ids_json IS NULL AND frozen_barrage_input_hash IS NULL AND frozen_vote_totals_json IS NULL AND frozen_vote_input_hash IS NULL AND frozen_barrage_count IS NULL AND frozen_vote_count IS NULL)",
            name="ck_interaction_windows_closed_shape",
        ),
        sa.CheckConstraint(
            "status <> 'finalized' OR (token_nonce IS NOT NULL AND opened_by IS NOT NULL AND opened_at IS NOT NULL AND finalized_by IS NOT NULL AND finalized_at IS NOT NULL AND frozen_barrage_ids_json IS NOT NULL AND frozen_barrage_input_hash IS NOT NULL AND frozen_vote_totals_json IS NOT NULL AND frozen_vote_input_hash IS NOT NULL AND frozen_barrage_count IS NOT NULL AND frozen_vote_count IS NOT NULL)",
            name="ck_interaction_windows_finalized_shape",
        ),
        sa.CheckConstraint(
            "status <> 'open' OR (token_nonce IS NOT NULL AND opened_by IS NOT NULL AND opened_at IS NOT NULL AND finalized_by IS NULL AND finalized_at IS NULL AND frozen_barrage_ids_json IS NULL AND frozen_barrage_input_hash IS NULL AND frozen_vote_totals_json IS NULL AND frozen_vote_input_hash IS NULL AND frozen_barrage_count IS NULL AND frozen_vote_count IS NULL)",
            name="ck_interaction_windows_open_shape",
        ),
        sa.CheckConstraint(
            "status IN ('closed', 'open', 'finalized')", name="ck_interaction_windows_status"
        ),
        sa.CheckConstraint(
            "frozen_barrage_count IS NULL OR frozen_barrage_count >= 0",
            name="ck_interaction_windows_barrage_count",
        ),
        sa.CheckConstraint(
            "frozen_vote_count IS NULL OR frozen_vote_count >= 0",
            name="ck_interaction_windows_vote_count",
        ),
        sa.CheckConstraint("revision >= 0", name="ck_interaction_windows_revision"),
        sa.CheckConstraint(
            "token_nonce IS NULL OR length(token_nonce) = 32",
            name="ck_interaction_windows_nonce_shape",
        ),
        sa.ForeignKeyConstraint(
            ["course_id", "finalized_by"],
            ["course_members.course_id", "course_members.user_id"],
            name="fk_interaction_windows_finalized_by_teacher",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["course_id", "opened_by"],
            ["course_members.course_id", "course_members.user_id"],
            name="fk_interaction_windows_opened_by_teacher",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["debate_id", "course_id"],
            ["debates.id", "debates.course_id"],
            name="fk_interaction_windows_debate_course",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("debate_id"),
        sa.UniqueConstraint("id", "debate_id", name="uq_interaction_windows_id_debate"),
    )
    op.create_index(
        "ix_interaction_windows_course_status",
        "classroom_interaction_windows",
        ["course_id", "status"],
        unique=False,
    )
    op.create_index(
        "uq_interaction_windows_nonce",
        "classroom_interaction_windows",
        ["token_nonce"],
        unique=True,
    )
    _backfill_interaction_windows()
    op.create_table(
        "translation_batches",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("debate_id", sa.String(length=36), nullable=False),
        sa.Column("course_id", sa.String(length=36), nullable=False),
        sa.Column("requested_by", sa.String(length=36), nullable=False),
        sa.Column("target_language", sa.String(length=16), nullable=False),
        sa.Column("policy_key", sa.String(length=80), nullable=False),
        sa.Column("quality_key", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("manifest_json", sa.Text(), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("total_items", sa.Integer(), nullable=False),
        sa.Column("succeeded_items", sa.Integer(), nullable=False),
        sa.Column("failed_items", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(status IN ('pending', 'running') AND succeeded_items + failed_items <= total_items) OR (status = 'completed' AND total_items = succeeded_items AND failed_items = 0) OR (status = 'failed' AND total_items = failed_items AND succeeded_items = 0) OR (status = 'partial' AND total_items = succeeded_items + failed_items AND succeeded_items > 0 AND failed_items > 0)",
            name="ck_translation_batches_terminal_counts",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'partial', 'failed')",
            name="ck_translation_batches_status",
        ),
        sa.CheckConstraint("target_language = 'zh-Hans'", name="ck_translation_batches_target"),
        sa.CheckConstraint("length(input_hash) = 64", name="ck_translation_batches_hash_shape"),
        sa.CheckConstraint(
            "total_items >= 0 AND succeeded_items >= 0 AND failed_items >= 0",
            name="ck_translation_batches_counts_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["course_id", "requested_by"],
            ["course_members.course_id", "course_members.user_id"],
            name="fk_translation_batches_requester_course",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["debate_id", "course_id"],
            ["debates.id", "debates.course_id"],
            name="fk_translation_batches_debate_course",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "debate_id", name="uq_translation_batches_id_debate"),
    )
    op.create_index(
        "ix_translation_batches_debate_created",
        "translation_batches",
        ["debate_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "uq_translation_batches_active_fence",
        "translation_batches",
        ["debate_id", "input_hash", "target_language"],
        unique=True,
        sqlite_where=sa.text("status IN ('pending', 'running')"),
    )
    op.create_table(
        "barrage_insight_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("window_id", sa.String(length=36), nullable=False),
        sa.Column("debate_id", sa.String(length=36), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("policy_key", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("included_count", sa.Integer(), nullable=False),
        sa.Column("filtered_count", sa.Integer(), nullable=False),
        sa.Column("safe_error_code", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(input_hash) = 64 AND input_hash NOT GLOB '*[^0-9a-f]*'",
            name="ck_barrage_insight_snapshots_input_hash",
        ),
        sa.CheckConstraint(
            "status != 'failed' OR (included_count = 0 AND filtered_count = 0 AND safe_error_code IS NOT NULL)",
            name="ck_barrage_insight_snapshots_failed_error",
        ),
        sa.CheckConstraint(
            "status != 'generating' OR (included_count = 0 AND filtered_count = 0 AND safe_error_code IS NULL)",
            name="ck_barrage_insight_snapshots_generating_shape",
        ),
        sa.CheckConstraint(
            "status != 'ready' OR safe_error_code IS NULL",
            name="ck_barrage_insight_snapshots_ready_error",
        ),
        sa.CheckConstraint(
            "status IN ('generating', 'ready', 'failed')",
            name="ck_barrage_insight_snapshots_status",
        ),
        sa.CheckConstraint(
            "attempt >= 1 AND attempt <= 2", name="ck_barrage_insight_snapshots_attempt"
        ),
        sa.CheckConstraint(
            "filtered_count >= 0", name="ck_barrage_insight_snapshots_filtered_count"
        ),
        sa.CheckConstraint(
            "included_count >= 0", name="ck_barrage_insight_snapshots_included_count"
        ),
        sa.ForeignKeyConstraint(
            ["debate_id"],
            ["debates.id"],
            name="fk_barrage_insight_snapshots_debate",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["window_id", "debate_id"],
            ["classroom_interaction_windows.id", "classroom_interaction_windows.debate_id"],
            name="fk_barrage_insight_snapshots_window_debate",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "debate_id", "revision_no", name="uq_barrage_insight_snapshots_debate_revision"
        ),
        sa.UniqueConstraint("id", "debate_id", name="uq_barrage_insight_snapshots_id_debate"),
        sa.UniqueConstraint(
            "id", "window_id", "debate_id", name="uq_barrage_insight_snapshots_id_window_debate"
        ),
    )
    op.create_index(
        "ix_barrage_insight_snapshots_active",
        "barrage_insight_snapshots",
        ["debate_id"],
        unique=True,
        sqlite_where=sa.text("status = 'generating'"),
    )
    op.create_index(
        "ix_barrage_insight_snapshots_debate",
        "barrage_insight_snapshots",
        ["debate_id", "revision_no"],
        unique=False,
    )
    op.create_table(
        "barrage_messages",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("window_id", sa.String(length=36), nullable=False),
        sa.Column("debate_id", sa.String(length=36), nullable=False),
        sa.Column("nickname", sa.Text(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("client_submission_id", sa.String(length=36), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(trim(nickname)) > 0", name="ck_barrage_messages_nickname_nonblank"
        ),
        sa.CheckConstraint("length(trim(raw_text)) > 0", name="ck_barrage_messages_text_nonblank"),
        sa.ForeignKeyConstraint(
            ["window_id", "debate_id"],
            ["classroom_interaction_windows.id", "classroom_interaction_windows.debate_id"],
            name="fk_barrage_messages_window_debate",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "window_id", "debate_id", name="uq_barrage_messages_scoped_id"),
        sa.UniqueConstraint(
            "window_id", "client_submission_id", name="uq_barrage_messages_window_submission"
        ),
        sa.UniqueConstraint("window_id", "sequence", name="uq_barrage_messages_window_sequence"),
    )
    op.create_index(
        "ix_barrage_messages_window_sequence",
        "barrage_messages",
        ["window_id", "sequence"],
        unique=False,
    )
    op.create_table(
        "barrage_insight_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("window_id", sa.String(length=36), nullable=False),
        sa.Column("debate_id", sa.String(length=36), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(length=16), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "category IN ('support', 'challenge', 'question')",
            name="ck_barrage_insight_items_category",
        ),
        sa.CheckConstraint("length(trim(summary)) > 0", name="ck_barrage_insight_items_summary"),
        sa.CheckConstraint("order_index >= 0", name="ck_barrage_insight_items_order"),
        sa.ForeignKeyConstraint(
            ["snapshot_id", "window_id", "debate_id"],
            [
                "barrage_insight_snapshots.id",
                "barrage_insight_snapshots.window_id",
                "barrage_insight_snapshots.debate_id",
            ],
            name="fk_barrage_insight_items_snapshot_scope",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "snapshot_id",
            "window_id",
            "debate_id",
            name="uq_barrage_insight_items_id_snapshot_scope",
        ),
        sa.UniqueConstraint(
            "snapshot_id", "order_index", name="uq_barrage_insight_items_snapshot_order"
        ),
    )
    op.create_index(
        "ix_barrage_insight_items_snapshot",
        "barrage_insight_items",
        ["snapshot_id", "order_index"],
        unique=False,
    )
    op.create_table(
        "civilization_report_revisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("report_id", sa.String(length=36), nullable=False),
        sa.Column("debate_id", sa.String(length=36), nullable=False),
        sa.Column("insight_snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("input_manifest_json", sa.Text(), nullable=False),
        sa.Column("input_manifest_hash", sa.String(length=64), nullable=False),
        sa.Column("english_markdown", sa.Text(), nullable=True),
        sa.Column("word_count", sa.Integer(), nullable=True),
        sa.Column("safe_error_code", sa.String(length=80), nullable=True),
        sa.Column("trigger", sa.String(length=32), nullable=False),
        sa.Column("requested_by", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(input_manifest_hash) = 64 AND input_manifest_hash NOT GLOB '*[^0-9a-f]*'",
            name="ck_civilization_report_revisions_input_hash",
        ),
        sa.CheckConstraint(
            "status != 'failed' OR (english_markdown IS NULL AND word_count IS NULL AND safe_error_code IS NOT NULL)",
            name="ck_civilization_report_revisions_failed_shape",
        ),
        sa.CheckConstraint(
            "status != 'generating' OR (english_markdown IS NULL AND word_count IS NULL AND safe_error_code IS NULL)",
            name="ck_civilization_report_revisions_generating_shape",
        ),
        sa.CheckConstraint(
            "status != 'ready' OR (english_markdown IS NOT NULL AND word_count >= 600 AND word_count <= 900 AND safe_error_code IS NULL)",
            name="ck_civilization_report_revisions_ready_shape",
        ),
        sa.CheckConstraint(
            "status IN ('generating', 'ready', 'failed')",
            name="ck_civilization_report_revisions_status",
        ),
        sa.CheckConstraint(
            "attempt >= 1 AND attempt <= 2", name="ck_civilization_report_revisions_attempt"
        ),
        sa.ForeignKeyConstraint(
            ["insight_snapshot_id", "debate_id"],
            ["barrage_insight_snapshots.id", "barrage_insight_snapshots.debate_id"],
            name="fk_civilization_report_revisions_insight_debate",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["report_id", "debate_id"],
            ["civilization_reports.id", "civilization_reports.debate_id"],
            name="fk_civilization_report_revisions_report_debate",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "debate_id", name="uq_civilization_report_revisions_id_debate"),
        sa.UniqueConstraint(
            "id",
            "report_id",
            "debate_id",
            "status",
            name="uq_civilization_report_revisions_id_scope_status",
        ),
        sa.UniqueConstraint(
            "id", "report_id", "debate_id", name="uq_civilization_report_revisions_id_scope"
        ),
        sa.UniqueConstraint(
            "report_id", "revision_no", name="uq_civilization_report_revisions_report_revision"
        ),
    )
    op.create_index(
        "ix_civilization_report_revisions_active",
        "civilization_report_revisions",
        ["debate_id"],
        unique=True,
        sqlite_where=sa.text("status = 'generating'"),
    )
    op.create_index(
        "ix_civilization_report_revisions_debate",
        "civilization_report_revisions",
        ["debate_id", "revision_no"],
        unique=False,
    )
    op.create_table(
        "interaction_final_barrages",
        sa.Column("window_id", sa.String(length=36), nullable=False),
        sa.Column("debate_id", sa.String(length=36), nullable=False),
        sa.Column("barrage_message_id", sa.String(length=36), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.CheckConstraint("sequence >= 1", name="ck_final_barrages_sequence"),
        sa.ForeignKeyConstraint(
            ["barrage_message_id", "window_id", "debate_id"],
            ["barrage_messages.id", "barrage_messages.window_id", "barrage_messages.debate_id"],
            name="fk_final_barrages_message_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["window_id", "debate_id"],
            ["classroom_interaction_windows.id", "classroom_interaction_windows.debate_id"],
            name="fk_final_barrages_window_debate",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("window_id", "debate_id", "barrage_message_id"),
        sa.UniqueConstraint(
            "window_id", "barrage_message_id", name="uq_final_barrages_window_message"
        ),
        sa.UniqueConstraint("window_id", "sequence", name="uq_final_barrages_window_sequence"),
    )
    op.create_table(
        "barrage_insight_assignments",
        sa.Column("snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("window_id", sa.String(length=36), nullable=False),
        sa.Column("debate_id", sa.String(length=36), nullable=False),
        sa.Column("barrage_message_id", sa.String(length=36), nullable=False),
        sa.Column("disposition", sa.String(length=16), nullable=False),
        sa.Column("item_id", sa.String(length=36), nullable=True),
        sa.Column("filter_reason", sa.String(length=120), nullable=True),
        sa.CheckConstraint(
            "(disposition = 'included' AND item_id IS NOT NULL AND filter_reason IS NULL) OR (disposition = 'filtered' AND item_id IS NULL AND filter_reason LIKE 'mock_barrage_insight_v1:%')",
            name="ck_barrage_insight_assignments_shape",
        ),
        sa.CheckConstraint(
            "disposition IN ('included', 'filtered')",
            name="ck_barrage_insight_assignments_disposition",
        ),
        sa.ForeignKeyConstraint(
            ["barrage_message_id", "window_id", "debate_id"],
            ["barrage_messages.id", "barrage_messages.window_id", "barrage_messages.debate_id"],
            name="fk_barrage_insight_assignments_barrage_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["item_id", "snapshot_id", "window_id", "debate_id"],
            [
                "barrage_insight_items.id",
                "barrage_insight_items.snapshot_id",
                "barrage_insight_items.window_id",
                "barrage_insight_items.debate_id",
            ],
            name="fk_barrage_insight_assignments_item_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id", "window_id", "debate_id"],
            [
                "barrage_insight_snapshots.id",
                "barrage_insight_snapshots.window_id",
                "barrage_insight_snapshots.debate_id",
            ],
            name="fk_barrage_insight_assignments_snapshot_scope",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("snapshot_id", "barrage_message_id"),
        sa.UniqueConstraint(
            "snapshot_id",
            "barrage_message_id",
            name="uq_barrage_insight_assignments_snapshot_message",
        ),
    )
    op.create_index(
        "ix_barrage_insight_assignments_snapshot",
        "barrage_insight_assignments",
        ["snapshot_id"],
        unique=False,
    )
    op.create_table(
        "civilization_report_current_success",
        sa.Column("report_id", sa.String(length=36), nullable=False),
        sa.Column("revision_id", sa.String(length=36), nullable=False),
        sa.Column("debate_id", sa.String(length=36), nullable=False),
        sa.Column("revision_status", sa.String(length=16), nullable=False),
        sa.CheckConstraint(
            "revision_status = 'ready'", name="ck_civilization_report_current_success_ready"
        ),
        sa.ForeignKeyConstraint(
            ["report_id", "debate_id"],
            ["civilization_reports.id", "civilization_reports.debate_id"],
            name="fk_civilization_report_current_success_report_debate",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["revision_id", "report_id", "debate_id", "revision_status"],
            [
                "civilization_report_revisions.id",
                "civilization_report_revisions.report_id",
                "civilization_report_revisions.debate_id",
                "civilization_report_revisions.status",
            ],
            name="fk_civilization_report_current_success_ready_revision",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("report_id"),
        sa.UniqueConstraint("debate_id"),
        sa.UniqueConstraint("revision_id"),
        sa.UniqueConstraint(
            "revision_id",
            "report_id",
            "debate_id",
            "revision_status",
            name="uq_civilization_report_current_success_scope",
        ),
    )
    op.create_table(
        "interaction_final_vote_counts",
        sa.Column("window_id", sa.String(length=36), nullable=False),
        sa.Column("debate_id", sa.String(length=36), nullable=False),
        sa.Column("participant_id", sa.String(length=36), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.CheckConstraint("count >= 0", name="ck_final_votes_count"),
        sa.ForeignKeyConstraint(
            ["participant_id", "debate_id"],
            ["debate_participants.id", "debate_participants.debate_id"],
            name="fk_final_votes_participant_debate",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["window_id", "debate_id"],
            ["classroom_interaction_windows.id", "classroom_interaction_windows.debate_id"],
            name="fk_final_votes_window_debate",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("window_id", "debate_id", "participant_id"),
        sa.UniqueConstraint(
            "window_id", "participant_id", name="uq_final_votes_window_participant"
        ),
    )
    op.create_table(
        "votes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("window_id", sa.String(length=36), nullable=False),
        sa.Column("debate_id", sa.String(length=36), nullable=False),
        sa.Column("participant_id", sa.String(length=36), nullable=False),
        sa.Column("client_submission_id", sa.String(length=36), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["participant_id", "debate_id"],
            ["debate_participants.id", "debate_participants.debate_id"],
            name="fk_votes_participant_debate",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["window_id", "debate_id"],
            ["classroom_interaction_windows.id", "classroom_interaction_windows.debate_id"],
            name="fk_votes_window_debate",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("window_id", "client_submission_id", name="uq_votes_window_submission"),
    )
    op.create_index(
        "ix_votes_window_participant", "votes", ["window_id", "participant_id"], unique=False
    )
    op.create_table(
        "translation_entries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("debate_id", sa.String(length=36), nullable=False),
        sa.Column("content_type", sa.String(length=24), nullable=False),
        sa.Column("turn_id", sa.String(length=36), nullable=True),
        sa.Column("report_revision_id", sa.String(length=36), nullable=True),
        sa.Column("source_text_hash", sa.String(length=64), nullable=False),
        sa.Column("target_language", sa.String(length=16), nullable=False),
        sa.Column("policy_key", sa.String(length=80), nullable=False),
        sa.Column("quality_key", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("translated_text", sa.Text(), nullable=True),
        sa.Column("safe_error_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(content_type = 'turn' AND turn_id IS NOT NULL AND report_revision_id IS NULL) OR (content_type = 'report_revision' AND turn_id IS NULL AND report_revision_id IS NOT NULL)",
            name="ck_translation_entries_content_shape",
        ),
        sa.CheckConstraint(
            "content_type IN ('turn', 'report_revision')",
            name="ck_translation_entries_content_type",
        ),
        sa.CheckConstraint(
            "status = 'ready' AND translated_text IS NOT NULL AND length(trim(translated_text)) > 0 AND safe_error_code IS NULL OR status = 'failed' AND translated_text IS NULL AND safe_error_code IS NOT NULL OR status IN ('pending', 'running') AND translated_text IS NULL AND safe_error_code IS NULL",
            name="ck_translation_entries_text_shape",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'ready', 'failed')",
            name="ck_translation_entries_status",
        ),
        sa.CheckConstraint("target_language = 'zh-Hans'", name="ck_translation_entries_target"),
        sa.ForeignKeyConstraint(
            ["report_revision_id", "debate_id"],
            ["civilization_report_revisions.id", "civilization_report_revisions.debate_id"],
            name="fk_translation_entries_report_revision",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["turn_id", "debate_id"],
            ["debate_turns.id", "debate_turns.debate_id"],
            name="fk_translation_entries_turn_debate",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "debate_id", name="uq_translation_entries_id_debate"),
    )
    op.create_index(
        "ix_translation_entries_debate", "translation_entries", ["debate_id"], unique=False
    )
    op.create_index(
        "uq_translation_entries_report_active_cache",
        "translation_entries",
        ["report_revision_id", "source_text_hash", "target_language", "policy_key", "quality_key"],
        unique=True,
        sqlite_where=sa.text("status IN ('pending', 'running') AND report_revision_id IS NOT NULL"),
    )
    op.create_index(
        "uq_translation_entries_report_ready_cache",
        "translation_entries",
        ["report_revision_id", "source_text_hash", "target_language", "policy_key", "quality_key"],
        unique=True,
        sqlite_where=sa.text("status = 'ready' AND report_revision_id IS NOT NULL"),
    )
    op.create_index(
        "uq_translation_entries_turn_active_cache",
        "translation_entries",
        ["turn_id", "source_text_hash", "target_language", "policy_key", "quality_key"],
        unique=True,
        sqlite_where=sa.text("status IN ('pending', 'running') AND turn_id IS NOT NULL"),
    )
    op.create_index(
        "uq_translation_entries_turn_ready_cache",
        "translation_entries",
        ["turn_id", "source_text_hash", "target_language", "policy_key", "quality_key"],
        unique=True,
        sqlite_where=sa.text("status = 'ready' AND turn_id IS NOT NULL"),
    )
    op.create_table(
        "translation_batch_items",
        sa.Column("batch_id", sa.String(length=36), nullable=False),
        sa.Column("entry_id", sa.String(length=36), nullable=False),
        sa.Column("debate_id", sa.String(length=36), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("reused", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("safe_error_code", sa.String(length=64), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'ready', 'failed')",
            name="ck_translation_batch_items_status",
        ),
        sa.CheckConstraint("order_index >= 0", name="ck_translation_batch_items_order"),
        sa.ForeignKeyConstraint(
            ["batch_id", "debate_id"],
            ["translation_batches.id", "translation_batches.debate_id"],
            name="fk_translation_batch_items_batch_debate",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["entry_id", "debate_id"],
            ["translation_entries.id", "translation_entries.debate_id"],
            name="fk_translation_batch_items_entry_debate",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("batch_id", "entry_id"),
        sa.UniqueConstraint("batch_id", "entry_id", name="uq_translation_batch_items_entry"),
        sa.UniqueConstraint("batch_id", "order_index", name="uq_translation_batch_items_order"),
    )
    op.create_index(
        "ix_translation_batch_items_batch",
        "translation_batch_items",
        ["batch_id", "order_index"],
        unique=False,
    )
    _upgrade_jobs()
    # ### end Alembic commands ###


def downgrade() -> None:
    """Downgrade schema."""
    # ### commands auto generated by Alembic - please adjust! ###
    operation_list = ", ".join(f"'{value}'" for value in _WAVE3_OPERATIONS)
    op.execute(sa.text(f"DELETE FROM idempotency_records WHERE operation IN ({operation_list})"))
    op.execute(
        sa.text(
            "DELETE FROM jobs WHERE operation IN "
            "('barrage_insight.generate', 'report.generate', 'translation.generate')"
        )
    )
    _downgrade_jobs()
    op.drop_index("ix_translation_batch_items_batch", table_name="translation_batch_items")
    op.drop_table("translation_batch_items")
    op.drop_index(
        "uq_translation_entries_turn_ready_cache",
        table_name="translation_entries",
        sqlite_where=sa.text("status = 'ready' AND turn_id IS NOT NULL"),
    )
    op.drop_index(
        "uq_translation_entries_turn_active_cache",
        table_name="translation_entries",
        sqlite_where=sa.text("status IN ('pending', 'running') AND turn_id IS NOT NULL"),
    )
    op.drop_index(
        "uq_translation_entries_report_ready_cache",
        table_name="translation_entries",
        sqlite_where=sa.text("status = 'ready' AND report_revision_id IS NOT NULL"),
    )
    op.drop_index(
        "uq_translation_entries_report_active_cache",
        table_name="translation_entries",
        sqlite_where=sa.text("status IN ('pending', 'running') AND report_revision_id IS NOT NULL"),
    )
    op.drop_index("ix_translation_entries_debate", table_name="translation_entries")
    op.drop_table("translation_entries")
    op.drop_index("ix_votes_window_participant", table_name="votes")
    op.drop_table("votes")
    op.drop_table("interaction_final_vote_counts")
    op.drop_table("civilization_report_current_success")
    op.drop_index(
        "ix_barrage_insight_assignments_snapshot", table_name="barrage_insight_assignments"
    )
    op.drop_table("barrage_insight_assignments")
    op.drop_table("interaction_final_barrages")
    op.drop_index(
        "ix_civilization_report_revisions_debate", table_name="civilization_report_revisions"
    )
    op.drop_index(
        "ix_civilization_report_revisions_active",
        table_name="civilization_report_revisions",
        sqlite_where=sa.text("status = 'generating'"),
    )
    op.drop_table("civilization_report_revisions")
    op.drop_index("ix_barrage_insight_items_snapshot", table_name="barrage_insight_items")
    op.drop_table("barrage_insight_items")
    op.drop_index("ix_barrage_messages_window_sequence", table_name="barrage_messages")
    op.drop_table("barrage_messages")
    op.drop_index("ix_barrage_insight_snapshots_debate", table_name="barrage_insight_snapshots")
    op.drop_index(
        "ix_barrage_insight_snapshots_active",
        table_name="barrage_insight_snapshots",
        sqlite_where=sa.text("status = 'generating'"),
    )
    op.drop_table("barrage_insight_snapshots")
    op.drop_index(
        "uq_translation_batches_active_fence",
        table_name="translation_batches",
        sqlite_where=sa.text("status IN ('pending', 'running')"),
    )
    op.drop_index("ix_translation_batches_debate_created", table_name="translation_batches")
    op.drop_table("translation_batches")
    op.drop_index("uq_interaction_windows_nonce", table_name="classroom_interaction_windows")
    op.drop_index(
        "ix_interaction_windows_course_status", table_name="classroom_interaction_windows"
    )
    op.drop_table("classroom_interaction_windows")
    op.drop_index("ix_civilization_reports_debate", table_name="civilization_reports")
    op.drop_table("civilization_reports")
    # ### end Alembic commands ###
