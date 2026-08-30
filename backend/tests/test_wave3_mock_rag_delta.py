"""Deterministic acceptance for the versioned Wave 3 Mock RAG honesty delta."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any
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
from app.modules.avatars import DEFAULT_AVATAR_CONFIG
from app.modules.debates.generation import (
    GenerationContext,
    ParticipantContext,
    TurnGenerationService,
    TurnPolicy,
)
from app.modules.debates.generation.retrieval import (
    RetrievalResult,
    SnapshotRetriever,
    TurnSubquery,
)
from app.modules.debates.schemas import (
    MOCK_RETRIEVAL_POLICY_ID,
    RULE_SET_ID_V1,
    RULE_SET_ID_V2,
    DebateRuleSnapshot,
)
from app.modules.debates.setup.rules import canonical_rule_snapshot_json
from app.modules.debates.setup.service import commit_start_plan
from app.modules.knowledge.markdown import EMBEDDING_DIMENSION, EMBEDDING_KEY, mock_embedding
from app.modules.knowledge.mock_lexical import (
    MOCK_LEXICAL_ANCHOR_POLICY_ID,
    MockLexicalAnchorV2,
    frozen_latin_tokens_v2,
)
from app.modules.knowledge.vector import MockVectorStore, StoredVectorRow
from app.providers.llm import MockLLMProvider
from fastapi.testclient import TestClient
from sqlalchemy import select

from tests.conftest import login

COURSE_ID = "b1ae79ed-e4a6-5b02-9abd-3a3ae944284b"
GROUP_BOWEN_ID = "66ee37fb-5772-5c8f-bb63-46d1783c53ae"
GROUP_KAIKAI_ID = "699112be-780b-5ffd-9a87-3762f596c558"


def _headers(csrf: str, **extra: str) -> dict[str, str]:
    return {"Origin": "http://testserver", "X-CSRF-Token": csrf, **extra}


def _insert_sql_published_agent(
    database: Database,
    *,
    group_id: str,
    name: str,
    evidence: str,
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
        db.add(
            AgentVersion(
                id=version_id,
                agent_id=agent_id,
                version_seq=0,
                state="published",
                revision=1,
                agent_md=f"# Identity\n{name} offers a careful classroom viewpoint.",
                avatar_config_json=DEFAULT_AVATAR_CONFIG.model_dump_json(),
                voice_profile_id=None,
                knowledge_snapshot_id=snapshot_id,
                published_at=now,
                created_at=now,
                updated_at=now,
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


def test_turn_generation_passes_authoritative_topic_separately_from_subquery_text() -> None:
    first = ParticipantContext(
        participant_id="participant-a",
        agent_id="agent-a",
        agent_name="A",
        slot="A",
        order_index=0,
        snapshot_id="snapshot-a",
        agent_md="# A\nA careful viewpoint.",
    )
    second = ParticipantContext(
        participant_id="participant-b",
        agent_id="agent-b",
        agent_name="B",
        slot="B",
        order_index=1,
        snapshot_id="snapshot-b",
        agent_md="# B\nA careful viewpoint.",
    )
    plan = TurnPolicy(rule_set_id=RULE_SET_ID_V2).plan((first, second))[0]
    service = TurnGenerationService(
        SnapshotRetriever(
            _FixedSearch(
                (
                    {
                        "chunk_id": "mineral",
                        "source_filename": "mineral.md",
                        "score": 0.99,
                        "chunk_text": (
                            "Bowenite is a hard green mineral used in carving and geology."
                        ),
                    },
                )
            )
        ),
        MockLLMProvider(),
        rule_set_id=RULE_SET_ID_V2,
        mock_retrieval_policy_id=MOCK_LEXICAL_ANCHOR_POLICY_ID,
    )
    result = service.generate(
        GenerationContext(
            "debate-a",
            "Should the United States ban TikTok's recommendation algorithm?",
            plan,
            first,
            (first, second),
        )
    )
    assert result.final_ready.retrieval_status == "no_match"
    assert result.final_ready.used_receipts == ()


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


def test_rule_snapshot_versions_are_explicit_and_legacy_json_remains_readable() -> None:
    current = json.loads(canonical_rule_snapshot_json())
    assert current["rule_set_id"] == RULE_SET_ID_V2
    assert current["retrieval_policy_id"] == MOCK_RETRIEVAL_POLICY_ID

    legacy_raw = (
        '{"rule_set_id":"ordered_multi_agent_rounds_demo_v1","round_count":2,'
        '"min_participants":2,"max_participants":5,"min_words":80,"max_words":200,'
        '"target_min_words":160,"target_max_words":185}'
    )
    parsed = DebateRuleSnapshot.model_validate_json(legacy_raw)
    assert parsed.rule_set_id == RULE_SET_ID_V1
    assert parsed.retrieval_policy_id is None
    assert "retrieval_policy_id" not in json.loads(
        canonical_rule_snapshot_json(rule_set_id=RULE_SET_ID_V1)
    )


def test_sql_turn_preparer_applies_v2_anchor_and_leaves_persisted_v1_unfiltered(
    app_factory: Any,
) -> None:
    """Exercise the real snapshot SQL adapter with a forced high vector score."""

    from app.modules.debates.models import Debate
    from app.modules.debates.playback.generation_adapter import SqlTurnPreparer
    from app.modules.debates.playback.protocols import PreparedTurn

    topic = "Should the United States ban TikTok's recommendation algorithm?"
    exact_query = (
        f"{topic}\nState this participant's viewpoint and core reasons.\n"
        "Current position: the current position"
    )
    app, database, settings = app_factory()
    with TestClient(app) as client:
        relevant_agent = _insert_sql_published_agent(
            database,
            group_id=GROUP_BOWEN_ID,
            name="Relevant SQL",
            evidence=(
                "TikTok recommendation algorithm governance affects creator visibility "
                "and user choice."
            ),
        )
        mineral_agent = _insert_sql_published_agent(
            database,
            group_id=GROUP_KAIKAI_ID,
            name="Mineral SQL",
            evidence="Bowenite is a hard green mineral used in carving and geological study.",
        )
        partner_agent = _insert_sql_published_agent(
            database,
            group_id=GROUP_BOWEN_ID,
            name="Partner SQL",
            evidence="Classroom dialogue can compare evidence and general reasoning.",
        )

        # Force both first chunks to a perfect score for the exact generated
        # subquery.  The v2 negative must still fail on chunk text, proving the
        # result is not merely below the vector threshold.
        with database.session() as db:
            for agent_id in (relevant_agent, mineral_agent):
                agent = db.get(Agent, agent_id)
                assert agent is not None and agent.current_published_version_id
                version = db.get(AgentVersion, agent.current_published_version_id)
                assert version is not None and version.knowledge_snapshot_id
                chunk = db.scalar(
                    select(KnowledgeChunk).where(
                        KnowledgeChunk.snapshot_id == version.knowledge_snapshot_id
                    )
                )
                assert chunk is not None
                chunk.embedding_blob = mock_embedding(exact_query)

        _session, csrf = login(client)

        def prepare(
            first_agent_id: str,
            *,
            idempotency_key: str,
            legacy_v1: bool = False,
        ) -> PreparedTurn:
            response = client.post(
                f"/api/v1/courses/{COURSE_ID}/debates",
                headers=_headers(csrf, **{"Idempotency-Key": idempotency_key}),
                json={
                    "topic": topic,
                    "participants": [
                        {"agent_id": first_agent_id, "stance_mode": "open"},
                        {"agent_id": partner_agent, "stance_mode": "open"},
                    ],
                    "round_count": 2,
                },
            )
            assert response.status_code == 201, response.text
            debate_id = response.json()["id"]
            with database.session() as db:
                debate = db.get(Debate, debate_id)
                assert debate is not None
                if legacy_v1:
                    debate.rule_set_id = RULE_SET_ID_V1
                    debate.rule_snapshot_json = canonical_rule_snapshot_json(
                        rule_set_id=RULE_SET_ID_V1
                    )
                turns = commit_start_plan(db, debate_id=debate_id)
                assert turns
                return SqlTurnPreparer(settings=settings)(
                    db,
                    debate,
                    turns[0],
                    attempt=1,
                    cancellation_generation=0,
                )

        relevant_v2 = prepare(
            relevant_agent,
            idempotency_key="wave3-rag-sql-relevant-v2",
        )
        unrelated_v2 = prepare(
            mineral_agent,
            idempotency_key="wave3-rag-sql-mineral-v2",
        )
        same_row_v1 = prepare(
            mineral_agent,
            idempotency_key="wave3-rag-sql-mineral-v1",
            legacy_v1=True,
        )

        assert relevant_v2.retrieval_status == "matched"
        assert len(relevant_v2.sources) >= 1
        assert unrelated_v2.retrieval_status == "no_match"
        assert unrelated_v2.sources == ()
        assert same_row_v1.retrieval_status == "matched"
        assert len(same_row_v1.sources) >= 1
