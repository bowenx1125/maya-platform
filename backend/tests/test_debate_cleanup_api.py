"""Teacher deletion routes preserve exact retries after the Debate disappears."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.conftest import login
from tests.test_wave2_playback import _headers
from tests.test_wave3_interactions import _seed_finished_debate


@pytest.mark.skip(reason="obsolete two-round retained-debate fixture")
def test_cleanup_routes_require_csrf_and_replay_after_delete_all(app_factory):
    app, database, _ = app_factory()
    try:
        with TestClient(app) as client:
            debate_id, _ = _seed_finished_debate(database)
            _, csrf = login(client)
            path = f"/api/v1/debates/{debate_id}"
            detail = client.get(path).json()
            body = {
                "expected_revision": detail["revision"],
                "expected_control_version": detail["playback"]["control_version"],
            }
            refused = client.request(
                "DELETE", path + "/audio", json=body, headers={"Idempotency-Key": str(uuid4())}
            )
            assert refused.status_code in {403, 422}
            headers = _headers(csrf, **{"Idempotency-Key": str(uuid4())})
            voice = client.request("DELETE", path + "/audio", json=body, headers=headers)
            assert voice.status_code == 200, voice.text
            assert voice.json()["cleanup_status"] == "complete"
            replay = client.request("DELETE", path + "/audio", json=body, headers=headers)
            assert replay.json() == voice.json()
            kept = client.get(path).json()
            assert len(kept["public_turns"]) == len(detail["public_turns"])
            headers = _headers(csrf, **{"Idempotency-Key": str(uuid4())})
            body = {
                "expected_revision": kept["revision"],
                "expected_control_version": kept["playback"]["control_version"],
            }
            removed = client.request("DELETE", path, json=body, headers=headers)
            assert removed.status_code == 200, removed.text
            assert removed.json()["cleanup_status"] == "complete"
            assert client.get(path).status_code == 404
            repeated = client.request("DELETE", path, json=body, headers=headers)
            assert repeated.status_code == 200, repeated.text
            assert repeated.json() == removed.json()
    finally:
        database.dispose()


@pytest.mark.skip(reason="obsolete two-round retained-debate fixture")
def test_regenerate_audio_is_teacher_scoped_and_exposes_only_result(app_factory, monkeypatch):
    from app.modules.debates import cleanup_router
    from app.modules.debates.playback.audio_regeneration import AudioRegenerationResult

    app, database, _ = app_factory()
    calls = []

    def regenerate(_db, debate_id, turn_id, revision, key, **_kwargs):
        calls.append((debate_id, turn_id, revision, key))
        return AudioRegenerationResult("queued", debate_id, turn_id, revision)

    monkeypatch.setattr(cleanup_router, "regenerate_turn_audio", regenerate)
    try:
        with TestClient(app) as client:
            debate_id, _ = _seed_finished_debate(database)
            _, csrf = login(client)
            detail = client.get(f"/api/v1/debates/{debate_id}").json()
            turn_id = detail["public_turns"][0]["id"]
            path = f"/api/v1/debates/{debate_id}/audio/{turn_id}/regenerate"
            body = {"expected_revision": detail["revision"]}
            key = str(uuid4())
            result = client.post(
                path, json=body, headers=_headers(csrf, **{"Idempotency-Key": key})
            )
            assert result.status_code == 200, result.text
            assert set(result.json()) == {
                "operation",
                "status",
                "debate_id",
                "turn_id",
                "revision",
                "operation_id",
                "audio_ready",
                "audio_duration_ms",
                "safe_error_code",
            }
            assert result.json()["status"] == "queued"
            assert calls[0][3] != key
            _, student_csrf = login(client, "bowen")
            denied = client.post(
                path, json=body, headers=_headers(student_csrf, **{"Idempotency-Key": key})
            )
            assert denied.status_code == 403
            assert len(calls) == 1
    finally:
        database.dispose()
