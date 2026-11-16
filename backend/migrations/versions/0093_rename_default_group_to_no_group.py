"""Rename default groups and add missing student memberships without deleting rows.

Only active students are backfilled; deactivated accounts remain untouched.
Downgrade intentionally preserves data: the prior names cannot be inferred safely.
"""

import logging
from collections.abc import Sequence
from uuid import UUID, uuid5

import sqlalchemy as sa
from alembic import op

revision: str = "0093_default_group_no_group"
down_revision: str | Sequence[str] | None = "0092_repair_feedback_v2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Freeze migration identities and names independently of future application changes.
_NAMESPACE = UUID("a7cea9e2-390f-5b48-b129-4f388b0362e3")
_DEMO = "7813f937-902c-5534-bfb2-ad773a43aeda"
_FIRST = "b1ae79ed-e4a6-5b02-9abd-3a3ae944284b"
_SECOND = str(uuid5(_NAMESPACE, "class-maya1002"))
_NAME = "No Group"
_KEY = "no group"
logger = logging.getLogger("alembic.runtime.migration")


def upgrade() -> None:
    connection = op.get_bind()
    candidates = connection.execute(
        sa.text(
            "SELECT id, course_id FROM groups WHERE id = :demo OR name = 'Students' "
            "ORDER BY CASE WHEN id = :demo THEN 0 ELSE 1 END, id"
        ),
        {"demo": _DEMO},
    ).all()
    skipped = 0
    for group_id, course_id in candidates:
        conflict = connection.scalar(
            sa.text(
                "SELECT id FROM groups WHERE course_id = :course AND id <> :id "
                "AND (name_key = :key OR lower(name) = :key) LIMIT 1"
            ),
            {"course": course_id, "id": group_id, "key": _KEY},
        )
        if conflict is not None:
            skipped += 1
            continue
        connection.execute(
            sa.text("UPDATE groups SET name = :name, name_key = :key WHERE id = :id"),
            {"name": _NAME, "key": _KEY, "id": group_id},
        )
    if skipped:
        logger.warning("default_group_rename_conflict_skipped count=%d", skipped)

    for course_id in connection.scalars(sa.text("SELECT id FROM courses ORDER BY id")).all():
        group_id = connection.scalar(
            sa.text(
                "SELECT id FROM groups WHERE course_id = :course "
                "AND (name_key = :key OR lower(name) = :key)"
            ),
            {"course": course_id, "key": _KEY},
        )
        if group_id is None:
            group_id = (
                _DEMO
                if course_id == _FIRST
                else str(uuid5(_NAMESPACE, "class-maya1002-students"))
                if course_id == _SECOND
                else str(uuid5(_NAMESPACE, f"class-students-{course_id}"))
            )
            connection.execute(
                sa.text(
                    "INSERT INTO groups (id, course_id, name, name_key, created_at) "
                    "VALUES (:id, :course, :name, :key, CURRENT_TIMESTAMP)"
                ),
                {"id": group_id, "course": course_id, "name": _NAME, "key": _KEY},
            )
        connection.execute(
            sa.text(
                "INSERT INTO group_members (group_id, user_id, role, created_at) "
                "SELECT :group, cm.user_id, 'member', CURRENT_TIMESTAMP "
                "FROM course_members cm JOIN users u ON u.id = cm.user_id "
                "WHERE cm.course_id = :course AND cm.role = 'student' AND u.status = 'active' "
                "AND NOT EXISTS (SELECT 1 FROM group_members gm "
                "JOIN groups g ON g.id = gm.group_id "
                "WHERE gm.user_id = cm.user_id AND g.course_id = cm.course_id) "
                "ON CONFLICT (group_id, user_id) DO NOTHING"
            ),
            {"group": group_id, "course": course_id},
        )


def downgrade() -> None:
    pass
