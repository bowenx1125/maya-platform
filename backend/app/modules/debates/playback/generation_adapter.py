"""SQL adapter from frozen Wave 2 rows to the pure M11 generator.

The adapter is deliberately provider-neutral.  It loads only the selected
participant's immutable AgentVersion and KnowledgeSnapshot, reconstructs the
complete final-ready predecessor prefix, and returns one validated
``PreparedTurn`` for the separate playback/TTS stage.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import replace
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import PlatformError, conflict
from app.core.models import (
    Agent,
    AgentVersion,
    CourseMember,
    Group,
    KnowledgeChunk,
    KnowledgeSnapshot,
    ProviderPolicySnapshot,
    SnapshotDocument,
)
from app.modules.agents.persona_service import (
    PERSONA_CONFIRMATION_REQUIRED,
    is_persona_confirmed,
)
from app.modules.debates.generation import (
    FinalReadyTurn,
    GenerationContext,
    MutualLearningValidator,
    ParticipantContext,
    SnapshotRetrievalReceipt,
    SnapshotRetriever,
    StructuredTurnResult,
    TurnGenerationService,
    TurnPolicy,
    build_provider_prompt,
    build_turn_subqueries,
    compute_prompt_receipt_hash,
    compute_transcript_hash,
    public_evidence_trace,
)
from app.modules.debates.generation.mutual_learning_policy import (
    MUTUAL_LEARNING_RULE_SET_ID,
)
from app.modules.debates.generation.prompt_request import confirmed_persona_provider_view
from app.modules.debates.generation.recovery import LLMRecoveryService
from app.modules.debates.generation.runtime import LLMTurnRuntime
from app.modules.debates.generation.types import MutualLearningTurnResultV1
from app.modules.debates.generation.validator import count_turn_words
from app.modules.debates.models import DebateParticipant, DebateTurn
from app.modules.knowledge.mock_lexical import MOCK_LEXICAL_ANCHOR_POLICY_ID
from app.modules.knowledge.providers.adapters import (
    DashScopeEmbeddingConfig,
    EmbeddingAcceptanceUnknown,
    EmbeddingTransportNotSent,
)
from app.modules.knowledge.providers.product_publication import (
    ProductPublicationError,
    require_exact_confirmation,
)
from app.modules.knowledge.providers.query_embedding import (
    QueryEmbeddingError,
    QueryEmbeddingService,
    persisted_snapshot_identity,
)
from app.modules.knowledge.providers.query_manifest import (
    QueryManifestError,
    ensure_real_query_export_manifest,
)
from app.modules.knowledge.providers.snapshot_build import REAL_EMBEDDING_PROVIDER
from app.modules.knowledge.providers.sql_query import (
    REAL_CORE_DEMO_QUERY_MAX_REQUESTS,
    SQL_QUERY_MAX_REQUESTS,
    SqlAlchemyQueryControlAdapter,
    SqlQueryError,
    controlled_query_provider,
)
from app.modules.knowledge.providers.sql_stage import SqlAlchemyEmbeddingStageStore
from app.modules.knowledge.providers.tokenizer import TokenizerError, count_tokens
from app.modules.knowledge.vector import IdentityVectorStore, StoredVectorRow
from app.providers.control import (
    LLM_DEBATE_TURN_BUCKET,
    ProviderScopeBudgetV1,
)
from app.providers.control_repository import ProviderRepository
from app.providers.factory import (
    embedding_provider as select_embedding_provider,
)
from app.providers.factory import (
    llm_provider as select_fixed_llm_provider,
)
from app.providers.llm import LLMProvider, llm_provider
from app.providers.llm_adapter import DashScopeLLMAdapter
from app.providers.llm_price_card import debate_budget_cap, real_core_demo_budget_cap

from .llm_publication import SqlLLMPublication
from .protocols import PreparedGenerationFence, PreparedSource, PreparedTurn
from .schemas import RetrievalSourceDTO


def _provider_policy_hash(settings: object | None, slice_name: str) -> str | None:
    """Resolve one endpoint policy while retaining legacy test settings."""

    resolver = getattr(settings, "provider_policy_hash_for", None)
    if callable(resolver):
        return cast(str | None, resolver(slice_name))
    explicit = getattr(settings, f"{slice_name}_provider_policy_hash", None)
    if isinstance(explicit, str) and explicit:
        return explicit
    legacy = getattr(settings, "provider_policy_hash", None)
    provider = getattr(settings, f"{slice_name}_provider", "mock")
    other = "llm" if slice_name == "embedding" else "embedding"
    other_provider = getattr(settings, f"{other}_provider", "mock")
    if (
        isinstance(legacy, str)
        and legacy
        and provider == "dashscope"
        and other_provider != "dashscope"
    ):
        return legacy
    return None


def _dual_real(settings: object | None) -> bool:
    return (
        getattr(settings, "llm_provider", "mock") == "dashscope"
        and getattr(settings, "embedding_provider", "mock") == "dashscope"
    )


def _assert_llm_provider_endpoint(
    adapter: DashScopeLLMAdapter,
    policy: object,
) -> None:
    """Bind the configured LLM resource to the selected policy before setup."""

    try:
        configured_endpoint = adapter.config.resolved_endpoint
        policy_endpoint = getattr(policy, "endpoint", None)
        matches = isinstance(policy_endpoint, str) and configured_endpoint == policy_endpoint
    except Exception:
        matches = False
    if not matches:
        raise PlatformError(
            "provider_preflight_blocked",
            "The exact LLM Provider resource changed.",
            503,
        )


class SqlSnapshotSearch:
    """Search one immutable Snapshot through its persisted five-field identity."""

    def __init__(
        self,
        db: Session,
        *,
        query_embeddings: QueryEmbeddingService | None = None,
    ) -> None:
        self.db = db
        self.query_embeddings = query_embeddings or QueryEmbeddingService()

    def search(self, snapshot_id: str, query: str, *, top_k: int = 6) -> tuple[object, ...]:
        snapshot = self.db.get(KnowledgeSnapshot, snapshot_id)
        if snapshot is None:
            raise ValueError("the immutable query Snapshot is unavailable")
        identity = persisted_snapshot_identity(snapshot)
        rows = self.db.execute(
            select(KnowledgeChunk, SnapshotDocument)
            .join(
                SnapshotDocument,
                SnapshotDocument.id == KnowledgeChunk.snapshot_document_id,
            )
            .where(
                KnowledgeChunk.snapshot_id == snapshot_id,
                SnapshotDocument.snapshot_id == snapshot_id,
            )
            .order_by(SnapshotDocument.order_index, KnowledgeChunk.chunk_index)
        ).all()
        vectors = [
            StoredVectorRow(
                chunk_id=chunk.id,
                source_filename=document.source_filename,
                chunk_text=chunk.chunk_text,
                blob=chunk.embedding_blob,
                dimension=chunk.embedding_dimension,
                key=chunk.embedding_key,
                document_order=document.order_index,
                chunk_index=chunk.chunk_index,
            )
            for chunk, document in rows
        ]
        store = IdentityVectorStore(identity, vectors)
        query_value = self.query_embeddings.embed_query(snapshot, query)
        return tuple(store.search_values(query_value, top_k=top_k))


class SqlSnapshotRetriever(SnapshotRetriever):
    """Snapshot retriever that binds immutable document offsets to receipts."""

    def __init__(
        self,
        db: Session,
        *,
        query_embeddings: QueryEmbeddingService | None = None,
    ) -> None:
        self._db = db
        super().__init__(SqlSnapshotSearch(db, query_embeddings=query_embeddings))

    def retrieve(self, *args: Any, **kwargs: Any) -> Any:
        result = super().retrieve(*args, **kwargs)
        enriched = []
        for receipt in result.receipts:
            chunk = self._db.get(KnowledgeChunk, receipt.chunk_id)
            document = (
                self._db.get(SnapshotDocument, chunk.snapshot_document_id)
                if chunk is not None
                else None
            )
            if chunk is None or document is None:
                enriched.append(receipt)
                continue
            enriched.append(
                replace(
                    receipt,
                    source_document_id=str(document.id),
                    source_start_offset=int(chunk.start_offset),
                    source_end_offset=int(chunk.end_offset),
                    excerpt=str(chunk.chunk_text),
                )
            )
        return replace(result, receipts=tuple(enriched))


class SqlTurnPreparer:
    """Build and run one M11 generation context from M10's immutable rows."""

    def __init__(
        self,
        *,
        settings: object | None = None,
        llm: LLMProvider | None = None,
        llm_runtime: LLMTurnRuntime | None = None,
        llm_runtime_options: Mapping[str, object] | None = None,
    ) -> None:
        self.settings = settings
        if llm is not None:
            self.llm = llm
        elif settings is not None and getattr(settings, "llm_provider", "mock") == "dashscope":
            self.llm = select_fixed_llm_provider(cast(Settings, settings))
        else:
            self.llm = llm_provider(cast(Settings, settings))
        self.llm_runtime = llm_runtime
        self.llm_runtime_options = dict(llm_runtime_options or {})

    @staticmethod
    def _authoritative_identity_tokens(
        db: Session,
        *,
        course_id: str,
        group_id: str,
        participants: tuple[ParticipantContext, ...],
    ) -> tuple[str, ...]:
        """Collect identity tokens from the current course/group graph only."""

        values: list[str] = []

        def add(value: object) -> None:
            if isinstance(value, str) and value.strip():
                values.append(value)

        member_ids = db.scalars(
            select(CourseMember.user_id).where(CourseMember.course_id == course_id)
        ).all()
        for member_id in member_ids:
            add(str(member_id))
        # Only the stable authenticated identifier is withheld. Usernames and
        # display names are deliberately not treated as identity here (owner
        # decision, 2026-09-02): they are ordinary given names a teacher may
        # legitimately put in a topic or an Agent name, and blocking them
        # failed the whole turn closed behind a code that named no cause.
        # Agent names are fictional or cultural labels and are an intentional
        # field of PersonaProviderViewV1 for the same reason.
        del group_id, participants
        return tuple(
            dict.fromkeys(
                value.strip()
                for value in values
                if isinstance(value, str) and len(value.strip()) >= 3
            )
        )

    def _llm_runtime_for_turn(
        self,
        db: Session,
        *,
        debate: Any,
        turn: DebateTurn,
        participant_row: DebateParticipant,
        participants: tuple[ParticipantContext, ...],
    ) -> tuple[LLMTurnRuntime | None, Mapping[str, object], Any | None]:
        """Compose the real LLM runtime and its pre-manifest callback.

        The callback is invoked only after the pure prompt builder has
        produced the exact two messages.  It scans those messages, persists
        the owner-bound manifest, and exposes the current confirmation state;
        no operation reservation exists until that callback succeeds.
        """

        if self.llm_runtime is not None:
            return self.llm_runtime, self.llm_runtime_options, None
        if not isinstance(self.llm, DashScopeLLMAdapter):
            return None, {}, None
        configured_policy_hash = _provider_policy_hash(self.settings, "llm")
        policy_hash = self.llm_runtime_options.get("policy_hash") or configured_policy_hash
        if not isinstance(policy_hash, str) or not policy_hash:
            raise PlatformError(
                "provider_preflight_blocked",
                "The exact LLM Provider policy is unavailable.",
                503,
            )
        repository = ProviderRepository(db, require_export_confirmation=False)
        publication = SqlLLMPublication(db, ledger=repository)
        policy = repository.get_policy_snapshot(policy_hash)
        if policy is None or policy.policy_hash != policy_hash:
            raise PlatformError(
                "provider_preflight_blocked",
                "The exact LLM Provider policy is unavailable.",
                503,
            )
        # Endpoint identity is checked before manifest creation, scope-budget
        # persistence or any transport boundary. A policy hash from the other
        # real slice (or a swapped workspace resource) therefore fails closed
        # without creating a zero-use operation or issuing a request.
        _assert_llm_provider_endpoint(self.llm, policy)
        policy_row_id = db.scalar(
            select(ProviderPolicySnapshot.id).where(
                ProviderPolicySnapshot.policy_hash == policy_hash
            )
        )
        if policy_row_id is None:
            raise PlatformError(
                "provider_preflight_blocked",
                "The exact LLM Provider policy snapshot is unavailable.",
                503,
            )
        try:
            dual_real = _dual_real(self.settings)
            # The Debate carries its own round count, so the budget scales with
            # the actual 2-5 Agent x 2-5 round shape instead of assuming two.
            debate_rounds = int(getattr(debate, "round_count", 2) or 2)
            cap = (
                real_core_demo_budget_cap(len(participants), round_count=debate_rounds)
                if dual_real
                else debate_budget_cap(len(participants), round_count=debate_rounds)
            )
            repository.ensure_scope_budget(
                str(debate.id),
                ProviderScopeBudgetV1(
                    max_requests=cap.max_requests,
                    max_total_tokens=cap.max_total_tokens,
                    max_cost_cny=float(cap.max_cost_cny),
                    budget_bucket=LLM_DEBATE_TURN_BUCKET,
                ),
            )
        except Exception as exc:
            raise PlatformError(
                "provider_preflight_blocked",
                "The exact LLM budget is unavailable.",
                503,
            ) from exc
        outbound_manifest = getattr(self.llm, "outbound_manifest", None)
        if outbound_manifest is None:
            from app.providers.llm_privacy import LLMOutboundManifestV1

            # The Real-Core Demo used to force a one-shot envelope so a fixed
            # seven-request budget could never be exceeded.  The acceptance
            # budget is now derived from the Debate's own shape, so the standard
            # two-attempt envelope applies here too: a structure repair is the
            # same authorized request sent once more with frozen feedback, and
            # it is what lets a real provider turn recover from a first reply
            # that misses a phase field instead of failing the whole Debate.
            outbound_manifest = LLMOutboundManifestV1()
            self.llm.outbound_manifest = outbound_manifest
        runtime = LLMTurnRuntime(
            ledger=repository,
            adapter=self.llm,
            stage_store=publication,
            manifest_store=repository,
            agent_count=len(participants),
            round_count=debate_rounds,
            defer_publication=True,
            budget_cap=cap,
        )
        version = db.get(AgentVersion, str(participant_row.agent_version_id))
        agent = db.get(Agent, version.agent_id) if version is not None else None
        group = db.get(Group, agent.group_id) if agent is not None else None
        if version is None or agent is None or group is None:
            raise PlatformError(
                "provider_preflight_blocked",
                "The frozen LLM Persona owner is unavailable.",
                503,
            )
        static_options: dict[str, object] = {
            "scope_id": str(debate.id),
            "policy_hash": policy_hash,
            "policy_snapshot_id": str(policy_row_id),
            "course_id": str(group.course_id),
            "group_id": str(group.id),
            "agent_version_id": str(version.id),
            "repair_policy_hash": getattr(outbound_manifest, "repair_policy_hash", None) or "",
            "outbound_manifest": outbound_manifest,
            "identity_tokens": tuple(
                dict.fromkeys(
                    (
                        *self._authoritative_identity_tokens(
                            db,
                            course_id=str(group.course_id),
                            group_id=str(group.id),
                            participants=participants,
                        ),
                        *tuple(getattr(self.llm, "identity_tokens", ())),
                    )
                )
            ),
        }

        def prepare_manifest(
            prompt: object,
            context: GenerationContext,
            _receipts: object,
            _queries: object,
        ) -> Mapping[str, object]:
            request = getattr(prompt, "request", None)
            request_hash = str(getattr(request, "request_hash", ""))
            build_manifest_hash = hashlib.sha256(
                json.dumps(
                    {
                        "version": "llm-turn-build-v1",
                        "debate_id": str(context.debate_id),
                        "turn_id": str(context.turn.turn_id),
                        "request_hash": request_hash,
                        "persona_spec_hash": str(getattr(request, "persona_spec_hash", "")),
                        "transcript_hash": str(getattr(request, "transcript_hash", "")),
                        "receipt_hash": str(getattr(request, "receipt_hash", "")),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            manifest = runtime.prepare_manifest(
                prompt,  # type: ignore[arg-type]
                debate_id=str(debate.id),
                turn_id=str(turn.id),
                policy_hash=policy_hash,
                build_manifest_hash=build_manifest_hash,
                policy_snapshot_id=str(policy_row_id),
                course_id=str(group.course_id),
                group_id=str(group.id),
                agent_version_id=str(version.id),
                identity_tokens=tuple(static_options["identity_tokens"]),  # type: ignore[arg-type]
                outbound_manifest=outbound_manifest,
            )
            persisted = repository.get_export_manifest(manifest.manifest_hash) or manifest
            confirmed = False
            confirmation_revision = int(persisted.operation_revision)
            try:
                require_exact_confirmation(
                    db,
                    persisted,
                    policy,
                    course_id=str(group.course_id),
                    group_id=str(group.id),
                    agent_version_id=str(version.id),
                )
            except ProductPublicationError as exc:
                if exc.code not in {
                    "provider_confirmation_required",
                    "provider_confirmation_stale",
                }:
                    raise
            else:
                confirmed = True
            return {
                **static_options,
                "manifest_hash": persisted.manifest_hash,
                "build_manifest_hash": persisted.build_manifest_hash,
                "confirmation_revision": confirmation_revision,
                "confirmed": confirmed,
            }

        return runtime, static_options, prepare_manifest

    @staticmethod
    def _accepted_operation_id(db: Session, turn_id: str) -> str | None:
        """Find one exact accepted LLM attempt for local restart continuation."""

        row = db.execute(
            text(
                "SELECT id FROM provider_operations "
                "WHERE provider_operation='llm_debate_turn' AND logical_item_id=:turn_id "
                "AND state='accepted' ORDER BY attempt_no DESC, id DESC LIMIT 1"
            ),
            {"turn_id": turn_id},
        ).first()
        return str(row[0]) if row is not None else None

    def _resume_accepted_turn(
        self,
        db: Session,
        *,
        turn: DebateTurn,
        context: GenerationContext,
        expected_fence: PreparedGenerationFence,
        cancellation_generation: int,
        runtime: LLMTurnRuntime,
        publication: SqlLLMPublication,
        participants: tuple[ParticipantContext, ...],
    ) -> PreparedTurn | None:
        operation_id = self._accepted_operation_id(db, str(turn.id))
        if operation_id is None:
            return None
        recovery = LLMRecoveryService(
            ProviderRepository(db, require_export_confirmation=False),
            stage_store=publication,
            runtime=runtime,
            recovery_store=publication,
            adapter=self.llm,
        )
        outcome = recovery.resume_accepted(
            operation_id,
            context=context,
            validator=MutualLearningValidator(),
        )
        if outcome.status != "succeeded" or outcome.final_ready is None:
            code = outcome.safe_error_code or "llm_recovery_failed"
            raise PlatformError(code, "The accepted LLM turn cannot be resumed locally.", 503)
        final = outcome.final_ready
        if final.turn_id != str(turn.id) or final.participant_id != str(turn.participant_id):
            raise PlatformError("llm_recovery_failed", "The accepted LLM turn owner is stale.", 503)
        expected_predecessors = tuple(str(item) for item in expected_fence.predecessor_turn_ids)
        if (
            final.snapshot_id != str(turn.knowledge_snapshot_id)
            or final.predecessor_turn_ids != expected_predecessors
            or final.transcript_hash != expected_fence.transcript_hash
            or final.cutoff_turn_index != expected_fence.cutoff_turn_index
        ):
            raise PlatformError(
                "llm_recovery_fence_stale", "The accepted turn fence is stale.", 503
            )
        stage = outcome.stage
        if stage is None:
            raise PlatformError("llm_recovery_failed", "The accepted stage is unavailable.", 503)
        if str(getattr(stage, "persona_spec_hash", "")) != str(
            context.participant.persona_spec_hash or ""
        ):
            raise PlatformError("llm_recovery_fence_stale", "The accepted Persona is stale.", 503)
        receipts = tuple(
            PreparedSource(
                snapshot_id=receipt.snapshot_id,
                query_kind=receipt.query_kind,
                query_hash=receipt.query_hash,
                threshold_key=receipt.threshold_key,
                source_filename=receipt.source_filename,
                chunk_id=receipt.chunk_id,
                evidence_id=receipt.resolved_evidence_id(),
                rank=receipt.rank,
                score=receipt.score,
                text=receipt.text,
                source_document_id=receipt.source_document_id,
                source_start_offset=receipt.source_start_offset,
                source_end_offset=receipt.source_end_offset,
                excerpt=receipt.excerpt,
                query_id=receipt.query_id,
            )
            for receipt in final.used_receipts
        )
        if str(getattr(stage, "receipt_hash", "")) != compute_prompt_receipt_hash(
            final.used_receipts
        ):
            raise PlatformError("llm_recovery_fence_stale", "The accepted evidence is stale.", 503)
        if str(getattr(stage, "transcript_hash", "")) != expected_fence.transcript_hash:
            raise PlatformError(
                "llm_recovery_fence_stale", "The accepted transcript is stale.", 503
            )
        expected_prompt = build_provider_prompt(
            context,
            persona=context.participant.persona,
            receipts=final.used_receipts,
        )
        if (
            str(getattr(stage, "prompt_hash", "")) != expected_prompt.request.request_hash
            or str(getattr(stage, "rule_set_hash", "")) != expected_prompt.request.rule_set_hash
        ):
            raise PlatformError("llm_recovery_fence_stale", "The accepted prompt is stale.", 503)
        operation_row = (
            db.execute(
                text(
                    "SELECT scope_id, logical_item_id, attempt_no, request_hash, policy_hash, "
                    "export_manifest_hash, build_manifest_hash, model_key "
                    "FROM provider_operations WHERE id=:operation_id"
                ),
                {"operation_id": str(getattr(stage, "operation_id", ""))},
            )
            .mappings()
            .first()
        )
        if operation_row is None or (
            str(operation_row["scope_id"]) != str(context.debate_id)
            or str(operation_row["logical_item_id"]) != str(turn.id)
            or int(operation_row["attempt_no"]) != int(getattr(stage, "attempt_no", 0))
            or str(operation_row["request_hash"]) != str(getattr(stage, "request_hash", ""))
            or str(operation_row["policy_hash"]) != str(getattr(stage, "policy_hash", ""))
            or str(operation_row["export_manifest_hash"])
            != str(getattr(stage, "export_manifest_hash", ""))
            or str(operation_row["build_manifest_hash"])
            != str(getattr(stage, "build_manifest_hash", ""))
            or str(operation_row["model_key"]) != "qwen3.7-plus-2026-05-26"
        ):
            raise PlatformError("llm_recovery_fence_stale", "The accepted operation is stale.", 503)
        expected_generation_fence = hashlib.sha256(
            json.dumps(
                {
                    "predecessor_turn_ids": list(expected_fence.predecessor_turn_ids),
                    "transcript_hash": expected_fence.transcript_hash,
                    "cutoff_turn_index": expected_fence.cutoff_turn_index,
                    "generation": cancellation_generation,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        if str(getattr(stage, "generation_fence", "")) != expected_generation_fence:
            raise PlatformError("llm_recovery_fence_stale", "The accepted fence is stale.", 503)
        deferred = outcome.deferred_publication
        recovery_input = getattr(deferred, "recovery_input", None)
        if recovery_input is None:
            raise PlatformError(
                "llm_recovery_input_unavailable",
                "The accepted recovery input is unavailable.",
                503,
            )
        input_json = getattr(recovery_input, "input_json", None)
        try:
            recovery_payload = json.loads(str(input_json))
            recovery_body = recovery_payload.get("input", {})
            if not isinstance(recovery_body, Mapping):
                raise ValueError("recovery input body is unavailable")
            recovery_fence = recovery_body.get("fence", {})
            if not isinstance(recovery_fence, Mapping):
                raise ValueError("recovery fence is unavailable")
            if int(recovery_fence.get("generation", -1)) != cancellation_generation:
                raise ValueError("recovery generation fence is stale")
        except (TypeError, ValueError, AttributeError, json.JSONDecodeError) as exc:
            raise PlatformError(
                "llm_recovery_fence_stale", "The accepted fence is stale.", 503
            ) from exc
        for receipt in final.used_receipts:
            chunk = db.execute(
                text("SELECT snapshot_id, text FROM knowledge_chunks WHERE id=:chunk_id"),
                {"chunk_id": receipt.chunk_id},
            ).first()
            if (
                chunk is None
                or str(chunk[0]) != receipt.snapshot_id
                or str(chunk[0]) != str(turn.knowledge_snapshot_id)
                or str(chunk[1]) != receipt.text
            ):
                raise PlatformError(
                    "llm_recovery_fence_stale", "The accepted evidence is stale.", 503
                )
        participant_row = next(
            (item for item in participants if str(item.participant_id) == str(turn.participant_id)),
            None,
        )
        if participant_row is None:
            raise PlatformError("llm_recovery_failed", "The accepted turn owner is stale.", 503)
        voice_kind = str(getattr(turn, "actual_tts_voice_kind", "mock_sentinel"))
        voice_profile_id = getattr(turn, "actual_tts_voice_profile_id", None)
        voice_token = str(voice_profile_id) if voice_kind == "platform_profile" else "mock"
        return PreparedTurn(
            speech=final.speech,
            sources=tuple(
                RetrievalSourceDTO(
                    source_filename=item.source_filename,
                    chunk_id=UUID(item.chunk_id),
                )
                for item in final.public_sources
            ),
            retrieval_status=final.retrieval_status,
            grounding_mode=final.grounding_mode,
            structured=final.structured.model_dump(mode="json"),
            voice_token=voice_token,
            actual_voice_kind=voice_kind,
            actual_voice_profile_id=(str(voice_profile_id) if voice_profile_id else None),
            source_receipts=receipts,
            predecessor_turn_ids=final.predecessor_turn_ids,
            transcript_hash=final.transcript_hash,
            cutoff_turn_index=final.cutoff_turn_index,
            word_count=count_turn_words(
                final.speech,
                final.structured.question.text
                if final.structured.question.type != "none"
                else None,
            ),
            generation_attempt=final.attempt,
            evidence_trace=tuple(dict(item) for item in final.evidence_trace),
            llm_publication=outcome.deferred_publication,
        )

    def __call__(
        self,
        db: Any,
        debate: Any,
        turn: Any,
        *,
        attempt: int,
        cancellation_generation: int,
    ) -> PreparedTurn:
        if not isinstance(db, Session):
            raise ValueError("SQL turn preparation requires a database Session")
        if attempt != 1:
            raise ValueError("M11 owns the complete attempt 1|2 repair budget")
        debate_id = str(debate.id)
        participant_rows = list(
            db.scalars(
                select(DebateParticipant)
                .where(DebateParticipant.debate_id == debate_id)
                .order_by(DebateParticipant.order_index)
            ).all()
        )
        turn_rows = list(
            db.scalars(
                select(DebateTurn)
                .where(DebateTurn.debate_id == debate_id)
                .order_by(DebateTurn.turn_index)
            ).all()
        )
        current = next((row for row in turn_rows if row.id == str(turn.id)), None)
        if current is None:
            raise ValueError("planned turn is unavailable")
        # Historical completed Debates are read/replay-only and do not enter
        # this generation adapter.  Any running generation that reaches this
        # boundary must nevertheless bind every frozen AgentVersion to an
        # exact, current Persona confirmation.  This deliberately ignores
        # ``persona_required``: pre-activation running rows may be legacy, but
        # they cannot resume or call a provider without the exact Persona
        # integrity tuple.
        self._require_confirmed_personas(db, participant_rows)
        participants = tuple(self._participant(db, row) for row in participant_rows)
        participant = next(
            (item for item in participants if item.participant_id == current.participant_id),
            None,
        )
        if participant is None:
            raise ValueError("turn participant is unavailable")
        participant_row = next(
            (row for row in participant_rows if str(row.id) == participant.participant_id), None
        )
        if participant_row is None:
            raise ValueError("turn participant row is unavailable")
        expected_fence = generation_fence(db, debate, current)
        persisted_rule_set_id = str(debate.rule_set_id)
        is_mutual = persisted_rule_set_id == MUTUAL_LEARNING_RULE_SET_ID
        round_count = self._round_count(debate) if is_mutual else 2
        policy = TurnPolicy(rule_set_id=persisted_rule_set_id)
        plans = policy.plan_with_ids(
            participants,
            [row.id for row in turn_rows],
            round_count=round_count,
        )
        plan = plans[current.turn_index]
        predecessor_rows = (
            [row for row in turn_rows if int(row.round_no) < int(current.round_no)]
            if is_mutual
            else turn_rows[: current.turn_index]
        )
        predecessors = tuple(self._final_ready(db, row) for row in predecessor_rows)
        context = GenerationContext(
            debate_id=debate_id,
            topic=str(debate.topic),
            turn=plan,
            participant=participant,
            participants=participants,
            predecessors=predecessors,
        )
        llm_runtime, llm_runtime_options, llm_manifest_preparer = self._llm_runtime_for_turn(
            db,
            debate=debate,
            turn=current,
            participant_row=participant_row,
            participants=participants,
        )
        if llm_runtime is not None:
            llm_runtime_options = {
                **dict(llm_runtime_options),
                "fence": {
                    "predecessor_turn_ids": list(expected_fence.predecessor_turn_ids),
                    "transcript_hash": expected_fence.transcript_hash,
                    "cutoff_turn_index": expected_fence.cutoff_turn_index,
                    "generation": cancellation_generation,
                },
            }
        if llm_runtime is not None and isinstance(self.llm, DashScopeLLMAdapter):
            publication = SqlLLMPublication(
                db,
                ledger=ProviderRepository(db, require_export_confirmation=False),
            )
            resumed = self._resume_accepted_turn(
                db,
                turn=current,
                context=context,
                expected_fence=expected_fence,
                cancellation_generation=cancellation_generation,
                runtime=llm_runtime,
                publication=publication,
                participants=participants,
            )
            if resumed is not None:
                return resumed
        query_embeddings = self._query_embedding_service(
            db,
            debate=debate,
            turn=current,
            participant_row=participant_row,
            context=context,
            transcript_hash=expected_fence.transcript_hash,
        )
        generator = TurnGenerationService(
            SqlSnapshotRetriever(db, query_embeddings=query_embeddings),
            self.llm,
            rule_set_id=persisted_rule_set_id,
            mock_retrieval_policy_id=(
                MOCK_LEXICAL_ANCHOR_POLICY_ID
                if getattr(self.settings, "embedding_provider", "mock") == "mock"
                and persisted_rule_set_id == "ordered_multi_agent_rounds_demo_v2"
                else None
            ),
            llm_runtime=llm_runtime,
            llm_runtime_options=llm_runtime_options,
            llm_manifest_preparer=llm_manifest_preparer,
        )
        generated = generator.generate(context)
        final = generated.final_ready
        if (
            final.predecessor_turn_ids != expected_fence.predecessor_turn_ids
            or final.transcript_hash != expected_fence.transcript_hash
            or final.cutoff_turn_index != expected_fence.cutoff_turn_index
        ):
            raise ValueError("generation result does not match the prepared prefix fence")
        sources = tuple(
            RetrievalSourceDTO(
                source_filename=source.source_filename,
                chunk_id=UUID(source.chunk_id),
            )
            for source in final.public_sources
        )
        receipts = tuple(
            PreparedSource(
                snapshot_id=receipt.snapshot_id,
                query_kind=receipt.query_kind,
                query_hash=receipt.query_hash,
                threshold_key=receipt.threshold_key,
                source_filename=receipt.source_filename,
                chunk_id=receipt.chunk_id,
                evidence_id=receipt.resolved_evidence_id(),
                rank=receipt.rank,
                score=receipt.score,
                text=receipt.text,
                source_document_id=receipt.source_document_id,
                source_start_offset=receipt.source_start_offset,
                source_end_offset=receipt.source_end_offset,
                excerpt=receipt.excerpt,
                query_id=receipt.query_id,
            )
            for receipt in final.used_receipts
        )
        voice_kind = str(getattr(participant_row, "effective_voice_kind", "mock_sentinel"))
        voice_profile_id = getattr(participant_row, "effective_voice_profile_id", None)
        if voice_kind not in {"platform_profile", "mock_sentinel"}:
            raise ValueError("frozen participant voice kind is invalid")
        if voice_kind == "platform_profile" and not voice_profile_id:
            raise ValueError("platform voice kind requires a frozen profile")
        if voice_kind == "mock_sentinel" and voice_profile_id is not None:
            raise ValueError("mock voice kind cannot carry a profile")
        voice_token = str(voice_profile_id) if voice_kind == "platform_profile" else "mock"
        return PreparedTurn(
            speech=final.speech,
            sources=sources,
            retrieval_status=final.retrieval_status,
            grounding_mode=final.grounding_mode,
            structured=final.structured.model_dump(mode="json"),
            voice_token=voice_token,
            actual_voice_kind=voice_kind,
            actual_voice_profile_id=(str(voice_profile_id) if voice_profile_id else None),
            source_receipts=receipts,
            predecessor_turn_ids=final.predecessor_turn_ids,
            transcript_hash=final.transcript_hash,
            cutoff_turn_index=final.cutoff_turn_index,
            word_count=count_turn_words(
                final.speech,
                final.structured.question.text
                if final.structured.question.type != "none"
                else None,
            ),
            generation_attempt=final.attempt,
            evidence_trace=tuple(dict(item) for item in final.evidence_trace),
            llm_publication=generated.llm_publication,
        )

    def _query_embedding_service(
        self,
        db: Session,
        *,
        debate: Any,
        turn: DebateTurn,
        participant_row: DebateParticipant,
        context: GenerationContext,
        transcript_hash: str,
    ) -> QueryEmbeddingService:
        snapshot = db.get(KnowledgeSnapshot, str(participant_row.knowledge_snapshot_id))
        if snapshot is None:
            raise ValueError("the immutable query Snapshot is unavailable")
        identity = persisted_snapshot_identity(snapshot)
        if identity.provider == "mock":
            return QueryEmbeddingService()
        if identity.provider != REAL_EMBEDDING_PROVIDER:
            raise PlatformError(
                "provider_unavailable", "The service is temporarily unavailable.", 503
            )
        if getattr(self.settings, "embedding_provider", "mock") != "dashscope":
            raise PlatformError(
                "provider_unavailable", "The service is temporarily unavailable.", 503
            )
        policy_hash = _provider_policy_hash(self.settings, "embedding")
        if not isinstance(policy_hash, str):
            raise PlatformError(
                "provider_preflight_blocked",
                "Real Embedding is unavailable until every policy control is verified.",
                503,
            )
        repository = ProviderRepository(db)
        policy = repository.get_policy_snapshot(policy_hash)
        if policy is None or policy.policy_hash != policy_hash:
            raise PlatformError(
                "provider_preflight_blocked",
                "Real Embedding is unavailable until every policy control is verified.",
                503,
            )
        version = db.get(AgentVersion, str(participant_row.agent_version_id))
        if version is None or not isinstance(version.persona_spec_hash, str):
            raise ValueError("the frozen query Persona is unavailable")
        agent = db.get(Agent, version.agent_id)
        group = db.get(Group, agent.group_id) if agent is not None else None
        if agent is None or group is None:
            raise ValueError("the frozen query owner is unavailable")
        subqueries = build_turn_subqueries(context)
        try:
            query_plan = ensure_real_query_export_manifest(
                db,
                db=db,
                scope_id=str(debate.id),
                turn_id=str(turn.id),
                course_id=group.course_id,
                group_id=group.id,
                agent_version_id=version.id,
                snapshot_id=snapshot.id,
                identity=identity,
                transcript_hash=transcript_hash,
                persona_spec_hash=version.persona_spec_hash,
                subqueries=tuple((item.query_kind, item.text) for item in subqueries),
                policy=policy,
            )
        except QueryManifestError as error:
            raise PlatformError(
                error.code,
                "The exact real query export manifest is unavailable.",
                503,
            ) from error
        logical_item_id = f"turn:{turn.id}"
        operations = tuple(
            operation
            for operation in repository.operations(scope_id=str(debate.id))
            if operation.provider_operation == "embedding_query"
            and operation.logical_item_id == logical_item_id
        )
        attempt_no = 1
        if operations:
            latest = max(operations, key=lambda operation: operation.attempt_no)
            if _dual_real(self.settings) and latest.state != "succeeded":
                raise PlatformError(
                    "provider_retry_forbidden",
                    "The Real-Core query attempt is terminal; no retry is authorized.",
                    503,
                )
            if latest.state == "not_sent" and latest.attempt_no < 2:
                attempt_no = latest.attempt_no + 1
            else:
                attempt_no = latest.attempt_no
        try:
            total_tokens = sum(count_tokens(text) for text in query_plan.query_texts)
            pending_control = SqlAlchemyQueryControlAdapter(
                db,
                scope_id=str(debate.id),
                snapshot_id=snapshot.id,
                identity=identity,
                policy_hash=policy.policy_hash,
                export_manifest_hash=query_plan.manifest.manifest_hash,
                build_manifest_hash=query_plan.build_manifest_hash,
                query_hashes=query_plan.query_hashes,
                attempt_no=attempt_no,
                logical_item_id=logical_item_id,
                max_requests=(
                    REAL_CORE_DEMO_QUERY_MAX_REQUESTS
                    if _dual_real(self.settings)
                    else SQL_QUERY_MAX_REQUESTS
                ),
                repository=ProviderRepository(db, require_export_confirmation=False),
            )
            pending_control.prepare_disclosure_operation(
                snapshot_id=snapshot.id,
                identity=identity,
                query_hashes=query_plan.query_hashes,
                total_tokens=total_tokens,
            )
        except (TokenizerError, SqlQueryError) as error:
            raise PlatformError(
                "provider_preflight_blocked",
                "The exact real query disclosure could not be persisted.",
                503,
            ) from error
        try:
            confirmation = require_exact_confirmation(
                db,
                query_plan.manifest,
                policy,
                course_id=group.course_id,
                group_id=group.id,
                agent_version_id=version.id,
            )
        except ProductPublicationError as error:
            if error.code == "provider_confirmation_required":
                raise conflict(
                    "provider_confirmation_required",
                    "The course teacher must confirm the exact query disclosure.",
                    {
                        "manifest_hash": query_plan.manifest.manifest_hash,
                        "turn_id": str(turn.id),
                    },
                ) from error
            raise PlatformError(
                "provider_preflight_blocked",
                "The exact real query confirmation is stale.",
                503,
            ) from error
        selected_provider = select_embedding_provider(cast(Settings, self.settings))
        config = getattr(selected_provider, "config", None)
        if not isinstance(config, DashScopeEmbeddingConfig):
            raise PlatformError(
                "provider_preflight_blocked",
                "The real query Provider resource is not fixed.",
                503,
            )
        try:
            endpoint_matches = config.resolved_endpoint == policy.endpoint
        except Exception:
            endpoint_matches = False
        if not endpoint_matches:
            raise PlatformError(
                "provider_preflight_blocked",
                "The real query Provider resource changed.",
                503,
            )
        control = SqlAlchemyQueryControlAdapter(
            db,
            scope_id=str(debate.id),
            snapshot_id=snapshot.id,
            identity=identity,
            policy_hash=policy.policy_hash,
            export_manifest_hash=query_plan.manifest.manifest_hash,
            build_manifest_hash=query_plan.build_manifest_hash,
            query_hashes=query_plan.query_hashes,
            attempt_no=attempt_no,
            logical_item_id=logical_item_id,
            confirmation_revision=confirmation.confirmation_revision,
            max_requests=(
                REAL_CORE_DEMO_QUERY_MAX_REQUESTS
                if _dual_real(self.settings)
                else SQL_QUERY_MAX_REQUESTS
            ),
        )
        stage_store = SqlAlchemyEmbeddingStageStore(db)
        controlled_provider = controlled_query_provider(
            selected_provider,
            control=control,
            stage_store=stage_store,
        )
        service = QueryEmbeddingService(
            provider=controlled_provider,
            control=control,
            manifest=control,
            budget=control,
            build_manifest_hash=query_plan.build_manifest_hash,
        )
        try:
            service.embed_subqueries(snapshot, query_plan.query_texts)
        except EmbeddingTransportNotSent as error:
            raise PlatformError(
                "provider_not_sent", "The real query request was not sent.", 503
            ) from error
        except EmbeddingAcceptanceUnknown as error:
            raise PlatformError(
                "acceptance_unknown", "The real query request outcome is unknown.", 503
            ) from error
        except (QueryEmbeddingError, SqlQueryError) as error:
            code = getattr(error, "code", "provider_unavailable")
            raise PlatformError(code, "The real query embedding failed safely.", 503) from error
        return service

    @staticmethod
    def _round_count(debate: Any) -> int:
        try:
            snapshot = json.loads(str(debate.rule_snapshot_json))
        except (TypeError, ValueError) as exc:
            raise ValueError("mutual-learning rule snapshot is invalid") from exc
        count = snapshot.get("round_count") if isinstance(snapshot, dict) else None
        if not isinstance(count, int) or isinstance(count, bool) or not 2 <= count <= 5:
            raise ValueError("mutual-learning round count is invalid")
        return count

    @staticmethod
    def generation_fence(
        db: Session,
        debate: Any,
        turn: Any,
        *,
        attempt: int = 1,
        cancellation_generation: int = 0,
    ) -> PreparedGenerationFence:
        """Expose the pre-provider prefix fence through the preparer seam."""

        del cancellation_generation
        if attempt != 1:
            raise ValueError("generation fencing starts at attempt one")
        return generation_fence(db, debate, turn)

    @staticmethod
    def _require_confirmed_personas(
        db: Session,
        rows: list[DebateParticipant],
    ) -> None:
        blocked: list[str] = []
        for row in rows:
            version = db.get(AgentVersion, row.agent_version_id)
            # Preserve the adapter's existing unavailable-version diagnostic;
            # the subsequent participant projection reports that typed error.
            if version is not None and not is_persona_confirmed(version):
                blocked.append(str(row.agent_version_id))
        if blocked:
            raise PlatformError(
                PERSONA_CONFIRMATION_REQUIRED,
                "Every running Debate participant must have a confirmed Persona.",
                422,
                {"agent_version_ids": blocked},
            )

    @staticmethod
    def _participant(db: Session, row: DebateParticipant) -> ParticipantContext:
        version = db.get(AgentVersion, row.agent_version_id)
        if version is None or version.state not in {"published", "superseded"}:
            raise ValueError("frozen AgentVersion is unavailable")
        if str(version.knowledge_snapshot_id or "") != str(row.knowledge_snapshot_id):
            raise ValueError("frozen AgentVersion snapshot does not match participant")
        persona = None
        persona_hash = getattr(version, "persona_spec_hash", None)
        persona_json = getattr(version, "persona_spec_json", None)
        if persona_json is not None or persona_hash is not None:
            if not isinstance(persona_json, str) or not isinstance(persona_hash, str):
                raise ValueError("frozen Persona fields are incomplete")
            persona, persona_hash = confirmed_persona_provider_view(
                persona_json,
                expected_persona_spec_hash=persona_hash,
            )
        return ParticipantContext(
            participant_id=row.id,
            agent_id=row.agent_id,
            agent_name=row.agent_name,
            slot=row.slot,
            order_index=row.order_index,
            snapshot_id=row.knowledge_snapshot_id,
            agent_md=version.agent_md,
            stance_mode=row.stance_mode,  # type: ignore[arg-type]
            initial_stance=row.initial_stance,  # type: ignore[arg-type]
            current_stance=row.current_stance,  # type: ignore[arg-type]
            initial_position_summary=row.initial_position_summary,
            current_position_summary=row.current_position_summary,
            teacher_note=row.teacher_note,
            persona=persona,
            persona_spec_hash=persona_hash,
        )

    @staticmethod
    def _receipt_from_payload(payload: object) -> SnapshotRetrievalReceipt:
        if not isinstance(payload, dict):
            raise ValueError("persisted retrieval receipt is not an object")
        required = {
            "snapshot_id",
            "query_kind",
            "query_hash",
            "threshold_key",
            "source_filename",
            "chunk_id",
            "evidence_id",
            "rank",
            "score",
            "text",
        }
        optional = {
            "source_document_id",
            "source_start_offset",
            "source_end_offset",
            "excerpt",
            "query_id",
        }
        if not required.issubset(payload) or set(payload) - required - optional:
            raise ValueError("persisted retrieval receipt shape is not exact")
        try:
            return SnapshotRetrievalReceipt(
                snapshot_id=str(payload["snapshot_id"]),
                query_kind=str(payload["query_kind"]),
                query_hash=str(payload["query_hash"]),
                threshold_key=payload["threshold_key"],
                source_filename=str(payload["source_filename"]),
                chunk_id=str(payload["chunk_id"]),
                evidence_id=str(payload["evidence_id"]),
                rank=int(payload["rank"]),
                score=float(payload["score"]),
                text=str(payload["text"]),
                source_document_id=(
                    str(payload["source_document_id"])
                    if payload.get("source_document_id") is not None
                    else None
                ),
                source_start_offset=(
                    int(payload["source_start_offset"])
                    if payload.get("source_start_offset") is not None
                    else None
                ),
                source_end_offset=(
                    int(payload["source_end_offset"])
                    if payload.get("source_end_offset") is not None
                    else None
                ),
                excerpt=(str(payload["excerpt"]) if payload.get("excerpt") is not None else None),
                query_id=(
                    str(payload["query_id"]) if payload.get("query_id") is not None else None
                ),
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("persisted retrieval receipt is invalid") from exc

    @classmethod
    def _persisted_receipts(
        cls,
        db: Session,
        row: DebateTurn,
        structured: StructuredTurnResult | MutualLearningTurnResultV1,
    ) -> tuple[SnapshotRetrievalReceipt, ...] | None:
        raw = getattr(row, "retrieval_receipts_json", None)
        if raw is None:
            return None
        try:
            payload = json.loads(str(raw))
        except (TypeError, ValueError) as exc:
            raise ValueError("persisted retrieval receipts are not valid JSON") from exc
        if not isinstance(payload, list):
            raise ValueError("persisted retrieval receipts are not a list")
        receipts = tuple(cls._receipt_from_payload(item) for item in payload)
        expected_ids = (
            tuple(structured.used_evidence_id)
            if isinstance(structured, StructuredTurnResult)
            else structured.used_evidence_ids
        )
        actual_ids = tuple(item.resolved_evidence_id() for item in receipts)
        if actual_ids != expected_ids:
            raise ValueError("persisted receipts do not match used evidence IDs")
        for receipt in receipts:
            if receipt.snapshot_id != str(row.knowledge_snapshot_id):
                raise ValueError("persisted receipt crossed the participant snapshot")
            chunk = db.get(KnowledgeChunk, receipt.chunk_id)
            if chunk is None or str(chunk.snapshot_id) != receipt.snapshot_id:
                raise ValueError("persisted receipt chunk crossed its snapshot")
            if str(chunk.chunk_text) != receipt.text:
                raise ValueError("persisted receipt text does not match the immutable chunk")
            document = db.get(SnapshotDocument, chunk.snapshot_document_id)
            if document is None or str(document.snapshot_id) != receipt.snapshot_id:
                raise ValueError("persisted receipt document crossed its snapshot")
            if str(document.source_filename) != receipt.source_filename:
                raise ValueError("persisted receipt filename does not match the snapshot")
        return receipts

    @classmethod
    def _final_ready(cls, db: Session, row: DebateTurn) -> FinalReadyTurn:
        if row.generation_status != "final_ready" or not row.speech or not row.structured_json:
            raise ValueError("the final-ready predecessor prefix is incomplete")
        try:
            structured_value = json.loads(row.structured_json)
        except (TypeError, ValueError) as exc:
            raise ValueError("a predecessor structured result is invalid JSON") from exc
        structured: StructuredTurnResult | MutualLearningTurnResultV1
        if isinstance(structured_value, dict) and "key_claims" in structured_value:
            structured = MutualLearningTurnResultV1.model_validate(structured_value)
        else:
            structured = StructuredTurnResult.model_validate(structured_value)
        persisted = cls._persisted_receipts(db, row, structured)
        if persisted is None:
            raise ValueError("a final-ready predecessor has no exact receipt payload")
        receipts = persisted
        evidence_trace: tuple[dict[str, Any], ...] = ()
        raw_trace = getattr(row, "evidence_trace_json", None)
        if raw_trace is None:
            raw_trace = getattr(row, "evidence_trace", None)
        if raw_trace is None:
            raw_trace = getattr(row, "evidence_traces", None)
        if raw_trace:
            try:
                trace_value = json.loads(str(raw_trace))
                evidence_trace = tuple(
                    item.model_dump(mode="json") for item in public_evidence_trace(trace_value)
                )
            except (TypeError, ValueError) as exc:
                raise ValueError("a predecessor evidence trace is invalid") from exc
        predecessor_ids = _decode_predecessor_ids(row)
        if row.transcript_hash is None or row.cutoff_turn_index is None:
            raise ValueError("a predecessor generation fence is incomplete")
        return FinalReadyTurn(
            turn_id=row.id,
            participant_id=row.participant_id,
            snapshot_id=row.knowledge_snapshot_id,
            round_no=row.round_no,
            turn_index=row.turn_index,
            speech=row.speech,
            structured=structured,
            retrieval_status=row.retrieval_status or "no_match",  # type: ignore[arg-type]
            grounding_mode=row.grounding_mode or "general_reasoning",  # type: ignore[arg-type]
            used_receipts=receipts,
            predecessor_turn_ids=predecessor_ids,
            cutoff_turn_index=row.cutoff_turn_index,
            transcript_hash=row.transcript_hash,
            attempt=row.attempt,  # type: ignore[arg-type]
            publication_status=("public" if row.publication_status == "public" else "final_ready"),
            evidence_trace=evidence_trace,
        )


def _decode_predecessor_ids(row: DebateTurn) -> tuple[str, ...]:
    raw = getattr(row, "predecessor_turn_ids_json", "[]")
    try:
        payload = json.loads(str(raw))
    except (TypeError, ValueError) as exc:
        raise ValueError("predecessor turn IDs are not valid JSON") from exc
    if not isinstance(payload, list) or not all(isinstance(item, str) and item for item in payload):
        raise ValueError("predecessor turn IDs have an invalid shape")
    return tuple(payload)


def generation_fence(db: Session, debate: Any, turn: Any) -> PreparedGenerationFence:
    """Compute the exact final-ready prefix identity before a provider call.

    This is intentionally a read-only helper.  The caller uses the returned
    IDs/hash/cutoff as the values in its single SQL completion CAS; a later
    predecessor mutation therefore cannot be mistaken for the context that a
    provider actually saw.
    """

    if not isinstance(db, Session):
        raise ValueError("generation fencing requires a database Session")
    debate_id = str(getattr(debate, "id", ""))
    turn_id = str(getattr(turn, "id", ""))
    if not debate_id or not turn_id:
        raise ValueError("generation fencing requires debate and turn IDs")
    rows = list(
        db.scalars(
            select(DebateTurn)
            .where(DebateTurn.debate_id == debate_id)
            .order_by(DebateTurn.turn_index, DebateTurn.id)
        ).all()
    )
    current = next((row for row in rows if str(row.id) == turn_id), None)
    if current is None:
        raise ValueError("planned turn is unavailable")
    if any(row.turn_index != index for index, row in enumerate(rows)):
        raise ValueError("persisted turn plan indexes are not contiguous")
    is_mutual = str(getattr(debate, "rule_set_id", "")) == MUTUAL_LEARNING_RULE_SET_ID
    if is_mutual:
        round_count = SqlTurnPreparer._round_count(debate)
        if int(current.round_no) > round_count:
            raise ValueError("turn round exceeds the frozen mutual-learning plan")
    expected_rows = (
        [row for row in rows if int(row.round_no) < int(current.round_no)]
        if is_mutual
        else rows[: current.turn_index]
    )
    expected_ids = tuple(str(row.id) for row in expected_rows)
    if _decode_predecessor_ids(current) != expected_ids:
        raise ValueError("persisted turn predecessor prefix is not exact")
    predecessors = tuple(SqlTurnPreparer._final_ready(db, row) for row in expected_rows)
    for index, predecessor in enumerate(predecessors):
        if is_mutual:
            expected_predecessors = tuple(
                item.turn_id for item in predecessors if item.round_no < predecessor.round_no
            )
        else:
            expected_predecessors = tuple(item.turn_id for item in predecessors[:index])
        if predecessor.predecessor_turn_ids != expected_predecessors:
            raise ValueError("a predecessor has a stale predecessor prefix")
        expected_cutoff = (
            max(
                (item.turn_index for item in predecessors if item.round_no < predecessor.round_no),
                default=-1,
            )
            if is_mutual
            else index - 1
        )
        if predecessor.cutoff_turn_index != expected_cutoff:
            raise ValueError("a predecessor has a stale cutoff index")
        if is_mutual:
            from app.modules.debates.generation.mutual_learning_prompts import (
                compute_mutual_transcript_hash,
            )

            visible = tuple(item for item in predecessors if item.round_no < predecessor.round_no)
            expected_predecessor_hash = compute_mutual_transcript_hash(visible)
        else:
            expected_predecessor_hash = compute_transcript_hash(predecessors[:index])
        if predecessor.transcript_hash != expected_predecessor_hash:
            raise ValueError("a predecessor has a stale transcript hash")
    if is_mutual:
        from app.modules.debates.generation.mutual_learning_prompts import (
            compute_mutual_transcript_hash,
        )

        transcript_hash = compute_mutual_transcript_hash(predecessors)
    else:
        transcript_hash = compute_transcript_hash(predecessors)
    stored_hash = getattr(current, "transcript_hash", None)
    if stored_hash is not None and str(stored_hash) != transcript_hash:
        raise ValueError("persisted turn transcript hash does not match its prefix")
    stored_cutoff = getattr(current, "cutoff_turn_index", None)
    expected_cutoff = (
        max((int(row.turn_index) for row in expected_rows), default=-1)
        if is_mutual
        else current.turn_index - 1
    )
    if stored_cutoff is not None and int(stored_cutoff) != expected_cutoff:
        raise ValueError("persisted turn cutoff does not match its prefix")
    return PreparedGenerationFence(
        predecessor_turn_ids=expected_ids,
        transcript_hash=transcript_hash,
        cutoff_turn_index=expected_cutoff,
        attempt=1,
    )


__all__ = ["SqlSnapshotRetriever", "SqlSnapshotSearch", "SqlTurnPreparer", "generation_fence"]
