# Wave 3 Classroom Interaction, Maya Report, History and Translation Gate Packet

Gate ID: `g0-2026-08-29.3-wave3`

Manual-feedback delta: `g0-2026-08-30.1-wave3-manual-feedback-delta`

Final disconnect/RAG delta: `g0-2026-08-30.2-wave3-disconnect-rag-final-delta`

Pre-Wave-4 UX/state delta: `g0-2026-08-30.3-wave3-pre-wave4-ux-state-delta`

Status: `WAVE_3_G3_PASS / PRE-WAVE-4 UX-STATE DELTA G2 PASS P0=0 P1=0 / MAIN G3 PASS / READY_FOR_WAVE_4 / WAVE_4 NOT STARTED / REAL PROVIDERS DEFERRED`

Modules: `M11 Mock-only retrieval honesty delta`, `M12 classroom playback/control`, `M13 classroom interaction`, `M14 barrage insight + Maya report`, `M15 history + on-demand translation`

This packet freezes the Mock-only Wave 3 implementation contract. It starts from the audited Wave 0–2 and pre-Wave-3 baseline, preserves all existing Agent/RAG/Debate/Playback behavior, and completes the post-debate classroom loop. No implementation worker may approve its own Gate.

## 1. Authorized outcome

The exact vertical slice is:

`finished debate → teacher opens interaction → public QR/form → independent vote and barrage → teacher live totals/raw barrage → teacher closes → immutable anonymous insight → Maya report revision → teacher history/download → optional Mock Chinese translation`

Wave 3 remains local/private Demo scope. Every Provider selector stays `mock`.

## 2. Explicitly out of scope

- no broad retrieval rewrite or real-Embedding relevance claim; the only authorized relevance delta is the versioned Mock-only lexical topic anchor in section 3.2;
- no real LLM, Embedding, TTS, Voice, Translation or paid call;
- no Provider selector UI, supplier field, model ID, external ID or API key in browser DTOs;
- no Wave 4, G4/G5 real-service claim, LAN load acceptance, public/cloud deployment or public repository change;
- no login/course/group redesign, no new debate rounds, no unrelated playback rewrite and no audio-download feature; the only playback delta is the approved manual Reconnect, recoverable Pause/Continue, full/partial Finish and Replay-catalog repair below;
- no device fingerprint, account linkage, one-person-one-vote promise, rate limit, moderation, pressure test or anti-abuse subsystem;
- no PDF report, report audio, Maya Avatar or automatic Chinese generation;
- no direct source-code copying from reference repositories.

## 3. Shared invariants

1. Only a fully `debate_finished` Debate whose final planned turn is public/final-ready and whose playback is terminal may open interaction.
2. A failed, stopped, draft or running Debate cannot open interaction.
3. Interaction is one-way: `closed → open → finalized`. It never reopens after finalization.
4. Vote and barrage are independent records and requests. A nickname is never accepted or stored by the vote route. A barrage never stores a participant vote.
5. Each browser page creates a separate UUID `client_submission_id` per vote action and per barrage action. Same ID + same payload replays the original success; same ID + different payload is `409 idempotency_conflict`. Refresh creates new IDs and may submit again. This is network idempotency, not anti-vote identity.
6. Public requests need no User Session and receive only the minimal topic/participant form. Teacher, course, group, transcript, source, report, totals and raw barrage list are not public fields.
7. Raw `nickname + raw_text` is retained and shown only on the authenticated teacher stage/history. Insight generation receives message ID + raw text only; nickname is removed before any policy/Provider boundary.
8. Maya receives no nickname and no raw barrage list. Its only inputs are the frozen Debate transcript, final participant/position summaries, TurnSource rows actually used by public turns, final vote aggregates and one validated anonymous BarrageInsightSnapshot.
9. Counts are computed from database message IDs/vote rows, never trusted from a Mock or real model.
10. Replay never calls interaction, insight, report or translation generation and never mutates their state.
11. All WebSocket events commit after the authoritative database transaction and use the existing Debate sequence/watermark/gap recovery. A WebSocket never owns a socket-lifetime SQLAlchemy Session.
12. Existing finished Debate/Turn/Source/Playback/audio rows remain immutable. Wave 3 creates derived records only.
13. The classroom socket makes one automatic initial connection only. A recoverable network close/error or sequence gap leaves the rendered authoritative snapshot intact; only one explicit teacher Reconnect click performs one snapshot refresh, one socket attempt and at most one controller acquire. No timer or background refresh retries. Terminal state, controller supersession, expired login and origin mismatch are not network loss and never expose a Reconnect action.
14. `Pause` is a recoverable live-playback command: it persists `PlaybackState.status=paused`, keeps the Debate `running`, preserves generated/public turns and does not cancel future generation. `Continue` revalidates the same turn/audio/CAS and returns to `ready`; it is distinct from terminal `stopped`.
15. Finish is independent of Pause. A complete final-ready/public turn catalog finishes normally as `debate_finished`; an incomplete catalog becomes partial, represented by the existing terminal `stopped` status while retaining immutable generated turns. Partial completion cannot expose interaction, report, history, translation or Replay.
16. Teacher navigation order is `Back to debate list → Finish debate → Classroom interaction & report`. Interaction, report, public speeches/history and test translation live on the dedicated teacher page; the playback page owns only classroom playback controls.
17. The translation surface has one language action. It generates missing exact-hash Mock translations only when needed, then toggles the public speech display between authoritative English and available Chinese test text. It never renders the same Chinese translation twice or feeds it into Replay/RAG/TTS/debate/report input.
18. Before Replay clears the visible public prefix, the page captures one immutable turn catalog containing speech and source rows. Every `replay.started` resolves from that catalog; a missing catalog entry fails closed instead of showing an empty speech card.

### 3.1 Final disconnect-cause delta

- Transport state and disconnect/control cause are separate frontend values. A generic `disconnected` boolean/string cannot be the presentation contract.
- `playback.status in {stopped, completed}` or `controller.revoked(reason=debate_terminal)` clears media/controller authority but shows the authoritative Debate/Playback terminal status. It never renders a Disconnected/Reconnect pill or overlay. A completed Debate may obtain a fresh controller epoch for retained Replay without opening a new socket or describing that controller transition as a reconnect.
- `controller.revoked(reason=superseded)` means another teacher page acquired authority. The stale page retains its authoritative transcript/sources, stops audio, does not auto-acquire again and displays `Another teacher page has taken control / 另一个教师页面已取得控制权`. It has no Reconnect action.
- WebSocket close `4401` means the login/session is no longer valid and displays `Login expired. Please sign in again / 登录已失效，请重新登录`. It has no Reconnect action.
- WebSocket close `4403` is reserved for an Origin mismatch and displays `The classroom address does not match the server configuration / 课堂访问地址与服务器配置不一致`. It has no Reconnect action. Missing server settings/database use a server-error close path, not 4403.
- Abnormal network close/error displays `Connection lost / 连接已断开` and one manual Reconnect action. A sequence/watermark gap displays a distinct state-resynchronization message but uses the same one-click, one-refresh, one-socket-attempt recovery budget.
- `onerror` cannot overwrite a later, more precise close code or private `controller.revoked` reason. Intentional unmount/terminal socket cleanup cannot be reclassified as network loss.
- The dedicated interaction/report page reuses the 4401/4403/network classification. It never adds automatic retry.
- Close reason messages are UI-only and contain no token, session value, configured private origin, supplier field or server path.

### 3.2 Versioned Mock RAG honesty delta

- New Debate drafts use rule set `ordered_multi_agent_rounds_demo_v2`; existing v1 rows, snapshots and generated turns remain immutable and readable. No migration rewrites existing `rule_set_id` or `rule_snapshot_json`.
- `mock_lexical_anchor_v2` runs only when the configured Embedding adapter is the deterministic Mock. Real Embedding/Vector adapters and Provider contracts are unchanged.
- Each retrieval attempt retains an authoritative topic anchor separate from typed round-one/round-two subquery text. Generic predecessor claims/questions cannot replace or bypass the topic anchor.
- Topic and candidate chunk text are normalized with the frozen Latin-token routine and a frozen stop-word set. If the topic has at least two meaningful tokens, a candidate needs at least two topic-token overlaps; if it has exactly one meaningful token, that token must overlap. Candidates failing the gate cannot become strict or relaxed receipts.
- Passing candidates still use the existing deterministic strict→relaxed score thresholds, ranking, receipt identity and six-receipt cap. This policy may create a bounded Mock false negative; it must not create a known unrelated false positive.
- The rule snapshot records the retrieval policy version. Student draft test-chat Mock retrieval uses the same current v2 topic-anchor policy; published KnowledgeSnapshot bytes and vector rows are never rebuilt.
- Deterministic acceptance is: TikTok topic→TikTok evidence matched; TikTok topic→mineral notes no_match; intimate-relationship topic→relationship evidence matched; hiking topic→TikTok/relationship evidence no_match; round-two generic predecessor text cannot turn an unrelated snapshot into matched.

### 3.3 Final delta Gate sequence and stop conditions

1. G1 implementation is split into mutually exclusive frontend connection, backend close-code and Mock RAG/rule-contract ownership. No implementation worker signs G2.
2. G1.5 runs targeted counterexamples, all backend/frontend tests, formatting/lint/type/build, OpenAPI/generated-client/WS/route checks, migrations 0001-0007, Docker and repository-secret boundaries. No real Provider call is allowed.
3. An independent reviewer audits pause/resume single-event behavior, SQL CAS/restart, partial downstream denial, Replay catalog, controller revocation/takeover, close-reason display and Mock RAG v2/v1 immutability. P0/P1 must be zero; in-scope P2 is fixed, while any product/provider-scope P2 requires explicit acceptance.
4. After G2 PASS, the main window is explicitly authorized by the user to perform G3 with real browser/runtime evidence: network restart/manual reconnect, two-page supersession, 4401, 4403, Pause/Continue, full/partial Finish, interaction/report, translation, Replay and controlled RAG contrast.
5. Only G2 PASS plus main-window G3 PASS permits `WAVE_3_G3_PASS / READY_TO_DISCUSS_WAVE_4`. Any automatic reconnect, stale-controller command acceptance/reacquire loop, duplicate resumed event, partial downstream access, Replay content loss, unrelated Mock RAG match, real-provider call or core-contract conflict stops the Gate.

## 4. M13 — Classroom interaction

### 4.1 Teacher lifecycle

- `GET /debates/{debate_id}/interaction` is course-teacher only and returns the window status, public URL while open, raw named barrages in committed sequence and anonymous vote aggregates.
- `POST /debates/{debate_id}/interaction/open` is course-teacher + CSRF + idempotency protected. It revalidates Debate completion in the final SQLite writer transaction.
- Open creates or transitions the single window, sets a random nonce and records the teacher/time. The public token is reconstructed as a signed, URL-safe `window_id + nonce + HMAC` using the server secret; the database stores the nonce but no bearer token, URL or QR image. The idempotency ledger stores a token-free canonical operation result and reconstructs `public_url` on every authorized response; it must not persist a bearer token, URL or QR payload.
- Token format is exactly `v1.<base64url(window_uuid_bytes || 32-byte_nonce)>.<base64url(HMAC-SHA256("maya.classroom.v1\0" || payload))>`, unpadded and fixed-pattern/length. Parsing is fixed-width and signature compare is constant-time. Token, URL and QR payload never enter logs, AuditLog, DebateEvent or idempotency response JSON.
- The token validator rejects malformed signature/shape before lookup. An unknown/forged valid-shaped token is 404; a finalized known token is 410.
- `CLASSROOM_PUBLIC_BASE_URL` builds the public platform URL at the frozen audience path `/classroom/{access_token}`. It is not accepted from the request and cannot contain a supplier URL. Startup accepts only an absolute `http|https` origin with no credentials/path/query/fragment. Open rejects missing, localhost, `127.0.0.0/8` and `::1` with `503 classroom_public_url_unavailable` without changing the window. G3 configures a reachable private-LAN origin and accesses the teacher site through the same normalized origin; public/non-private deployment is outside this Gate. WebSocket Origin validation reuses the same canonical origin helper.
- `POST /debates/{debate_id}/interaction/close` is course-teacher + CSRF + idempotency protected. It executes `open → finalized` in one writer transaction, freezes the exact ordered barrage ID list/final vote aggregate JSON/input hash, and then creates one insight Job. New public submissions lose the same writer race and return 410.
- Open, vote, barrage and close each use a dedicated short Session. `BEGIN IMMEDIATE` is the first database statement; the same transaction revalidates window/debate/participant/teacher state, claims idempotency, writes the business row, CAS-increments Debate sequence, persists the closed DebateEvent, and on close freezes inputs + creates the insight snapshot/Job. Open revalidates `debate_finished`, every planned turn `public + final_ready`, the final turn public, and Playback terminal with no controller/pending media authority. Only after commit may the event hub publish. No route reuses a request/socket Session or makes pre-claim reads authoritative.
- Same client submission ID replay returns the original success without a row, sequence or WS event; different payload returns 409. Vote percentages, REST aggregates, WS aggregates, frozen totals and input hashes use one canonical function and participant `order_index` ordering (`total=0 → 0`, otherwise one frozen precision).
- Closing an empty window is valid and continues to insight/report generation with explicit zero-interaction semantics.

### 4.2 Public form

- `GET /classroom-interactions/{access_token}` returns only topic and frozen `participant_id/slot/name` options while open.
- `POST .../votes` accepts only `participant_id + client_submission_id`. The participant must belong to that Debate.
- `POST .../barrages` accepts only `nickname + raw_text + client_submission_id`; validation checks `value.strip()` is nonblank but stores and returns the original JSON string bytes/characters without trimming, normalization, moderation or rewriting.
- Each barrage receives a monotonically increasing per-window sequence under `BEGIN IMMEDIATE`.
- Public success bodies contain only the frozen boolean. They never disclose totals, other barrages, User IDs, course IDs or internal errors.

### 4.3 Teacher UI and events

- After a full Finish, the playback page exposes a dedicated `Classroom interaction & report` navigation action. The playback Dock contains Start, Next, context-sensitive Pause/Continue and whole Replay; Finish remains in the page header. Partial Finish exposes none of the downstream actions.
- Open state shows an on-platform QR code/public URL, live vote totals/percentages and raw named barrage slow scroll. Vote and barrage module positions follow frozen Visual Draft V2.
- M13 owns a new `interaction` frontend component boundary and audience route. It must not append interaction logic to the large playback service or DebateStage state machine; the stage consumes a stable interaction view model/component.
- Closed/expired audience UI explains that collection is unavailable. Vote and barrage have independent busy/error/success states; one success leaves the other usable, and both success states produce the final success screen. Token-bearing HTML/API responses set `Cache-Control: no-store`; the audience page sets `Referrer-Policy: no-referrer` and loads no third-party analytics/QR resource.
- Existing closed WS event schemas are implemented for open, vote aggregate update, raw barrage created and finalized totals. `interaction.opened` is revised to carry status + zero aggregates only; it must not contain `public_url`, token or `qr_payload` because DebateEvent payloads are durable. The authorized REST response reconstructs the URL. Raw barrage events are teacher-authenticated only; before every server event delivery, each subscribed connection is reauthorized with a fresh short Session so a revoked/expired Session or lost teacher membership cannot continue receiving nickname/raw text.

## 5. M14 — Anonymous insight and Maya report

### 5.1 Insight snapshot

- Close creates immutable input boundaries: ordered barrage IDs, raw-text hash and final vote hash.
- `BarrageInsightPolicy` receives a closed typed array of `{message_id, raw_text}` without nickname/author/User/Vote/device fields. Forbidden-key scans enforce structural de-identification. Free text may self-identify a person; Demo does not perform general PII/name recognition and must not claim that it does. Identical raw text with different database nickname must produce byte-identical policy input/output.
- Mock policy `mock_barrage_insight_v1` is exact and visibly Mock: NFKC + Unicode casefold + collapse every Unicode-whitespace run to one ASCII space + trim outer whitespace forms the grouping key; it does not perform semantic/fuzzy clustering. A message is filtered only when it contains no Unicode letter or number. Every other message is included, including ambiguous, critical and minority content. Exact duplicate normalized text is grouped.
- Classification tokenization uses Unicode letter/number runs for Latin words and direct substring matching for CJK markers. Priority is `question > challenge > support`. Question means literal `?` or first token/substr in `who, what, when, where, why, how, which, can, could, would, should, do, does, did, is, are, was, were, 谁, 什么, 何时, 哪里, 为什么, 怎么, 如何, 是否, 能否, 应否`. Challenge markers are `disagree, oppose, challenge, doubt, concern, however, but, not, no, 反对, 不同意, 质疑, 怀疑, 担心, 但是, 然而, 不`; Latin markers require whole-token match, CJK markers use substring. Otherwise category is support. Summary is the first original raw text in sequence order. This is a deterministic flow test, not semantic-insight quality.
- Each output item is a normalized row with category/summary; included and filtered messages are separate exact assignment rows. Counts are queried from assignments, never accepted from policy output. Public/teacher DTOs omit the source mapping.
- Insight validation proves: every frozen message ID is assigned exactly once as included or filtered; included references one same-snapshot item, filtered has a versioned reason; no unknown/duplicate ID; `included_count + filtered_count = frozen barrage count`; item counts equal assignment rows.
- A validation/provider failure receives one shared attempt-2 repair. Exhaustion marks only the insight/report attempt failed. Debate, raw barrage and votes remain available.
- Empty interaction creates a ready zero-item insight, not a failure.
- The first automatic post-close pipeline makes Debate `completed` when it reaches a terminal report-ready state or a terminal insight/report failure; this Debate transition and terminal event commit with that terminal derived state. Manual later regeneration never moves the Debate out of `completed` and never changes public turns/playback.

### 5.2 Maya report

- `CivilizationMutualLearningReport` is the Debate-level aggregate. Every HTTP/automatic command creates a new immutable insight/report revision; attempt `1→2` is only the shared repair inside that revision. Ready/failed revisions never mutate. A failed new attempt never hides the previous successful revision.
- Close atomically creates insight revision 1 in generating state plus a pending Job. A worker claim makes both running/generating in one writer transaction. A ready insight commit atomically creates the report aggregate if missing plus the next generating report revision and pending report Job. `POST /report/generate` creates a new insight revision when insight must retry, otherwise a new report revision.
- Mock Maya `mock_maya_report_v1` is deterministic, provider-neutral and explicitly labelled in internal metadata. It produces a closed structured section DTO that the backend renders into 600–900 English-word Markdown. Code inserts canonical vote counts and evidence citations; the Mock does not free-write them. It does not announce a winner and must state `This session had no classroom interaction data.` only when frozen total votes and barrages are both zero.
- Required headings in exact order are `# Civilization Mutual Learning Report`, `## Debate Overview`, `## Evidence and Arguments`, `## Areas of Convergence`, `## Continuing Tensions and Questions`, `## Classroom Perspectives`, `## Mutual Learning Reflection`. Citations are exactly `[evidence:<turn_source_uuid>]`. For word count, remove those citation tokens, then apply the existing generation `WORD_RE = [A-Za-z0-9]+(?:['’\-][A-Za-z0-9]+)*` to the complete rendered Markdown; heading words count, Markdown punctuation does not. The validator rejects unknown TurnSource IDs, independent nickname fields/mappings, noncanonical counts and winner declarations. One shared repair attempt is allowed; exhaustion marks the revision failed with a safe code.
- Actual RAG input is limited to TurnSource rows used by public turns, joined to immutable chunk text. Citation identity is global `turn_sources.id`; naked turn-local `evidence_id` is never used as a report citation. The complete Agent RAG/Snapshot, `retrieval_receipts_json`, teacher note and unused chunks/receipts are forbidden.
- Every revision stores canonical `ReportInputManifestV1` JSON/hash: policy/render/validator versions; ordered frozen participant display/initial-final position data; ordered public final-ready Turn IDs/text hashes; exact TurnSource IDs/snapshot/chunk/content hashes; normalized finalized vote rows; one ready insight snapshot and item rows. It contains no independent nickname field/mapping or raw barrage list. Generator and validator consume the same manifest.
- Canonical JSON is UTF-8 without BOM, `ensure_ascii=false`, lexicographically sorted object keys, compact `,`/`:` separators, explicit null/empty arrays and no floating-point values. Source strings remain exact stored text without normalization. Arrays sort participants by order index, turns by turn index, TurnSources by turn index then rank then TurnSource ID, votes by participant order and insight items by stored item order then ID. Input hash is lowercase SHA-256 of these canonical UTF-8 bytes.
- Current success uses a separate exact pointer row referencing a ready revision from the same report, avoiding a circular create-time FK. Aggregate projection distinguishes current success, latest attempt and active generating revision; a new failure never clears current success.
- Report routes are course-teacher only. Students and public audience receive 404/403 according to the existing course-visibility boundary.
- English Markdown download uses safe `Content-Disposition`, `text/markdown; charset=utf-8`, `Cache-Control: no-store` and `X-Content-Type-Options: nosniff`; teacher rendering disables raw HTML and inserts topic/name/summary as text. Chinese download exists only when M15 has a successful translation for that exact revision hash.

## 6. M15 — History and on-demand translation

- Existing teacher Debate list remains the history index; the control/detail page adds transcript, interaction, current report and report revision/history sections without changing playback authority.
- All finished Debate text, used sources, named raw barrages, anonymous vote aggregates, insight/report revision metadata and successful translation items are retained. Audio remains available only for the course's current-audio Debate under the existing pointer/file checks.
- `GET/POST /debates/{debate_id}/translations` is course-teacher only; POST is CSRF + idempotency protected.
- A batch stores `TranslationInputManifestV1`: ordered `public + final_ready` turns by `turn_index` with IDs and exact English hashes, then the current ready report revision ID/hash when present, target language and policy version. Prepared/unpublished turns and failed report attempts are excluded. Canonical manifest JSON/hash uses UTF-8, fixed key order and explicit null/array rules.
- Source hash is SHA-256 of the authoritative English UTF-8 bytes exactly as stored—no trim, NFKC or line-ending rewrite at translation time.
- Successful reusable translations live in global immutable `translation_entries` keyed by content identity + exact source hash + target language + policy key + quality; `translation_batch_items` relates one batch to reused or newly generated entries. Changed English or policy/quality creates a new entry. Translation never changes the English source. Read models select only a ready entry matching the requested batch policy/quality; Mock and future real translations never cross-reuse.
- Same-input concurrent requests under different idempotency keys reuse the one active batch/fence; a Job has an exact typed batch owner FK rather than hiding the owner UUID in a generic key.
- Mock policy `mock_translation_v1` returns exactly `【测试中文表示，不代表翻译质量】\n` followed by the unchanged authoritative English source, with provider-neutral `quality=test_representation`. The UI always displays “测试表示，不代表翻译质量”. It proves batching/cache/failure/UI boundaries and is not a translation-quality claim. No DeepL or network call occurs.
- Batch status is `pending|running|completed|partial|failed`: completed means all nonempty manifest items successful (including all-cache-hit, with no Job/provider call); partial means `succeeded>0 && failed>0`; failed means `succeeded=0 && failed=total`. Terminal `total = succeeded + failed`; interruption marks remaining nonterminal items failed and sets a safe batch/Job error, then uses the same exclusive completed/partial/failed count rule. If the manifest has no public final-ready turn and no current ready report, POST returns `422 no_translatable_content` and creates no batch/idempotency success.
- Startup schedules a pending Job at most once. Running Job + batch + nonterminal entries become failed `operation_interrupted` in one writer transaction; already ready entries remain reusable.
- DebateTurn `translated_text` and ReportRevision `translated_markdown` read models derive only from the latest successful exact-hash entry. Playback/RAG/generation/report-manifest builders accept source English types without translated fields and have dependency/serialization regression tests proving translation cannot feed them.

## 7. Migration `0007_wave3_interaction_report`

Migration 0007 is additive and may not rewrite 0001–0006. It must pass fresh, repeat, populated 0006→0007, downgrade/re-upgrade, full historical schema fingerprint and empty foreign-key checks.

### 7.1 Tables

1. `classroom_interaction_windows`
   - `id`, unique `debate_id`, `course_id`, `status`, nullable fixed 32-byte encoded `token_nonce`, `revision`, `opened_by/opened_at`, `finalized_by/finalized_at`, `frozen_barrage_ids_json`, `frozen_barrage_input_hash`, `frozen_vote_totals_json`, `frozen_vote_input_hash`, nullable frozen barrage/vote counts, timestamps;
   - `UNIQUE(id, debate_id)`, composite Debate/course FK, exact `(course_id,user_id)` FKs to CourseMember for opener/finalizer plus service-level teacher-role checks, status/shape/revision checks and unique nonce;
   - closed: no nonce/open/final/frozen fields; open: nonce+opened fields only; finalized: open+final actor/time and every frozen JSON/hash/count field non-null and canonical;
   - existing Debates are backfilled as `closed` without nonce; every new Debate creates one closed window in the same final writer transaction as Debate creation. No route may lazily create a second source of truth.
2. `votes`
   - `id`, `window_id`, `debate_id`, `participant_id`, `client_submission_id`, `submitted_at`;
   - exact `(window_id,debate_id)` and `(participant_id,debate_id)` composite FKs; unique `(window_id, client_submission_id)`; no nickname/User/device columns.
3. `barrage_messages`
   - `id`, `window_id`, `debate_id`, `nickname`, `raw_text`, `client_submission_id`, `sequence`, `submitted_at`;
   - exact window/debate FK; unique `(id,window_id,debate_id)`, `(window_id, client_submission_id)` and `(window_id, sequence)`; nonblank checks only.
4. `interaction_final_vote_counts` and `interaction_final_barrages`
   - final vote row is `(window_id,debate_id,participant_id,count)` with exact window/Debate and participant/Debate FKs, unique window+participant and nonnegative count;
   - final barrage row is `(window_id,debate_id,barrage_message_id,sequence)` with exact three-column FK to `barrage_messages(id,window_id,debate_id)`, unique window+message and window+sequence;
   - canonical hashes/counts on the window must equal these rows; later code does not reconstruct a different snapshot.
5. `barrage_insight_snapshots`
   - `id`, `window_id`, `debate_id`, `revision_no`, `policy_key`, `status`, `attempt`, input hash, included/filtered counts, safe error code and timestamps;
   - unique `(id,window_id,debate_id)` and `(debate_id,revision_no)`, one active-generation partial index, discriminated state/attempt/count/hash checks.
6. `barrage_insight_items` and `barrage_insight_assignments`
   - item rows hold `id,snapshot_id,window_id,debate_id,order_index,category,summary`; `order_index` is the earliest assigned BarrageMessage sequence for that item, with exact `(snapshot_id,window_id,debate_id)` FK, unique `(id,snapshot_id,window_id,debate_id)` and `(snapshot_id,order_index)`;
   - assignment rows hold `(snapshot_id,window_id,debate_id,barrage_message_id,disposition,item_id,filter_reason)` and exact FKs to the same scoped snapshot, `barrage_messages(id,window_id,debate_id)` and optional `items(id,snapshot_id,window_id,debate_id)` using the same child-column order;
   - unique `(snapshot_id,barrage_message_id)`; included requires same-snapshot item and no reason, filtered requires a versioned reason and no item. Counts derive from assignments.
   - window-owned raw/final/insight child rows cascade only when the Wave 3 window is explicitly removed; references to DebateParticipant, BarrageMessage and immutable Debate/Turn/Source history use RESTRICT where deletion would break audit evidence.
7. `civilization_reports`
   - `id`, unique `debate_id`, generation/latest-attempt status, policy key and timestamps; no circular revision pointer.
8. `civilization_report_revisions`
   - `id`, `report_id`, `debate_id`, `insight_snapshot_id`, `revision_no`, `status`, attempt, canonical input manifest JSON/hash, nullable English Markdown/word count, safe error code, trigger/requester and timestamps;
   - unique `(id,report_id,debate_id)`, `(id,report_id,debate_id,status)`, `(id,debate_id)` and `(report_id,revision_no)`, exact report/debate and insight/debate FKs, one active-generation partial index, generating/ready/failed shape and 600–900 checks.
9. `civilization_report_current_success`
   - one row per report with `revision_status='ready'` CHECK and exact `(revision_id,report_id,debate_id,revision_status)` FK to revision `(id,report_id,debate_id,status)`; updates atomically in the revision-success transaction.
10. `translation_batches`

- `id`, `debate_id`, `course_id`, `requested_by`, target language, policy/quality key, status, canonical manifest JSON/input hash, total/success/failed counts and timestamps;
- exact Debate/course and `(course_id,requested_by)` CourseMember FKs plus service teacher check; target exactly `zh-Hans`; active `(debate_id,input_hash,target_language)` partial unique fence; count/status/terminal-shape checks.

11. `translation_entries`

- `id`, `debate_id`, `content_type`, nullable `turn_id`, nullable `report_revision_id`, source hash, target language, policy/quality key, status, nullable translated text, safe error and timestamps;
- exactly one content FK is non-null; exact `(turn_id,debate_id)` or `(report_revision_id,debate_id)` FK; ready-cache and active-generation partial unique indexes include content/source hash/target/policy key/quality; ready text nonblank and failed text null.

12. `translation_batch_items`

- `batch_id`, `entry_id`, `debate_id`, stable order index, `reused`, status and safe error projection;
- exact batch/debate and entry/debate FKs; unique batch+entry and batch+order. A cache hit links the existing ready entry rather than copying provider/text state.

13. `jobs` additive owner columns

- nullable exact `insight_snapshot_id`, `report_revision_id`, `translation_batch_id` FKs are added; operation/owner shape checks require exactly the typed owner for each Wave 3 generation Job while preserving all Wave 0–2 Job rows.

Generic `jobs` and the existing User-bound idempotency ledger are reused only for authenticated commands `interaction.open`, `interaction.close`, `report.generate`, and `translation.generate`; generation Job idempotency keys target the immutable typed owner row. Anonymous vote/barrage never write `idempotency_records` and have no User linkage: their own business-table `UNIQUE(window_id,client_submission_id)` plus stored payload comparison provides replay/conflict behavior. Startup schedules each still-pending Wave 3 Job at most once; a running Job and its nonterminal typed owner/entries become failed `operation_interrupted` in one writer transaction. It never reruns ready/failed rows, reopens interaction or clears current success. Teachers may regenerate failed work as a new revision/batch.

### 7.2 Downgrade

- Downgrade first removes Wave 3 Job rows and every Wave 3 idempotency record/response for the namespaced operations, then removes only Wave 3 derived tables/indexes/FKs after proving no 0001–0006 row changed. Re-upgrade must never replay a stale token-bearing or table-referencing result.
- It never deletes Debate/Turn/Source/Playback/audio/Agent/RAG rows.
- Product UI/routes are unavailable on old code; historical Wave 3 rows are intentionally lost only by an explicit operator downgrade, never by ordinary startup.

## 8. OpenAPI and browser client

The 13 frozen later-Wave placeholders become implemented and are removed from `route-surface-placeholders.json`:

- M13: `getTeacherInteraction`, `openInteraction`, `closeInteraction`, `getClassroomInteractionForm`, `submitVote`, `submitBarrage`;
- M14: `getCurrentReport`, `regenerateReport`, `listReportRevisions`, `getReportRevision`, `downloadCurrentReport`;
- M15: `listTranslationBatches`, `translateCurrentPublishedContent`.

All Wave 3 request/response object schemas are closed with `additionalProperties: false`, including nested public participant rows and request bodies. `TeacherInteraction` has a status-discriminated shape: `public_url` is an absolute URI only while open and is null while closed/finalized; votes/barrages remain arrays in every state. `ReportRevisionSummary` has no Markdown. Detail is a closed `oneOf`: generating has null content/error, ready requires nonblank Markdown + 600–900 word count + null error, failed requires safe error + null content/count. `current_success_revision` is ready-only. Download contracts attachment filename + UTF-8 filename, no-store, nosniff and Markdown charset.

Teacher routes explicitly contract 403/404 plus lifecycle 409 where applicable; public POST routes contract 400/404/409/410/422. The custom FastAPI OpenAPI normalizer must retain explicit business 422 for `submitVote`, `submitBarrage`, and `translateCurrentPublishedContent` instead of silently deleting it.

Translation GET/POST explicitly contract 403/404; POST also contracts 409 active/idempotency conflict and `422 no_translatable_content` when the frozen manifest has zero source items. `TranslationBatch` is a closed DTO with ID, debate/input hash, status, target, `quality=test_representation`, timestamps, counts and closed item summaries `{content_type,content_id,source_text_hash,status,reused,safe_error_code}`. It contains no Provider/model/key or translated body; transcript/report REST read models carry successful derived text.

All request/response/security/status/content headers must match the resulting frozen OpenAPI exactly. Contract changes are permitted only to close an actual contradiction with Project and require main + Sol review before implementation. Generated TypeScript remains main-owned and clean-diff checked.

## 9. WebSocket contract

The already generated closed schemas become live behavior; no free-form event is added. Implemented events include:

- interaction opened without token/URL/QR, vote totals updated, raw barrage created, interaction finalized;
- barrage insight started/completed/failed with snapshot/revision/status/counts only;
- report started/completed/failed with revision/status/current-success ID/word-count or safe error only;
- translation batch started requires `status=running`; completed requires `status=completed|partial`; failed requires `status=failed`. Every terminal event enforces `total=succeeded+failed` and carries IDs/counts/status only;
- snapshot fields for interaction/insight/report remain authoritative after refresh/gap/restart.

Events normally contain stable platform IDs/counts/status only. The authenticated `interaction.barrage_created` event is the sole raw-text/nickname exception and is reauthorized per delivery; report/insight/translation events and reconnect snapshot never contain summaries, nickname, raw/source mappings, Provider metadata, translation text, `english_markdown` or `translated_markdown`. Snapshot report projection is summary-only IDs/status/counts/word-count. Full insight/report/translations are fetched through teacher REST routes.

## 10. Permissions

| Action                                   | Course teacher        | Student/group account        | Anonymous open token  |
| ---------------------------------------- | --------------------- | ---------------------------- | --------------------- |
| Open/close/query teacher interaction     | allow                 | 403/404 by existing boundary | no route authority    |
| Read public form                         | not Session-dependent | not Session-dependent        | allow only while open |
| Submit vote/barrage                      | not Session-dependent | not Session-dependent        | allow only while open |
| Read totals/raw barrages                 | allow                 | deny                         | deny                  |
| Generate/read/download reports/revisions | allow                 | deny                         | deny                  |
| Create/read translation batches          | allow                 | deny                         | deny                  |

Cross-course object probing remains 404. CSRF is required for authenticated mutations and absent for the two public POST routes. Public token validation never creates a User/Session.

## 11. Ownership and parallelism

- Main owns this packet, shared ORM registration/composition root, migration 0007 integration, frozen OpenAPI/generated client, WS generators/fixtures, route allowlists, Project/workbook, Docker and final browser acceptance.
- M13 Luna owns `backend/app/modules/interactions/**`, audience/teacher interaction components/routes and focused tests.
- M14 Luna owns `backend/app/modules/reports/**`, Mock insight/report policies, teacher report components and focused tests.
- M15 Luna owns `backend/app/modules/translations/**`, Mock translation policy, history/translation components and focused tests.
- Workers are not alone, do not revert others and do not modify another module's files. Shared-file changes are proposed to main rather than raced.
- Three independent Sol High auditors review M13, M14 and M15 design/code. Main resolves cross-module findings and signs G3.

## 12. Gate sequence

`G0 Main → G0-S three Sol High design audits → G1 three Luna Max implementations → G1.5 deterministic checks → G2 three independent Sol High code audits → G3 main integration/runtime/browser acceptance`

No G1 begins until all G0-S P0/P1 findings are closed and this packet is marked `FROZEN / G0-S PASS / G1 AUTHORIZED`.

### G0-S closure

- M13 Sol High final: `PASS / P0=0 / P1=0` after closing token persistence, closed OpenAPI/422 responses, dedicated `BEGIN IMMEDIATE` submit/close transactions, exact scoped FK/normalized final rows, anonymous idempotency without User linkage, LAN origin validation and per-event teacher reauthorization.
- M14 Sol High final: `PASS / P0=0 / P1=0` after closing structural de-identification, exact Mock insight constants, normalized assignment partition, canonical report manifest/citation/word-count policy, immutable revision/Job recovery, ready-only current-success exact FK, status-discriminated REST and summary-only WS.
- M15 Sol High final: `PASS / P0=0 / P1=0` after closing immutable cache entry/batch relations, exact source/manifest hashes, active fence/typed Job owner/restart, exclusive terminal counts, closed REST DTO/statuses, summary-only WS and deterministic test-representation semantics.
- Main synchronized the frozen parent/product OpenAPI to `0.1.0-g0.8-wave3`, SHA-256 manifest, generated TypeScript client, response allowlist, closed WS generator/fixtures and explicit business 422 retention. Redocly, parent-byte/hash, 66-operation response check, generated client, WS `30/18`, command `6/7`, private result `5/6` and generator clean-diff checks pass. The 13 routes remain explicitly classified as M13-M15 placeholders until G1 implements them.

### High-risk narrow G2 closure (2026-08-29)

Per explicit user authorization, the final code review was limited to the five
requested risk boundaries rather than a full three-auditor Wave 3 review:
anonymous token integrity, interaction idempotency/concurrency, nickname removal
and Maya input boundaries, and translation restart recovery. The review found two
P1 defects and one P2 integrity gap; all were fixed with focused regression tests.
Independent Sol re-review concluded `PASS / P0=0 / P1=0`. This narrow result does
not sign Full Wave 3 G2/G3; the project is now at the pre-Wave4 manual
verification stage.

## 13. Deterministic acceptance

### M13

- open before finish rejected; open exact finish accepted; same/different-key idempotency; two-teacher race one winner;
- malformed/forged/unknown/finalized token; public DTO forbidden-field scan;
- independent vote/barrage success, same-key replay/different-payload conflict, refresh-new-ID repeat accepted;
- wrong participant rejected; vote row has no nickname identity; barrage has no vote relation;
- submit-versus-close writer race; close exact immutable counts/order/hash; closed empty input;
- teacher/student/cross-course permissions; post-commit WS ordering; refresh/restart snapshot;
- 360x800 public form and V2 teacher QR/totals/raw slow-scroll UI.

### M14

- independent nickname column/value and author mapping are never selected/appended/serialized into policy/report/Job/event/log; same raw text with different nickname produces byte-identical policy input/output, while a name self-disclosed inside raw text is explicitly outside the semantic-anonymity promise;
- exact include/filter partition, duplicate/unknown source ID rejection, code counts and minority criticism preservation;
- no-interaction ready insight/report phrase;
- report reads public turns + used TurnSource only; unused/cross-snapshot evidence rejected;
- 599/600/900/901 word validation, no winner/invented vote/nickname/unknown evidence;
- one repair, fail-safe revision, successful-current pointer retention and concurrent regenerate single winner;
- Markdown content/header/filename and English-only availability before translation.

### M15

- frozen current-public input set/hash, no prepared turn, exact report revision;
- successful exact-hash reuse; changed source creates new item; partial/failure preserves successes;
- Mock translation visibly marked and never feeds RAG/context/TTS/report;
- teacher-only list/create; student/cross-course/public denied;
- history text/source/barrage/vote/report survives audio replacement; only current-audio Debate plays.

### Global

- 0007 fresh/repeat/populated/downgrade/re-upgrade/full fingerprints/FK=0;
- OpenAPI Redocly/response/strict route/generated clean diff with all 13 placeholders removed;
- closed WS positive/negative/clean-diff and server-event conformance;
- Ruff/format/mypy/full backend pytest; ESLint/TypeScript/Prettier/full Vitest/Next build;
- repository/secret/provider-field scans; Compose build/config; all selectors Mock;
- authenticated desktop/tablet/mobile teacher flow plus anonymous phone flow in a real browser;
- no new RAG/LLM/TTS call on replay; no real Provider/network call anywhere in Wave 3.

## 14. Stop conditions

Stop the affected Gate for:

- any change to Debate rules, published snapshot immutability, existing playback/audio retention or Wave 0–2 permission semantics;
- interaction opening before complete Debate, reopening after finalization or post-close accepted submission;
- linking vote to nickname/User/device/Barrage, or sending nickname/raw list to Maya;
- Maya reading unused/full RAG or inventing counts/evidence/winner semantics;
- destructive migration or mutation of 0001–0006 rows;
- socket-lifetime DB Session, pre-commit event broadcast or unbounded background retry;
- real Provider selector/key/network/billed call, Mock RAG repair, Wave 4/public deployment;
- source-unknown concurrent changes or shared-file ownership conflict.

Other independent modules may continue when their contracts do not depend on the blocked decision.

## 15. Manual-feedback delta acceptance

The 2026-08-30 delta is not covered by the earlier narrow G2 signature. It reaches G3 only when all of the following pass together:

- frozen OpenAPI, generated TypeScript and the concrete `PlatformApi` expose `pauseDebate`, `resumeDebate` and `finishDebate`; strict FastAPI route comparison has no extra/missing operation;
- SQL/REST tests prove pause across restart, resume CAS/audio revalidation, full Finish, partial Finish, concurrent stale controls and fail-closed partial interaction/report/history/translation/replay;
- existing auto-reconnect expectations are replaced with one-initial-attempt plus explicit one-shot Reconnect tests; no background snapshot request occurs after disconnect;
- Replay restores speech and sources from the immutable catalog and produces no debug console output;
- the dedicated teacher page is the only interaction/report/history/translation surface, and translation is a one-button English/Chinese display switch without duplicate Chinese rendering;
- Ruff/format/mypy/full backend pytest, ESLint/TypeScript/Prettier/full Vitest/Next build, 0007 migration, OpenAPI/response/route/generated/WS/secret checks, Compose, rebuilt Docker and real-browser checks all pass;
- cleanup happens only after the passing checkpoint: runtime databases, generated audio/history/backups, duplicate handoff files and caches are removed; `.env` and `backend/config/demo-accounts/accounts.private.md` are the only retained private runtime inputs.

### 15.1 G1.5 and main runtime evidence (2026-08-30)

- backend `386/386`; frontend `27 files / 164 tests`; Ruff format/check, mypy, ESLint, TypeScript, Prettier and Next production build passed;
- OpenAPI parent-byte/SHA/generated/Redocly/69-operation response checks, WS events `30/18`, commands `6/7`, private results `5/6`, route comparator negative fixtures and strict FastAPI schema comparison passed;
- 0001-0007 fresh/repeat/populated/downgrade/re-upgrade fingerprints and foreign-key checks passed;
- real teacher browser passed stable disconnect plus one-shot Reconnect, persisted Pause, Continue back to `playing`, partial/full Finish, dedicated interaction/report page, `4 → 0` Chinese marker single-view toggle and `replay/playing` speech/source restoration;
- runtime testing exposed a duplicate `playback.resumed` defect: REST resume and media started-ack emitted indistinguishable events, and the client paused audio while handling the true resumed event. The service now emits resumed only after media starts; the client maps it to `playing` without pausing or preparing again; backend single-event and frontend ready→resumed→playing regressions pass;
- after user-authorized cleanup, a missing-data-root rebuild reached 0007 with `7 users / 1 course / 2 groups / 0 agents / 0 debates / 0 derived Wave 3 rows`, foreign-key check empty and teacher password login successful; containers were then stopped and the regenerated `data/` was deleted again;
- `.env` and `backend/config/demo-accounts/accounts.private.md` remain mode 0600. Runtime databases, all 14 historical debates, published Agent/RAG data, generated audio, backups, duplicate handoff materials, legacy account YAML and private voice inputs were permanently deleted.

### 15.2 Final disconnect/RAG delta G2 and G3 (2026-08-30)

- Independent read-only G2 passed with `P0=0 / P1=0 / P2=1 accepted`. The accepted P2 is bounded Mock-only false-negative risk; any known unrelated `matched` result remains a blocker.
- Backend full regression passed `401/401`; frontend passed `28 files / 182 tests`. Ruff check, scoped Ruff format, mypy, ESLint, TypeScript, Prettier, Next production build, generated contracts, OpenAPI 69-operation responses, WS `30/18`, route `13` negatives, repository boundary, bootstrap safety and 0001-0007 migration probes passed.
- G3 reproduced a v2 false positive where relationship prose supplied `require` and a citation URL slug supplied `rules`. HTTP(S) destinations are now removed before Mock v2 tokenization; the exact relationship snapshot retested `no_match`, while explicit AI-school recommendation evidence remains `matched`. v1 and non-Mock Provider paths are unchanged.
- Real-browser G3 passed: network restart with no background retry and one manual Reconnect; persisted Pause and Continue; two-page `superseded` revocation; accurate 4401/HTTP-401 login-expired and 4403 Origin-mismatch copy; full natural completion; partial Finish downstream blocking; anonymous vote and raw barrage; finalized insight and 609-word report; one-batch Chinese/English display toggle; and four-step retained speech/source Replay.
- Stopped/completed terminal pages retain the transcript without a disconnect overlay or Reconnect. HTTP 403 remains a normal retryable permission/network failure and is not mislabeled as 4403.
- No real Provider or billed call occurred. After evidence capture, containers were stopped and both `data/` and `backend/data/` were permanently deleted; only ignored mode-0600 `.env` and `backend/config/demo-accounts/accounts.private.md` remain as private runtime inputs.

G2 and G3 therefore both pass. Wave 3 is signed `WAVE_3_G3_PASS / READY_TO_DISCUSS_WAVE_4`; this does not start Wave 4 or approve real LLM/Embedding/TTS, formal content, classroom load or public deployment.

## 16. Pre-Wave-4 UX/state delta (2026-08-30)

The user's later manual review supersedes the ready-to-discuss status without invalidating the completed `.2` evidence. This delta must pass before Wave 4 can start.

### 16.1 Current-language-only controls

- Every visible button and navigation link in teacher playback, interaction/report/history/translation and audience interaction renders only the active locale. Literal bilingual controls such as `English / 中文` or `Raw barrages / 原始弹幕` are forbidden.
- Accessible names follow the same locale; they must not retain a hidden bilingual hybrid that makes screen-reader and selector behavior diverge from the visible control.
- The control-page navigation text is `Back to debate list` in English and its Chinese equivalent in Chinese. It must not say `Back to debate`.
- Static explanatory copy may remain translated through the locale catalog, but one rendered view never concatenates both languages.

### 16.2 Simple classroom phase and actions

- The ordinary teacher control surface removes Pause/Continue. Backend pause/resume protocol may remain as an internal recovery primitive but is not a standard product control.
- No new duplicate Debate database status is introduced. The UI derives one classroom phase from authoritative state: `ready` for an unstarted draft, `in_progress` for preparing/ready/playing and an in-flight command, `waiting` for live `waiting_next`, and `finished` for a teacher-finished or naturally completed terminal Debate. Connection health remains a separate line above the phase.
- Start is available only before the first live turn. Next and Finish are enabled only in `waiting`, after controller authority is confirmed. During `in_progress` both are fail-closed in UI and handler code.
- Leaving the control page while `waiting` does not change server state. Returning later restores the same public transcript, current turn and `waiting` phase.
- Explicit Finish while waiting may end an incomplete turn plan. The Debate is presented as finished, but the playback remains terminal and every interaction/report/translation/Replay gate continues to require the complete public two-round plan. Abnormal generation failure remains distinct from teacher Finish.

### 16.3 Replay is retained playback, not regeneration

- Starting Replay never clears or replaces the authoritative published transcript. All saved speeches and sources remain visible while a current replay cursor highlights the turn being played.
- Replay reads only the immutable turn catalog and retained current-course audio. It makes zero RAG, LLM, Embedding, translation or TTS generation calls.
- Each replayed turn ends in persistent `replay + waiting_next`; Next advances the saved catalog immediately. The final replay turn restores terminal `finished` presentation with the full transcript still visible.
- After each completed replay cycle, the same open teacher page automatically performs exactly one fresh controller acquire for a possible later Replay. This is controller renewal, not network reconnection: no timer, snapshot loop, WebSocket reconnect or automatic recovery from a real network failure is permitted.
- A completed page loaded fresh does not acquire a controller in the background. Its Replay button remains available when retained audio is current; the teacher's single Replay click performs exactly one on-demand controller acquire on the existing socket, then one replay command. Duplicate clicks are fenced.

### 16.4 Localhost/LAN Origin behavior

- In private `DEMO_MODE`, the configured `CLASSROOM_PUBLIC_BASE_URL` origin remains canonical for QR/public links, but same-machine loopback gateway origins `http://localhost:<gateway-port>` and `http://127.0.0.1:<gateway-port>` are also accepted by the shared authenticated REST same-origin check and teacher WebSockets.
- This exception is limited to loopback HTTP origins in Demo mode and must use the same gateway port. Non-loopback mismatches, HTTPS downgrade/mismatch, malformed origins and all production/non-Demo cases retain close code 4403.
- 4401/session-expired, REST CSRF/authentication, superseded and true network classification remain unchanged. Real network failures still require a manual single Reconnect.

### 16.5 Gate and workflow

- Three Luna Max workers own mutually exclusive implementation lines: locale-only controls; playback phase/Finish/Replay; and Origin validation. They do not self-sign.
- Main updates shared contracts, reviews every diff, runs full G1.5, then performs independent G2 with `P0=0/P1=0` and a fresh real-browser G3.
- G3 must cover both locales, navigation wording, leave/re-enter waiting, Finish disabled in progress, early/full Finish downstream boundaries, retained four-turn Replay with repeated cycle readiness, localhost and LAN teacher control, and true network manual-only Reconnect.
- Any mixed-language interactive control, cleared replay transcript, generation call during Replay, automatic network retry, downstream access after incomplete Finish, or non-loopback Origin acceptance stops the Gate.

### 16.6 G2 and main-window G3 evidence

- Main-window code audit found and closed all in-scope P0/P1 findings: arbitrary Host/Origin trust, incomplete-plan downstream leakage, missing waiting/live SQL Finish CAS, same-event Next→Finish, terminal controller noise, Replay phase/Finish contradictions, and completed-page Replay disabled after refresh. Final delta result is `G2 PASS / P0=0 / P1=0`.
- Backend passed `433/433`; frontend passed `28 files / 193 tests`. Ruff format/check, mypy (`109 source files`), ESLint, TypeScript, Prettier, Next production build and `git diff --check` passed.
- Contract and migration checks passed: Redocly/generated OpenAPI, 69-operation response surface, generated WebSocket schema/fixtures, events `30/18`, commands `6/7`, private results `5/6`, route comparator `13` negatives, deterministic Latin tables, repository/secret boundary, bootstrap safety, and 0001–0007 migration probes with foreign-key checks empty.
- Real-browser G3 passed both English and Chinese locale-only controls, `Back to debate list`, draft `Ready`, live `In progress → Waiting`, waiting persistence across navigation, Finish disabled while in progress, early Finish with one retained turn and no downstream link, and natural completion with four retained turns.
- A real backend restart left the page at `Connection lost` for multiple seconds with no background retry; one manual Reconnect restored the same `Waiting` turn and transcript. Stopped/completed pages showed no Reconnect, invalid-state alert, or controller-waiting noise.
- Two complete Replay cycles used the retained four-turn transcript and sources, required teacher Next between turns, made no regeneration call, and returned to terminal with Replay available. The second cycle started from a freshly loaded LAN teacher page through one on-demand same-socket controller acquire; Replay playing showed `In progress`, Replay waiting showed `Waiting`, and no Finish control was rendered.
- The configured LAN origin remained the QR/public origin. Authenticated teacher REST and WebSocket control succeeded from both `localhost:8080` and the configured LAN gateway. The strict negative origin matrix retained 4403 for wrong port/protocol, malformed origins, other private hosts and non-Demo use.
- The completed classroom flow accepted one anonymous vote and one named raw barrage, froze the interaction, generated one ready Mock insight and a 611-word report, and completed a `5/5` Mock translation batch. No real Provider or billed call occurred.

G2 and G3 both pass. Wave 3 is signed `WAVE_3_G3_PASS / READY_FOR_WAVE_4`. This permits planning the Wave 4 G0 contract only; Wave 4, real LLM/Embedding/TTS, formal TikTok content acceptance, 30–60 participant load, licensing/privacy and public deployment remain unstarted or separately gated.
