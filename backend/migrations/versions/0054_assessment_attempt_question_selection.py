"""Pin each Assessment attempt to its current Question selection revision."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0054_assessment_attempt_question_selection"
down_revision: str | Sequence[str] | None = "0053_user_profile"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _begin() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite" and not bind.connection.driver_connection.in_transaction:
        bind.exec_driver_sql("BEGIN IMMEDIATE")


def upgrade() -> None:
    _begin()
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        bind.exec_driver_sql(
            "ALTER TABLE assessment_attempts ADD COLUMN "
            "question_selection_revision INTEGER NOT NULL DEFAULT 1 "
            "CHECK (question_selection_revision >= 1)"
        )
    else:
        op.add_column(
            "assessment_attempts",
            sa.Column(
                "question_selection_revision",
                sa.Integer(),
                nullable=False,
                server_default="1",
            ),
        )
        op.create_check_constraint(
            "ck_assessment_attempt_question_selection_revision",
            "assessment_attempts",
            "question_selection_revision >= 1",
        )
    op.execute(
        sa.text(
            """
            UPDATE assessment_attempts
            SET question_selection_revision = COALESCE(
                (
                    SELECT MAX(activity_question.selection_revision)
                    FROM assessment_attempt_questions AS attempt_question
                    JOIN assessment_activity_questions AS activity_question
                      ON activity_question.id = attempt_question.activity_question_id
                    WHERE attempt_question.attempt_id = assessment_attempts.id
                ),
                (
                    SELECT activity.question_selection_revision
                    FROM assessment_activities AS activity
                    WHERE activity.id = assessment_attempts.activity_id
                ),
                1
            )
            """
        )
    )


def downgrade() -> None:
    _begin()
    bind = op.get_bind()
    unsafe = bind.execute(
        sa.text(
            """
            SELECT 1
            FROM assessment_attempts AS attempt
            WHERE EXISTS (
                SELECT 1
                FROM assessment_attempt_questions AS attempt_question
                JOIN assessment_activity_questions AS activity_question
                  ON activity_question.id = attempt_question.activity_question_id
                WHERE attempt_question.attempt_id = attempt.id
                  AND activity_question.selection_revision
                      != attempt.question_selection_revision
            )
            LIMIT 1
            """
        )
    ).first()
    if unsafe is not None:
        raise RuntimeError(
            "Cannot downgrade assessment question generations without making old answers current."
        )
    if bind.dialect.name == "sqlite":
        bind.exec_driver_sql(
            "ALTER TABLE assessment_attempts DROP COLUMN question_selection_revision"
        )
    else:
        op.drop_constraint(
            "ck_assessment_attempt_question_selection_revision",
            "assessment_attempts",
            type_="check",
        )
        op.drop_column("assessment_attempts", "question_selection_revision")
