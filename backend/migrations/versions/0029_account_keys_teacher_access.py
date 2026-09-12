"""Persist canonical account/group keys and independent teacher workspace access."""

import unicodedata

import sqlalchemy as sa
from alembic import op

revision = "0029_account_keys_teacher_access"
down_revision = "0028_student_self_registration"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    # Freeze normalization here so future application edits cannot alter a migration.
    users = [
        (row.id, unicodedata.normalize("NFKC", row.username).strip().casefold())
        for row in connection.execute(sa.text("SELECT id, username FROM users"))
    ]
    groups = [
        (
            row.id,
            row.course_id,
            " ".join(unicodedata.normalize("NFKC", row.name).split()).casefold(),
        )
        for row in connection.execute(sa.text("SELECT id, course_id, name FROM groups"))
    ]
    if len({key for _, key in users}) != len(users) or any(not key for _, key in users):
        raise RuntimeError(
            "Canonical username collision requires explicit resolution before upgrade"
        )
    if len({(course, key) for _, course, key in groups}) != len(groups) or any(
        not key for _, _, key in groups
    ):
        raise RuntimeError("Canonical group collision requires explicit resolution before upgrade")

    # Add/backfill in place; rebuilding users or groups would disturb foreign keys.
    op.add_column(
        "users", sa.Column("username_key", sa.String(240), nullable=False, server_default="")
    )
    op.add_column(
        "groups", sa.Column("name_key", sa.String(400), nullable=False, server_default="")
    )
    for user_id, key in users:
        connection.execute(
            sa.text("UPDATE users SET username_key = :key WHERE id = :id"),
            {"key": key, "id": user_id},
        )
    for group_id, _course, key in groups:
        connection.execute(
            sa.text("UPDATE groups SET name_key = :key WHERE id = :id"),
            {"key": key, "id": group_id},
        )
    op.create_index("uq_users_username_key", "users", ["username_key"], unique=True)
    op.create_index("uq_groups_course_name_key", "groups", ["course_id", "name_key"], unique=True)
    op.create_table(
        "teacher_group_access",
        sa.Column(
            "group_id",
            sa.String(36),
            sa.ForeignKey("groups.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.execute("""
        INSERT INTO teacher_group_access (group_id, user_id, created_at)
        SELECT gm.group_id, gm.user_id, gm.created_at
        FROM group_members gm
        JOIN groups g ON g.id = gm.group_id
        JOIN course_members cm ON cm.course_id = g.course_id AND cm.user_id = gm.user_id
        WHERE cm.role = 'teacher'
    """)
    op.execute("""
        DELETE FROM group_members WHERE EXISTS (
            SELECT 1 FROM teacher_group_access a
            WHERE a.group_id = group_members.group_id AND a.user_id = group_members.user_id
        )
    """)


def downgrade() -> None:
    op.execute("""
        INSERT OR IGNORE INTO group_members (group_id, user_id, role, created_at)
        SELECT group_id, user_id, 'member', created_at FROM teacher_group_access
    """)
    op.drop_table("teacher_group_access")
    op.drop_index("uq_groups_course_name_key", table_name="groups")
    op.drop_index("uq_users_username_key", table_name="users")
    op.execute("ALTER TABLE groups DROP COLUMN name_key")
    op.execute("ALTER TABLE users DROP COLUMN username_key")
