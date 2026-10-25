"""Real deletion regressions (owner request 2026-10-24).

After an Agent, RAG, Voice, Knowledge, Team or chat is deleted: Debates still
replay and speak with their own voice, Records/grades/history still open, and
chats that were in progress are ended rather than left half-alive.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.core.models import Agent, VoiceProfile
from app.modules.auth.service import get_auth_context
from app.modules.debates.models import DebateParticipant
from app.modules.debates.playback.sql_repository import SqlPlaybackRepository, SqlRow
from app.modules.learning.attempts import (
    _raw_answers,
    _record_answer_or_skip,
    mark_attempt_question_presented,
)
from app.modules.learning.models import (
    AssessmentActivityQuestion,
    AssessmentAttempt,
    AssessmentAttemptQuestion,
)
from app.modules.learning.reports import list_my_assessment_attempts
from app.modules.voices.crypto import encrypt_external_voice_id
from app.modules.workspace.models import Conversation, ConversationTurn
from app.seed import BOWEN_ID
from fastapi.testclient import TestClient
from sqlalchemy import select

from tests import test_wave2_setup as debate_fixtures
from tests.conftest import login
from tests.test_debate_voice_clones import FakeCloneProvider, _create_voiced_debate
from tests.test_wave2_setup import GROUP_DEMO_ID, _insert_published_agent
from tests.test_workspace_reentry import (  # noqa: F401
    HISTORY_TEXT,
    _create_attempt,
    _login,
    reentry_env,
)

debate_app = debate_fixtures.debate_app


def _mutation_headers(csrf: str) -> dict[str, str]:
    return {
        "Origin": "http://testserver",
        "X-CSRF-Token": csrf,
        "Idempotency-Key": f"true-delete-regression-{uuid4()}",
    }


def _answers(db: Any, attempt_id: str) -> list[tuple[int, str]]:
    attempt = db.get(AssessmentAttempt, attempt_id)
    assert attempt is not None
    return [(answer.question_ordinal, answer.answer_text) for answer in _raw_answers(db, attempt)]


def _answered_attempt(database: Any, settings: Any, client: TestClient) -> tuple[str, str, str]:
    """A completed attempt with one answer saved for its first question."""

    user_id, token, _csrf = _login(client, "bowen")
    chat_id, team_id, attempt_id, _revision = _create_attempt(
        database,
        settings,
        actor_user_id=user_id,
        actor_token=token,
        visibility="private",
        status="in_progress",
    )
    with database.session() as db:
        actor = get_auth_context(db, settings, token)
        attempt = db.get(AssessmentAttempt, attempt_id)
        question = db.scalars(
            select(AssessmentAttemptQuestion)
            .where(AssessmentAttemptQuestion.attempt_id == attempt_id)
            .order_by(AssessmentAttemptQuestion.ordinal)
        ).first()
        assert actor is not None and attempt is not None and question is not None
        source = db.get(AssessmentActivityQuestion, question.activity_question_id)
        assert source is not None and source.question_version_id
        mark_attempt_question_presented(
            db, actor, chat_id, question_version_id=source.question_version_id
        )
        _record_answer_or_skip(
            db,
            actor=actor,
            attempt=attempt,
            question=question,
            event_id=str(uuid4()),
            kind="answer",
            payload={"answer_text": "光合作用"},
            classification="answer_only",
            request_hash="a" * 64,
        )
        attempt.status = "completed"
        attempt.completed_at = datetime.now(UTC)
    return chat_id, team_id, attempt_id


def test_deleting_a_team_ends_its_chat_and_keeps_the_record(
    reentry_env: Any,  # noqa: F811
) -> None:
    database, settings, client = reentry_env
    chat_id, team_id, attempt_id = _answered_attempt(database, settings, client)
    with database.session() as db:
        before = _answers(db, attempt_id)
    assert [text for _ordinal, text in before] == ["光合作用"]

    _teacher, teacher_csrf = login(client, "maya")
    deleted = client.delete(f"/api/v1/teams/{team_id}", headers=_mutation_headers(teacher_csrf))
    assert deleted.status_code == 204, deleted.text

    _user, _token, csrf = _login(client, "bowen")
    opened = client.get(f"/api/v1/conversations/{chat_id}")
    assert opened.status_code == 200, opened.text
    body = opened.json()
    assert body["can_send"] is False
    assert body["team"]["name"]
    assert HISTORY_TEXT in str(body["turns"])
    refused = client.post(
        f"/api/v1/conversations/{chat_id}/messages:stream",
        headers={
            "Origin": "http://testserver",
            "X-CSRF-Token": csrf,
            "Accept": "text/event-stream",
        },
        json={"request_id": str(uuid4()), "expected_revision": body["revision"], "message": "hi"},
    )
    assert refused.status_code == 409
    assert refused.json()["code"] == "team_deleted"
    with database.session() as db:
        attempt = db.get(AssessmentAttempt, attempt_id)
        assert attempt is not None and attempt.status == "completed"
        assert attempt.team_name_snapshot
        assert _answers(db, attempt_id) == before
        actor = get_auth_context(db, settings, client.cookies.get("maya_session"))
        row = db.get(Conversation, chat_id)
        assert row is not None
        listed = list_my_assessment_attempts(db, actor, course_id=row.course_id)
        assert attempt_id in str(listed)


def test_deleting_a_chat_keeps_the_answers_saved_per_question(
    reentry_env: Any,  # noqa: F811
) -> None:
    database, settings, client = reentry_env
    chat_id, _team_id, attempt_id = _answered_attempt(database, settings, client)
    _user, token, csrf = _login(client, "bowen")
    with database.session() as db:
        before = _answers(db, attempt_id)
        course_id = db.get(Conversation, chat_id).course_id  # type: ignore[union-attr]
    deleted = client.delete(
        f"/api/v1/conversations/{chat_id}",
        headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
    )
    assert deleted.status_code == 204, deleted.text
    with database.session() as db:
        assert db.get(Conversation, chat_id) is None
        assert (
            db.scalar(
                select(ConversationTurn.id).where(ConversationTurn.conversation_id == chat_id)
            )
            is None
        )
        assert _answers(db, attempt_id) == before == [(0, "光合作用")]
        actor = get_auth_context(db, settings, token)
        assert attempt_id in str(list_my_assessment_attempts(db, actor, course_id=course_id))


def test_deleting_an_agent_ends_a_chat_that_was_mid_reply(debate_app: Any) -> None:
    _app, database, client = debate_app
    agent_id, version_id, _snapshot = _insert_published_agent(
        database, group_id=GROUP_DEMO_ID, name="Midreply"
    )
    with database.session() as db:
        owned = db.get(Agent, agent_id)
        assert owned is not None
        owned.owner_user_id = BOWEN_ID
    _payload, csrf = login(client, "bowen")
    created = client.post(
        "/api/v1/conversations",
        headers={"X-CSRF-Token": csrf, "Origin": "http://testserver"},
        json={"version_id": version_id},
    )
    assert created.status_code == 200, created.text
    chat_id = created.json()["id"]
    request_id = str(uuid4())
    turn_id = str(uuid4())
    with database.session() as db:
        row = db.get(Conversation, chat_id)
        assert row is not None
        row.active_request_id = request_id
        db.add(
            ConversationTurn(
                id=turn_id,
                conversation_id=chat_id,
                position=0,
                user_text="still thinking",
                assistant_text=None,
                sources_json="[]",
                mode="mock",
                state="pending",
                created_at=datetime.now(UTC),
            )
        )
    deleted = client.delete(f"/api/v1/agents/{agent_id}", headers=_mutation_headers(csrf))
    assert deleted.status_code == 204, deleted.text
    with database.session() as db:
        assert db.get(Agent, agent_id) is None
        row = db.get(Conversation, chat_id)
        assert row is not None
        assert row.active_request_id is None
        assert row.source_removed_at is not None
        turn = db.get(ConversationTurn, turn_id)
        assert turn is not None
        assert turn.state == "failed" and turn.safe_error_code == "agent_deleted"
    opened = client.get(f"/api/v1/conversations/{chat_id}")
    assert opened.status_code == 200, opened.text
    assert opened.json()["can_send"] is False
    assert opened.json()["agent"]["name"] == "Midreply"


def test_deleting_a_legacy_voice_keeps_its_debate_speaking(
    debate_app: Any, monkeypatch: Any
) -> None:
    """A Voice uploaded before samples were kept cannot be cloned for a Debate.

    Deleting it removes the platform row but keeps the supplier voice, and the
    Debate speaks with the supplier id frozen in its snapshot.
    """

    app, database, client = debate_app
    settings = app.state.settings
    settings.fallback_voice_profile_id = None
    voice_id = str(uuid4())
    supplier_id = "cosyvoice-legacy-speaker"
    now = datetime.now(UTC)
    with database.session() as db:
        db.add(
            VoiceProfile(
                id=voice_id,
                scope="group",
                group_id=GROUP_DEMO_ID,
                display_name="Legacy",
                status="ready",
                provider_key="dashscope",
                target_model_key="qwen-audio-3.1-tts-flash",
                recovery_name=f"legacy{voice_id[:8]}",
                provenance_json="{}",
                consent_actor_user_id=BOWEN_ID,
                external_id_encrypted=encrypt_external_voice_id(
                    supplier_id,
                    settings.secret_bytes,
                    profile_id=voice_id,
                    scope="group",
                    group_id=GROUP_DEMO_ID,
                    provider_key="dashscope",
                    target_model_key="qwen-audio-3.1-tts-flash",
                ),
                sample_file_id=None,
                created_at=now,
                updated_at=now,
            )
        )
    debate_id = _create_voiced_debate(database, client, voice_id)
    provider = FakeCloneProvider()
    monkeypatch.setattr("app.providers.factory.voice_provider", lambda _settings: provider)
    _payload, csrf = login(client, "bowen")
    deleted = client.delete(f"/api/v1/voice-profiles/{voice_id}", headers=_mutation_headers(csrf))
    assert deleted.status_code == 200, deleted.text
    assert provider.deleted == []
    with database.session() as db:
        assert db.get(VoiceProfile, voice_id) is None
        participant = db.scalars(
            select(DebateParticipant).where(
                DebateParticipant.debate_id == debate_id, DebateParticipant.order_index == 0
            )
        ).one()
        row = SqlRow(
            {
                "debate_id": debate_id,
                "effective_voice_kind": "platform_profile",
                "effective_voice_profile_id": participant.effective_voice_profile_id,
                "voice_snapshot_json": participant.voice_snapshot_json,
                "voice_external_id_encrypted": participant.voice_external_id_encrypted,
            }
        )
        voice = SqlPlaybackRepository.resolve_effective_voice(
            db, row, settings.model_copy(update={"tts_provider": "dashscope"})
        )
    assert voice.voice_token == supplier_id


def test_prune_keeps_a_version_a_live_team_chat_still_runs_on(
    client: TestClient, database: Any
) -> None:
    from app.core.models import AgentVersion
    from app.modules.real_delete import prune_agent_versions

    from tests.test_mayaform_team_conversations import _create, _team

    team, versions, csrf = _team(client, database)
    session = _create(client, csrf, {"kind": "team", "team_id": team["id"]})
    pinned_id = versions[0]
    now = datetime.now(UTC)
    with database.session() as db:
        pinned = db.get(AgentVersion, pinned_id)
        assert pinned is not None
        agent = db.get(Agent, pinned.agent_id)
        assert agent is not None
        pinned_md = pinned.agent_md
        # The Team chat stays on its version (for example, an unfinished
        # attempt) while the Agent moves on three versions.
        pinned.state = "superseded"
        current_id = ""
        for seq in (1, 2, 3):
            version_id = str(uuid4())
            db.add(
                AgentVersion(
                    id=version_id,
                    agent_id=agent.id,
                    version_seq=pinned.version_seq + seq,
                    state="published" if seq == 3 else "superseded",
                    revision=1,
                    agent_md=f"version {seq}",
                    avatar_config_json=pinned.avatar_config_json,
                    created_at=now,
                    updated_at=now,
                )
            )
            current_id = version_id
        db.flush()
        agent.current_published_version_id = current_id
        agent_id = agent.id
    with database.session() as db:
        prune_agent_versions(db, agent_id, database.data_root)
    with database.session() as db:
        kept = db.get(AgentVersion, pinned_id)
        assert kept is not None and kept.agent_md == pinned_md
        row = db.get(Conversation, session["id"])
        assert row is not None and row.source_removed_at is None
        remaining = db.scalars(
            select(AgentVersion.version_seq).where(AgentVersion.agent_id == agent_id)
        ).all()
        assert len(remaining) == 3


def test_one_agent_failing_to_prune_does_not_stop_the_sweep(
    app_bundle: Any, client: TestClient, monkeypatch: Any, caplog: Any
) -> None:
    """Production 2026-10-25: one failure left every later Agent unpruned."""

    from app.core.models import AgentVersion
    from app.modules import real_delete
    from app.modules.agents.cascade import _sweep_team_chats_and_junk
    from app.modules.demo_baseline.service import ensure_demo_baseline

    _app, database, settings = app_bundle
    now = datetime.now(UTC)
    with database.session() as db:
        ensure_demo_baseline(db, settings.resolved_data_root)
        agents = db.scalars(
            select(Agent).where(Agent.current_published_version_id.is_not(None)).limit(2)
        ).all()
        assert len(agents) == 2
        for agent in agents:
            current = db.get(AgentVersion, agent.current_published_version_id)
            assert current is not None
            base = current.version_seq
            current.version_seq = base + 10
            db.flush()
            for seq in (1, 2, 3):
                db.add(
                    AgentVersion(
                        id=str(uuid4()),
                        agent_id=agent.id,
                        version_seq=base + seq,
                        state="superseded",
                        revision=1,
                        agent_md=f"old {seq}",
                        avatar_config_json=current.avatar_config_json,
                        created_at=now,
                        updated_at=now,
                    )
                )
        agent_ids = [agent.id for agent in agents]
    real_prune = real_delete.prune_agent_versions
    seen: list[str] = []

    def flaky_prune(db: Any, agent_id: str, data_root: Any) -> int:
        seen.append(agent_id)
        if len(seen) == 1:
            raise RuntimeError("constraint only production has")
        return real_prune(db, agent_id, data_root)

    monkeypatch.setattr(real_delete, "prune_agent_versions", flaky_prune)
    _sweep_team_chats_and_junk(database, settings)

    assert sorted(seen) == sorted(agent_ids)
    assert "Agent version prune failed" in caplog.text
    with database.session() as db:
        counts = {
            agent_id: len(
                db.scalars(select(AgentVersion.id).where(AgentVersion.agent_id == agent_id)).all()
            )
            for agent_id in agent_ids
        }
    assert counts[seen[0]] == 4  # the failed Agent is rolled back, untouched
    assert counts[seen[1]] == 2  # current + the previous version's AGENT.md


def test_prune_keeps_a_version_a_withdrawn_chat_still_names(
    client: TestClient, database: Any
) -> None:
    """Production 2026-10-25: clearing it broke ck_conversations_entry."""

    from app.core.models import AgentVersion
    from app.modules.real_delete import prune_agent_versions

    from tests.test_mayaform_team_conversations import _create, _make_agent_version
    from tests.test_mayaform_teams import MAYA_ID

    _, csrf = login(client, "maya")
    # Not a Team member: nothing but the chat keeps this version.
    _agent_id, pinned_id = _make_agent_version(
        database, owner_id=MAYA_ID, name="Withdrawn chat Agent", visibility="public"
    )
    chat = _create(client, csrf, {"kind": "agent", "version_id": pinned_id})
    now = datetime.now(UTC)
    with database.session() as db:
        row = db.get(Conversation, chat["id"])
        assert row is not None
        row.withdrawn_at = now
        db.add(
            ConversationTurn(
                id=str(uuid4()),
                conversation_id=row.id,
                position=0,
                user_text="kept",
                assistant_text="still here",
                sources_json="[]",
                mode="mock",
                state="ready",
                created_at=now,
            )
        )
        pinned = db.get(AgentVersion, pinned_id)
        assert pinned is not None
        agent = db.get(Agent, pinned.agent_id)
        assert agent is not None
        pinned.state = "superseded"
        current_id = ""
        for seq in (1, 2, 3):
            version_id = str(uuid4())
            db.add(
                AgentVersion(
                    id=version_id,
                    agent_id=agent.id,
                    version_seq=pinned.version_seq + seq,
                    state="published" if seq == 3 else "superseded",
                    revision=1,
                    agent_md=f"version {seq}",
                    avatar_config_json=pinned.avatar_config_json,
                    created_at=now,
                    updated_at=now,
                )
            )
            current_id = version_id
        db.flush()
        agent.current_published_version_id = current_id
        agent_id = agent.id
    with database.session() as db:
        prune_agent_versions(db, agent_id, database.data_root)
    with database.session() as db:
        row = db.get(Conversation, chat["id"])
        assert row is not None and row.agent_version_id == pinned_id
        assert row.source_removed_at is None
        assert [turn.user_text for turn in row_turns(db, row.id)] == ["kept"]
        remaining = db.scalars(
            select(AgentVersion.version_seq).where(AgentVersion.agent_id == agent_id)
        ).all()
        # The chat's version, the previous AGENT.md and the current version.
        assert len(remaining) == 3


def row_turns(db: Any, conversation_id: str) -> list[Any]:
    return list(
        db.scalars(
            select(ConversationTurn).where(ConversationTurn.conversation_id == conversation_id)
        ).all()
    )
