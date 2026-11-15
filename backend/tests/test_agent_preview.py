"""Preview has no chat or memory side effects, even for current unsaved drafts."""

from __future__ import annotations

import base64
import io
import json
import re
import wave
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from app.core.models import (
    AgentVersion,
    KnowledgeDocumentChunk,
    KnowledgeSnapshot,
)
from app.modules.agents import preview
from app.modules.avatars.catalog import default_config_for
from app.modules.knowledge.markdown import EMBEDDING_DIMENSION, EMBEDDING_KEY, mock_embedding
from app.modules.knowledge.vector import MockVectorStore
from app.modules.workspace.models import AgentAccountMemory, Conversation, ConversationTurn
from app.providers.tts import TTSProviderError, TTSResult
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from tests.conftest import login
from tests.test_wave2_setup import (
    COURSE_ID,
    GROUP_DEMO_ID,
    headers,
)


def body(**extra: Any) -> dict[str, Any]:
    return {
        "message": "What is evidence?",
        "agent_md": "You are an amber philosopher.",
        "avatar_config": default_config_for("egg").model_dump(),
        "group_id": GROUP_DEMO_ID,
        **extra,
    }


@pytest.mark.parametrize(
    "text,expected",
    [
        ("First. Second.", "First."),
        ("第一句。第二句。", "第一句。"),
        ("Why? Another!", "Why?"),
        ("A value of 3.14 is useful. More.", "A value of 3.14 is useful."),
        ("One clause", "One clause."),
        ("“Hello!” More.", "“Hello!”"),
    ],
)
def test_first_sentence(text: str, expected: str) -> None:
    assert preview.first_sentence(text) == expected


def test_endpoint_is_stateless_and_uses_unsaved_persona_and_rag(
    app_factory: Any, monkeypatch: Any
) -> None:
    app, database, settings = app_factory()
    captured = []

    def reply(*args: Any, **kwargs: Any) -> tuple[str, str]:
        captured.append(kwargs)
        return "Evidence supports a claim. This must be discarded.", "unused"

    monkeypatch.setattr(preview, "preview_reply", reply)
    # Inject a provider boundary; this never contacts a real supplier.
    with TestClient(app) as client:
        _, csrf = login(client, "bowen")
        settings.llm_provider = "dashscope"
        upload = client.post(
            f"/api/v1/groups/{GROUP_DEMO_ID}/knowledge-documents",
            headers=headers(csrf, **{"Idempotency-Key": "preview-evidence"}),
            files={
                "file": (
                    "evidence.md",
                    b"# Evidence\nEvidence supports a claim with reasons.",
                    "text/markdown",
                )
            },
        )
        assert upload.status_code == 201, upload.text
        document_id = upload.json()["document"]["id"]
        with database.session() as db:
            before = {
                model: db.scalar(select(func.count()).select_from(model))
                for model in (Conversation, ConversationTurn, AgentAccountMemory, AgentVersion)
            }
        for question in ["What is evidence?", "What is a claim?"]:
            response = client.post(
                "/api/v1/agents/preview",
                headers=headers(csrf),
                json=body(message=question, document_ids=[document_id]),
            )
            assert response.status_code == 200, response.text
            assert response.json() == {
                "answer": "Evidence supports a claim.",
                "audio_base64": None,
                "audio_content_type": None,
            }
        assert len(captured) == 2
        for call in captured:
            assert [m["role"] for m in call["messages"]] == ["system", "user"]
            system = call["messages"][0]["content"]
            assert "exactly one nonempty sentence" in system
            assert "amber philosopher" in system
            assert "Evidence supports a claim with reasons." in system
            assert "actor_context" not in call  # No runtime Tools, including memory.
        assert captured[1]["messages"][-1]["content"] == "What is a claim?"
        assert "What is evidence?" not in json.dumps(captured[1]["messages"])
        assert captured[0]["scope_id"] != captured[1]["scope_id"]
        with database.session() as db:
            assert before == {
                model: db.scalar(select(func.count()).select_from(model)) for model in before
            }


@pytest.mark.parametrize("version", [{}, {"version_id": None}])
def test_teacher_create_preview_without_version_uses_mock_provider(
    client: TestClient, version: dict[str, Any]
) -> None:
    _, csrf = login(client)
    response = client.post(
        "/api/v1/agents/preview",
        headers=headers(csrf),
        json=body(group_id=None, course_id=COURSE_ID, **version),
    )
    assert response.status_code == 200, response.text
    assert response.json() == {
        "answer": "This is a single-turn preview.",
        "audio_base64": None,
        "audio_content_type": None,
    }


def test_preview_rejects_foreign_sources_and_history(client: TestClient) -> None:
    _, csrf = login(client, "bowen")
    response = client.post(
        "/api/v1/agents/preview", headers=headers(csrf), json=body(document_ids=[str(uuid4())])
    )
    assert response.status_code == 404
    response = client.post("/api/v1/agents/preview", headers=headers(csrf), json=body(history=[]))
    assert response.status_code == 400


def test_preview_uses_configured_voice_and_keeps_text_on_tts_failure(
    app_factory: Any, monkeypatch: Any
) -> None:
    app, _, settings = app_factory()
    profile = SimpleNamespace(target_model_key="fixture")
    monkeypatch.setattr(
        preview,
        "resolve_effective_voice_profile",
        lambda *a: SimpleNamespace(profile=profile, fallback_active=False),
    )
    monkeypatch.setattr(preview, "_profile_external_id", lambda *a: "fixture-voice")
    stream = io.BytesIO()
    with wave.open(stream, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(b"\x00\x00" * 2400)
    calls = []

    def synthesize(text: str, voice: str, **kwargs: Any) -> TTSResult:
        calls.append((text, voice, kwargs))
        return TTSResult(stream.getvalue())

    monkeypatch.setattr(preview, "tts_provider", lambda _: SimpleNamespace(synthesize=synthesize))
    with TestClient(app) as client:
        _, csrf = login(client, "bowen")
        settings.tts_provider = "dashscope"
        request = body(voice_profile_id=str(uuid4()))
        result = client.post("/api/v1/agents/preview", headers=headers(csrf), json=request)
        assert result.status_code == 200, result.text
        assert base64.b64decode(result.json()["audio_base64"]) == stream.getvalue()
        assert calls == [
            (
                "This is a single-turn preview.",
                "fixture-voice",
                {"language": "auto", "target_model_key": "fixture"},
            )
        ]

        def failure(*a: Any, **kw: Any) -> TTSResult:
            raise TTSProviderError()

        monkeypatch.setattr(preview, "tts_provider", lambda _: SimpleNamespace(synthesize=failure))
        result = client.post("/api/v1/agents/preview", headers=headers(csrf), json=request)
        assert result.status_code == 200
        assert result.json()["answer"] == "This is a single-turn preview."
        assert result.json()["audio_base64"] is None


def test_debate_snapshot_freezes_egg_after_agent_changes(app_factory: Any) -> None:
    app, database, _ = app_factory()
    with TestClient(app) as client:
        _, csrf = login(client, "bowen")
        ids = []
        for name in ("Egg", "Scholar"):
            result = client.post(
                f"/api/v1/groups/{GROUP_DEMO_ID}/agents",
                headers=headers(csrf, **{"Idempotency-Key": "egg-freeze-create-" + name}),
                json={"name": name, "visibility": "public"},
            )
            assert result.status_code == 201, result.text
            ids.append((result.json()["id"], result.json()["versions"][0]["id"]))
        a, version_id = ids[0]
        b, _ = ids[1]
        for _, vid in ids:
            result = client.patch(
                f"/api/v1/agent-versions/{vid}",
                headers=headers(csrf),
                json={
                    "expected_revision": 0,
                    "agent_md": "# Philosopher\nYou examine claims with evidence.",
                },
            )
            assert result.status_code == 200, result.text
            revision = result.json()["revision"]
            upload = client.post(
                f"/api/v1/groups/{GROUP_DEMO_ID}/knowledge-documents",
                headers=headers(csrf, **{"Idempotency-Key": "freeze-evidence-" + vid}),
                data={
                    "target_agent_version_id": vid,
                    "expected_revision": str(revision),
                    "visibility": "public",
                },
                files={
                    "file": ("evidence.md", b"# Evidence\nClaims need evidence.", "text/markdown")
                },
            )
            assert upload.status_code == 201, upload.text
            result = client.get(f"/api/v1/agent-versions/{vid}")
            result = client.post(
                f"/api/v1/agent-versions/{vid}/publish",
                headers=headers(csrf, **{"Idempotency-Key": "publish-" + vid}),
                json={"expected_revision": result.json()["revision"]},
            )
            assert result.status_code == 200, result.text
    with database.session() as db:
        version = db.get(AgentVersion, version_id)
        assert version is not None
        version.avatar_config_json = default_config_for("egg").model_dump_json()
    with TestClient(app) as client:
        _, csrf = login(client)
        result = client.post(
            f"/api/v1/courses/{COURSE_ID}/debates",
            headers=headers(csrf, **{"Idempotency-Key": "egg-snapshot-freeze"}),
            json={
                "topic": "What is evidence?",
                "participants": [
                    {"agent_id": a, "stance_mode": "open"},
                    {"agent_id": b, "stance_mode": "open"},
                ],
            },
        )
        assert result.status_code == 201, result.text
        debate = result.json()
        assert debate["participants"][0]["avatar_config"]["template_id"] == "egg"
        with database.session() as db:
            version = db.get(AgentVersion, version_id)
            assert version is not None
            version.avatar_config_json = default_config_for("maya-warm-scholar").model_dump_json()
        reread = client.get(f"/api/v1/debates/{debate['id']}")
        assert reread.status_code == 200
        assert reread.json()["participants"][0]["avatar_config"]["template_id"] == "egg"


def test_real_preview_path_accounts_once_without_chat_rows(
    app_factory: Any, monkeypatch: Any
) -> None:
    from dataclasses import replace

    from app.core.models import ProviderOperation
    from app.modules.agents import preview_provider
    from app.modules.runtime_tools.models import RuntimeModelCallStage
    from app.providers.control_repository import ProviderRepository
    from app.providers.llm_adapter import DashScopeLLMAdapter, DashScopeLLMConfig
    from httpx import Response

    from tests.test_wave4_llm_ledger import _valid_policy

    app, database, settings = app_factory()
    adapter = DashScopeLLMAdapter(
        DashScopeLLMConfig(
            api_key="fixture",
            workspace_id="fixture",
            model_key=settings.chat_settings().llm_model,
        )
    )
    policy = replace(_valid_policy(), endpoint=adapter.config.resolved_endpoint)
    ProviderRepository(database).save_policy_snapshot(policy)
    monkeypatch.setattr(preview_provider, "llm_provider", lambda _: adapter)
    calls = []

    def transport(*a: Any, **kw: Any) -> Response:
        calls.append(json.loads(kw["content"]))
        return Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "One sentence. Another."},
                        "finish_reason": "stop",
                    }
                ]
            },
        )

    monkeypatch.setattr(preview_provider.HttpxLLMTransport, "post_bytes", transport)
    with TestClient(app) as client:
        _, csrf = login(client, "bowen")
        settings.llm_provider = "dashscope"
        settings.llm_provider_policy_hash = policy.policy_hash
        result = client.post("/api/v1/agents/preview", headers=headers(csrf), json=body())
        assert result.status_code == 200, result.text
        assert result.json()["answer"] == "One sentence."
    assert len(calls) == 1
    assert [m["role"] for m in calls[0]["messages"]] == ["system", "user"]
    assert "max_tokens" not in calls[0] and "tools" not in calls[0]
    with database.session() as db:
        operations = list(db.scalars(select(ProviderOperation)))
        assert len(operations) == 1
        assert operations[0].state == "succeeded"
        assert operations[0].charged_request_count == 1
        for model in (Conversation, ConversationTurn, RuntimeModelCallStage, AgentAccountMemory):
            assert db.scalar(select(func.count()).select_from(model)) == 0


def _upload_ready_document(client: TestClient, csrf: str, *, name: str, body_bytes: bytes) -> str:
    upload = client.post(
        f"/api/v1/groups/{GROUP_DEMO_ID}/knowledge-documents",
        headers=headers(csrf, **{"Idempotency-Key": f"preview-doc-{name}"}),
        files={"file": (f"{name}.md", body_bytes, "text/markdown")},
    )
    assert upload.status_code == 201, upload.text
    return upload.json()["document"]["id"]


def _old_lexical_ranking(message: str, chunks: list[KnowledgeDocumentChunk]) -> list[str]:
    """Reproduce the rejected Preview term-overlap ranking for regression contrast."""

    terms = set(re.findall(r"[a-z0-9]+|[\u3400-\u9fff]", message.lower()))
    ranked = [(sum(term in chunk.chunk_text.lower() for term in terms), chunk) for chunk in chunks]
    ranked = [item for item in ranked if item[0]]
    ranked.sort(key=lambda row: (-row[0], row[1].document_id, row[1].chunk_index))
    return [chunk.id for _, chunk in ranked[:6]]


def _replace_document_chunks(
    database: Any,
    document_id: str,
    rows: list[tuple[str, bytes]],
) -> list[KnowledgeDocumentChunk]:
    with database.session() as db:
        db.execute(
            delete(KnowledgeDocumentChunk).where(KnowledgeDocumentChunk.document_id == document_id)
        )
        chunks: list[KnowledgeDocumentChunk] = []
        offset = 0
        for index, (text, blob) in enumerate(rows):
            chunk = KnowledgeDocumentChunk(
                id=str(uuid4()),
                document_id=document_id,
                chunk_index=index,
                chunk_text=text,
                start_offset=offset,
                end_offset=offset + len(text),
                embedding_blob=blob,
                embedding_dimension=EMBEDDING_DIMENSION,
                embedding_key=EMBEDDING_KEY,
            )
            db.add(chunk)
            chunks.append(chunk)
            offset += len(text) + 1
        db.flush()
        for chunk in chunks:
            db.expunge(chunk)
        return chunks


def test_preview_vector_ranking_differs_from_rejected_lexical(
    app_factory: Any, monkeypatch: Any
) -> None:
    app, database, settings = app_factory()
    captured: list[dict[str, Any]] = []

    def reply(*args: Any, **kwargs: Any) -> tuple[str, str]:
        captured.append(kwargs)
        return "Vector evidence wins.", "unused"

    monkeypatch.setattr(preview, "preview_reply", reply)
    question = "alpha beta gamma"
    lexical_text = "alpha beta gamma alpha beta gamma repeated terms."
    vector_text = "alpha beta unique vector target."
    with TestClient(app) as client:
        _, csrf = login(client, "bowen")
        settings.llm_provider = "dashscope"
        document_id = _upload_ready_document(
            client,
            csrf,
            name="vector-vs-lexical",
            body_bytes=b"# Seed\nSeed markdown for indexed document.\n",
        )
        # Zero vector scores below SnapshotRetriever's relaxed threshold, so
        # only the query-aligned chunk survives vector retrieval — while the
        # rejected lexical term-overlap ranker would still prefer the first row.
        zero_blob = mock_embedding("")
        chunks = _replace_document_chunks(
            database,
            document_id,
            [
                (lexical_text, zero_blob),
                (vector_text, mock_embedding(question)),
            ],
        )
        assert _old_lexical_ranking(question, chunks)[0] == chunks[0].id
        result = client.post(
            "/api/v1/agents/preview",
            headers=headers(csrf),
            json=body(
                message=question,
                document_ids=[document_id],
                version_id=None,
                agent_md="You cite the vector winner.",
            ),
        )
        assert result.status_code == 200, result.text
        assert result.json()["answer"] == "Vector evidence wins."
        assert len(captured) == 1
        evidence = json.loads(captured[0]["messages"][0]["content"].split("\n", 1)[1])["evidence"]
        assert evidence == [{"text": vector_text}]
        assert chunks[0].id != chunks[1].id


def test_preview_selected_documents_only_and_rejects_cross_course(
    app_factory: Any, monkeypatch: Any
) -> None:
    app, database, settings = app_factory()
    captured: list[dict[str, Any]] = []

    def reply(*args: Any, **kwargs: Any) -> tuple[str, str]:
        captured.append(kwargs)
        return "Only selected evidence.", "unused"

    monkeypatch.setattr(preview, "preview_reply", reply)
    with TestClient(app) as client:
        _, csrf = login(client, "bowen")
        settings.llm_provider = "dashscope"
        selected = _upload_ready_document(
            client,
            csrf,
            name="selected-evidence",
            body_bytes=b"# Selected\nSelected passage about orchids.\n",
        )
        ignored = _upload_ready_document(
            client,
            csrf,
            name="ignored-evidence",
            body_bytes=b"# Ignored\nIgnored passage about volcanoes.\n",
        )
        result = client.post(
            "/api/v1/agents/preview",
            headers=headers(csrf),
            json=body(
                message="What about orchids?",
                document_ids=[selected],
                version_id=None,
            ),
        )
        assert result.status_code == 200, result.text
        system = captured[0]["messages"][0]["content"]
        assert "orchids" in system
        assert "volcanoes" not in system
        assert ignored != selected

        real_visible = preview.visible_student_document

        def cross_course(db: Any, context: Any, document_id: str) -> Any:
            scoped = real_visible(db, context, document_id)
            scoped.document.course_id = "00000000-0000-4000-8000-000000000099"
            return scoped

        monkeypatch.setattr(preview, "visible_student_document", cross_course)
        denied = client.post(
            "/api/v1/agents/preview",
            headers=headers(csrf),
            json=body(document_ids=[selected], version_id=None),
        )
        assert denied.status_code == 404


def test_preview_unsaved_draft_needs_no_snapshot_or_version(app_factory: Any) -> None:
    app, database, _ = app_factory()
    with TestClient(app) as client:
        _, csrf = login(client, "bowen")
        document_id = _upload_ready_document(
            client,
            csrf,
            name="draft-only",
            body_bytes=b"# Draft\nDraft evidence about rivers.\n",
        )
        with database.session() as db:
            before_versions = db.scalar(select(func.count()).select_from(AgentVersion))
            before_snapshots = db.scalar(select(func.count()).select_from(KnowledgeSnapshot))
            before_chats = {
                model: db.scalar(select(func.count()).select_from(model))
                for model in (Conversation, ConversationTurn, AgentAccountMemory)
            }
        result = client.post(
            "/api/v1/agents/preview",
            headers=headers(csrf),
            json=body(
                message="What about rivers?",
                document_ids=[document_id],
                version_id=None,
                agent_md="You are an unsaved draft persona.",
                voice_profile_id=None,
            ),
        )
        assert result.status_code == 200, result.text
        assert result.json()["answer"] == "This is a single-turn preview."
        with database.session() as db:
            assert db.scalar(select(func.count()).select_from(AgentVersion)) == before_versions
            assert (
                db.scalar(select(func.count()).select_from(KnowledgeSnapshot)) == before_snapshots
            )
            assert before_chats == {
                model: db.scalar(select(func.count()).select_from(model)) for model in before_chats
            }


def test_preview_vector_failure_does_not_lexical_fallback(
    app_factory: Any, monkeypatch: Any
) -> None:
    app, _, settings = app_factory()
    calls: list[str] = []

    def boom(self: MockVectorStore, query: str, *, top_k: int = 6) -> list[Any]:
        del self, query, top_k
        calls.append("vector")
        raise ValueError("vector search failed")

    monkeypatch.setattr(MockVectorStore, "search", boom)
    monkeypatch.setattr(
        preview,
        "preview_reply",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("LLM must not run")),
    )
    with TestClient(app) as client:
        _, csrf = login(client, "bowen")
        settings.llm_provider = "dashscope"
        document_id = _upload_ready_document(
            client,
            csrf,
            name="vector-fail",
            body_bytes=b"# Fail\nalpha beta gamma lexical bait.\n",
        )
        result = client.post(
            "/api/v1/agents/preview",
            headers=headers(csrf),
            json=body(
                message="alpha beta gamma",
                document_ids=[document_id],
                version_id=None,
            ),
        )
        assert result.status_code == 503, result.text
        assert result.json()["code"] == "provider_unavailable"
        assert calls == ["vector"]


def test_preview_sources_uses_mock_vector_store_not_term_overlap() -> None:
    source = (preview.__file__ and open(preview.__file__, encoding="utf-8").read()) or ""
    assert "MockVectorStore" in source
    assert "SnapshotRetriever" in source
    assert "sum(term in chunk.chunk_text.lower() for term in terms)" not in source
    assert 're.findall(r"[a-z0-9]+|[\\u3400-\\u9fff]"' not in source
