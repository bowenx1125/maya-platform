"""Database work per Team message, on PostgreSQL, with fixed ceilings.

Load test 2026-10-19 (N=40): writes per message rose from 32 to 37-42 and
write-queue waits from ~7 ms to 6.5-14 s at p95; CPU and the write queue, not
the model, were the bottleneck. These tests count every INSERT/UPDATE/DELETE,
COMMIT and SELECT of one message through the real dispatch path (synthetic
provider) and fail when a change makes a message do more database work.

Phases: ``claim`` (the send stores the turn), ``turn`` (members answer) and,
for an assessment, ``finalize`` (the server-run Scorer and Summarizer turns
after the last answer). On failure the message lists the call sites, so the
change that added work is easy to find.
"""

from __future__ import annotations

import json
import os
import re
import threading
import traceback
from collections import Counter, defaultdict
from collections.abc import Callable, Iterator
from typing import Any
from uuid import uuid4

import pytest
from app.core.config import Settings
from app.core.db import Database
from app.core.models import AgentVersion
from app.main import create_app
from app.modules.auth.service import get_auth_context
from app.modules.demo_baseline.service import ensure_demo_baseline
from app.modules.provider_disclosure.team_standing import (
    confirm_team_standing_grant,
    prepare_team_standing_grant,
)
from app.modules.workspace import team_runtime as runtime
from app.modules.workspace.chat_team_provider import (
    dispatch_team_model as real_dispatch_team_model,
)
from app.modules.workspace.models import Conversation, TeamTurnResult
from app.modules.workspace.schemas import TeamRouting
from app.providers.control_repository import ProviderRepository
from app.providers.llm_adapter import DashScopeLLMConfig
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event, select, text

from tests.test_mayaform_assessment_attempts import _login
from tests.test_mayaform_team_conversations import _create
from tests.test_mayaform_teams import COURSE_ID, MAYA_ID, _headers, _make_agent_version
from tests.test_wave4_provider_preflight import _digest, _policy

_POSTGRES_URL = os.environ.get("MAYA_TEST_POSTGRES_URL")

# Measured on PostgreSQL (2026-10-19): main 8efc2bd, then the ledger merges
# and read memos below. Lower them when a change saves work; never raise them
# without saying why in the PR. (main: ordinary turn 60 writes / 677 reads;
# assessment turn 32 / 454, finalize 78 / 1139, retried turn 47 / 595.)
ORDINARY_BUDGET = {
    "claim": {"dml": 4, "commit": 1, "select": 55},
    "turn": {"dml": 48, "commit": 24, "select": 645},
}
ASSESSMENT_BUDGET = {
    "clean": {
        "claim": {"dml": 4, "commit": 1, "select": 110},
        "turn": {"dml": 28, "commit": 11, "select": 445},
        "finalize": {"dml": 67, "commit": 28, "select": 935},
    },
    # The Scorer's arguments arrive cut once and the call is retried (#187).
    "truncated_once": {
        "claim": {"dml": 4, "commit": 1, "select": 110},
        "turn": {"dml": 40, "commit": 17, "select": 575},
        "finalize": {"dml": 67, "commit": 28, "select": 935},
    },
}


@pytest.fixture()
def app_bundle(
    app_factory: Callable[..., tuple[FastAPI, Database, Settings]],
) -> Iterator[tuple[FastAPI, Database, Settings]]:
    """The suite's app, on a fresh PostgreSQL schema."""

    if not _POSTGRES_URL:
        pytest.skip("MAYA_TEST_POSTGRES_URL is not set")
    _app, sqlite_database, base = app_factory()
    sqlite_database.dispose()
    settings = base.model_copy(update={"database_url": _POSTGRES_URL})
    database = Database(_POSTGRES_URL, settings.data_root)
    with database.engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    yield create_app(settings, database), database, settings
    database.dispose()


class _Recorder:
    """Every statement of the wrapped phases, with its app call site."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self._phase = threading.local()

    def record(self, _conn: Any, _cursor: Any, statement: str, *_args: Any) -> None:
        phase = getattr(self._phase, "name", None)
        if phase is None:
            return
        sql = re.sub(r"\s+", " ", statement.strip())
        verb = sql.split(" ", 1)[0].upper()
        if verb == "SELECT":
            table = re.search(r"\bFROM\s+\"?(\w+)", sql, re.I)
        else:
            table = re.match(r"(?:INSERT INTO|UPDATE|DELETE FROM)\s+\"?(\w+)", sql, re.I)
        site = next(
            (
                f"{frame.filename.split('/app/')[1]}:{frame.name}"
                for frame in reversed(traceback.extract_stack()[:-2])
                if "/app/" in frame.filename
                and not any(skip in frame.filename for skip in ("core/db.py", "read_memo"))
            ),
            "?",
        )
        self.rows.append(
            {"phase": phase, "verb": verb, "table": table.group(1) if table else "", "site": site}
        )

    def commit(self, _conn: Any) -> None:
        phase = getattr(self._phase, "name", None)
        if phase is not None:
            self.rows.append({"phase": phase, "verb": "COMMIT", "table": "", "site": ""})

    def wrap(self, name: str, function: Any) -> Any:
        def phased(*args: Any, **kwargs: Any) -> Any:
            if getattr(self._phase, "name", None) is not None:
                return function(*args, **kwargs)
            self._phase.name = name
            try:
                return function(*args, **kwargs)
            finally:
                self._phase.name = None

        return phased

    def counts(self) -> dict[str, dict[str, int]]:
        found: dict[str, dict[str, int]] = defaultdict(lambda: {"dml": 0, "commit": 0, "select": 0})
        for row in self.rows:
            kind = (
                "commit"
                if row["verb"] == "COMMIT"
                else "select"
                if row["verb"] == "SELECT"
                else "dml"
                if row["verb"] in {"INSERT", "UPDATE", "DELETE"}
                else None
            )
            if kind:
                found[row["phase"]][kind] += 1
        return dict(found)

    def report(self) -> str:
        sites = Counter(
            f"{row['phase']} {row['verb']} {row['table']} <- {row['site']}"
            for row in self.rows
            if row["verb"] in {"INSERT", "UPDATE", "DELETE"}
        )
        return "\n".join(f"{count:4d} {site}" for site, count in sites.most_common())

    def check(self, budget: dict[str, dict[str, int]]) -> None:
        counts = self.counts()
        print(json.dumps(counts, sort_keys=True))  # shown with -s, for the PR table
        if os.environ.get("DB_BUDGET_REPORT"):
            print(self.report())
            sel = Counter(
                f"{row['phase']} {row['site']}" for row in self.rows if row["verb"] == "SELECT"
            )
            print("\n".join(f"{n:4d} {k}" for k, n in sel.most_common(15)))
        over = [
            f"{phase}.{kind}={counts.get(phase, {}).get(kind, 0)} > {cap}"
            for phase, caps in budget.items()
            for kind, cap in caps.items()
            if counts.get(phase, {}).get(kind, 0) > cap
        ]
        assert not over, f"{over}\n{self.report()}"


@pytest.fixture()
def recorder(database: Database, monkeypatch: pytest.MonkeyPatch) -> Iterator[_Recorder]:
    from app.modules.learning import finalizer

    recorder = _Recorder()
    monkeypatch.setattr(runtime, "claim_team_turn", recorder.wrap("claim", runtime.claim_team_turn))
    monkeypatch.setattr(
        runtime, "execute_team_turn", recorder.wrap("turn", runtime.execute_team_turn)
    )
    monkeypatch.setattr(
        finalizer, "drive_assessment", recorder.wrap("finalize", finalizer.drive_assessment)
    )
    event.listen(database.engine, "after_cursor_execute", recorder.record)
    event.listen(database.engine, "commit", recorder.commit)
    yield recorder
    event.remove(database.engine, "after_cursor_execute", recorder.record)
    event.remove(database.engine, "commit", recorder.commit)


def _text_reply(content: str) -> bytes:
    return json.dumps(
        {
            "choices": [
                {"message": {"role": "assistant", "content": content}, "finish_reason": "stop"}
            ]
        }
    ).encode()


class _Response:
    status_code = 200

    def __init__(self, content: bytes) -> None:
        self.content = content


class _Transport:
    def __init__(self, content: bytes) -> None:
        self.content = content

    def post_bytes(self, _endpoint: str, **_kwargs: Any) -> Any:
        return _Response(self.content)


def test_ordinary_team_message_db_budget(
    client: TestClient,
    database: Database,
    app_bundle: Any,
    monkeypatch: pytest.MonkeyPatch,
    recorder: _Recorder,
) -> None:
    """A student's message to a teacher's public (non-assessment) Team, 3 members."""

    app, _database, base_settings = app_bundle
    _token, teacher_csrf = _login(client, "maya")
    with database.session() as db:
        ensure_demo_baseline(db, base_settings.resolved_data_root)
    version_ids = []
    for name in ("Guide", "Critic", "Helper"):
        _agent_id, version_id = _make_agent_version(
            database, owner_id=MAYA_ID, name=name, visibility="public"
        )
        with database.session() as db:
            version = db.get(AgentVersion, version_id)
            assert version is not None
            version.agent_md = f"# {name}\n\nAnswer briefly."
            version.avatar_config_json = json.dumps(
                {
                    "template_id": "synthetic",
                    "material_theme": "default",
                    "default_expression": "neutral",
                    "expression_strength": "low",
                    "motion_style": "calm",
                }
            )
            db.commit()
        version_ids.append(version_id)
    created = client.post(
        f"/api/v1/courses/{COURSE_ID}/teams",
        headers=_headers(teacher_csrf, f"db-budget-{uuid4()}"),
        json={
            "display_name": "Ordinary three",
            "visibility": "public",
            "members": [
                {"agent_version_id": version_id, "is_leader": index == 0, "position": index}
                for index, version_id in enumerate(version_ids)
            ],
        },
    )
    assert created.status_code == 201, created.text
    student_token, student_csrf = _login(client, "bowen")
    session = _create(client, student_csrf, {"kind": "maya_team", "team_id": created.json()["id"]})
    conversation_id = session["id"]

    settings = base_settings.model_copy(
        update={
            "llm_provider": "dashscope",
            "dashscope_api_key": "synthetic-key",
            "dashscope_workspace_id": "synthetic-workspace",
            "dashscope_region": "cn-beijing",
        }
    )
    policy = _policy(
        policy_id="db-budget-ordinary",
        endpoint=DashScopeLLMConfig(
            api_key="synthetic-key",
            workspace_id="synthetic-workspace",
            region="cn-beijing",
            model_key=settings.llm_model,
            policy_hash=_digest("db-budget-ordinary-policy"),
        ).resolved_endpoint,
    )
    settings = settings.model_copy(update={"llm_provider_policy_hash": policy.policy_hash})
    app.state.settings = settings
    ProviderRepository(database).save_policy_snapshot(policy)
    with database.session() as db:
        conversation = db.get(Conversation, conversation_id)
        assert conversation is not None and conversation.team_version_id is not None
        plan = prepare_team_standing_grant(
            db,
            MAYA_ID,
            team_version_id=conversation.team_version_id,
            policy_hash=policy.policy_hash,
            provider_operation="llm_agent_chat",
        )
        confirm_team_standing_grant(
            db,
            MAYA_ID,
            team_version_id=conversation.team_version_id,
            policy_hash=policy.policy_hash,
            provider_operation="llm_agent_chat",
            expected_resource_hash=plan.resource_hash,
            expected_team_epoch=plan.team_epoch,
            expected_publication_epoch=plan.publication_epoch,
        )
        db.commit()
        actor = get_auth_context(db, settings, student_token)
        assert actor is not None
        revision = conversation.revision

    def synthetic_dispatch(db: Any, _settings: Any, request: Any, *args: Any, **kwargs: Any) -> Any:
        transport = _Transport(_text_reply(f"{request.speaker_name}: a short answer."))
        return real_dispatch_team_model(db, settings, request, *args, transport=transport, **kwargs)

    monkeypatch.setattr(
        "app.modules.workspace.chat_team_provider.dispatch_team_model", synthetic_dispatch
    )
    with database.session() as db:
        claim = runtime.claim_team_turn(
            db,
            settings,
            conversation_id=conversation_id,
            actor_id=actor.user.id,
            request_id=str(uuid4()),
            expected_revision=revision,
            message="你好，请简单介绍一下你们自己。",
            routing=TeamRouting(mode="all"),
            actor_context=actor,
        )
    runtime.execute_team_turn(database.session_factory, claim)

    with database.session() as db:
        states = db.scalars(
            select(TeamTurnResult.state).where(TeamTurnResult.turn_id == claim.turn_id)
        ).all()
    assert sorted(states) == ["ready", "ready", "ready"], states
    recorder.check(ORDINARY_BUDGET)


@pytest.mark.parametrize("scorer_wire", ["clean", "truncated_once"])
def test_assessment_message_db_budget(
    scorer_wire: str,
    client: TestClient,
    database: Database,
    app_bundle: Any,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    recorder: _Recorder,
) -> None:
    """The last answer of a formal test, then the Scorer and Summarizer runs.

    The scenario is the answer-turn test of test_team_assessment_projection
    (it already drives the last answer and ``finalizer.drive_assessment``
    through the real dispatch path); here it runs on PostgreSQL, counted.
    """

    from tests.test_team_assessment_projection import (
        test_open_test_runs_the_leader_alone_and_the_server_scores_without_leaks as scenario,
    )

    scenario(
        client=client,
        database=database,
        app_bundle=app_bundle,
        monkeypatch=monkeypatch,
        follow_up=False,
        scorer_wire=scorer_wire,
        caplog=caplog,
    )
    recorder.check(ASSESSMENT_BUDGET[scorer_wire])
