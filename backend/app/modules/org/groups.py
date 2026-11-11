"""Remove unused roster groups without cascading into retained work."""

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import registered_metadata
from app.core.locks import xact_lock
from app.core.models import Group, GroupMember
from app.modules.org.classes import SECOND_CLASS_GROUP_ID, default_class_group
from app.seed import GROUP_DEMO_ID, seed_uuid

IGNORED_GROUP_REFERENCES = frozenset(
    {"group_members", "teacher_group_access", "demo_account_bindings"}
)


def prune_empty_groups(db: Session, course_id: str, group_ids: Iterable[str]) -> None:
    candidates = sorted(set(group_ids))
    if not candidates:
        return
    db.flush()
    # Named joins hold this through membership insertion. A course-wide lock also
    # avoids opposite-direction moves taking old/new group locks in reverse order.
    xact_lock(db, f"course-groups:{course_id}")
    protected = {
        GROUP_DEMO_ID,
        SECOND_CLASS_GROUP_ID,
        seed_uuid(f"class-students-{course_id}"),
        default_class_group(db, course_id).id,
    }
    for group_id in candidates:
        # FK inserts take a conflicting key-share lock, so new work cannot
        # slip between the reference checks and deletion.
        group = db.scalar(
            select(Group)
            .where(Group.course_id == course_id, Group.id == group_id)
            .with_for_update()
        )
        if group is None or group.id in protected:
            continue
        # Account purges can remove memberships by database cascade, leaving
        # loaded ORM collections stale. Only the current real roster counts.
        db.expire(group, ["memberships"])
        if (
            db.scalar(select(GroupMember.group_id).where(GroupMember.group_id == group.id).limit(1))
            is not None
        ):
            continue
        referenced = False
        for table in registered_metadata().tables.values():
            if table.name in IGNORED_GROUP_REFERENCES:
                continue
            for fk in table.foreign_key_constraints:
                if fk.referred_table.name != "groups":
                    continue
                # Include every component of composite FKs and every row,
                # including tombstones: deleting those would destroy history.
                if db.scalar(
                    select(
                        select(table)
                        .where(
                            *(
                                element.parent == getattr(group, element.column.key)
                                for element in fk.elements
                            )
                        )
                        .exists()
                    )
                ):
                    referenced = True
                    break
            if referenced:
                break
        if not referenced:
            db.delete(group)
            db.flush()
