"""Repo-wide N+1 sweep (2026-10-26): ceilings and the caches behind them.

The full suite was run with ``tests/n_plus_one_report.py`` recording, per
request, how often one statement repeated. The worst repeats were a course
role read up to 32 times per request, a recovery input, audio file and
cited chunk per Debate turn, and ~120 catalog reads on the first hard delete
of a process. These tests pin the fixes.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest
from app.core import request_timing
from app.core.models import CourseMember
from app.modules.knowledge.services import course_member_role
from app.seed import COURSE_ID, TEACHER_ID
from fastapi.testclient import TestClient
from sqlalchemy import event, select

from tests.conftest import login
from tests.test_classroom_lifecycle import _saved_classroom


def _queries(caplog: pytest.LogCaptureFixture, client: TestClient, url: str) -> int:
    client.get(url)
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="maya.request_timing"):
        assert client.get(url).status_code == 200
    lines = [
        json.loads(record.getMessage())
        for record in caplog.records
        if record.name == "maya.request_timing"
    ]
    return int(lines[-1]["db_queries"])


def test_debate_detail_reads_its_turns_in_batches(
    app_factory: Any, caplog: pytest.LogCaptureFixture
) -> None:
    app, database, settings = app_factory()
    try:
        with TestClient(app) as client:
            debate_id = _saved_classroom(database, settings)
            login(client)
            # 8 saved turns; was 30 (an audio file, a recovery input and the
            # sources once per turn).
            assert _queries(caplog, client, f"/api/v1/debates/{debate_id}") <= 20
    finally:
        database.dispose()


def test_a_role_read_is_reused_in_a_transaction_until_it_writes(
    app_bundle: Any, client: TestClient
) -> None:
    _app, database, _settings = app_bundle
    statements: list[str] = []

    def record(conn, cursor, statement, *_args):  # type: ignore[no-untyped-def]
        if "course_members" in statement:
            statements.append(statement)

    with database.session() as db:
        event.listen(database.engine, "before_cursor_execute", record)
        try:
            assert course_member_role(db, TEACHER_ID, COURSE_ID) == "teacher"
            assert course_member_role(db, TEACHER_ID, COURSE_ID) == "teacher"
            assert len(statements) == 1
            # A write in the same transaction drops the cached role.
            member = db.scalar(
                select(CourseMember).where(
                    CourseMember.course_id == COURSE_ID, CourseMember.user_id == TEACHER_ID
                )
            )
            assert member is not None
            member.role = "student"
            db.flush()
            assert course_member_role(db, TEACHER_ID, COURSE_ID) == "student"
        finally:
            event.remove(database.engine, "before_cursor_execute", record)
        db.rollback()
        # A new transaction reads again.
        assert course_member_role(db, TEACHER_ID, COURSE_ID) == "teacher"


def test_request_timing_summary_lists_routes_without_ids(client: TestClient) -> None:
    request_timing.reset_summary()
    login(client)
    for _ in range(3):
        assert client.get(f"/api/v1/courses/{COURSE_ID}/published-agents").status_code == 200
    summary = client.get("/health/request-timing")
    assert summary.status_code == 200
    body = summary.json()
    row = next(
        item
        for item in body["routes"]
        if item["route"] == "/api/v1/courses/{course_id}/published-agents"
    )
    assert row["method"] == "GET" and row["count"] == 3 and row["samples"] == 3
    assert row["ms"]["p50"] is not None and row["db_queries"]["max"] >= 1
    assert COURSE_ID not in summary.text


def test_transaction_memo_is_dropped_by_any_write(app_bundle: Any, client: TestClient) -> None:
    from app.core.read_memo import transaction_memoized

    _app, database, _settings = app_bundle
    calls: list[int] = []

    def compute() -> int:
        calls.append(1)
        return len(calls)

    with database.session() as db:
        assert transaction_memoized(db, ("probe",), compute) == 1
        assert transaction_memoized(db, ("probe",), compute) == 1
        member = db.scalar(select(CourseMember).where(CourseMember.course_id == COURSE_ID))
        assert member is not None
        member.created_at = member.created_at
        db.execute(
            CourseMember.__table__.update()
            .where(CourseMember.course_id == "no-such-course")
            .values(role="student")
        )
        assert transaction_memoized(db, ("probe",), compute) == 2
        db.commit()
        assert transaction_memoized(db, ("probe",), compute) == 3
