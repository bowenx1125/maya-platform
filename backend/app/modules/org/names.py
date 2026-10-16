"""Resolve one course group using the same durable key in every write path."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.identity import group_name_key, normalize_group_name
from app.core.models import Group
from app.core.sqlutil import dialect_insert


def resolve_named_group(db: Session, course_id: str, name: str) -> Group:
    normalized = normalize_group_name(name)
    key = group_name_key(normalized)
    # The unique key arbitrates simultaneous first joins, including Unicode variants.
    db.execute(
        dialect_insert(db, Group)
        .values(
            id=str(uuid4()),
            course_id=course_id,
            name=normalized,
            name_key=key,
            created_at=datetime.now(UTC),
        )
        .on_conflict_do_nothing(index_elements=["course_id", "name_key"])
    )
    return db.scalars(
        select(Group).where(Group.course_id == course_id, Group.name_key == key)
    ).one()
