"""Turn preparation: generation fence, provider call, audio swap."""

from __future__ import annotations

import asyncio
import functools
import inspect
import logging
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import PureWindowsPath
from typing import Any

from app.core.errors import PlatformError
from app.modules.debates.output_language import debate_output_language
from app.modules.debates.round_count import debate_round_count, uses_segment_protocol
from app.providers.tts import TTS_UNAVAILABLE_CODES, TTSProviderError, TTSVoiceUnavailableError

from ._core import (
    _SAFE_GENERATION_CODES,
    PlaybackCore,
)
from .audio import AudioMetadata, StagedAudio
from .events import EventRecord
from .protocols import (
    PreparedGenerationFence,
    PreparedSource,
    PreparedTurn,
    ResolvedTurnVoice,
)
from .schemas import (
    RetrievalSourceDTO,
)

LOGGER = logging.getLogger(__name__)


async def _finish_thread_after_cancellation(work: asyncio.Task[Any]) -> Any:
    # A second cancellation (for example Stop followed by shutdown) must not
    # let claim cleanup reuse the Session while its worker still owns it.
    while not work.done():
        try:
            return await asyncio.shield(work)
        except asyncio.CancelledError:
            continue
    return work.result()


def _raise_site(exc: BaseException, *, frames: int = 4) -> str:
    """The last few source positions an exception passed through.

    Deliberately positions only: `file:line:function`, joined innermost last.
    The exception's own message is never included, because it can quote a
    provider response or a student's text.
    """

    import traceback

    parts: list[str] = []
    current: BaseException | None = exc
    seen: set[int] = set()
    try:
        while current is not None and id(current) not in seen and len(parts) < 4:
            seen.add(id(current))
            trace = traceback.extract_tb(current.__traceback__)
            locations = " > ".join(
                f"{PureWindowsPath(frame.filename).name}:{frame.lineno}:{frame.name}"
                for frame in trace[-frames:]
            )
            parts.append(f"{type(current).__name__}[{locations or '-'}]")
            current = current.__cause__
    except Exception:  # pragma: no cover - diagnosis must never raise
        return "-"
    return " caused_by ".join(parts) or "-"


class PlaybackPreparationMixin(PlaybackCore):
    """Turn preparation: generation fence, provider call, audio swap."""

    def _default_prepared(self, debate: Any, turn: Any, participant: Any | None) -> PreparedTurn:
        name = str(self._get(participant, "name", "agent_name", default="Agent"))
        topic = str(self._get(debate, "topic", default="the discussion"))
        round_no = self._round(turn)
        # Deterministic Mock copy: it intentionally carries no factual claim
        # or source, preserving the no-match honesty boundary when M11 is not
        # connected yet.  There are exactly 80+ words, including no question.
        words = (
            f"{name} approaches {topic} as a classroom question about responsibility, "
            "evidence, and the choices communities make when technology changes daily life. "
            f"In round {round_no}, this perspective values careful listening and "
            "clear distinctions. "
            "A policy should protect people from real harm while leaving room for legitimate "
            "expression, innovation, and cultural exchange. The strongest answer compares likely "
            "benefits with costs, acknowledges uncertainty, and explains who carries each burden. "
            "This statement is a general reasoned position rather than a claim from the knowledge "
            "base. It invites the other participant to examine assumptions, clarify trade offs, "
            "and consider practical safeguards before choosing a final conclusion."
        )
        return PreparedTurn(
            speech=words, retrieval_status="no_match", grounding_mode="general_reasoning"
        )

    async def _call_preparer(self, db: Any, debate: Any, turn: Any, attempt: int) -> PreparedTurn:
        participant = self._participant_for_turn(self._participants(db, debate), turn)
        if self.turn_preparer is None:
            existing_speech = self._get(turn, "speech", "original_text", default=None)
            if isinstance(existing_speech, str) and existing_speech.strip():
                return PreparedTurn(
                    speech=existing_speech,
                    sources=tuple(
                        RetrievalSourceDTO.model_validate(value) for value in self._sources(turn)
                    ),
                    retrieval_status=str(self._get(turn, "retrieval_status", default="no_match")),
                    grounding_mode=str(
                        self._get(turn, "grounding_mode", default="general_reasoning")
                    ),
                    structured=dict(
                        self._get(turn, "structured", "structured_json", default={}) or {}
                    ),
                    voice_token=str(
                        self._get(participant, "effective_voice_profile_id", default="mock")
                        or "mock"
                    ),
                    evidence_trace=tuple(self._evidence_trace(turn)),
                )
            return self._default_prepared(debate, turn, participant)
        call = functools.partial(
            self.turn_preparer,
            db,
            debate,
            turn,
            attempt=attempt,
            cancellation_generation=int(
                self._get(debate, "cancellation_generation", default=0) or 0
            ),
        )
        # The SQL preparer is synchronous and spends most of a turn inside one
        # blocking provider HTTP call.  Run directly, that call sat on the
        # event loop: uvicorn served nothing for its whole duration, so every
        # page load, poll and stage event in the room stalled for as long as
        # the model took.  A measured probe saw an unrelated request wait 24s.
        #
        # A thread is safe here rather than merely convenient: the session is
        # handed over, not shared.  This coroutine awaits the thread and
        # touches ``db`` neither before the handover nor until it returns, and
        # the SQLite connections are built with ``check_same_thread=False``.
        # An async preparer is only constructed in the thread and is still
        # awaited on the loop, so a test double keeps its own semantics.
        work = asyncio.create_task(asyncio.to_thread(call))
        try:
            result = await asyncio.shield(work)
        except asyncio.CancelledError:
            # Cancelling an asyncio wrapper does not stop its provider thread.
            # Keep the worker's Session alive until that thread relinquishes it;
            # durable job/generation fences already reject late publication.
            try:
                await _finish_thread_after_cancellation(work)
            except Exception:
                pass
            raise
        if inspect.isawaitable(result):
            result = await result
        if isinstance(result, PreparedTurn):
            return result
        if not isinstance(result, Mapping):
            raise ValueError("turn preparer returned an invalid result")
        source_values = result.get("sources", ())
        sources = tuple(
            item
            if isinstance(item, RetrievalSourceDTO)
            else RetrievalSourceDTO.model_validate(item)
            for item in source_values
        )
        receipt_values = result.get("source_receipts", ()) or ()
        receipts = tuple(
            item if isinstance(item, PreparedSource) else PreparedSource(**dict(item))
            for item in receipt_values
        )
        return PreparedTurn(
            speech=str(result.get("speech", "")),
            sources=sources,
            retrieval_status=str(result.get("retrieval_status", "no_match")),
            grounding_mode=str(result.get("grounding_mode", "general_reasoning")),
            structured=dict(result.get("structured", {})),
            voice_token=str(result.get("voice_token", "mock")),
            actual_voice_kind=str(result.get("actual_voice_kind", "mock_sentinel")),
            actual_voice_profile_id=(
                str(result["actual_voice_profile_id"])
                if result.get("actual_voice_profile_id") is not None
                else None
            ),
            source_receipts=receipts,
            predecessor_turn_ids=tuple(
                str(item) for item in result.get("predecessor_turn_ids", ())
            ),
            transcript_hash=(
                str(result["transcript_hash"])
                if result.get("transcript_hash") is not None
                else None
            ),
            cutoff_turn_index=(
                int(result["cutoff_turn_index"])
                if result.get("cutoff_turn_index") is not None
                else None
            ),
            word_count=(
                int(result["word_count"]) if result.get("word_count") is not None else None
            ),
            generation_attempt=int(result.get("generation_attempt", attempt) or attempt),
            evidence_trace=tuple(
                dict(item)
                for item in self._evidence_trace(
                    {"evidence_trace": result.get("evidence_trace", ())}
                )
            ),
            llm_publication=result.get("llm_publication"),
        )

    async def _generation_fence(
        self,
        db: Any,
        debate: Any,
        turn: Any,
        *,
        attempt: int,
        cancellation_generation: int,
    ) -> PreparedGenerationFence | None:
        """Resolve M11's prompt-prefix fence before any provider call.

        The SQL turn preparer exposes this as a small provider-free method.
        Keeping the lookup optional preserves the in-memory repository and
        older test doubles, while the SQL repository can require the exact
        predecessor hash/CAS identity.
        """

        preparer = self.turn_preparer
        if preparer is None:
            return None
        resolver = getattr(preparer, "generation_fence", None)
        value: Any = None
        if callable(resolver):
            try:
                value = resolver(
                    db,
                    debate,
                    turn,
                    attempt=attempt,
                    cancellation_generation=cancellation_generation,
                )
            except TypeError:
                # Keep compatibility with a provider-free resolver that only
                # accepts the three immutable row arguments.
                value = resolver(db, debate, turn)
            if inspect.isawaitable(value):
                value = await value
        elif isinstance(resolver, PreparedGenerationFence):
            value = resolver
        if isinstance(value, PreparedGenerationFence):
            return value
        # A prepared row from a previous attempt may already carry the exact
        # fence.  Do not invent a hash when it is absent: SQL must fail closed
        # instead of allowing an unbound provider result to commit.
        predecessor_value = self._get(turn, "predecessor_turn_ids", default=None)
        if predecessor_value is None:
            predecessor_value = self._get(turn, "predecessor_turn_ids_json", default=None)
            if isinstance(predecessor_value, str):
                try:
                    import json

                    parsed = json.loads(predecessor_value)
                    predecessor_value = parsed if isinstance(parsed, list) else ()
                except (TypeError, ValueError):
                    predecessor_value = ()
        transcript_hash = self._get(turn, "transcript_hash", "predecessor_hash", default=None)
        cutoff = self._get(turn, "cutoff_turn_index", default=None)
        if transcript_hash is None or cutoff is None:
            return None
        return PreparedGenerationFence(
            predecessor_turn_ids=tuple(str(item) for item in predecessor_value or ()),
            transcript_hash=str(transcript_hash),
            cutoff_turn_index=int(cutoff),
            attempt=attempt,
        )

    def _resolve_voice(
        self,
        db: Any,
        participant: Any | None,
    ) -> ResolvedTurnVoice:
        resolver = getattr(self.repository, "resolve_effective_voice", None)
        if callable(resolver):
            value = resolver(db, participant, self.settings)
            if isinstance(value, ResolvedTurnVoice):
                return value
            if isinstance(value, Mapping):
                raw_model = value.get("target_model_key")
                return ResolvedTurnVoice(
                    kind=str(value.get("kind", "mock_sentinel")),
                    profile_id=(
                        str(value["profile_id"]) if value.get("profile_id") is not None else None
                    ),
                    voice_token=str(value.get("voice_token", "mock")),
                    target_model_key=str(raw_model) if raw_model else None,
                )
        return ResolvedTurnVoice(
            kind="mock_sentinel",
            profile_id=None,
            voice_token=str(
                self._get(participant, "effective_voice_profile_id", default="mock") or "mock"
            ),
        )

    @staticmethod
    def _validate_prepared(prepared: PreparedTurn, language: str = "en") -> PreparedTurn:
        # The same bound the generation validator applies, in the unit the
        # Debate's language is measured in. Counting Latin words in a Chinese
        # speech finds none, so every Chinese turn failed here after passing
        # every rule that had been taught about the language.
        from app.modules.debates.generation.types import TurnValidationError
        from app.modules.debates.output_language import (
            TURN_MAX_WORDS,
            TURN_MIN_WORDS,
            speech_units,
            unit_bounds,
        )

        if prepared.structured.get("schema_version") == "segment_turn_v2":
            segments = prepared.structured.get("segments")
            if (
                not isinstance(segments, (list, tuple))
                or not segments
                or any(
                    not isinstance(segment, Mapping) or not isinstance(segment.get("text"), str)
                    for segment in segments
                )
            ):
                raise TurnValidationError("Prepared paragraphs are invalid.", code="schema_invalid")
            if prepared.speech != "\n\n".join(segment["text"] for segment in segments):
                raise TurnValidationError("Prepared text changed.", code="schema_invalid")
            return prepared

        speech = prepared.speech.strip()
        minimum, maximum = unit_bounds(language, TURN_MIN_WORDS, TURN_MAX_WORDS)  # type: ignore[arg-type]
        count = speech_units(speech, "zh") if language == "zh" else PlaybackCore._word_count(speech)
        if not speech or count < minimum or count > maximum:
            # Coded, because an uncoded failure here is invisible: the turn
            # stops, no status changes, and the lesson waits on nothing.
            raise TurnValidationError(
                "The prepared speech is outside this debate's per-turn length.",
                code="turn_length_invalid",
                json_pointers=("/speech",),
            )
        sources = tuple(prepared.sources)
        if sources:
            # Wave 2 intentionally uses mixed rather than claiming claim-level
            # RAG grounding.  Retrieval status is derived from receipt use.
            return replace(
                prepared,
                speech=speech,
                sources=sources,
                retrieval_status="matched",
                grounding_mode="mixed",
                word_count=count,
            )
        return replace(
            prepared,
            speech=speech,
            sources=(),
            source_receipts=(),
            retrieval_status="no_match",
            grounding_mode="general_reasoning",
            word_count=count,
        )

    def _provider_allowed(self) -> None:
        if self.settings is not None:
            embedding = getattr(self.settings, "embedding_provider", "mock")
            speech_selectors = (
                getattr(self.settings, "tts_provider", "mock"),
                getattr(self.settings, "voice_provider", "mock"),
            )
            if embedding not in {"mock", "dashscope"} or any(
                value not in {"mock", "dashscope"} for value in speech_selectors
            ):
                raise PlatformError(
                    "provider_unavailable", "The service is temporarily unavailable.", 503
                )
        if getattr(self.tts_provider, "key", "mock") not in {"mock", "dashscope"}:
            raise PlatformError(
                "provider_unavailable", "The service is temporarily unavailable.", 503
            )

    def _release_claim(
        self,
        db: Any,
        debate: Any,
        turn: Any,
        claim_token: str | None,
        *,
        cancellation_generation: int,
    ) -> None:
        """Hand a claimed job back when preparation cannot continue.

        A claim that is taken and never released leaves the Job ``running``
        forever, and every later attempt is refused because it looks like work
        already in flight. That is how a draft can stop warming without
        anything visible going wrong.
        """

        del debate
        release = getattr(self.repository, "reset_prewarm_turn", None)
        if not callable(release) or claim_token is None:
            return
        try:
            release(
                db,
                turn,
                claim_token=claim_token,
                cancellation_generation=cancellation_generation,
            )
            self._commit(db)
        except Exception as exc:
            self._rollback(db)
            LOGGER.error(
                "Could not release turn claim turn_id=%s error_type=%s",
                getattr(turn, "id", "?"),
                type(exc).__name__,
            )

    @staticmethod
    def _has_accepted_llm_stage(db: Any, turn_id: str) -> bool:
        """Whether a charged reply for this turn is staged and unpublished.

        A real-provider turn is produced in two passes on purpose: the first
        accepts and stages the reply the supplier was paid for, and a later
        pass publishes it, so a crash between the two can never lose a charged
        answer. Nothing was making that second pass, so every real turn stopped
        one step short of ready: the money was spent, the answer was on disk,
        and the turn stayed pending with no error to show for it.
        """

        execute = getattr(db, "execute", None)
        if not callable(execute):
            return False
        try:
            from sqlalchemy import text

            row = execute(
                text(
                    "SELECT 1 FROM provider_operations "
                    "WHERE provider_operation='llm_debate_turn' "
                    "AND logical_item_id=:turn_id AND state='accepted' LIMIT 1"
                ),
                {"turn_id": turn_id},
            ).first()
        except Exception:
            # A repository without this table simply has no staged reply.
            return False
        return row is not None

    def _turn_is_ready(self, db: Any, debate_id: str, turn_id: str) -> bool:
        try:
            debate = self._get_debate(db, debate_id)
            if debate is None:
                return True
            for item in self._turns(db, debate):
                if str(self._get(item, "id", default="")) == turn_id:
                    return str(self._get(item, "generation_status", default="")) in {
                        "final_ready",
                        "ready",
                        "completed",
                    }
        except Exception:
            return True
        return True

    async def prepare_turn(self, db: Any, debate_id: str, turn_id: str) -> None:
        """Produce one turn, publishing a staged reply when one is waiting.

        The pass below is the whole of preparation for a Mock turn. A real
        provider turn needs a second pass to publish what the first one staged,
        and the gate is deliberately narrow: only a turn that is still not
        ready and has an accepted, unpublished operation gets one. That second
        pass resumes the staged reply and cannot reach the supplier, so it can
        neither spend money nor spin.
        """

        await self._prepare_turn_pass(db, debate_id, turn_id)
        if self._turn_is_ready(db, debate_id, turn_id):
            return
        if not self._has_accepted_llm_stage(db, turn_id):
            return
        await self._prepare_turn_pass(db, debate_id, turn_id)

    async def _prepare_turn_pass(self, db: Any, debate_id: str, turn_id: str) -> None:
        owned_claim: tuple[Any, Any, str, int] | None = None

        def remember_claim(debate: Any, turn: Any, token: str, generation: int) -> None:
            nonlocal owned_claim
            owned_claim = (debate, turn, token, generation)

        try:
            await self._prepare_turn_pass_with_claim(db, debate_id, turn_id, remember_claim)
        finally:
            # A refused claim is not ours to repair. The owner waits for its
            # provider thread before releasing only its unfinished draft work.
            if owned_claim is not None:
                debate, turn, token, generation = owned_claim
                self._rollback(db)
                self._release_claim(db, debate, turn, token, cancellation_generation=generation)

    async def _prepare_turn_pass_with_claim(
        self,
        db: Any,
        debate_id: str,
        turn_id: str,
        remember_claim: Callable[[Any, Any, str, int], None],
    ) -> None:
        """Generate/TTS one turn: the current one, its successor, or a pre-warm.

        A running Debate keeps the CAS fence it always had -- only the playing
        turn and the one after it may be prepared, and the successor only once
        the current turn is ready. That fence governs who may advance playback
        and is untouched.

        A draft is a different question with a different answer. Nothing is
        playing, so there is nothing to fence against; the turns are prepared
        strictly in order so each one sees the speeches before it, exactly as
        it would during the lesson. The rows are the same rows, so when the
        teacher starts the debate the work is simply already done.
        """

        async with self._lock:
            debate = self._get_debate(db, debate_id)
            state = self._state(db, debate)
            turns = self._turns(db, debate)
            turn = next((item for item in turns if str(getattr(item, "id", "")) == turn_id), None)
            if turn is None:
                LOGGER.info(
                    "prepare_skip debate_id=%s turn_id=%s reason=turn_missing",
                    debate_id,
                    turn_id,
                )
                return
            status = str(getattr(debate, "status", ""))
            prewarming = status == "draft"
            if status != "running" and not prewarming:
                LOGGER.info(
                    "prepare_skip debate_id=%s turn_id=%s reason=not_draft_or_running status=%s",
                    debate_id,
                    turn_id,
                    status,
                )
                return
            if uses_segment_protocol(debate) and self._round(turn) == debate_round_count(debate):
                if prewarming or not getattr(debate, "final_input_json", None):
                    return
            if prewarming:
                current_index = -1
                turn_index = int(self._get(turn, "turn_index", default=0) or 0)
                # Strictly the next unprepared turn. Preparing out of order
                # would give a turn predecessors it will not have in the room.
                if any(
                    not (self._turn_ready(item) or self._turn_text_fallback_ready(item))
                    for item in turns
                    if int(self._get(item, "turn_index", default=0) or 0) < turn_index
                ):
                    LOGGER.info(
                        "prepare_skip debate_id=%s turn_id=%s reason=draft_out_of_order "
                        "turn_index=%s",
                        debate_id,
                        turn_id,
                        turn_index,
                    )
                    return
            else:
                if state.current_turn_id is None:
                    return
                current_index = next(
                    (
                        index
                        for index, item in enumerate(turns)
                        if str(getattr(item, "id", "")) == state.current_turn_id
                    ),
                    -1,
                )
                if current_index < 0:
                    return
                turn_index = int(
                    self._get(turn, "turn_index", default=current_index) or current_index
                )
                if turn_index not in {current_index, current_index + 1}:
                    return
                if turn_index == current_index + 1:
                    previous = turns[current_index]
                    previous_generation = str(
                        self._get(previous, "generation_status", default="pending")
                    )
                    if previous_generation not in {"final_ready", "ready", "completed"}:
                        return
            cancellation_generation = int(
                self._get(debate, "cancellation_generation", default=0) or 0
            )
            if self._turn_text_fallback_ready(turn):
                if not prewarming and turn_index == current_index:
                    await self._publish_text_current(db, debate, turn)
                return
            if self._turn_ready(turn):
                # Pre-warm makes this the normal case rather than a redundant
                # re-enqueue: the turn was generated before the lesson reached
                # it. Returning silently meant the classroom never heard
                # "turn.ready", so playback never started, nothing was ever
                # published, and a debate whose speeches were finished showed
                # none of them.
                #
                # Only a running lesson standing on this turn may announce it.
                # Saying it while warming a draft drove that draft's playback
                # state forward with no teacher present, and it published
                # itself to the end.
                if prewarming or turn_index != current_index:
                    return
                state.status = "ready"
                state.cursor_ms = 0
                state.audio_duration_ms = int(self._get(turn, "audio_duration_ms", default=0) or 0)
                state.pending_action = None
                state.pending_ticket_hash = None
                state.pending_media_command_id = None
                self._clear_media_results(debate_id)
                self._save(db, debate, state)
                ready_now = self._stage_event(
                    db,
                    debate_id,
                    "turn.ready",
                    {
                        "turn_id": turn_id,
                        "slot": self._slot(
                            self._participant_for_turn(self._participants(db, debate), turn)
                        ),
                        "round_no": self._round(turn),
                        "audio_ready": self._get(turn, "audio_file_id", "audio_relative_path")
                        is not None,
                        "retrieval_status": str(
                            self._get(turn, "retrieval_status", default="no_match")
                        ),
                        "grounding_mode": str(
                            self._get(turn, "grounding_mode", default="general_reasoning")
                        ),
                        "audio_duration_ms": state.audio_duration_ms,
                        **self._mutual_phase_payload(debate, turn),
                    },
                )
                self._commit(db)
                # Announced while the lock is held, which is safe here and
                # nowhere else in this method: the commit above already
                # happened, and publishing only pushes to the event hub, which
                # never re-enters this lock. The alternative was to carry a
                # flag past a hundred lines of generation that must not run.
                await self._publish_events([ready_now])
                return
            claim_token: str | None = None
            generation_fence: PreparedGenerationFence | None = None
            claim_job = getattr(self.repository, "claim_turn_job", None)
            if callable(claim_job):
                claim_token = claim_job(
                    db,
                    debate,
                    turn,
                    cancellation_generation=cancellation_generation,
                )
                if claim_token is None:
                    LOGGER.warning(
                        "prepare_skip debate_id=%s turn_id=%s reason=claim_unavailable "
                        "prewarming=%s",
                        debate_id,
                        turn_id,
                        prewarming,
                    )
                    return
                if prewarming:
                    remember_claim(debate, turn, claim_token, cancellation_generation)
                generation_fence = await self._generation_fence(
                    db,
                    debate,
                    turn,
                    attempt=1,
                    cancellation_generation=cancellation_generation,
                )
                mark_running = getattr(
                    self.repository,
                    "mark_turn_prewarming" if prewarming else "mark_turn_running",
                    None,
                )
                if mark_running is None and prewarming:
                    # A repository double without the draft statement simply
                    # does not pre-warm; it must not fall back to the live one.
                    LOGGER.warning(
                        "prepare_skip debate_id=%s turn_id=%s reason=mark_prewarming_missing "
                        "claim=%s",
                        debate_id,
                        turn_id,
                        claim_token,
                    )
                    self._release_claim(
                        db,
                        debate,
                        turn,
                        claim_token,
                        cancellation_generation=cancellation_generation,
                    )
                    return
                if not callable(mark_running):
                    LOGGER.warning(
                        "prepare_skip debate_id=%s turn_id=%s reason=mark_running_missing",
                        debate_id,
                        turn_id,
                    )
                    return
                mark_kwargs: dict[str, Any] = {
                    "cancellation_generation": cancellation_generation,
                    "claim_token": claim_token,
                }
                # M12 remains compatible with the early repository double,
                # while the SQL adapter receives the exact M11 prefix fence
                # before any RAG/LLM/TTS provider call.
                try:
                    mark_signature = inspect.signature(mark_running)
                    accepts_fence = "fence" in mark_signature.parameters or any(
                        parameter.kind is inspect.Parameter.VAR_KEYWORD
                        for parameter in mark_signature.parameters.values()
                    )
                except (TypeError, ValueError):
                    accepts_fence = True
                if accepts_fence:
                    mark_kwargs["fence"] = generation_fence
                if not mark_running(db, turn, **mark_kwargs):
                    LOGGER.warning(
                        "prepare_skip debate_id=%s turn_id=%s reason=mark_running_rejected "
                        "claim=%s prewarming=%s",
                        debate_id,
                        turn_id,
                        claim_token,
                        prewarming,
                    )
                    self._release_claim(
                        db,
                        debate,
                        turn,
                        claim_token,
                        cancellation_generation=cancellation_generation,
                    )
                    return
            else:
                turn.generation_status = "running"
                turn.preparation_stage = "generation"
                if hasattr(turn, "failed_code"):
                    turn.failed_code = None
            participants = self._participants(db, debate)
            participant = self._participant_for_turn(participants, turn)
            slot = self._slot(participant)
            round_no = self._round(turn)
            is_current = turn_index == current_index
            staged_events: list[EventRecord] = []
            if is_current:
                staged_events.append(
                    self._stage_event(
                        db,
                        debate_id,
                        "turn.preparing",
                        {
                            "turn_id": turn_id,
                            "slot": slot,
                            "round_no": round_no,
                            "stage": "llm",
                            **self._mutual_phase_payload(debate, turn),
                        },
                    )
                )
            self._save(db, debate, state)
            self._commit(db)

        await self._publish_events(staged_events)

        ready_events: list[EventRecord] = []
        next_turn_to_enqueue: Any | None = None
        last_error: Exception | None = None
        audio: AudioMetadata | None = None
        audio_committed = False
        audio_error_code: str | None = None
        staged_audio: StagedAudio | None = None
        prepared: PreparedTurn | None = None
        try:
            # M11 owns the single shared attempt 1|2 repair budget.  Playback
            # invokes that orchestrator once and therefore cannot multiply two
            # generation attempts into four provider calls.
            prepared = self._validate_prepared(
                await self._call_preparer(db, debate, turn, 1),
                debate_output_language(debate),
            )
            # Accepted LLM stage + its recovery input must survive a process
            # crash before TTS.  Generation deliberately leaves the provider
            # operation ``accepted``; only the final mark_turn_ready
            # transaction may promote it to ``succeeded``.
            if prepared.llm_publication is not None:
                self._commit(db)
            if uses_segment_protocol(debate):
                save_text = getattr(self.repository, "save_turn_text", None)
                if not callable(save_text) or not save_text(
                    db,
                    turn,
                    prepared,
                    claim_token=claim_token,
                    generation=cancellation_generation,
                    debate_status="draft" if prewarming else "running",
                ):
                    raise PlatformError("turn_generation_failed", "The saved turn changed.", 409)
                self._commit(db)
            try:
                voice = self._resolve_voice(db, participant)
                prepared = replace(
                    prepared,
                    voice_token=voice.voice_token,
                    actual_voice_kind=voice.kind,
                    actual_voice_profile_id=voice.profile_id,
                )
                self._provider_allowed()
                voice_token = prepared.voice_token
                if not voice_token:
                    raise TTSVoiceUnavailableError()
                if self.audio_store is None:
                    from .audio import AudioStore

                    root = getattr(self.settings, "resolved_data_root", None)
                    if root is None:
                        raise TTSProviderError("audio store is not configured")
                    self.audio_store = AudioStore(root, tts_provider=self.tts_provider)
                # Same reason as the preparer above: a real TTS provider is one
                # more blocking HTTP call, and the audio store writes a file. Mock
                # TTS returns fast enough to hide this, so leaving it on the loop
                # would put the freeze back the moment the voice slice goes real.
                if uses_segment_protocol(debate):
                    stage_work = asyncio.create_task(
                        asyncio.to_thread(
                            self.audio_store.stage_synthesis,
                            course_id=self._course_id(debate),
                            debate_id=debate_id,
                            turn_id=turn_id,
                            operation_id=claim_token,
                            speech=prepared.speech,
                            voice_token=voice_token,
                            language=debate_output_language(debate),
                            target_model_key=voice.target_model_key,
                        )
                    )
                    try:
                        staged_audio = await asyncio.shield(stage_work)
                    except asyncio.CancelledError:
                        try:
                            abandoned_stage = await _finish_thread_after_cancellation(stage_work)
                            self.audio_store.discard_staged_audio(abandoned_stage)
                        except Exception:
                            pass
                        raise
                else:
                    synthesize: Callable[[], AudioMetadata] = functools.partial(
                        self.audio_store.synthesize_and_store,
                        course_id=self._course_id(debate),
                        debate_id=debate_id,
                        turn_id=turn_id,
                        speech=prepared.speech,
                        voice_token=voice_token,
                        language=debate_output_language(debate),
                        target_model_key=voice.target_model_key,
                    )
                    synthesis_work = asyncio.create_task(asyncio.to_thread(synthesize))
                    try:
                        audio = await asyncio.shield(synthesis_work)
                    except asyncio.CancelledError:
                        try:
                            await _finish_thread_after_cancellation(synthesis_work)
                        except Exception:
                            pass
                        raise
            except TTSProviderError as exc:
                if exc.safe_code not in TTS_UNAVAILABLE_CODES:
                    raise
                audio_error_code = exc.safe_code
                LOGGER.warning(
                    "Turn audio unavailable debate_id=%s turn_id=%s safe_code=%s",
                    debate_id,
                    turn_id,
                    audio_error_code,
                )
            async with self._lock:
                fresh_debate = self._get_debate(db, debate_id)
                fresh_turn = next(
                    (
                        item
                        for item in self._turns(db, fresh_debate)
                        if str(getattr(item, "id", "")) == turn_id
                    ),
                    None,
                )
                expected_status = "draft" if prewarming else "running"
                if (
                    fresh_turn is None
                    or str(getattr(fresh_debate, "status", "")) != expected_status
                    or int(self._get(fresh_debate, "cancellation_generation", default=0) or 0)
                    != cancellation_generation
                    or self._get(fresh_turn, "generation_status", default="")
                    not in {"running", "pending"}
                ):
                    if staged_audio is not None:
                        assert self.audio_store is not None
                        self.audio_store.discard_staged_audio(staged_audio)
                    elif audio is not None and self.audio_store is not None:
                        self.audio_store.remove_turn(debate_id, turn_id)
                    return
                if staged_audio is not None:
                    assert self.audio_store is not None
                    fence_audio = getattr(self.repository, "fence_audio_promotion", None)
                    if not callable(fence_audio) or not fence_audio(
                        db, fresh_debate, fresh_turn, claim_token, cancellation_generation
                    ):
                        self._rollback(db)
                        self.audio_store.discard_staged_audio(staged_audio)
                        return
                    audio = self.audio_store.promote_staged_audio(staged_audio)
                if audio_error_code is None:
                    assert audio is not None
                audio_arguments: dict[str, Any] = {}
                if audio_error_code is not None:
                    audio_arguments["audio_error_code"] = audio_error_code
                accepted = self.repository.mark_turn_ready(
                    db,
                    fresh_turn,
                    prepared,
                    audio,
                    generation=cancellation_generation,
                    debate_status=expected_status,
                    attempt=prepared.generation_attempt,
                    claim_token=claim_token,
                    **audio_arguments,
                )
                if not accepted:
                    if staged_audio is not None:
                        assert self.audio_store is not None
                        self.audio_store.remove_promoted_audio_if_owned(staged_audio)
                        self._rollback(db)
                    elif audio is not None and self.audio_store is not None:
                        self.audio_store.remove_turn(debate_id, turn_id)
                    return
                if prewarming:
                    # The Preview scheduler alone advances a draft. Enqueuing
                    # its successor here races a second worker for that turn.
                    self._commit(db)
                    audio_committed = True
                    return
                if audio is None:
                    self._commit(db)
                    fresh_debate = self._get_debate(db, debate_id)
                    fresh_turn = next(
                        item for item in self._turns(db, fresh_debate) if str(item.id) == turn_id
                    )
                    if await self._publish_text_current(db, fresh_debate, fresh_turn):
                        return
                    current_state = self._state(db, fresh_debate)
                    if (
                        current_state.mode == "live"
                        and current_state.status == "waiting_next"
                        and current_state.current_turn_id is not None
                        and self._next_turn_ready(db, fresh_debate, current_state)
                    ):
                        event = self._stage_event(
                            db,
                            debate_id,
                            "playback.waiting_next",
                            {
                                "mode": "live",
                                "completed_turn_id": current_state.current_turn_id,
                                "control_version": current_state.control_version,
                                "next_turn_ready": True,
                            },
                        )
                        self._commit(db)
                        await self._publish_event(event)
                    return
                current_state = self._state(db, fresh_debate)
                current_turns = self._turns(db, fresh_debate)
                current_index = next(
                    (
                        index
                        for index, item in enumerate(current_turns)
                        if str(getattr(item, "id", "")) == current_state.current_turn_id
                    ),
                    0,
                )
                is_current = (
                    int(self._get(fresh_turn, "turn_index", default=0) or 0) == current_index
                )
                ready_events = []
                if is_current:
                    current_state.status = "ready"
                    current_state.cursor_ms = 0
                    current_state.audio_duration_ms = audio.duration_ms if audio is not None else 0
                    current_state.pending_action = None
                    current_state.pending_ticket_hash = None
                    current_state.pending_media_command_id = None
                    self._clear_media_results(debate_id)
                    self._save(db, fresh_debate, current_state)
                    ready_events.append(
                        self._stage_event(
                            db,
                            debate_id,
                            "turn.ready",
                            {
                                "turn_id": turn_id,
                                "slot": self._slot(
                                    self._participant_for_turn(
                                        self._participants(db, fresh_debate), fresh_turn
                                    )
                                ),
                                "round_no": self._round(fresh_turn),
                                "audio_ready": audio is not None,
                                "retrieval_status": prepared.retrieval_status,
                                "grounding_mode": prepared.grounding_mode,
                                "audio_duration_ms": audio.duration_ms if audio is not None else 0,
                                **self._mutual_phase_payload(fresh_debate, fresh_turn),
                            },
                        )
                    )
                elif (
                    current_state.mode == "live"
                    and current_state.status == "waiting_next"
                    and current_state.current_turn_id is not None
                    and self._next_turn_ready(db, fresh_debate, current_state)
                ):
                    # A successor may finish its slow generation/TTS after
                    # the current turn has ended.  Only the readiness bit is
                    # public; the completed current turn and its control
                    # version remain the event's sole identity.
                    ready_events.append(
                        self._stage_event(
                            db,
                            debate_id,
                            "playback.waiting_next",
                            {
                                "mode": "live",
                                "completed_turn_id": current_state.current_turn_id,
                                "control_version": current_state.control_version,
                                "next_turn_ready": True,
                            },
                        )
                    )
                self._commit(db)
                audio_committed = True
                if is_current:
                    next_turn = (
                        current_turns[current_index + 1]
                        if current_index + 1 < len(current_turns)
                        else None
                    )
                    if next_turn is not None:
                        next_turn_to_enqueue = next_turn
            await self._publish_events(ready_events)
            if next_turn_to_enqueue is not None:
                await self._enqueue(fresh_debate, next_turn_to_enqueue)
            return
        except asyncio.CancelledError:
            if staged_audio is not None and self.audio_store is not None:
                self.audio_store.discard_staged_audio(staged_audio)
                if audio is not None and not audio_committed:
                    self.audio_store.remove_promoted_audio_if_owned(staged_audio)
            raise
        except Exception as exc:
            last_error = exc
            # Record the exception type and its safe code, never the message:
            # the message can carry provider or student data. Without this
            # line a turn that dies before its provider manifest leaves
            # nothing but the generic ``turn_generation_failed`` code.
            LOGGER.error(
                "Turn preparation failed debate_id=%s turn_id=%s error_type=%s "
                "safe_code=%s raised_at=%s",
                debate_id,
                turn_id,
                type(exc).__name__,
                # A safe code is the same string the browser already receives,
                # so recording it leaks nothing and is often the only thing
                # that distinguishes a missing policy from a refused request.
                getattr(exc, "code", None) or getattr(exc, "safe_code", "-"),
                # Where it was raised, never what it said. An exception that
                # carries no safe code -- a bare ValueError from somewhere deep
                # in generation -- otherwise leaves a line that names a type and
                # nothing a person can act on, and a turn stops with the failure
                # invisible. File, line and function are our own source
                # positions and cannot contain provider or student data, which
                # is what keeps the message itself out of this.
                _raise_site(exc),
                exc_info=False,
            )
            # The final Turn/source/job writes and the LLM operation CAS share
            # this transaction.  Roll back before either the recoverable or
            # terminal handler starts a new state transition.
            if staged_audio is not None and self.audio_store is not None:
                self.audio_store.discard_staged_audio(staged_audio)
                if audio is not None and not audio_committed:
                    self.audio_store.remove_promoted_audio_if_owned(staged_audio)
            self._rollback(db)
            if (
                staged_audio is None
                and audio is not None
                and not audio_committed
                and self.audio_store is not None
            ):
                self.audio_store.remove_turn(debate_id, turn_id)
        error_code = getattr(last_error, "code", None) or getattr(last_error, "safe_code", None)
        from app.modules.debates.generation.segments_runtime import SEGMENT_REPAIR_CODES

        recoverable_provider_error = error_code in {
            "provider_confirmation_required",
            "provider_not_sent",
            "acceptance_unknown",
            "question_route_invalid",
            "discussion_memory_invalid",
            "segment_shape_invalid",
            "support_mode_invalid",
            "final_reply_missing",
        }
        recoverable_tts_error = (
            isinstance(error_code, str)
            and error_code.startswith("tts_")
            and prepared is not None
            and (prepared.llm_publication is not None or uses_segment_protocol(debate))
        )
        recoverable_provider_error = recoverable_provider_error or (
            uses_segment_protocol(debate) and error_code in SEGMENT_REPAIR_CODES
        )
        if (
            recoverable_provider_error or recoverable_tts_error
        ) and await self._defer_provider_preparation(
            db,
            debate_id=debate_id,
            turn_id=turn_id,
            claim_token=claim_token,
            code=str(error_code),
        ):
            return
        if prewarming:
            async with self._lock:
                debate = self._get_debate(db, debate_id)
                turns = self._turns(db, debate)
                current = next(
                    (item for item in turns if str(getattr(item, "id", "")) == turn_id), turn
                )
                code = (
                    str(error_code)
                    if error_code in _SAFE_GENERATION_CODES
                    else "turn_generation_failed"
                )
                fail_prewarm = getattr(self.repository, "fail_prewarm_turn", None)
                if callable(fail_prewarm):
                    fail_prewarm(db, current, claim_token=claim_token, code=code)
                    self._commit(db)
                else:
                    self._release_claim(
                        db,
                        debate,
                        current,
                        claim_token,
                        cancellation_generation=cancellation_generation,
                    )
            return
        failed_event: EventRecord | None = None
        failed_epoch: str | None = None
        async with self._lock:
            debate = self._get_debate(db, debate_id)
            turns = self._turns(db, debate)
            turn = next((item for item in turns if str(getattr(item, "id", "")) == turn_id), turn)
            code = "turn_generation_failed"
            if isinstance(last_error, PlatformError) and last_error.code in _SAFE_GENERATION_CODES:
                code = last_error.code
            elif error_code in _SAFE_GENERATION_CODES:
                code = str(error_code)
            fail_job = getattr(self.repository, "fail_turn_job", None)
            if callable(fail_job):
                fail_job(db, turn, claim_token, code)
            self.repository.fail_turn_and_debate(db, debate, turn, code)
            state = self._state(db, debate)
            self._set_nonplaying(state, "stopped")
            state.control_version += 1
            failed_epoch = state.controller_epoch
            state.controller_epoch = None
            state.controller_session_hash = None
            state.controller_connection_id = None
            self._controller_sessions.pop(debate_id, None)
            self._save(db, debate, state)
            failed_event = self._stage_event(
                db,
                debate_id,
                "debate.failed",
                {
                    "final_states": {
                        "debate": "failed",
                        "playback": self._state_dto(state, db, debate).model_dump(mode="json"),
                        "interaction": "closed",
                        "insight": "not_started",
                        "report": "not_started",
                    },
                    "downstream_outcome": "failed",
                    "safe_error_code": code,
                },
            )
            self._commit(db)
            self.ticket_store.revoke_debate(debate_id)
            if failed_epoch is not None:
                self._revoke_epoch(failed_epoch, debate_id, "debate_terminal")
        if failed_event is not None:
            await self._publish_event(failed_event)

    async def _defer_provider_preparation(
        self,
        db: Any,
        *,
        debate_id: str,
        turn_id: str,
        claim_token: str | None,
        code: str,
    ) -> bool:
        """Park an exact provider-gated turn while keeping its Debate resumable."""

        self._rollback(db)
        deferred_event: EventRecord | None = None
        async with self._lock:
            try:
                debate = self._get_debate(db, debate_id)
                turns = self._turns(db, debate)
                turn = next(
                    (item for item in turns if str(getattr(item, "id", "")) == turn_id),
                    None,
                )
                if turn is None or str(getattr(debate, "status", "")) != "running":
                    return False
                defer = getattr(self.repository, "defer_turn_job", None)
                if not callable(defer) or not defer(db, debate, turn, claim_token, code):
                    self._rollback(db)
                    return False
                deferred_event = self._stage_event(
                    db,
                    debate_id,
                    "error",
                    {
                        "code": code,
                        "message": (
                            "Teacher confirmation is required before this turn can continue."
                            if code == "provider_confirmation_required"
                            else (
                                "The provider acceptance is unknown and requires reconciliation."
                                if code == "acceptance_unknown"
                                else (
                                    "The TTS stage did not complete. The accepted LLM result "
                                    "is retained for a local retry."
                                    if code.startswith("tts_")
                                    else (
                                        "The provider request was not sent. "
                                        "The teacher may retry safely."
                                    )
                                )
                            )
                        ),
                        "recoverable": True,
                    },
                )
                self._commit(db)
            except Exception:
                self._rollback(db)
                return False
        if deferred_event is not None:
            await self._publish_event(deferred_event)
        return deferred_event is not None

    # ------------------------------------------------------------------
    # Public controls
    # ------------------------------------------------------------------
