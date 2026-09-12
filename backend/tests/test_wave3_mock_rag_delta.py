"""Deterministic acceptance for the versioned Wave 3 Mock RAG honesty delta."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from datetime import UTC, datetime
from uuid import uuid4

from app.core.db import Database
from app.core.models import (
    Agent,
    AgentVersion,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeSnapshot,
    SnapshotDocument,
    StoredFile,
)
from app.modules.agents.persona import compile_persona
from app.modules.avatars import DEFAULT_AVATAR_CONFIG
from app.modules.debates.generation.retrieval import (
    RetrievalResult,
    SnapshotRetriever,
    TurnSubquery,
)
from app.modules.knowledge.markdown import EMBEDDING_DIMENSION, EMBEDDING_KEY, mock_embedding
from app.modules.knowledge.mock_lexical import (
    MOCK_LEXICAL_ANCHOR_POLICY_ID,
    MockLexicalAnchorV2,
    frozen_latin_tokens_v2,
)
from app.modules.knowledge.vector import MockVectorStore, StoredVectorRow

COURSE_ID = "b1ae79ed-e4a6-5b02-9abd-3a3ae944284b"
GROUP_DEMO_ID = "7813f937-902c-5534-bfb2-ad773a43aeda"
GROUP_DEMO_ID = "7813f937-902c-5534-bfb2-ad773a43aeda"


def _headers(csrf: str, **extra: str) -> dict[str, str]:
    return {"Origin": "http://testserver", "X-CSRF-Token": csrf, **extra}


def _insert_sql_published_agent(
    database: Database,
    *,
    group_id: str,
    name: str,
    evidence: str,
    confirmed_persona: bool = True,
) -> str:
    now = datetime.now(UTC)
    agent_id, version_id, snapshot_id, document_id, file_id, snapshot_document_id = (
        str(uuid4()) for _ in range(6)
    )
    chunk_id = str(uuid4())
    relative_path = f"groups/{group_id}/knowledge/{document_id}/{name.lower()}.md"
    path = database.data_root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = evidence.encode("utf-8")
    path.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    with database.session() as db:
        db.add(
            StoredFile(
                id=file_id,
                kind="markdown",
                relative_path=relative_path,
                sha256=digest,
                size_bytes=len(raw),
                state="active",
                created_at=now,
                updated_at=now,
            )
        )
        db.add(
            KnowledgeDocument(
                id=document_id,
                group_id=group_id,
                source_filename=f"{name.lower()}-evidence.md",
                stored_file_id=file_id,
                char_count=len(evidence),
                index_status="ready",
                index_revision=1,
                workspace_state="active",
                content_hash=digest,
                safe_error_code=None,
                created_at=now,
                updated_at=now,
            )
        )
        db.flush()
        db.add(
            Agent(
                id=agent_id,
                group_id=group_id,
                name=name,
                description=f"{name} classroom perspective",
                status="active",
                current_published_version_id=version_id,
                created_at=now,
                updated_at=now,
            )
        )
        db.flush()
        agent_md = f"# Identity\n{name} offers a careful classroom viewpoint."
        persona_fields: dict[str, object] = {}
        if confirmed_persona:
            agent_md = (
                f"# {name}\n\n"
                "## Identity\n\n"
                "- Role: Classroom technology ethics expert\n"
                "- Historical or cultural context: A fictional cross-cultural classroom.\n\n"
                "## Cultural lens\n\n- Community accountability\n\n"
                "## Core values\n\n- Fairness\n- Transparency\n\n"
                "## Initial position\n\nPrefer evidence-aware proportional safeguards.\n\n"
                "## Speaking style\n\n"
                "- Tone: Careful and respectful\n"
                "- Argument pattern: State a claim, examine evidence, then qualify it\n"
                "- Concession style: Acknowledge a sound point before refining it\n"
                "- Question style: Ask one focused and answerable question\n\n"
                "## Debate strategy\n\n- Compare trade-offs without manufacturing conflict\n\n"
                "## Boundaries\n\n- Never invent evidence outside the assigned snapshot\n"
            )
            compiled = compile_persona(agent_md, expected_name=name)
            assert compiled.compiled and compiled.canonical_json and compiled.persona_spec_hash
            persona_fields = {
                "raw_agent_md_hash": compiled.source_agent_md_hash,
                "persona_spec_json": compiled.canonical_json,
                "persona_spec_hash": compiled.persona_spec_hash,
                "persona_compiler_version": compiled.compiler_version,
                "persona_diagnostics_json": "[]",
                "persona_confirmation_revision": 1,
                "student_confirmed_at": now,
                "persona_confirming_user_id": "wave4-test-student",
            }
        db.add(
            AgentVersion(
                id=version_id,
                agent_id=agent_id,
                version_seq=0,
                state="published",
                revision=1,
                agent_md=agent_md,
                avatar_config_json=DEFAULT_AVATAR_CONFIG.model_dump_json(),
                voice_profile_id=None,
                knowledge_snapshot_id=snapshot_id,
                published_at=now,
                created_at=now,
                updated_at=now,
                **persona_fields,
            )
        )
        db.flush()
        db.add(
            KnowledgeSnapshot(
                id=snapshot_id,
                agent_version_id=version_id,
                stored_file_id=file_id,
                content_hash=digest,
                total_char_count=len(evidence),
                embedding_key=EMBEDDING_KEY,
                chunking_json='{"kind":"test"}',
                created_at=now,
            )
        )
        db.flush()
        db.add(
            SnapshotDocument(
                id=snapshot_document_id,
                snapshot_id=snapshot_id,
                document_id=document_id,
                stored_file_id=file_id,
                source_filename=f"{name.lower()}-evidence.md",
                char_count=len(evidence),
                order_index=0,
            )
        )
        db.flush()
        db.add(
            KnowledgeChunk(
                id=chunk_id,
                snapshot_id=snapshot_id,
                snapshot_document_id=snapshot_document_id,
                document_id=document_id,
                chunk_index=0,
                chunk_text=evidence,
                start_offset=0,
                end_offset=len(evidence),
                embedding_blob=mock_embedding(evidence),
                embedding_dimension=EMBEDDING_DIMENSION,
                embedding_key=EMBEDDING_KEY,
            )
        )
    return agent_id


class _FixedSearch:
    def __init__(self, rows: Iterable[object]) -> None:
        self.rows = tuple(rows)

    def search(self, snapshot_id: str, query: str, *, top_k: int = 6) -> tuple[object, ...]:
        del snapshot_id, query
        return self.rows[:top_k]


def _retrieval(
    topic: str, chunks: tuple[str, ...], *, subquery: str | None = None
) -> RetrievalResult:
    rows = tuple(
        StoredVectorRow(
            chunk_id=f"chunk-{index}",
            source_filename=f"source-{index}.md",
            chunk_text=text,
            blob=mock_embedding(text),
            dimension=EMBEDDING_DIMENSION,
            key=EMBEDDING_KEY,
            document_order=index,
            chunk_index=0,
        )
        for index, text in enumerate(chunks)
    )
    return SnapshotRetriever(MockVectorStore(rows)).retrieve(
        "snapshot-a",
        (TurnSubquery("rebuttal", subquery or topic),),
        policy_id=MOCK_LEXICAL_ANCHOR_POLICY_ID,
        topic_anchor=topic,
    )


def test_frozen_latin_topic_tokens_remove_stop_words_possessives_and_diacritics() -> None:
    assert frozen_latin_tokens_v2(
        "Should TikTok's naïve recommendation be trusted in 2026?"
    ) == frozenset({"tiktok", "naive", "recommendation", "trusted"})
    assert MockLexicalAnchorV2.from_topic("How to climb the mountain?").required_overlap == 2
    assert MockLexicalAnchorV2.from_topic("TikTok").required_overlap == 1
    assert not MockLexicalAnchorV2.from_topic("Should we?").accepts("Should we continue?")


def test_mock_v2_fixed_positive_and_negative_relevance_examples() -> None:
    tiktok_topic = "Should the United States ban TikTok's recommendation algorithm?"
    tiktok = _retrieval(
        tiktok_topic,
        (
            "TikTok recommendation algorithm governance can affect creator visibility "
            "and user choice.",
        ),
    )
    minerals = _retrieval(
        tiktok_topic,
        ("Bowenite is a hard green mineral variety used for carving and geological study.",),
    )

    intimacy_topic = (
        "Can lasting intimacy preserve excitement and independence without sacrificing honesty, "
        "trust, and emotional security?"
    )
    intimacy = _retrieval(
        intimacy_topic,
        (
            "Lasting intimacy grows through honest responsiveness, trust, emotional security, "
            "and room for independence.",
        ),
    )
    hiking = _retrieval(
        "How to climb the mountain?",
        (
            "TikTok recommendation systems shape digital visibility.",
            "Intimacy and partner responsiveness can strengthen trust in relationships.",
        ),
    )

    assert tiktok.matched
    assert not minerals.matched
    assert intimacy.matched
    assert not hiking.matched


def test_g3_ai_policy_topic_rejects_relationship_policy_scaffolding() -> None:
    topic = "Should schools require transparent rules for AI recommendation systems?"
    relationship_chunk = (
        "Gratitude is not submission and does not require accepting every request. "
        "Official resource: https://rainn.org/5-rules-for-getting-consent/"
    )
    relevant_chunk = (
        "Schools should publish transparent rules explaining how AI recommendation systems "
        "rank classroom content."
    )
    anchor = MockLexicalAnchorV2.from_topic(topic)

    # Before this fix, ``require`` came from the prose while ``rules`` came
    # only from the RAINN URL slug.  URL provenance must not provide a second
    # lexical anchor token for unrelated evidence.
    assert anchor.topic_tokens.intersection(frozen_latin_tokens_v2(relationship_chunk)) == {
        "require"
    }
    assert not anchor.accepts(relationship_chunk)
    assert anchor.accepts(relevant_chunk)

    unrelated = _retrieval(topic, (relationship_chunk,))
    relevant = _retrieval(topic, (relevant_chunk,))
    assert not unrelated.matched
    assert relevant.matched


def test_single_topic_token_must_overlap_and_relaxed_threshold_stays_available() -> None:
    single_match = _retrieval(
        "TikTok",
        ("TikTok platforms can shape creator visibility.",),
    )
    single_miss = _retrieval(
        "TikTok",
        ("Bowenite is a hard green mineral.",),
    )
    relaxed = SnapshotRetriever(
        _FixedSearch(
            (
                {
                    "chunk_id": "relaxed",
                    "source_filename": "relaxed.md",
                    "score": 0.10,
                    "chunk_text": "TikTok recommendation evidence.",
                },
            )
        )
    ).retrieve(
        "snapshot-relaxed",
        (TurnSubquery("viewpoint", "TikTok recommendation"),),
        policy_id=MOCK_LEXICAL_ANCHOR_POLICY_ID,
        topic_anchor="TikTok recommendation",
    )
    assert single_match.matched
    assert not single_miss.matched
    assert relaxed.matched
    assert relaxed.receipts[0].threshold_key == "relaxed"
    assert relaxed.relaxed_calls == 1


def test_round_two_generic_predecessor_query_cannot_bypass_topic_anchor() -> None:
    result = _retrieval(
        "How to climb the mountain?",
        ("TikTok recommendation algorithm policy protects digital platform users.",),
        subquery=(
            "Rebut this generic predecessor claim about TikTok recommendation algorithm policy "
            "and support the updated position."
        ),
    )
    assert not result.matched
    assert result.policy_id == MOCK_LEXICAL_ANCHOR_POLICY_ID
    assert result.topic_anchor_hash is not None


def test_v2_keeps_receipt_rank_identity_cap_and_v1_behavior_is_unchanged() -> None:
    topic = "TikTok recommendation algorithm"
    chunks = tuple(
        f"TikTok recommendation algorithm evidence passage number {index}." for index in range(9)
    )
    v2 = _retrieval(topic, chunks)
    assert len(v2.receipts) == 6
    assert [item.rank for item in v2.receipts] == [1, 2, 3, 4, 5, 6]
    assert len({item.resolved_evidence_id() for item in v2.receipts}) == 6

    unrelated = "Bowenite is a hard green mineral used in carving."
    legacy = SnapshotRetriever(
        MockVectorStore(
            (
                StoredVectorRow(
                    chunk_id="legacy-chunk",
                    source_filename="legacy.md",
                    chunk_text=unrelated,
                    blob=mock_embedding(unrelated),
                    dimension=EMBEDDING_DIMENSION,
                    key=EMBEDDING_KEY,
                    document_order=0,
                    chunk_index=0,
                ),
            )
        )
    ).retrieve(
        "legacy-snapshot",
        (TurnSubquery("viewpoint", unrelated),),
    )
    assert legacy.matched
    assert legacy.policy_id is None
