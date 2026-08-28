# Wave 2 Gate Packet — M10 Debate Setup + M11 Turn Generation + M12 Playback

Status: historical `.5` baseline `G0-S/G3 PASS`; active `.6` manual-acceptance delta `G0-S/G1/G1.5/G2 PASS / M07+M12 BROWSER PASS / M08 REAL TTS FAILED-DEFERRED / OVERALL MANUAL G3 NOT PASS`
Authorized scope: `2026-08-27 Asia/Shanghai`
Modules: `M10 debate creation/rules`, `M11 RAG/LLM turn generation`, `M12 teacher stage/playback/recovery`
Dependencies: `Wave 0 G3 PASS`, `Wave 1A G3 PASS`, `Wave 1B Mock G3 PASS`, `Wave 1C G3 PASS`, historical Wave 2 baseline `g0-2026-08-27.5`; active manual-acceptance delta `g0-2026-08-28.6-manual-acceptance-delta` has completed concentrated Sol High G2 review
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
- historical `.5` baseline only: no real TTS call. The active `.6` delta in section 17 superseded this with exactly one reviewed attempt=3 call; that call failed and still did not activate `FALLBACK_VOICE_PROFILE_ID`;
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

## 16. G1–G3 implementation and runtime record

Final main-agent sign-off: `2026-08-28 01:08 Asia/Shanghai`.

- `M10`, `M11` and `M12` each completed `G1 → G1.5 → independent G2`; the data/setup, generation/RAG and playback/UI auditors returned final `PASS`. The implementation checkpoint before browser hardening is `21252f3 feat: complete audited wave 2 candidate`;
- the final deterministic tree passes backend `161/161`, frontend `12 files / 64 tests`, Ruff format/check, mypy, ESLint, TypeScript, Prettier and Next production build. Fresh/repeat/populated `0004` migration preserves Wave 0/1/Voice fingerprints with empty foreign-key checks;
- frozen OpenAPI remains `58 paths / 67 operations` with exact `54 implemented / 13 later-wave placeholders`; Redocly, generated Client, response contract, WS events `29/14`, commands `5/7`, private results `5/6`, WS clean-diff, route positive plus 13 negative cases, repository/secret boundary and Compose configuration pass;
- isolated Docker G3 runs the exact two-participant, two-round order `A1/B1/A2/B2`. Bowen V1.0 produces matched same-snapshot receipts and visible `bowen-evidence.md`; KaiKai V1.1 follows the explicit no-match/general-reasoning path with zero receipts and no fabricated source. Round 2 preserves the complete predecessor prefix; A asks the next Agent and B answers then asks the class reflection question;
- teacher start, pause, resume, immediate skip, stop, refresh, backend restart, full replay and single-turn replay were exercised through the real local UI/API. Replay/recovery retain four completed generation jobs and do not call RAG/LLM/TTS again. Prepared speech and sources remain absent before `playback.started`;
- G3 exposed and closed six material runtime defects before sign-off: default setup-controller render recursion; resume/action leakage across turns and missing public-predecessor fence; full replay stopping after item one; delayed media/control/socket callbacks crossing turn generations; WebSocket lifetime Sessions exhausting SQLite's connection pool; and Start/terminal/replay controller CAS races. Each has a deterministic regression and independent Sol review;
- the WebSocket now uses short database Sessions for handshake, snapshot, each command and disconnect. Snapshot DTO plus watermark remain one transaction; a constrained two-connection test keeps five sockets open while GET and two-connection create-idempotency replay still succeed and checked-out connections return to baseline;
- Docker Desktop operational rule: never open a running container's bind-mounted SQLite/WAL file directly from the macOS host. Online checks use the platform API or a connection inside the container; host-side SQLite inspection is allowed only after the backend is stopped. This prevents host/container WAL inode divergence;
- final 1280×720 and 360×800 browser checks have no horizontal overflow, all six controls remain 44px high, Avatar speaking/listening/idle states render, and browser warning/error logs are empty. Backend/frontend/gateway and FFmpeg 5.1.9 are healthy;
- all Wave 2 selectors and runtime calls remained Mock. No Voice enrollment, TTS, LLM, Embedding or Translation call was added. `RAG_PIPELINE_PASS / FORMAL_TIKTOK_RAG_CONTENT_ACCEPTANCE_PENDING` remains the exact content status;
- this record signs only `WAVE_2_G3_PASS` and the Mock two-person/two-round classroom candidate. `M13–M15`, voting, barrage, Maya report, translation/history product work, real LLM/Embedding/TTS and Wave 3/4 remain unimplemented and locked.

## 17. User manual-acceptance repair delta (2026-08-28)

Status: `G0-S/G1/G1.5/G2 PASS / MANUAL G3 NOT PASS`.

The historical G3 record above remains evidence for the old Mock/auto-advance contract. It does not sign this delta. User manual acceptance exposed a ready-but-transparent Avatar, Mock tone instead of human speech, and an unwanted auto-continuous live timeline. Only the following M07/M08/M12 increment is authorized; Wave 3/4 remains locked.

### 17.1 Visible Avatar

- preserve material cardinality: a single-material mesh remains one `Material`; a multi-material mesh remains `Material[]`;
- GLB/Draco HTTP 200 and `onReady` are insufficient. Acceptance requires visible, non-transparent checked-in GLB pixels at student preview and teacher 2–5 card sizes;
- tests must fail on the old single-material-to-array bug and real-browser G3 must show visible idle/listening/speaking geometry. Static fallback remains failure for the normal path.

### 17.2 One-call real TTS diagnostic Gate

- enrollment/list/exists/delete calls: `0`; new TTS calls: at most `1`; automatic retry: `0`; LLM/Embedding/Translation calls: `0`;
- use only the existing unique `scope=system/status=preview_ready` VoiceProfile and its server-only decrypted mapping. Never print or expose Key, Authorization, external voice ID, supplier URL/response, Base64, absolute/private path or source filename;
- introduce a new operator-only durable `tts_preview` diagnostic attempt instead of resetting/deleting the two failed historical ledger rows. Before the external request, persist a Gate-specific request hash, `prepared→dispatched`, and counters. The operation ID is deterministic from the fixed Gate identity plus internal profile/request hash, so the existing primary-key uniqueness is the database-level claim across processes; creation is a single atomic insert/commit and only the winning committed row may dispatch. A filesystem lock is only an optimization, never the correctness boundary. A loser must replay the committed result or return outcome_unknown while making zero provider calls;
- classify failures only as stable safe codes: `tts_http_rejected`, `tts_response_invalid`, `tts_result_url_rejected`, `tts_result_dns_failed`, `tts_result_download_failed`, `tts_audio_invalid`, `tts_timeout`, or `tts_outcome_unknown`;
- success requires nonempty bytes, complete decode, non-silence, reasonable duration, no obvious full-duration clipping, technical validation, temporary-file cleanup, and a same-origin authenticated platform preview. Only then may the profile transition `preview_ready→ready`;
- timeout/ambiguous billing becomes durable `outcome_unknown` and forbids another call. Failure leaves the profile `preview_ready` and does not activate fallback;
- the diagnostic itself must not edit `.env`. After profile-ready plus platform-preview acceptance, a separate local configuration step may set the internal UUID as `FALLBACK_VOICE_PROFILE_ID` and restart;
- startup may allow only `TTS_PROVIDER=dashscope` while LLM/Embedding/Voice/Translation remain Mock. PlaybackService and AudioStore must receive the reviewed factory result instead of hard-coded `MockTTSProvider`. Public contracts remain provider-neutral;
- one technical preview PASS is not four-turn real classroom TTS PASS. Real classroom pacing remains a later bounded acceptance after this diagnostic.
- the host `/opt/homebrew` parent is currently world-writable without sticky/ACL, so the charged attempt must not execute through host Homebrew Python/uv/FFmpeg. Run only inside the rebuilt, locked backend Docker image with container Python while invoking Docker through the root-owned `/usr/local/bin/docker` symlink. If that isolated path cannot complete the Gate, stop and require host permission remediation; do not fall back to host tools.

### 17.3 Teacher-gated live advancement

Add OpenAPI operation 68:

`POST /debates/{debate_id}/next`, operation ID `advanceDebatePlayback`, request `AdvancePlaybackRequest`, response `PlaybackState`, exact `401/403/404/409` errors. The closed request contains required `expected_control_version` and `expected_current_turn_id`. A single transaction CAS provides at-most-once advancement; no separate idempotency ledger is added. Strict surface becomes `59 paths / 68 operations`, `55 implemented / 13 later-wave placeholders`.

`PlaybackState.status` adds `waiting_next`; every response adds required derived boolean `next_turn_ready`. It may be true only for `mode=live/status=waiting_next`. It never carries successor text, sources, audio/media URL or supplier data.

Live transitions are frozen as:

1. Start arms only the first turn: `preparing→ready→media.prepare→audio.play→started_ack→playing`;
2. intermediate native `ended_ack` or Skip completes the public current turn, revokes media, increments control version and enters `waiting_next`; `current_turn_id` remains the just-completed public turn and no successor content is published;
3. hidden preparation may continue within the existing current-plus-one cap. If the successor was not ready when the first `playback.waiting_next` event committed, that event carries `next_turn_ready=false`. When the successor later commits final/TTS/audio ready under the same fence, the server persists a new sequenced `playback.waiting_next` readiness-change event for the same completed turn/control version with `next_turn_ready=true`; it still carries no successor ID, speech, sources or media. `turn.ready` does not carry `next_turn_ready` and is not relied on to unlock the button;
4. Next succeeds only when the caller is still course teacher, Debate is running, playback is live waiting-next, both expected values match, the current turn is public with a complete public prefix, the deterministic adjacent successor exists and is final/TTS/audio ready, and no cancellation fence invalidated it;
5. successful Next atomically moves `current_turn_id` to the adjacent successor, enters `ready`, increments control version, then uses `playback_action=next` in the existing media/started/play-failed handshake. The successor becomes public only at committed `playback.started`;
6. early/stale/duplicate/wrong-turn Next returns a stable 409 with zero side effects. It cannot arm future autoplay;
7. final ended/Skip enters completed/debate_finished with no Next;
8. pause/resume affect only the current playing/paused item; stop also accepts waiting-next. Refresh/WS reconnect/backend restart preserve waiting-next and never auto-advance. If Next already committed to ready before refresh, that authorization remains committed;
9. full replay keeps automatic continuous playback of already-public items; single replay is unchanged. `waiting_next` is live-only.

Add closed persistent WS event `playback.waiting_next` with only `completed_turn_id`, `control_version`, and `next_turn_ready`. Do not add a WS inbound Next command. Add `next` to media prepare/started/play-failed `playback_action`. `media.prepare` rejects waiting-next and every unadvanced successor.

Frontend adds one 44px bilingual Next button, enabled only for live `waiting_next && next_turn_ready && controllerReady && !busy`. Native ended sends only ended-ack and never prepares the successor locally. The committed waiting state retains the completed turn, makes all Avatars non-speaking, shows neutral waiting copy and exposes no successor.

### 17.4 Migration and deterministic checks

- add immutable migration `0005_wave2_manual_advance`; SQLite rebuilds only `playback_states` to add `waiting_next` to the status check and a live-only waiting constraint. `next_turn_ready` remains a query-derived field, not a column;
- fresh/repeat/populated `0004→0005`, downgrade/re-upgrade, named constraint/index reflection, full Wave/Voice fingerprints and empty FK check are mandatory; VoiceProfile and historical TTS ledger receive zero migration updates/deletes;
- parent/product OpenAPI remain byte-identical; update SHA, generated client, route/response fixtures, WS event/command schemas and positive/negative clean-diff generators;
- tests cover ended/skip waiting, early/stale/duplicate/multitab Next, hidden prepared successor, Next→exactly one media prepare, final completion, stop/refresh/gap/restart, delayed callbacks, replay unchanged, Avatar pixels and TTS one-call/no-retry/redaction/cleanup;
- full backend/frontend regression, Docker rebuild and real-browser G3 are mandatory.

### 17.5 Stop conditions and current gate state

Stop for a second enrollment, more than one new diagnostic TTS call, ambiguous supplier outcome, missing existing mapping, supplier/prepared-content leakage, migration data loss, 3D still transparent, automatic live successor publication/playback, or any Wave 3/4 expansion.

The earlier lower-effort review was problem-finding only and has no Gate-signing authority. Independent `gpt-5.6-sol high` reviewed the final stable design and returned `PASS / G1 AUTHORIZED` with zero P0/P1. After Luna implementation and deterministic checks, a concentrated independent Sol High G2 audit returned `PASS` with zero P0/P1/P2 and authorized exactly one locked-Docker attempt=3 call. That real call failed safely, so G2 remains code PASS but manual G3 remains unsigned.

## 18. `.6` implementation, audit, Docker and real-TTS record

Main-agent status at `2026-08-28 09:05 Asia/Shanghai`: `G1/G1.5/G2 PASS / M07+M12 BROWSER PASS / M08 REAL TTS FAILED-DEFERRED / OVERALL MANUAL G3 NOT PASS`.

- visible Avatar: the renderer preserves `Material` versus `Material[]`, tests fail on the old transparent-canvas regression, and the authenticated 1280×720 Docker browser now shows both local GLB faces as `data-avatar-status=ready` canvases. During live turns the current participant is `speaking` and the other is `listening`; both return to `idle` in `waiting_next`. Classroom projection-distance readability remains a separate user-site check;
- teacher published-version inspection: the authenticated browser reproduced that a selected V1.0 rendered an `Inspect` link back to the exact current snapshot URL, so clicking looked broken. The selected snapshot is now shown as a non-interactive bilingual `Viewing/正在查看` state with `aria-current=page`; only unselected immutable historical snapshots retain links. Focused and full frontend checks plus an independent Sol High review pass, and the rebuilt 1280×720 browser page shows both duplicated selected rows consistently without a no-op link;
- teacher advancement: backend-authoritative `waiting_next`, derived `next_turn_ready`, adjacent-successor CAS, public-prefix/audio/fence revalidation, sequenced readiness change and action=`next` are implemented. The frontend native-ended path only acknowledges completion; it never prepares or starts the successor. Multitab, delayed HTTP/WS, stale snapshot, stop/final, restart and replay regressions pass;
- concurrency and migration: the cross-process SQLite claim starts with `BEGIN IMMEDIATE` in a fresh Session and revalidates every Next invariant in the same writer transaction. `0005_wave2_manual_advance` passes fresh/repeat/populated, 0004→0005, downgrade/re-upgrade, named schema/index, full Wave/Voice/TTS-ledger fingerprints and empty foreign-key checks;
- TTS safety: canonical Beijing result URL handling, DNS/TLS pinning, complete-WAV validation, deterministic UUID5 durable claim, one-call/no-retry counters, operator-only preview, teacher-only same-origin media and provider composition all passed the focused and concentrated Sol High audits;
- full deterministic checks pass: backend `204/204`; frontend `13 files / 72 tests`; Ruff check/format; mypy `78` sources; ESLint; TypeScript; Prettier; Next production build; OpenAPI `59 paths / 68 operations`, exact `55 implemented / 13 placeholders`; 68-response contract; route positive + 13 negatives; WS events `30/17`, commands `6/7`, private results `5/6`; clean generation; repository/secret boundary; Compose;
- rebuilt backend/frontend/gateway containers are healthy, FFmpeg remains in the locked backend image, and container Alembic is `0005_wave2_manual_advance (head)`;
- exactly one attempt=3 TTS call ran inside the locked backend Docker. It returned durable `failed` with safe code `tts_audio_invalid`, `request_count=1`, `charged_count=1`, no preview ID/bytes, and left the system profile `preview_ready`. Active preview/file counts are zero. There was no retry, enrollment, list/exists/delete, `.env` edit or fallback activation;
- cumulative real calls are Voice enrollment `1` successful, TTS `3` failed, LLM `0`, Embedding `0`, Translation `0`. The supplier-side cloned voice still exists;
- `RAG_PIPELINE_PASS / FORMAL_TIKTOK_RAG_CONTENT_ACCEPTANCE_PENDING` remains exact;
- M07/M12 browser acceptance is signed for this delta. The real-English TTS Gate remains failed/deferred, so the combined `.6` manual G3 and any complete-Demo claim remain unsigned. No Wave 3/4 implementation was entered.

### 18.1 Authenticated browser continuation

- the user explicitly deferred further TTS troubleshooting. No fourth TTS, enrollment, list/exists/delete, `.env` or fallback change is permitted or performed;
- authenticated 1280×720 Docker browser verification now proves the teacher V1.0 selection feedback and two visibly rendered ready Avatar canvases. Both teacher Agent and classroom pages have zero captured warning/error logs and no horizontal overflow;
- the user explicitly authorized the start-time cleanup for normal-data draft `9c9f1560-0cb5-4ddc-865c-faf51bf3ba31`. The application removed only the prior current-debate Mock replay-audio directory, retained prior text/source/debate rows, made this debate the course current-audio debate and created four new decodable one-second Mock WAV files;
- authenticated browser acceptance at 1280×720 completed the exact A1/B1/A2/B2 plan. Start exposed only A1; each of A1, B1 and A2 ended in durable `waiting_next` with the completed speech still visible, an enabled teacher Next button and no successor speech/source leak. A page refresh at A1 preserved the same one-public-turn boundary and Next readiness. Each teacher Next exposed exactly the deterministic adjacent successor;
- A2 pause/resume preserved the same turn and returned to `waiting_next`; live state evidence showed Bowen `speaking`/Kaikai `listening` for A2 and Bowen `listening`/Kaikai `speaking` for B2. B2 ended naturally with four public turns, debate status `debate_finished`, playback terminal, Next disabled and full replay enabled. Full replay started from stored public media and returned to the same terminal state; viewport width and document scroll width both remained 1280;
- browser evidence therefore signs the `.6` M07 visible-Avatar and M12 teacher-paced-Next portions. Skip/stop/backend-restart/single-turn replay remain covered by the deterministic and historical authenticated G3 suites rather than being repeated destructively in this one normal-data run. Projection-distance readability remains for the user to inspect in the real classroom;
- local checkpoint `41343a3 fix: clarify selected agent snapshot` contains the reviewed M09 feedback repair. It is local only; no push, PR or deployment occurred.

### 18.2 Replay-retention follow-up

- after the preceding run, the user started a later classroom debate, so the course `current_audio_debate_id` moved away from `9c9f1560-0cb5-4ddc-865c-faf51bf3ba31` and that debate's Mock WAV directory was correctly removed. Reopening the old debate exposed a real UI defect: all four single-turn replay buttons and full replay remained enabled until the server returned `audio_not_retained`;
- replay eligibility now has one server-authoritative chain: the course pointer must equal the debate; the target turn must be public/final-ready and reference an active `debate_audio` StoredFile; the StoredFile path must exactly equal the server-generated course/debate/turn WAV path; size and SHA-256 must match; the path and every component must not be a symlink; the bytes must decode as a valid WAV. A missing process cache is rehydrated only after all durable facts pass;
- full replay validates every public turn atomically; single-turn replay validates only its requested public turn. Pointer mismatch is rejected before playback state/control-version mutation. Media authorization repeats the current-pointer and durable-file check;
- the final byte response now reads and validates one immutable byte snapshot and derives full/Range/ETag output from that same snapshot. A deterministic regression replaces the canonical path with same-size different bytes immediately after validation and proves that only the already-validated snapshot can be returned;
- successful next-debate audio cleanup and journal recovery mark only the old debate's `debate_audio` StoredFile rows `deleted`; historical turn, text, sources and `audio_file_id` audit fields remain. A one-time local reconciliation changed 12 already-removed legacy audio rows across three old debates from `active` to `deleted` only after confirming each old directory was absent; the two files belonging to the course's current debate remained `active`;
- the control page now treats current pointer equality as a replay precondition. Old, null or unknown pointers disable full and per-turn replay without sending API requests and display the existing bilingual `audio_not_retained` explanation. A successful Start updates the local pointer even if the HTTP response loses a race to authoritative WebSocket events;
- independent Sol High first returned `CHANGES_REQUIRED` for persistent/cache truth and a validated-read TOCTOU; after the focused repairs its final result is `PASS` with zero P0/P1/P2. Final checks pass: backend `218/218`, frontend `13 files / 77 tests`, focused playback `61/61 + 30/30`, Ruff check/format, mypy `78` sources, ESLint, TypeScript, Prettier, Next build, Redocly, generated-client check, route positive + 13 negatives, repository boundary and Compose;
- rebuilt backend/frontend/gateway containers are healthy and Alembic remains `0005_wave2_manual_advance (head)`. Authenticated 1280×720 Docker browser verification shows the old debate's four single-turn buttons and full-replay button disabled, one clear Chinese retention notice, no horizontal overflow and still-visible ready Avatar canvases. No new debate, TTS, Voice, LLM, Embedding or Translation call was made by this repair.

### 18.3 English-topic early-validation follow-up

Status: `G0-S REPAIR FROZEN / G1 + G1.5 + G2 PASS / DOCKER + BROWSER PASS`.

- authenticated manual testing created draft `da32661a-2a59-45bd-9013-1e79f0a37183` with the Chinese topic `如何与人建立亲密关系`. The first two round-one turns completed, but Mock round-two A embedded the topic in its required question and the authoritative English-speech validator rejected the CJK text twice, leaving turn index 2 as `turn_generation_failed` and the Debate failed. This is a delayed input-contract defect, not a missing-LLM or random generation failure;
- Project, this Gate and the teacher form already say the topic is English. The repaired contract therefore rejects an invalid topic at create/update, retains the English output validator as defence in depth, and rechecks legacy drafts at start. The system does not translate topics or accept arbitrary-language topics while hoping the provider returns English;
- the deterministic boundary requires trim-nonempty text with at least one Latin letter. It accepts Unicode Latin diacritics, numbers, punctuation and ordinary Unicode `Zs` spaces, including NFD combining marks only when attached to a validated Latin base; it rejects non-Latin letters, C0/C1/format controls, symbols, isolated marks and non-space separators. There is still no product-level maximum length;
- create validates before its idempotency claim; update validates before revision CAS or participant replacement; start validates a historical draft before start idempotency, prior-audio staging/cleanup, turn-plan/Job creation, Provider work or state changes, and repeats the check inside the start writer lock. Failures return `422 topic_language_invalid` with only `{field: topic, required_language: en, allowed_script: Latin}` and never echo the topic;
- failed/completed/history rows are not migrated or rewritten. An old invalid draft remains editable and may be patched to a valid English topic, after which the ordinary start path applies;
- the teacher form mirrors the server rule for immediate bilingual feedback, preserves the input, uses `aria-invalid/aria-describedby`, and sends no create request for invalid text. Server validation remains authoritative when a client bypasses the form;
- G1.5 passes: backend full `247/247`; frontend `13 files / 107 tests`; focused setup/playback, full A1/B1/A2/B2 accented-topic accident path and topic/a11y negatives; deterministic Node 24.14.0 `Letter && Script_Extensions=Latin` table generation/clean-diff, including Node-new/Python-old Unicode reachability; Ruff CI scope and mypy 80; ESLint, TypeScript, root Prettier and Next build; byte-identical parent/product OpenAPI, SHA, Redocly, generated client, 68 responses, route positive + 13 negatives, exported FastAPI semantic comparison and repository boundary;
- Sol High required two rounds of repair for Unicode cross-runtime drift and the missing full accident-path test. After the generated shared table, U+A7CB reachability, Glagolitic negatives and complete accented A1/B1/A2/B2 test were added, final G2 is `PASS` with `P0=0 / P1=0 / P2=0`;
- backend/frontend images rebuilt successfully, all three containers are healthy and Alembic remains `0005_wave2_manual_advance (head)`. Authenticated 1280×720 browser testing kept `如何与人建立亲密关系` in the textarea, showed the Chinese inline error with `aria-invalid=true`/`aria-describedby`, produced zero Debate rows and no navigation. The accepted NFD/precomposed topic `Should Māori and Café/Ç perspectives shape platform policy?` created draft `15fb9eb2-6c19-49ce-bf44-66eef421e3e4` with zero turns and was not started; page width remained 1280/1280 and console warn/error was empty;
- no current or historical Debate was modified by the repair, no migration was added, and no TTS, Voice, LLM, Embedding or Translation Provider was called. M08 remains `FAILED-DEFERRED`; Wave 3/4 remain locked.
