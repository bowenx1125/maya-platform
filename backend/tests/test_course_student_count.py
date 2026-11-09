from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.core.models import Course, CourseMember, User
from app.modules.org.classes import SECOND_CLASS_ID
from app.seed import COURSE_ID
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select

from tests.conftest import login


def _expected(database: Any, course_id: str) -> int:
    with database.session() as db:
        return int(
            db.scalar(
                select(func.count(CourseMember.user_id))
                .join(User, User.id == CourseMember.user_id)
                .where(
                    CourseMember.course_id == course_id,
                    CourseMember.role == "student",
                    User.status == "active",
                )
            )
            or 0
        )


def _count_queries(database: Any, client: TestClient) -> tuple[int, list[dict[str, Any]]]:
    seen = [0]

    def tick(*_args: Any) -> None:
        seen[0] += 1

    event.listen(database.engine, "before_cursor_execute", tick)
    try:
        response = client.get("/api/v1/courses")
    finally:
        event.remove(database.engine, "before_cursor_execute", tick)
    assert response.status_code == 200
    return seen[0], response.json()


def test_teacher_sees_active_student_count(client: TestClient, database: Any) -> None:
    login(client, "maya")
    courses = client.get("/api/v1/courses").json()
    assert courses
    for course in courses:
        assert course["student_count"] == _expected(database, course["id"])
    counts = {course["id"]: course["student_count"] for course in courses}
    assert set(counts) == {COURSE_ID, SECOND_CLASS_ID}
    assert counts[COURSE_ID] > 0
    assert counts[SECOND_CLASS_ID] == 0


def test_inactive_students_are_not_counted(client: TestClient, database: Any) -> None:
    login(client, "maya")
    course = client.get("/api/v1/courses").json()[0]
    before = course["student_count"]
    with database.session() as db:
        student_id = db.scalar(
            select(CourseMember.user_id).where(
                CourseMember.course_id == course["id"], CourseMember.role == "student"
            )
        )
        db.get(User, student_id).status = "inactive"
        db.commit()
    after = client.get("/api/v1/courses").json()[0]["student_count"]
    assert after == before - 1


def test_student_gets_null(client: TestClient) -> None:
    login(client, "bowen")
    courses = client.get("/api/v1/courses").json()
    assert courses
    assert all(course["student_count"] is None for course in courses)


def test_count_is_one_aggregate_not_per_course(client: TestClient, database: Any) -> None:
    login(client, "maya")
    one_course, before = _count_queries(database, client)
    with database.session() as db:
        teacher_id = db.scalar(select(User.id).where(User.username == "maya"))
        now = datetime.now(UTC)
        for index in range(3):
            course_id = str(uuid4())
            db.add(Course(id=course_id, code=f"ZZ{index}", name=f"Extra {index}", created_at=now))
            db.flush()
            db.add(
                CourseMember(
                    course_id=course_id, user_id=teacher_id, role="teacher", created_at=now
                )
            )
        db.commit()
    four_courses, after = _count_queries(database, client)
    assert len(after) == len(before) + 3
    assert four_courses == one_course
    assert [c["student_count"] for c in after if c["code"].startswith("ZZ")] == [0, 0, 0]
