# Wave 2 Gate Packet — M10 Debate Setup + M11 Turn Generation + M12 Playback

Status: `G0-S PASS — G1 LUNA IMPLEMENTATION AUTHORIZED`
Authorized scope: `2026-08-27 Asia/Shanghai`
Modules: `M10 debate creation/rules`, `M11 RAG/LLM turn generation`, `M12 teacher stage/playback/recovery`
Dependencies: `Wave 0 G3 PASS`, `Wave 1A G3 PASS`, `Wave 1B Mock G3 PASS`, `Wave 1C G3 PASS`, reviewed Wave 2 contract delta `g0-2026-08-27.5`
Initial product commit: `e86f8799c5f274c5830c8a529b139d0b698543ac`
Initial Project SHA-256: `728dcf13557f3f4f9c55d3b55d30915fd730365d1cd063b25a8173647f270889`
Initial Git state: clean

## 1. Goal

Wave 2 must produce a two-person/two-round classroom-debate candidate without entering interaction or reporting:

1. a teacher creates a course debate from 2–5 current published Agents in click order;
2. the server freezes each participant's AgentVersion, KnowledgeSnapshot, Avatar configuration and server-only effective-voice decision;
3. a versioned deterministic rule set plans exactly `participant_count × 2` turns;
4. every turn retrieves only its participant snapshot, uses the exact immutable final-ready planned-predecessor prefix, generates a validated English speech and then produces Mock TTS audio;
5. the teacher starts once, and the server remains authoritative for preparation, publication, playback, controls, replay, WebSocket events and restart recovery;
6. the default G3 candidate demonstrates Bowen support vs KaiKai oppose on the TikTok recommendation-algorithm question.

## 2. Non-goals and hard stop boundary

- no M13/M14/M15 implementation: no QR, anonymous audience, vote, barrage, insight, Maya report, history product page or translation;
- no Wave 3/4 routes, tables, buttons or placeholder interactions;
- no real Embedding migration or rebuild of existing 256-dimensional Mock snapshots;
- no real TTS call. The real system voice enrollment succeeded, but two authorized technical TTS attempts failed; Wave 2 uses Mock TTS only and never activates `FALLBACK_VOICE_PROFILE_ID`;
- no real LLM call until the LLM adapter has separately passed design/security audit. The default Wave 2 G1/G1.5 path is deterministic Mock;
- no 5-person real-provider run, pressure test, DeepL, public deployment, cloud deployment or Git push;
- no edit to published AgentVersion/KnowledgeSnapshot and no copying reference-repository source.

Entering any Wave 3/4 feature, changing the two-round user experience, inventing a TTS fallback, deleting the supplier-side cloned system voice, or changing data retention requires a stop.

## 3. Frozen public behavior

### 3.1 Debate draft

- course teacher only; students receive `403`, outside-course users receive `404`;
- topic is non-empty English text; Demo does not add a product max length in Wave 2;
- participants are the teacher's click order, 2–5 unique current published, non-archived Agents from the same course;
- slots are consecutive `A–E` and `order_index=0–4`; removing a draft participant reletters the remaining order;
- `round_count` must equal 2; both duration fields remain `null`;
- `stance_mode=assigned|open`; assigned requires `support|oppose|neutral`, open requires null assigned stance;
- create/update re-resolves the then-current published version/snapshot. Start never silently upgrades them again;
- update requires `expected_revision`; create is idempotent, and both operations revalidate teacher scope plus all current Agent/version/snapshot pointers inside the final write transaction after any idempotency claim;
- `Maya` is not a participant, slot, turn, voice or 3D card.

### 3.2 Two-round rule set

Stable rule ID: `ordered_multi_agent_rounds_demo_v1`.

- turn order is all participants in slot order for round 1, then the same order for round 2;
- round 1: state a viewpoint, use retrieved evidence when present, make a distinct claim and summarize the current position; no mandatory participant question;
- round 2: address a specific earlier claim, rebut or refine it with retrieved evidence when present, answer any question directed to this participant, and update/concede/reframe the position through civil persuasion;
- every round-2 turn except the final overall turn asks the next scheduled participant one specific question;
- the final overall turn asks the whole class one reflection question instead of asking a next participant;
- changing stance, conceding or reframing is allowed and recorded; direct vote solicitation is forbidden;
- authoritative speech is English, 80–200 words with a 160–185 target. Questions count toward the limit.

### 3.3 RAG and prompt honesty

- each turn searches only the frozen `knowledge_snapshot_id` fixed on its participant;
- retrieval query includes topic, current rule task, the immediately relevant earlier claim/question and the participant's current position summary. Round 1 uses the viewpoint task; round 2 uses at most three typed subqueries for the assigned pending question, a specific rebuttal target and support for the updated position;
- use the existing combined `top_k=6` receipt boundary. Each subquery runs strict once and only runs relaxed if strict has no semantic match; strict→relaxed is one semantic retrieval attempt and does not consume the turn repair budget. Receipts are merged and deduplicated by `(snapshot_id, chunk_id)` before the six-item cap;
- freeze `SnapshotRetrievalReceipt = snapshot_id + query_kind + query_hash + threshold_key + rank + score + chunk_id + source_filename + text`. Every receipt is server-created from the exact participant snapshot;
- the LLM may return only server-assigned `used_evidence_id[]`; it never supplies a trusted filename or chunk identity. Persisted/public sources are reconstructed from selected receipts. A retrieved-but-unused receipt is not a source;
- matched citations must point to actually used receipts from that exact snapshot and preserve safe source filenames;
- no match is legitimate: `retrieval_status=no_match`, `grounding_mode=general_reasoning`, `sources=[]`; the Agent may make normal general arguments but cannot invent evidence;
- retrieval/grounding fields are server-derived, never trusted from the LLM: no selected receipts produces exactly `no_match + general_reasoning + sources=[]`; any selected receipts produces `retrieval_status=matched`, requires at least one valid `used_evidence_id`, and maps sources only from those used IDs. A matched result with no used evidence is a rule failure that consumes the shared repair;
- Wave 2 conservatively labels every valid evidence-using speech `grounding_mode=mixed`; it does not claim `rag_grounded` without a future claim-level grounding proof. The public enum remains forward-compatible, but Mock/real Wave 2 generation cannot emit `rag_grounded`;
- the LLM input contains frozen `AGENT.md`, the exact immutable final-ready prefix of all lower `turn_index` values, the teacher stance/note, versioned rule instruction and selected retrieval receipts. Final-ready means speech, structured result and sources are committed and immutable; it is intentionally separate from TTS readiness and public playback;
- `TurnPromptInput` freezes `predecessor_turn_ids`, `cutoff_turn_index` and `transcript_hash`. The predecessor IDs must exactly equal the full planned prefix. The hash covers every injected predecessor speech, question/rebuttal/position field and receipt identity. A generation completion may commit only if that prefix and hash still pass CAS;
- no hidden web search, other Agent RAG, extra persona or platform-authored factual evidence;
- structured output is validated before persistence. One shared turn repair retry covers technical RAG, provider, JSON/shape, word-count and rule violations; exhaustion sets `turn_generation_failed`, fails the Debate and stops all later work.

### 3.3.1 Frozen internal generation DTO and validator

`StructuredTurnResult` is closed and contains only:

- `speech`, `answered_question_id`, `rebuttal_target_turn_id`, `rebuttal_summary`, `new_argument_summary`, `turn_summary`, `position_summary`;
- `position_update=unchanged|refined|partial_concession|reframed|switched`, nullable `new_stance`, nullable `position_update_reason`;
- `used_evidence_id[]` referencing only receipts assigned in this request;
- `question.type=agent|audience_reflection|none`, nullable `target_participant_id`, nullable `text`.

The server validator, not the prompt, is authoritative:

- round 1 has no answered question or rebuttal, uses `question=none`, and requires argument/turn/current-position summaries;
- every round-2 rebuttal target is a previously final-ready turn from a different participant. When a question is assigned to this participant, `answered_question_id` must match it exactly;
- every non-final round-2 question targets the next planned participant; the final overall turn uses `audience_reflection` with no participant target;
- `mixed` requires at least one used receipt; `general_reasoning` requires none. Fabricated, cross-request or cross-snapshot evidence IDs, and matched-but-unused receipts, fail validation. Wave 2 generation never emits `rag_grounded`;
- assigned `switched` requires a new stance, reason and a real influencing opponent turn or used receipt; open stance never synthesizes an enum stance. Significant changes atomically append position history;
- deterministic English word counting includes the question. Tests cover 79/80/200/201. A short/long result first consumes the single repair; a still-overlong result may be shortened only at complete-sentence boundaries and must rerun every structural/rule check, so required questions or evidence semantics cannot be truncated away;
- direct vote solicitation and manipulative voting language fail validation; civil persuasion based on evidence, accurate response and genuine position change remains allowed.

### 3.4 Preparation and publication

- start creates the full deterministic turn plan, but only the current turn may enter active preparation;
- once the current turn has committed final-ready text/structure/sources, at most the immediately next planned turn may be prepared in the background while current-turn TTS continues;
- an internally prepared next turn, its speech, sources and audio URL are absent from all public DTOs and events;
- `turn.ready` is emitted only when that turn becomes the current planned turn. It contains readiness/retrieval metadata but never speech;
- an unpublished final-ready turn never updates public participant stance/position or public PositionHistory. A prepared successor derives context from the predecessor's internal immutable result. Before a successor can become current or emit `turn.ready`, every predecessor must be public; a stopped, failed, TTS-failed or fenced predecessor invalidates its successor permanently;
- speech, sources and public Avatar states first appear in `playback.started` after the browser has successfully started the platform audio. The current-only media bootstrap protocol is frozen separately in section 4; a prepared-next audio resource is never authorized;
- the cap is exactly current + immediate successor. A prepared successor cannot recursively claim another turn;
- public turns are immutable. Replay never calls RAG, LLM or TTS and never changes transcript, sources or position history.

## 4. Closed browser playback command contract

G0-S accepted a closed WebSocket command transport without adding a new HTTP operation. The frozen 67-operation OpenAPI remains 67 operations, while its existing retained-audio operation gains exact media request/response semantics.

### 4.1 Controller and current-only media bootstrap

- only one authenticated teacher WebSocket connection is the active audio controller for a Debate. `playback.controller.acquire` uses `command_id`, `command_version=1`, `debate_id` and `expected_control_version`; a successful private result returns a new opaque connection epoch;
- acquiring a new controller while the old controller is playing atomically estimates/persists the bounded cursor, parks playback in `paused`, increments control version, persists/broadcasts `playback.paused`, revokes the old epoch, and only then returns the new epoch. If already paused/ready it preserves that state while still incrementing the controller/control version. The old socket receives private `controller.revoked` and immediately performs terminal local cleanup;
- controller disconnect/session revocation similarly parks an actively playing item in a committed `paused` transition before revocation. A replacement controller must issue explicit REST resume to reach `ready`; therefore authority never remains orphaned in `playing` and media.prepare never deadlocks;
- `playback.media.prepare` is allowed only for the active epoch and only for the current `ready` live turn or current ready replay item. It returns a short-lived, connection/session/epoch/turn-scoped same-origin media URL in a private nonpersistent command result;
- a prepared-next turn is never current and therefore receives `404` from the audio operation and can never obtain a media ticket. Paths are not guessed from local storage and no supplier URL is returned;
- the private media URL may be used to prebuffer/start only the current item. After `audio.play()` resolves, the controller sends `playback.started_ack`; the backend commits `ready→playing` and broadcasts only after commit. For an initial live turn it atomically publishes that immutable turn/position delta and emits `playback.started`; for resume it emits `playback.resumed` without republishing; for replay it emits `replay.started` without changing Debate/Turn/Position data;
- physical audio can precede the authoritative `playback.started` event by one local WebSocket round trip. This is the unavoidable non-atomic browser/server boundary and is accepted for the local Demo. It must not be widened by timers or speculative publication;
- `playback.ended_ack` is sent only from the actual platform audio `ended` event. A live item commits `playback.completed` plus next-current preparation or Debate `debate_finished`; a replay item emits `replay.completed` or prepares the next already-public replay item. Duplicate ended acknowledgements are no-ops/private duplicate results;
- REST resume and replay commands transition to `ready` with the saved/replay cursor; they do not claim `playing`. They require the same media-prepare → browser `play()` → started-ack handshake as the initial turn;
- `playback.play_failed` carries `failure_phase=pre_ack|post_ack`, bounded observed `cursor_ms`, `start|resume|replay` and a closed safe client code. Pre-ack rejection leaves `ready` unchanged and private; post-ack media/decode/Range/error atomically parks `playing→ready`, persists cursor/control version, emits a safe recoverable persistent `error`, never advances or republishes, and offers an explicit teacher retry. No provider is called;
- pause/skip/stop remain REST CAS commands. No WebSocket command constructs a turn, chooses the next speaker or advances without backend validation.

### 4.2 Closed schemas and command results

- add `contracts/ws-commands.v1.schema.json` for `playback.controller.acquire`, `playback.media.prepare`, `playback.started_ack`, `playback.ended_ack` and `playback.play_failed`;
- add a separate closed `contracts/ws-command-results.v1.schema.json`. `command.result` and `controller.revoked` are private socket messages keyed by `command_id`; they are not Debate events, are not persisted, have no Debate sequence and are never broadcast;
- malformed, stale, duplicate or unauthorized commands return only a private closed result and produce no state change. They must not reuse the persistent `error` event because doing so would mutate/repeat Debate sequence for a command with no committed Debate transition;
- generated positive/negative fixtures and clean-diff checks reject unknown commands/results, wrong versions, missing epoch/CAS data, prepared turn IDs, supplier fields, external voice IDs, keys, absolute paths and unrestricted properties.
- the WS upgrade requires an exact same-origin `Origin` matching the configured gateway origin; missing/mismatched Origin is rejected. Every command revalidates the live unrevoked Session, current course-teacher membership, Debate path/course scope, active connection epoch and control-version CAS; authentication at upgrade time is not reused as permanent authority;
- private `media_url` and public `playback_url` are relative same-origin `/api/v1/debates/{uuid}/audio/{uuid}` paths only. A private URL has exactly one 32-byte URL-safe ticket query; absolute/scheme-relative/supplier URLs fail schema and runtime validation;
- Uvicorn access logging is disabled for the single local backend process, and application request/log/error fields never record raw query strings or media tickets. The ticket is stored only as a hash, bound to Session/controller epoch/Debate/turn/action, and invalidated on controller revocation, skip, stop, item completion or start-next;
- to keep browser Range reads uninterrupted, a ticket that has successfully started the current item remains valid for that same controller/item until completion or `audio_duration + 60 seconds`, whichever occurs first. Resume/replay obtains a fresh ticket. Observation-only tabs render committed events but never attach/play audio.

### 4.3 Snapshot and sequence

- the server subscribes/buffers committed events before reading the authoritative snapshot. It then reads a transaction-consistent watermark `N`, sends exactly one snapshot with envelope `sequence=N` and required `payload.latest_sequence=N`, then sends only events with sequence `>N`;
- a new Draft with no events uses snapshot sequence `0`; every non-snapshot persistent event remains sequence `>=1`. The client never receives old `<=N` backfill after the current snapshot;
- event gaps stop local advancement and trigger a new snapshot connection. Tests cover zero-event draft, a commit racing connection setup, duplicate delivery, missing sequence and backend restart;
- `turn.ready` contains only turn/slot/round, `audio_ready`, retrieval/grounding state and duration. It never contains speech, sources or a public playback URL. The existing schema/generator must reject `turn.ready.sources`.

Implementation must not replace this contract with a server timer, browser-owned state, a guessable prepared-audio path or an undocumented HTTP route.

## 5. Backend ownership and schema

### 5.1 Migration `0004_wave2_debate_playback`

New tables:

- `debates`: course/topic/rule IDs and immutable snapshot JSON, status, revision, last sequence, cancellation generation, creator/timestamps;
- `debate_participants`: debate/course/group, slot/order, agent/version/snapshot, frozen name/Avatar JSON, frozen requested voice and `effective_voice_kind=platform_profile|mock_sentinel`, nullable effective platform profile ID, fallback flag, initial/public current stance and position summary;
- `debate_turns`: direct debate+participant+snapshot keys, round/turn index, generation/publication states, preparation stage, validated speech/structured JSON, predecessor IDs/hash/cutoff, retrieval/grounding, word count, attempt, audio file/duration, actual TTS voice kind/profile and timestamps;
- `turn_sources`: turn/participant/snapshot/chunk, server-assigned evidence ID, safe filename/rank; only actually used same-snapshot receipts;
- `position_history`: participant/turn, before/after summary, update kind/reason;
- `playback_states`: one per debate, status/mode/current turn/cursor/rate/control version, controller epoch/owner connection, server start timestamp and replay scope/index;
- `debate_events`: event ID, debate, monotonic sequence, type/version, closed payload JSON and timestamp.

Existing-table extensions:

- `courses.current_audio_debate_id` nullable restrictive FK;
- `jobs.debate_id`, `jobs.turn_id`, `jobs.idempotency_key`, `jobs.claim_token`, `jobs.cancellation_generation` nullable fields and debate/turn indexes;
- the existing file-operation journal gains the typed `debate_audio_swap` operation and its old-pointer/source/staging metadata; it does not reuse generic delete-both recovery.

Required database constraints:

- one running Debate per course using a named partial unique index;
- unique `(debate, slot)`, `(debate, order_index)`, `(debate, agent_id)`, `(debate, agent_version)`, `(debate, turn_index)` and `(debate, sequence)`;
- slots `A–E`, order 0–4 and exact `slot=char(65+order_index)` mapping; rounds 1–2; word count 80–200 when generation succeeded; playback rate 0.95–1.25; assigned/open stance shapes; platform-profile/mock-sentinel shape with sentinel requiring a null profile ID;
- required parent unique keys include `debates(id,course_id)`, `groups(id,course_id)`, `agents(id,group_id)`, `agent_versions(id,agent_id,knowledge_snapshot_id)`, `knowledge_snapshots(id,agent_version_id)` and `knowledge_chunks(id,snapshot_id)`;
- participants use composite relationships that prove Debate→Course, Group→Course, Agent→Group and Version→Agent+Snapshot. Turns use `(participant_id,debate_id)` and expose parent unique `(id,participant_id)`; sources simultaneously bind `(turn_id,participant_id)`, `(participant_id,snapshot_id)` and `(chunk_id,snapshot_id)`; position history uses exact composite FK `(turn_id,participant_id)→debate_turns(id,participant_id)`, so B's change cannot attach to A's turn even inside the same Debate;
- Debate jobs have a named partial unique `(operation,idempotency_key)` where the key is not null;
- all new checks/indexes/FKs are named and reflected in a dedicated migration test;
- fresh/repeat and populated `0001→0002→0003→0004→head` preserve all Wave 0/1 rows and the real system VoiceProfile/operation ledger. The populated fixture includes a synthetic encrypted `preview_ready` system profile and failed TTS-preview ledger, fingerprints every field before/after, asserts no `UPDATE/DELETE` on the three voice tables and finishes with empty `foreign_key_check`.

No Wave 3 tables are created by `0004`.

### 5.2 Internal immutable snapshots

The public `DebateParticipant` remains provider-neutral and is expanded only with stable frozen display data required by the classroom: `agent_id`, `agent_name`, `version_label`, `avatar_config`, nullable platform `effective_voice_profile_id`, and `voice_fallback_active`. It never contains a provider/model/external voice ID. Internal participant rows additionally freeze:

- `agent_id`, safe display name and group/course ownership;
- exact immutable `avatar_config_json`;
- selected voice profile and resolved `effective_voice_kind` plus nullable internal platform profile ID at draft resolution;
- a Mock-only server sentinel may be used only when all Voice/TTS selectors are Mock and no ready system fallback ID exists. It is a kind, never a fake `voice_profile_id`, never creates/updates a system VoiceProfile and can never satisfy real-provider readiness;
- before every TTS request the server revalidates the frozen effective profile. A subsequently deleted/unavailable custom profile may switch only to the configured ready system fallback, or the Mock-only kind when all Voice/TTS selectors are Mock. The Turn records the actually used kind/profile without rewriting the participant's initial snapshot. No other provider inference is permitted.

## 6. Ports and worker boundary

### 6.1 Provider-neutral ports

- `LLMProvider.generate_turn(TurnPromptInput) -> StructuredTurnResult`;
- existing `EmbeddingProvider`/local vector search consumes a snapshot/query and returns the closed `SnapshotRetrievalReceipt` contract above;
- existing `TTSProvider.synthesize` receives validated speech plus a server-resolved internal voice mapping;
- `DebateAudioStore` writes typed relative audio paths with staging/fsync/atomic promotion and file references.

Mock defaults are deterministic and local. Mock LLM output is a byte-stable function of the canonical prompt/receipt hash and never of clock, randomness or call order; test-only injections cover technical, JSON, rule and word-count failures. Provider/model/key/external voice ID/raw response never enters a DTO, WS payload, normal log or committed fixture.

### 6.2 Single-process TaskManager

- FastAPI remains one process/one worker; no Redis/Celery;
- start and playback advancement enqueue bounded turn work after the database transaction commits;
- each Debate turn/stage receives a deterministic idempotency key. A single SQL CAS claims `pending→running` and writes a claim token; duplicate enqueue/claim cannot create a second provider call;
- every stage completion must match job ID/state/claim token, Debate `running`, the same cancellation generation, exact Turn stage/attempt and the frozen predecessor prefix/hash. A zero-row CAS discards the result, removes staged audio and cannot persist speech/source/event or schedule work;
- stop increments cancellation generation and marks pending/running Debate jobs `interrupted` with safe code `debate_stopped` in the same transaction before requesting in-process cancellation;
- startup atomically marks both pending and running Debate generation/TTS jobs `interrupted`. If a current/next turn still depends on one, the Debate becomes failed with a safe code; this includes a crash after the start transaction commits but before after-commit enqueue. If text+audio were already committed ready/public, restart never regenerates them;
- playing/paused restart as `ready`, `cursor_ms=0`, same current turn/audio, new control version and no LLM/RAG/TTS call;
- the claim transaction may select only the current turn or `current_index+1`; a database query plus concurrent double-enqueue/ended tests prove no later turn is preparing/ready.

## 7. Playback and audio state

- `startDebate` is idempotent and requires debate revision, the explicitly supplied nullable prior course-audio pointer and cleanup confirmation;
- after idempotency claim, create/update/start revalidate the teacher's course scope in the final transaction. Create/update use one limited join for current published, non-archived Agent→Version→Snapshot and CAS every captured pointer before commit. Update atomically replaces the participant set and increments revision;
- start never upgrades participants. It combines `draft+expected_revision` CAS, exact course audio-pointer CAS and the one-running-per-course unique fence so concurrent starts have exactly one side effect;
- audio swap order is fixed: idempotency claim → independently commit `debate_audio_swap/prepared` journal containing expected old pointer/source/staging/new Debate → atomic rename old audio to staging → persist journal `staged` → one DB transaction CAS-commits Debate running, course pointer, plan/jobs and journal `committed` → delete staging. DB failure restores the old directory; commit success deletes staging. Startup recovery decides restore-versus-delete only from committed DB pointer/journal state and never runs generic delete-both recovery;
- `PlaybackState` is authoritative. All pause/resume/skip/stop/replay commands use `expected_control_version`; stale commands change nothing;
- server cursor uses persisted cursor plus elapsed monotonic time while playing; pause/resume persist the bounded cursor;
- skip preserves turn text/audio/sources and advances only through a backend transaction;
- stop is irreversible, cancels generation and never plays a later turn;
- full and single-turn replay are allowed only when referenced public audio is retained; stopped Debates do not replay in Wave 2;
- replay uses the same public transcript/audio and changes no Debate status or generation records;
- backend restart from playing/paused starts the same turn from zero, matching the Project decision;
- each course retains audio only for its current started Debate. Starting the next Debate first terminates any old replay, increments its control version and broadcasts the committed transition; successful confirmed swap makes previous audio URLs return `410` while retaining text/sources;
- current/replay audio is a same-origin teacher-only URL with `Cache-Control: no-store`, exact `Range`/`If-Range`, `200/206/416`, bounded seeking and cleanup `410`. The browser never receives a supplier URL;
- terminal cleanup for stop/fail/controller revocation/start-next is `pause → removeAttribute(src) → load → clear queue/cursor → all Avatars idle`. Next-turn preparation failure immediately fails the Debate, stops current audio/Avatar and invalidates any staged successor;
- bytes already buffered by a browser cannot be remotely erased. The product contract promises event-driven local cleanup and server denial of new reads, not impossible revocation of bytes already delivered.

## 8. Public API and event surface

Implement exactly the fourteen already-frozen Debate operations owned by M10–M12:

- `listDebates`, `createDebate`, `getDebate`, `updateDebateDraft`, `startDebate`;
- `pauseDebate`, `resumeDebate`, `skipTurnPlayback`, `stopDebate`;
- `replayDebate`, `replayDebateTurn`;
- `connectDebateEvents`, `getDebateTranscript`, `streamRetainedTurnAudio`.

Expected strict route surface after Wave 2: `54 implemented / 13 later-wave placeholders`, with the frozen 67 operations unchanged. Hidden media implementation details do not become extra OpenAPI operations.

Public `DebateDetail.public_turns` contains public turns only. Snapshot/events remain closed and server-authored. Interaction/insight/report fields remain the frozen inactive values (`closed/not_started/not_started`) and no Wave 3 action exists.

Before M10 implementation, the reviewed OpenAPI defect patch must:

- add `DebateDraftUpdateRequest` with required `expected_revision` for PATCH;
- make `expected_current_audio_debate_id` required on start;
- add the exact teacher `403`, outside-course/not-found `404`, create idempotency `409`, and audio `206/416` responses identified by G0-S;
- expand only provider-neutral frozen participant display fields needed by M12;
- copy parent→product byte-for-byte, update SHA/generated Client/response and negative fixtures, and move exactly the 14 operations above from placeholders so strict comparison is `54/13`.

## 9. Frontend

New pages:

- `/teacher/debates`: draft/running/debate_finished/completed/failed/stopped summaries and create action;
- `/teacher/debates/new`: V2 topic/participant/stance form, selected click-order A–E list and fixed-two-round explanation;
- `/teacher/debates/{debate_id}/control`: V2 classroom stage/control surface;
- no separate history product page in Wave 2; transcript/replay live on the control page.

Control page requirements:

- render names/version/immutable Avatar config only from frozen provider-neutral DebateParticipant display fields; do not join mutable current Agent state and expose no provider metadata;
- render 2–5 local head canvases, current speaker with gold/high-contrast motion and all others `listening+attentive`; visible labels never say speaking/support/listening/attentive;
- show full speech and sources only after `playback.started`;
- start/pause/resume/skip/stop and replay controls expose busy/disabled/failure reasons and are keyboard reachable;
- refresh begins with GET authoritative snapshot, then WebSocket snapshot/sequence catch-up;
- one HTML audio element follows backend state and sends closed WS acknowledgements; pause/resume/skip never advances locally;
- Avatar/view mapping is pure: preparing/ready=current thinking; playing=current speaking and all others listening+attentive; paused=current non-speaking and others attentive; terminal=all idle; replay uses the replay current item. Disconnect adds a neutral connection overlay, pauses local audio and waits for backend snapshot without local advancement;
- locale changes static copy only and do not recreate Session/API/WS/audio, reset selected participants or duplicate controls;
- after the final live turn, display a neutral debate-complete state. Do not show QR, vote, barrage, Maya report or translation controls.

## 10. Error and retry semantics

- participant/rule validation uses frozen 422 codes; cross-course/not-visible resources use 404;
- draft state/CAS/start/audio-pointer/control-version conflicts use frozen 409 codes;
- create/start idempotency uses the existing actor/operation/key/hash ledger; same hash replays, different hash conflicts. A claim that performs an internal rollback invalidates all pre-claim reads, so final authority is always re-read in the write transaction;
- semantic RAG no-match does not consume the one technical repair retry;
- a Turn has attempt `1|2`. Strict→relaxed semantic search is within one attempt; a technical RAG error, LLM/provider error, JSON/shape, word or rule failure may enter attempt 2, and no third attempt/provider call exists. Exhaustion atomically fails the Debate and prevents later publication;
- Mock TTS is expected to succeed. An unexpected TTS exception follows the same safe turn failure path; it does not invent silence/browser speech/text-only success;
- WebSocket disconnect uses snapshot+sequence recovery; malformed command/event cannot mutate state;
- framework/provider exceptions expose only stable codes and request IDs.

## 11. G1 ownership plan

After G0-S PASS only:

- Luna M10 owns `backend/app/modules/debates/setup/**`, debate schemas/repositories, `0004` core domain migration/tests and teacher draft/list pages;
- Luna M11 owns `backend/app/modules/debates/generation/**`, LLM port/Mock, snapshot retrieval/prompt/rule validation/position tests;
- Luna M12 owns `backend/app/modules/debates/playback/**`, audio store, TaskManager/WS commands/events/recovery and classroom stage/control UI;
- a contract Luna owns OpenAPI route placeholders, WS event/command generation, generated Client, CI and migration/route fixtures after routes stabilize;
- main alone integrates `main.py`, shared models/config/platform API, resolves ownership overlaps, runs G1.5/G3 and updates Project/V2 workbook;
- multiple Sol High auditors independently review M10 data/idempotency, M11 prompt/RAG integrity, M12 state/audio/WS recovery and the final contract/frontend surface.

All workers are told they are not alone, may not revert others and may not expand to M13–M15.

## 12. Deterministic acceptance

Required before G2:

- fresh/repeat/populated `0004` migration with full named schema reflection, empty foreign-key check, Wave 0/1 fingerprint preservation and no voice-table mutation;
- exact two-, three- and five-participant turn plans; default A1/B1/A2/B2;
- create/update expected revision, participant order, duplicate/current/archived/course/rule validation, concurrent publish pointer CAS and immutable snapshot proof;
- one-running-per-course, same/different-key create/start concurrency and typed audio-swap crash boundaries at prepared-journal commit, rename-before-staged-journal, staged, DB commit and cleanup;
- RAG matched/no-match/matched-but-unused/unused/forged/cross-snapshot receipts and exact server-derived retrieval/grounding matrix; exact final-ready predecessor IDs/hash/cutoff; no early public position leak; 79/80/200/201 and full rule/question/position matrix; one shared repair retry;
- current+one-next preparation cap and prepared speech/source/audio non-disclosure in GET/WS/browser;
- controller/media/start/failed/ended WS command plus private-result schema positive/negative/clean-diff, current-only media, stale/duplicate command CAS and multi-tab loser cleanup;
- zero-event/racing/gap/restart snapshot sequence tests; `turn.ready.sources` negative fixture;
- start/pause/resume/play-rejection/skip/stop/replay matrices, audio authorization/retention/`Range`/`If-Range`/`200/206/416/410`, terminal HTMLAudio/Avatar cleanup and no generation on replay;
- stop-during-provider and process restart pending/running generation -> failed/fenced; restart ready/playing/paused -> same turn ready/cursor zero/no provider call;
- teacher-only API/WS/audio, students 403, outside course 404; browser bundle/DTO has no supplier fields;
- full existing Wave 0/1 regression, Prettier/Ruff/mypy/ESLint/TypeScript/Vitest/build, OpenAPI/WS/boundary/Compose.

G3 Mock runtime uses an isolated data root and must show:

1. published Bowen/KaiKai Agents with placeholder English Markdown and Mock-ready voices;
2. topic `Should the United States ban TikTok's recommendation algorithm?`;
3. A Bowen assigned support, B KaiKai assigned oppose, exactly A1/B1/A2/B2;
4. matched citations and an explicit no-match path without fabricated sources;
5. complete prior-turn context, second-round response/question/update and B2 class reflection;
6. start/pause/resume/browser play rejection/skip, replay turn/all, refresh and backend restart without new RAG/LLM/TTS on replay/recovery;
7. prepared next speech absent until its `playback.started`;
8. 1280×720 and 360px V2 browser checks, real local Avatar canvases, safe platform audio and no console/overflow failures;
9. normal Demo data restored afterward; isolated data moved recoverably to Trash.

## 13. Real-service status and cost boundary

- `LLM_PROVIDER=mock`, `EMBEDDING_PROVIDER=mock`, `TTS_PROVIDER=mock`, `VOICE_PROVIDER=mock` and `TRANSLATION_PROVIDER=mock` throughout Wave 2 implementation/G1.5/G3. Startup fails closed if any selector is non-Mock; tests fail if a real adapter is constructed;
- current real counts carried forward: Voice enroll 1 successful, TTS 2 failed, LLM 0, Embedding 0, Translation 0;
- no additional Voice enrollment is allowed; supplier-side cloned voice remains;
- if a later reviewed real LLM G3 is run, only the default four formal turns may call it, with at most one retry per failed external operation and total first-run spend under CNY 100;
- no formal TikTok materials exist: `RAG_PIPELINE_PASS / FORMAL_TIKTOK_RAG_CONTENT_ACCEPTANCE_PENDING` remains mandatory.

## 14. Stop conditions

Stop the affected Gate for:

- any need to alter user-visible debate rules, permissions, frozen version/snapshot behavior, playback semantics, audio retention or real-provider policy;
- unresolved playback acknowledgement transport;
- migration risk to the normal `0003` database or real system VoiceProfile ledger;
- prepared speech/source/audio leakage;
- a second Voice enrollment or any real TTS call;
- OpenAPI/WS/Project conflict not fixed as a reviewed contract defect;
- source-unknown concurrent edits, secret leakage, public push/deployment or any M13–M15/Wave 3/4 work.

Other independent Mock work may continue while a bounded sub-Gate is stopped.

## 15. G0-S audit record

Final design sign-off: `2026-08-27 06:48 Asia/Shanghai`.

- `/root/wave2_g0s_data` — `PASS`: exact OpenAPI permission/CAS/idempotency responses, executable SQLite composite relationships, pending/running Job fencing, typed audio-swap journal and Range/If-Range headers;
- `/root/wave2_g0s_generation` — `PASS`: immutable final-ready predecessor prefix, typed retrieval receipts/used-only sources, server-derived retrieval/grounding matrix, two-round structured validator, shared attempt `1|2`, deterministic all-Mock and stale-result fencing;
- `/root/wave2_g0s_playback` — `PASS`: single controller/current-only media bootstrap, pre/post-ack failure recovery, exact Origin/continued authorization, snapshot sequence, private command results, same-origin URL contracts, terminal cleanup and Voice/Debate playback-resource separation;
- main-agent deterministic contract checks — `PASS`: parent/product byte equality and SHA, Redocly, 67-operation response contract, generated Client, WS events `29/14`, commands `5/7`, private results `5/6`, generator clean-diff, route comparator `13` negatives, repository boundary and Prettier.

This is a design/contract PASS only. No M10/M11/M12 business implementation, migration `0004`, Debate route, provider call or classroom UI is signed by this record. G1/G1.5/G2/G3 remain mandatory.
