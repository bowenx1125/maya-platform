"""Read-only workspace scope combining student membership and teacher access."""

from sqlalchemy import func, literal, select, union
from sqlalchemy.orm import aliased

from app.core.models import CourseMember, Group, GroupMember, TeacherGroupAccess, User

# An expired visit or a teacher who is no longer active must not answer as a
# member, even in the minute before the sweeper deletes the row.
_workspace_members = union(
    select(GroupMember.group_id, GroupMember.user_id, GroupMember.role, GroupMember.created_at),
    select(
        TeacherGroupAccess.group_id,
        TeacherGroupAccess.user_id,
        literal("member").label("role"),
        TeacherGroupAccess.created_at,
    )
    .join(Group, Group.id == TeacherGroupAccess.group_id)
    .join(CourseMember, CourseMember.course_id == Group.course_id)
    .join(User, User.id == TeacherGroupAccess.user_id)
    .where(
        CourseMember.user_id == TeacherGroupAccess.user_id,
        CourseMember.role == "teacher",
        User.status == "active",
        TeacherGroupAccess.expires_at > func.now(),
    ),
).subquery("workspace_members")

# Used only in reads. Teacher access is never written into catalog-owned membership.
WorkspaceMember = aliased(GroupMember, _workspace_members, adapt_on_names=True)
