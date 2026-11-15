"""Verify deployed profile group resolution without authentication or writes.

From the server checkout, run inside the already-running backend container:
    docker exec -i maya-production-backend-1 python - < scripts/verify_profile_groups.py
"""

from app.core.config import get_settings
from app.core.db import registered_metadata
from app.core.identity import group_name_key
from app.core.models import Course, CourseMember, Group, GroupMember, User
from app.modules.auth.identity_choice import student_landing_group
from app.modules.auth.models import DemoAccountBinding
from app.modules.auth.profile import resolve_student_group
from app.seed import BOWEN_ID, COURSE_ID
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session


def verify(db: Session) -> None:
    assert db.scalar(text("SHOW transaction_read_only")) == "on"
    course = db.get(Course, COURSE_ID)
    bowen = db.scalar(select(User).where(User.username_key == "bowen"))
    assert course is not None and course.name == "Maya1002"
    assert bowen is not None and bowen.id == BOWEN_ID and bowen.status == "active"
    membership = db.get(CourseMember, (course.id, bowen.id))
    assert membership is not None and membership.role == "student"
    groups = list(
        db.scalars(select(Group).where(Group.course_id == course.id).order_by(Group.id))
    )
    assert groups
    for group in groups:
        assert group.name_key == group_name_key(group.name), (
            "Persisted group key mismatch"
        )
        assert (
            resolve_student_group(db, bowen, group.name, course_id=course.id).id
            == group.id
        )
    five = resolve_student_group(db, bowen, "5", course_id=course.id)
    print(
        f"PASS Maya1002 existing groups: {len(groups)}; all real ids and name keys resolve"
    )
    print(f"PASS Maya1002 switch validation: 5 -> {five.id}")
    binding = db.scalar(
        select(DemoAccountBinding).where(
            DemoAccountBinding.user_id == bowen.id, DemoAccountBinding.active.is_(True)
        )
    )
    landing = student_landing_group(db, bowen, course.id)
    if landing is None:
        print(
            "Bowen Maya1002 landing: none (no existing membership; no grant restored)"
        )
    else:
        assert db.get(GroupMember, (landing.id, bowen.id)) is not None
        saved = binding is not None and binding.selected_group_id == landing.id
        print(
            f"Bowen Maya1002 landing: {landing.name} -> {landing.id}; saved_choice={saved}"
        )
    assert not db.new and not db.dirty and not db.deleted


def main() -> None:
    registered_metadata()
    engine = create_engine(get_settings().database_url, echo=False)
    try:
        with Session(engine, autoflush=False) as db:
            try:
                db.execute(
                    text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                )
                verify(db)
            finally:
                db.rollback()
                print(
                    "ROLLBACK; read-only verification ended; no session or token created"
                )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
