"""A Debate keeps a copy of its voice: sample plus supplier ID (2026-10-24).

Nothing is enrolled. Deleting the platform Voice leaves the supplier voice
while a Debate still names it; deleting the last Debate that names it, with no
Voice row left, deletes it at the supplier exactly once.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.core.models import AgentVersion, StoredFile, VoiceProfile
from app.modules.debates.models import Debate, DebateParticipant, DebateVoiceClone
from app.modules.debates.playback.sql_repository import SqlPlaybackRepository, SqlRow
from app.modules.debates.voice_clones import sweep_debate_voice_clones
from app.modules.knowledge.files import write_atomic
from app.modules.voices.crypto import encrypt_external_voice_id
from app.seed import BOWEN_ID
from sqlalchemy import select

from tests import test_wave2_setup as debate_fixtures
from tests.conftest import login
from tests.postgres_db import named_url
from tests.test_wave2_setup import COURSE_ID, GROUP_DEMO_ID, _insert_published_agent, headers

debate_app = debate_fixtures.debate_app

SUPPLIER_ID = "cosyvoice-v2-supplier-voice"
MODEL = "qwen-audio-3.1-tts-flash"


@dataclass
class FakeCloneProvider:
    """A supplier stand-in that fails the test on any charged enrollment."""

    key: str = "dashscope"
    target_model_key: str = MODEL
    deleted: list[str] = field(default_factory=list)

    def enroll(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover
        raise AssertionError("a Debate voice must never be enrolled")

    def exists(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover
        raise AssertionError("the stored supplier id is used directly")

    def delete(self, external_voice_id: str, *, target_model_key: str) -> None:
        self.deleted.append(external_voice_id)


def _voice_with_sample(database: Any, settings: Any, *, sample: bool = True) -> str:
    voice_id = str(uuid4())
    now = datetime.now(UTC)
    file_id = None
    with database.session() as db:
        if sample:
            file_id = str(uuid4())
            relative = f"voice-samples/{voice_id}.wav"
            digest, size = write_atomic(settings.resolved_data_root, relative, b"RIFF-sample")
            db.add(
                StoredFile(
                    id=file_id,
                    kind="voice_sample",
                    relative_path=relative,
                    sha256=digest,
                    size_bytes=size,
                    state="active",
                    created_at=now,
                    updated_at=now,
                )
            )
            db.flush()
        db.add(
            VoiceProfile(
                id=voice_id,
                scope="group",
                group_id=GROUP_DEMO_ID,
                display_name="Bowen",
                status="ready",
                provider_key="dashscope",
                target_model_key=MODEL,
                recovery_name=f"t{voice_id[:8]}",
                provenance_json="{}",
                consent_actor_user_id=BOWEN_ID,
                external_id_encrypted=encrypt_external_voice_id(
                    SUPPLIER_ID,
                    settings.secret_bytes,
                    profile_id=voice_id,
                    scope="group",
                    group_id=GROUP_DEMO_ID,
                    provider_key="dashscope",
                    target_model_key=MODEL,
                ),
                sample_file_id=file_id,
                sample_language="en",
                created_at=now,
                updated_at=now,
            )
        )
    return voice_id


def _create_voiced_debate(database: Any, client: Any, voice_id: str) -> str:
    first, first_version, _ = _insert_published_agent(database, group_id=GROUP_DEMO_ID, name="A")
    second, _, _ = _insert_published_agent(database, group_id=GROUP_DEMO_ID, name="B")
    with database.session() as db:
        version = db.get(AgentVersion, first_version)
        assert version is not None
        version.voice_profile_id = voice_id
    _, csrf = login(client)
    response = client.post(
        f"/api/v1/courses/{COURSE_ID}/debates",
        headers=headers(csrf, **{"Idempotency-Key": f"voice-copy-{uuid4()}"}),
        json={
            "topic": "How should people learn together?",
            "participants": [
                {"agent_id": first, "stance_mode": "open"},
                {"agent_id": second, "stance_mode": "open"},
            ],
            "round_count": 4,
            "rule_set_id": "ordered_multi_expert_mutual_learning_v1",
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["participants"][0]["effective_voice_profile_id"] == voice_id
    return str(response.json()["id"])


def _speaks_with(db: Any, settings: Any, debate_id: str) -> str:
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
    real = settings.model_copy(update={"tts_provider": "dashscope"})
    return SqlPlaybackRepository.resolve_effective_voice(db, row, real).voice_token


def _delete_debate(client: Any, debate_id: str) -> None:
    _, csrf = login(client)
    detail = client.get(f"/api/v1/debates/{debate_id}").json()
    deleted = client.request(
        "DELETE",
        f"/api/v1/debates/{debate_id}",
        headers=headers(csrf, **{"Idempotency-Key": f"voice-copy-delete-{uuid4()}"}),
        json={
            "expected_revision": detail["revision"],
            "expected_control_version": detail["playback"]["control_version"],
        },
    )
    assert deleted.status_code == 200, deleted.text


def _delete_voice(client: Any, voice_id: str) -> None:
    _, csrf = login(client, "bowen")
    response = client.delete(
        f"/api/v1/voice-profiles/{voice_id}",
        headers=headers(csrf, **{"Idempotency-Key": f"voice-copy-vdel-{uuid4()}"}),
    )
    assert response.status_code == 200, response.text


def _sweep(db: Any, settings: Any, provider: FakeCloneProvider) -> dict[str, int]:
    return sweep_debate_voice_clones(
        db, data_root=settings.resolved_data_root, settings=settings, provider=provider
    )


def test_create_copies_the_sample_and_supplier_id_without_enrolling(debate_app: Any) -> None:
    app, database, client = debate_app
    settings = app.state.settings
    voice_id = _voice_with_sample(database, settings)
    debate_id = _create_voiced_debate(database, client, voice_id)
    with database.session() as db:
        row = db.scalars(
            select(DebateVoiceClone).where(DebateVoiceClone.debate_id == debate_id)
        ).one()
        assert (row.status, row.source_voice_profile_id) == ("ready", voice_id)
        assert row.provider_voice_hash and row.external_id_encrypted
        copy = db.get(StoredFile, row.sample_file_id)
        source = db.get(StoredFile, db.get(VoiceProfile, voice_id).sample_file_id)
        assert copy is not None and source is not None and copy.id != source.id
        assert copy.relative_path.startswith("debate-voice-samples/")
        assert (settings.resolved_data_root / copy.relative_path).read_bytes() == b"RIFF-sample"
        assert _speaks_with(db, settings, debate_id) == SUPPLIER_ID


def test_voice_delete_keeps_the_debate_speaking_without_a_supplier_call(
    debate_app: Any, monkeypatch: Any
) -> None:
    app, database, client = debate_app
    settings = app.state.settings
    settings.fallback_voice_profile_id = None
    provider = FakeCloneProvider()
    monkeypatch.setattr("app.providers.factory.voice_provider", lambda _settings: provider)
    voice_id = _voice_with_sample(database, settings)
    debate_id = _create_voiced_debate(database, client, voice_id)
    _delete_voice(client, voice_id)
    assert provider.deleted == []
    with database.session() as db:
        assert db.get(VoiceProfile, voice_id) is None
        # Playback and new speech read only the Debate's snapshot.
        assert _speaks_with(db, settings, debate_id) == SUPPLIER_ID
        _sweep(db, settings, provider)
    assert provider.deleted == []
    login(client)
    assert client.get(f"/api/v1/debates/{debate_id}").status_code == 200


def test_the_last_debate_deletes_the_supplier_voice_once(debate_app: Any, monkeypatch: Any) -> None:
    app, database, client = debate_app
    settings = app.state.settings
    provider = FakeCloneProvider()
    monkeypatch.setattr("app.providers.factory.voice_provider", lambda _settings: provider)
    voice_id = _voice_with_sample(database, settings)
    debate_id = _create_voiced_debate(database, client, voice_id)
    _delete_voice(client, voice_id)
    with database.session() as db:
        sample = db.scalars(
            select(DebateVoiceClone.sample_file_id).where(DebateVoiceClone.debate_id == debate_id)
        ).one()
        relative = db.get(StoredFile, sample).relative_path
    _delete_debate(client, debate_id)
    with database.session() as db:
        assert _sweep(db, settings, provider)["supplier_deleted"] == 1
        assert _sweep(db, settings, provider)["supplier_deleted"] == 0
        assert db.scalars(select(DebateVoiceClone)).all() == []
        assert db.get(StoredFile, sample) is None
    assert provider.deleted == [SUPPLIER_ID]
    assert not (settings.resolved_data_root / relative).exists()


def test_two_debates_share_a_voice_and_one_delete_spares_the_other(
    debate_app: Any, monkeypatch: Any
) -> None:
    app, database, client = debate_app
    settings = app.state.settings
    settings.fallback_voice_profile_id = None
    provider = FakeCloneProvider()
    monkeypatch.setattr("app.providers.factory.voice_provider", lambda _settings: provider)
    voice_id = _voice_with_sample(database, settings)
    first = _create_voiced_debate(database, client, voice_id)
    second = _create_voiced_debate(database, client, voice_id)
    _delete_voice(client, voice_id)
    _delete_debate(client, first)
    with database.session() as db:
        assert _sweep(db, settings, provider)["kept"] == 1
        assert provider.deleted == []
        assert _speaks_with(db, settings, second) == SUPPLIER_ID
    _delete_debate(client, second)
    with database.session() as db:
        _sweep(db, settings, provider)
    assert provider.deleted == [SUPPLIER_ID]


def test_a_debate_delete_leaves_a_live_voice_to_its_own_delete(
    debate_app: Any, monkeypatch: Any
) -> None:
    app, database, client = debate_app
    settings = app.state.settings
    provider = FakeCloneProvider()
    monkeypatch.setattr("app.providers.factory.voice_provider", lambda _settings: provider)
    voice_id = _voice_with_sample(database, settings)
    debate_id = _create_voiced_debate(database, client, voice_id)
    _delete_debate(client, debate_id)
    with database.session() as db:
        assert _sweep(db, settings, provider)["kept"] == 1
    assert provider.deleted == []
    # Now no Debate names it: the Voice's own delete removes it.
    _delete_voice(client, voice_id)
    assert provider.deleted == [SUPPLIER_ID]


def test_backfill_copies_once_and_calls_no_supplier(debate_app: Any, monkeypatch: Any) -> None:
    import importlib.util
    from pathlib import Path

    app, database, client = debate_app
    settings = app.state.settings
    voice_id = _voice_with_sample(database, settings)
    debate_id = _create_voiced_debate(database, client, voice_id)
    with database.session() as db:
        # An existing Debate from before voice copies.
        for row in db.scalars(
            select(DebateVoiceClone).where(DebateVoiceClone.debate_id == debate_id)
        ):
            db.delete(row)
    path = Path(__file__).parents[2] / "scripts" / "backfill_debate_voice_clones.py"
    spec = importlib.util.spec_from_file_location("backfill_voices", path)
    assert spec is not None and spec.loader is not None
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)

    def calls_nothing(_settings: Any) -> Any:  # pragma: no cover
        raise AssertionError("the backfill must not reach a supplier")

    monkeypatch.setattr("app.providers.factory.voice_provider", calls_nothing)
    args = ["--database-url", settings.database_url, "--data-root", str(settings.data_root)]
    assert script.main(args) == 0
    assert script.main([*args, "--apply"]) == 0
    assert script.main([*args, "--apply"]) == 0
    with database.session() as db:
        rows = db.scalars(
            select(DebateVoiceClone).where(DebateVoiceClone.debate_id == debate_id)
        ).all()
        assert len(rows) == 1
        assert rows[0].origin == "backfill" and rows[0].sample_file_id is not None
        assert _speaks_with(db, settings, debate_id) == SUPPLIER_ID
        assert db.get(Debate, debate_id) is not None


def test_postgres_voice_delete_racing_the_last_debate_frees_the_voice_once(
    app_factory: Any, monkeypatch: Any
) -> None:
    """The voice lock orders a Voice delete and a Debate release: one call."""

    import os
    import threading

    import pytest
    from app.core import adaptive_admission as aa
    from app.core import write_guard as wg
    from app.core.db import Database
    from app.main import create_app
    from app.modules.debates.setup.router import router as debate_setup_router
    from app.modules.demo_baseline.service import ensure_demo_baseline
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    url = os.environ.get("MAYA_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("MAYA_TEST_POSTGRES_URL is not set")
    url = named_url("pg", schema=False)
    _app, sqlite_database, base = app_factory()
    sqlite_database.dispose()
    settings = base.model_copy(update={"database_url": url})
    database = Database(url, settings.data_root)
    with database.engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    app = create_app(settings, database)
    app.include_router(debate_setup_router, prefix="/api/v1")
    aa.reset_adaptive_admission_state()
    wg.reset_write_guard_state()
    provider = FakeCloneProvider()
    monkeypatch.setattr("app.providers.factory.voice_provider", lambda _settings: provider)
    try:
        with TestClient(app) as client:
            client.headers["Origin"] = "http://testserver"
            with database.session() as db:
                ensure_demo_baseline(db, settings.resolved_data_root)
            for _round in range(3):
                provider.deleted.clear()
                voice_id = _voice_with_sample(database, settings)
                debate_id = _create_voiced_debate(database, client, voice_id)
                _delete_debate(client, debate_id)
                barrier = threading.Barrier(2)

                def release(barrier: threading.Barrier = barrier) -> None:
                    barrier.wait()
                    with database.session() as db:
                        _sweep(db, settings, provider)

                worker = threading.Thread(target=release)
                worker.start()
                barrier.wait()
                _delete_voice(client, voice_id)
                worker.join()
                with database.session() as db:
                    _sweep(db, settings, provider)
                    assert db.scalars(select(DebateVoiceClone)).all() == []
                assert provider.deleted == [SUPPLIER_ID]
    finally:
        database.dispose()
