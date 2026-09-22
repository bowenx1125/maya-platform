from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import not_found
from app.core.models import CourseMember
from app.modules.auth.service import AuthContext


def course_member(
    db: Session, context: AuthContext, course_id: str, *, teacher: bool = False
) -> CourseMember:
    row = db.scalar(
        select(CourseMember).where(
            CourseMember.course_id == course_id,
            CourseMember.user_id == context.user.id,
        )
    )
    if row is None or (teacher and row.role != "teacher"):
        raise not_found()
    return row
