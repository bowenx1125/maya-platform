# Wave 1B Gate Packet — M07 Avatar + M08 Voice/TTS

Status: `G3 PASS (MOCK RUNTIME) — REAL FALLBACK TTS ACCEPTANCE PENDING`
Authorized scope: `2026-08-27 Asia/Shanghai`
Modules: `M07 3D avatar templates` and `M08 voice cloning / fallback / TTS`
Dependencies: `Wave 0 G3 PASS`, `Wave 1A G3 PASS`, frozen `g0-2026-08-26.4`
G0-S audits: domain `/root/wave1b_design_domain` and security `/root/wave1b_design_security`, both `gpt-5.6-sol high`, final `PASS` at `2026-08-27 03:23 Asia/Shanghai` after one bounded correction round
G1 implementers: M07 `/root/wave1b_m07_luna`; M08 `/root/wave1b_m08_luna` with bounded completion `/root/wave1b_m08_finish`; all `gpt-5.6-luna max`
G1.5 main sign-off refreshed: `2026-08-27 05:39 Asia/Shanghai`
Initial product commit: `d4e5c0830344fed6f019f6a77f62f513fd01f2d0`
Initial Project SHA-256: `8bc10962be81f603c92db7406cde470e234b0da7a3cb8f558edbc0e17a7849c9`
Initial Git state: clean

## 1. Goal and non-goals

Wave 1B completes the provider-neutral avatar and voice resources that a published AgentVersion and later DebateParticipant can freeze and consume.

M07 goal:

- expose the frozen `AvatarTemplate` catalog through the existing platform API;
- replace the Wave 1A sentinel with a validated template/parameter catalog without changing `AvatarConfig`;
- render a local head/head-shoulder 3D preview and the frozen states `idle`, `listening`, `speaking`, `thinking`, `nod_yes` plus `attentive` expression;
- provide three selectable built-in presets over compatible local assets/configuration, while reporting the exact number of distinct underlying compatible assets honestly;
- preserve a static name/avatar fallback only for asset-load failure, not as the primary M07 acceptance.

M08 goal:

- implement group-scoped VoiceProfile enrollment, list/detail, preview, confirmation, deletion and Agent draft binding using the six already-frozen operations;
- implement Mock and real server-side `VoiceCloneProvider` and `TTSProvider` ports with the same platform behavior;
- create one system-scope `System English Fallback` platform VoiceProfile through a private operator command, then let all Agents without a ready custom profile resolve to its internal platform ID;
- prove sample files and enrollment intermediates are deleted on success, validation failure, provider failure, timeout and cancellation;
- keep the supplier identity, model, key, raw response, external voice ID, Base64 audio, supplier URL and absolute/private path out of browser DTOs, Git and normal logs.

Non-goals:

- no Debate, playback state machine or retained classroom audio (M10-M12);
- no Wave 3 interaction, Maya report, history or translation;
- no real Embedding and no mutation/rebuild of existing KnowledgeSnapshot vectors;
- no custom GLB upload, body/full-scene editor, precise lip sync, Lincoln likeness or public asset-license sign-off;
- no subjective fallback-voice approval; the authorized system fallback uses technical acceptance only;
- no deletion/rotation of the system fallback during the unattended run.

## 2. Frozen operations and contract impact

M07 implements exactly:

- `listAvatarTemplates`
- the already-implemented `updateAgentDraft` avatar branch now validates the catalog instead of the Wave 1A sentinel.

M08 implements exactly:

- `listVoiceProfiles`
- `enrollVoice`
- `getVoiceProfile`
- `deleteVoiceProfile`
- `createVoicePreview`
- `confirmVoiceProfile`
- the already-implemented `updateAgentDraft` voice branch now validates group ownership and `ready` state.

No public operation or browser-visible field is added. `PlaybackResource.playback_url` is an opaque, short-lived, same-origin media capability URL returned by the frozen API; the browser never assembles a supplier URL. The media transport is not a second business DTO and must be guarded by an unguessable expiring token, content type, no-store headers and group/session scope before bytes are returned.

After G1, the strict route surface must contain exactly 40 implemented operations (`33 + 7`) and 27 later-wave placeholders. The frozen parent/product OpenAPI and generated schema remain byte-identical.

## 3. Database and migration contract

Migration head becomes `0003_wave1b_avatar_voice` and must preserve populated `0001 -> 0002` data byte-for-byte.

### 3.1 Voice tables

`voice_profiles`:

- `id` platform UUID, `scope=system|group`, nullable `group_id` with the exact system/group nullability check;
- `display_name`, `status=validating|enrolling|preview_ready|ready|deleting|outcome_unknown|failed|deleted`;
- internal `provider_key` and `target_model_key`; neither is projected to the API;
- authenticated encryption of the external voice identifier at rest; plaintext external ID is never stored;
- unique deterministic `recovery_name` used only for provider list/reconciliation after an ambiguous create;
- safe `source_filename`, consent copy/version/actor/time metadata and safe error code; no sample bytes/path/transcript;
- one immutable system fallback row is allowed to be selected by `FALLBACK_VOICE_PROFILE_ID`; students cannot mutate it.

`voice_provider_operations`:

- durable charged-operation ledger with `prepared|dispatched|reconciling|succeeded|failed|outcome_unknown`, operation/profile, attempt number, claim token, provider deadline, safe request/cost counters and timestamps;
- the row is committed as `dispatched` before a provider request leaves the process; an expired generic idempotency lease cannot authorize another create/delete while this ledger is dispatched, reconciling or outcome-unknown;
- provider completion updates use `(operation_id, attempt, claim_token, current_state)` compare-and-swap so a stale worker cannot overwrite recovery or spend a second attempt;
- a database uniqueness guard permits only one system fallback profile and one active fallback enrollment operation.

`voice_previews`:

- one short-lived preview resource per request with a random non-secret platform UUID, profile/group ID, relative stored-file reference, expiry and state;
- the UUID is only a resource locator: the media GET always requires the current same-group Session and never relies on a URL capability secret;
- expired/confirmed/replaced previews lose their file reference and are physically removed through the existing file containment helpers.

Existing `agent_versions.voice_profile_id` becomes a restrictive FK only if SQLite migration can prove populated preservation without table-loss risk; otherwise the service plus migration checks enforce the same invariant and the physical FK is deferred. Historical version references remain after a profile becomes `deleted`.

### 3.2 Secret mapping

- external voice IDs use `cryptography` HKDF-SHA-256 to derive a 256-bit voice-mapping key from the existing server secret with a fixed versioned purpose string, then AES-256-GCM with a fresh random 96-bit nonce;
- the versioned envelope stores only version + nonce + ciphertext/tag. AAD binds profile UUID, scope, nullable group ID, provider key and target-model key, preventing cross-row/provider substitution;
- decryption is limited to provider adapters after profile/scope authorization;
- wrong key/corrupt ciphertext returns a safe internal failure and never logs the value;
- key-purpose separation is explicit in the derivation context so session tokens and voice mappings do not reuse raw key material.

## 4. M07 avatar contract

### 4.1 Catalog and validation

- catalog entries are server-owned immutable configuration with stable IDs, names, `available` and supported parameter names. The exact Demo IDs are `wave1-default-head`, `maya-warm-scholar` and `maya-civic-observer`;
- all three presets use the currently inspected compatible base asset but different defaults. `wave1-default-head` preserves the existing `material_theme=demo`; new defaults are `warm_sand` and `civic_olive`. Internal material allowlist is `demo|warm_sand|cool_slate|civic_olive`; eye allowlist is null or `brown|hazel|blue|green|gray`;
- only catalog IDs marked available can be saved or published;
- expression/strength/motion values remain exactly the frozen enums. The internal material/eye allowlists narrow the two frozen free-string fields without changing their schema; unsupported values return the existing stable business envelope;
- existing draft/published JSON using `wave1-default-head/demo` remains valid and is never rewritten. Populated migration/runtime tests fingerprint these rows;
- a new draft and next-version clone preserve their exact avatar config; published versions remain immutable;
- templates may share one compatible base mesh as distinct parameter presets, but G3 evidence must separately report preset count and distinct compatible asset count. Presets may not be misreported as three independently modeled characters.

### 4.2 Rendering

- the browser renderer is a small isolated component/adapter, not an addition to the existing 1,429-line Agent workspace;
- local assets live below product-owned static paths; no runtime CDN, model supplier or reference-repository path appears in the bundle/API;
- material/eye color/default expression/strength/motion style are applied from the frozen config;
- `speaking` drives a deterministic approximate mouth animation; `listening + attentive`, `thinking`, `nod_yes` and idle motion are visibly distinct without textual status labels on the future classroom stage;
- renderer cleanup disposes animation frames, geometry/material clones and listeners on unmount;
- a load failure shows a safe static avatar/name and does not break the editor. It remains a visible degraded state and cannot be used to claim 3D compatibility.

Reference question: how a view adapter maps stable platform avatar states onto one render loop and cleans up resources.

Allowed principles: catalog-driven capability validation, adapter boundaries, state-to-animation mapping, deterministic UI tests and local asset loading.

Forbidden reuse: any source fragment, component, loader wrapper, state object, animation code or test from TalkingHead, MotionEngine, OpenAvatarChat or other references. Third-party npm packages and their runtime decoder assets may be used under their own license with pinned versions and notices.

## 5. M08 file, provider and state contract

### 5.1 Input and temporary files

- accept only WAV 16-bit, MP3 or M4A, at most 10 MB, after content probing rather than extension trust;
- require `consent_accepted=true`; group enrollment records uploader/time/copy version without retaining the sample;
- receive uploads with an M08-specific counted streaming reader; never call unbounded `request.body()`. Exceeding 10 MB or disconnecting aborts immediately;
- copy input into a controlled UUID request directory under `DATA_ROOT/tmp/voice-enrollment`, mode 0700/0600;
- invoke FFmpeg with fixed argv and paths, `shell=False`, closed unrelated descriptors and a hard timeout to create WAV PCM signed 16-bit, 24 kHz, mono;
- timeout/cancellation performs terminate, bounded wait, kill if required, final wait and handle close before cleanup;
- validate decoded duration 10-20 seconds for the Demo, nonempty audio and decodability before provider use;
- Base64 data URI exists only in server memory for the outbound request and is never logged/persisted;
- one `finally` cleanup removes request copies/intermediates on every outcome. Startup cleanup accepts only controlled UUID directory names, rejects symlinks and removes only non-active directories older than the safety threshold/operation lease;
- Base64 is created only in the smallest outbound provider-call scope from the validated WAV, SDK/HTTP body debugging is disabled, and references are released after the call.

The private system-fallback source is read-only. The operator command copies bytes into the same request pipeline and never moves, chmods, edits or deletes the source.

### 5.2 Provider selectors and endpoints

The actual code-defined selector values are `mock` and `dashscope`. They remain server-only.

- frozen domain Port remains `VoiceCloneProvider.enroll/exists/delete`; DashScope list pagination/recovery-name matching is a private adapter implementation of `exists` and never a public/provider-branded DTO;
- `TTSProvider.synthesize`
- DashScope voice creation uses `qwen-voice-enrollment`, target `qwen3-tts-vc-2026-01-22`, Beijing credentials and Base64 WAV data URI;
- DashScope TTS uses the same target model; a non-streaming supplier URL is downloaded server-side, validated and never returned to the browser;
- connect/read/total timeouts are explicit. Retry policy is per operation: `exists/list` may retry once; charged enroll never repeats until durable reconciliation proves no created result and the remaining attempt is atomically claimed; delete reconciles before a retry; real TTS may retry once as authorized tonight, then stops without an invented fallback;
- provider exceptions are converted to safe platform error codes with request ID and exception type only in logs.

Supplier audio downloader is a dedicated server-only component: HTTPS only; exact approved DashScope result-host suffixes; no userinfo, IP literal, localhost/private/link-local/reserved resolution; connection bound to an approved resolved address with peer verification; redirects disabled or each hop fully revalidated; no Authorization forwarding; streamed byte cap, content probing and total timeout. Supplier URL and redirect values never enter logs or storage.

### 5.3 Enrollment idempotency and ambiguous outcomes

- public enrollment first claims the existing actor/operation/idempotency record using a canonical hash of group, safe filename, audio SHA-256 and consent metadata;
- a platform profile and unique recovery name exist before the first charged create;
- success stores only encrypted external mapping and `preview_ready` state;
- the durable provider ledger is committed `dispatched` before the request. A process crash, expired 10-second generic lease or timeout forces `reconciling/outcome_unknown`; it can never jump directly to another create;
- a same-key retry must list and reconcile the recovery name/target before any second create. Exactly one recovered match completes the original profile; multiple matches or unclear visibility/billing stops in `outcome_unknown`;
- zero matches allow one remaining create attempt only after the provider visibility window/deadline has elapsed and an explicit operator/student retry atomically advances the attempt counter; system fallback ambiguity never permits another create during this unattended run;
- same key/same hash replays, same key/different hash conflicts, and stale workers cannot overwrite a recovered outcome;
- enrollment and delete both freeze canonical request hashes, same-key replay, different-hash conflict, stale-worker CAS and every pre/post-dispatch crash boundary;
- system fallback enrollment has an additional database uniqueness/command lock: at most one successful platform fallback create. If the row/mapping or provider list is ambiguous, stop real calls and keep Mock work moving.

### 5.4 Preview, confirmation, deletion and fallback

- custom group enrollment ends at `preview_ready`; preview synthesizes a new English sentence that differs from any sample transcript and returns a short-lived platform playback URL;
- group confirmation changes only `preview_ready -> ready`; it never calls enrollment again;
- system fallback operator flow performs preview synthesis plus technical audio checks, then marks the system profile `ready` without subjective confirmation;
- students can delete only a profile in their group. `ready/preview_ready -> deleting` makes all new effective resolution fall back before the external delete call;
- delete success becomes `deleted`; ambiguous timeout becomes `outcome_unknown` and list reconciliation precedes any later request;
- published historical `voice_profile_id` remains; effective resolution returns the ready custom platform ID only when valid, otherwise the configured ready system platform ID and `voice_fallback_active=true`;
- if no configured ready fallback exists, the API reports an unconfigured fallback state and Debate start must later fail rather than inventing browser speech/silence.

`UpdateAgentDraftRequest.voice_profile_id` has three distinct meanings: field absent means no voice change; explicit null clears a custom binding and restores effective fallback; UUID binds only a same-group `ready` profile. Pydantic/service code must preserve this distinction. Student, historical-published and teacher projections all call one dynamic effective resolver; profile deletion never rewrites immutable historical IDs.

The C08.4 teacher-only rule applies to retained Debate audio. Voice preview media is separately same-group student-authorized, profile/resource/expiry bound, cross-group 404 and `Cache-Control: no-store`. Its hidden media handler is transport-only, excluded from the business OpenAPI and 40-operation route count; the returned URL remains an opaque server-generated value, not a browser-assembled API contract.

### 5.5 Technical fallback acceptance

The single authorized fallback enrollment may run only after this packet receives G0-S PASS and the secure pipeline passes Mock/security G1.5. Acceptance:

1. one successful fallback create at most;
2. a new English TTS sentence succeeds, with at most one retry; both attempts and result are counted safely;
3. downloaded/normalized PCM16 24 kHz mono audio decodes to end, is 1-60 seconds, has RMS amplitude at least 100, at least 1% nonzero samples and fewer than 5% samples at absolute amplitude >=32760;
4. opaque same-origin platform playback URL returns the audio to an authorized session and expires;
5. an Agent with no custom voice projects the internal fallback platform ID and `voice_fallback_active=true`;
6. request temp directories are empty and the user source metadata/content hash are unchanged;
7. report states that deleting platform temp files does not delete the supplier-side cloned voice.

## 6. Permissions and provider-neutrality

- same-group students may list/create/preview/confirm/delete/bind group profiles;
- other-group students and outside-course actors receive uniform 404 for list/detail/media/bind/delete;
- teachers may inspect the effective state attached to published versions but do not mutate student profiles through these routes;
- system profiles are visible only as platform fallback semantics needed by the current Agent; no private provenance/source is exposed;
- frontend/network/OpenAPI/WS responses recursively reject `provider`, `model`, `key`, `api_key`, `external_voice_id`, supplier hostname/URL and absolute paths.

Settings validate provider selectors against exactly `mock|dashscope`. `EMBEDDING_PROVIDER` must remain Mock. Real acceptance commands take an exclusive local lock and permit at most one of `VOICE_PROVIDER`, `TTS_PROVIDER` and `LLM_PROVIDER` to be non-Mock at a time: fallback enrollment runs with Voice real only; technical preview runs later with TTS real only. Unknown/mixed real configuration fails closed before an external request.

## 7. File ownership and decomposition

Main/contract owner:

- `docs/gates/wave1b/**`, shared migration/contract integration decisions, route placeholder/fixture regeneration, final Project/V2 update;
- approval of new dependencies and local product asset/notice files.

Luna M07 owner:

- new `backend/app/modules/avatars/**` and isolated avatar backend tests;
- new `frontend/components/avatar/**`, M07 pages/tests and explicitly assigned avatar assets/styles;
- only narrow delegated edits to draft avatar validation/UI call sites.

Luna M08 owner:

- new `backend/app/modules/voices/**`, `backend/app/providers/**` voice/TTS files, voice-specific tests/operator command;
- new `frontend/components/voice/**`, voices route/tests and narrow draft binding UI;
- must not put M08 logic into existing `knowledge/services.py`, `knowledge/router.py`, `agents/router.py` or 1,000+ line frontend components beyond a thin call/delegation.

Shared files (`core/models.py`, `main.py`, `platform.ts`, config, package/lock, migration, CI/contracts) have one owner at a time and are integrated by main or an explicitly assigned worker. Nobody edits Project, the parent frozen contract or V2 workbook except main.

## 8. Deterministic acceptance

M07:

- catalog stable order/IDs/capabilities; unavailable/unknown/invalid parameters rejected;
- draft revision/immutability/next-version clone and publish blocker behavior unchanged;
- renderer states and cleanup tested; local asset success plus intentional load failure; no runtime CDN/reference path;
- desktop/mobile editor has no overflow and preserves frozen V2 visual language.

M08:

- `0002 -> 0003`, fresh head, repeated head and populated preservation;
- format/content spoof/size/duration/decoding/consent validation; exact FFmpeg output format;
- success/failure/timeout/cancel/startup temp cleanup and no absolute paths;
- authenticated encryption round trip/wrong-key failure; external IDs absent from DB plaintext search, responses, browser bundle and logs;
- all enrollment idempotency/recovery branches including ambiguous provider outcomes and at-most-one fallback create;
- provider-ledger lease expiry, dual-command races, every pre/post-dispatch crash point, eventual-visibility zero/one/multiple recovery matches and exact safe call/cost counters;
- group/teacher/system permission matrix, draft voice binding and deleted-profile fallback;
- preview authorization/expiry/no-store, confirmation transition and deletion saga;
- Mock TTS produces valid nonempty WAV and exposes only platform playback URLs;
- streaming upload over-limit/disconnect, FFmpeg hang/cancel/kill-wait, symlink/active/aged startup cleanup and private/redirect/rebinding/oversize supplier-download rejection;
- AES-GCM nonce uniqueness, tag/nonce/ciphertext/wrong-key/cross-row swap failures and plaintext DB/log/repository scan;
- frozen OpenAPI/hash/Redocly/generated client/response/WS checks; strict 40 implemented/27 placeholder route comparison;
- full frontend/backend quality, all Wave 0/1A regression tests, migration smoke and Compose config.

G3 runtime (Mock): through `http://localhost:8080`, a student selects/renders an avatar, enrolls/previews/confirms/binds/deletes a group Mock profile, sees fallback resolve, teacher sees only published safe fields, other group receives 404, restart preserves safe records and leaves no enrollment temp files.

G3 real fallback is a separate bounded acceptance after Mock/security G1.5. A failure or ambiguous charged outcome cannot be converted into PASS or retried blindly; M07/M02/Mock work continues independently.

## 9. Stop conditions

Stop the affected Gate if implementation requires:

- changing the frozen public DTO/operation/error/state semantics;
- exposing a supplier/model/key/external ID/private path/Base64/audio sample to the browser, Git, Project, workbook or ordinary logs;
- storing or retaining the original voice sample;
- mutating/deleting the authorized user source or deleting/rotating the system fallback;
- a migration that cannot prove populated-data preservation;
- a second successful fallback enrollment or an external charged result whose outcome cannot be reconciled;
- deciding a new TTS failure user experience, browser speech/silence/text-only fallback, or Wave 2/3 behavior;
- copying any reference source fragment;
- public push/deployment or asset-license claims beyond the private local Demo exception.

## 10. Gate sequence and audit tier

`G0 Main draft -> G0-S Sol High design challenge -> G1 Luna Max -> G1.5 deterministic checks -> G2 Sol High independent audit -> G3 main sign-off`

- M08 is high risk and receives focused G0-S and G2.
- M07 renderer is low risk only while it remains presentation-only; catalog validation, dependencies/assets and published avatar semantics are included in the Wave 1B Sol review.
- Sol returns only `PASS` or `CHANGES_REQUIRED`, at most five blocking findings tied to this packet/frozen contract.
- Worker self-tests do not authorize the next Gate; main records every transition.

## 11. Initial read-only baseline evidence

- product HEAD `d4e5c08`, clean worktree, Wave 1A 33 implemented/34 placeholders;
- frontend lint/type/Vitest 22 tests/build PASS;
- backend Ruff/mypy/pytest 28 PASS with one existing Starlette/httpx deprecation warning;
- frozen OpenAPI/hash/generated types/responses, WS 29 positive/11 negative, route 12 negatives, boundary/secret probes and Compose config PASS;
- Docker client/server 29.3.1, Compose 5.1.1, all three services healthy;
- server selectors remain Mock; credentials/workspace/Beijing region are present, `.env` is 0600, Embedding remains Mock and fallback platform ID is not configured;
- the authorized source satisfies the known container/length/mode facts, but no provider call has occurred;
- local asset inspection found one GLB with 72 morph targets on eye/head/teeth meshes and no baked animations. This proves a promising input, not browser/TalkingHead compatibility or three distinct assets.

## 12. G0-S live evidence

- first domain review returned five bounded blockers: generic lease fencing, frozen Port/retry drift, legacy avatar compatibility, absent/null/UUID voice patch semantics and preview-media authorization/counting;
- first security review returned five bounded blockers: charged dispatch journal, supplier URL/preview logging, streaming upload and FFmpeg teardown, concrete AEAD envelope and provider activation/technical thresholds;
- main amended only the technical contract, preserving the public OpenAPI and latest user decisions. Both reviewers independently returned `PASS`; no code or real supplier call occurred during G0-S.

## 13. G1/G1.5 live evidence

- M07 provides three stable parameter presets over one honestly reported compatible morph-target GLB, a server catalog/validator, local Three.js/Draco renderer and original state-animation adapter. Backend M07 tests: 10;
- M08 provides migration `0003`, encrypted internal mappings, durable provider-operation ledger, streaming/FFmpeg/file cleanup, group voice API/UI and split enrollment/preview/deletion modules. The former 1,160-line service is split; the largest file is now `service.py` at 905 lines, while deletion, preview, upload, fallback and DashScope adapter state machines remain separate tested boundaries;
- the system fallback operator flow is explicitly two-stage: Voice enrollment stops at `preview_ready`; a separate TTS-only technical verification can mark `ready`, with at most one retry. Ambiguous enrollment only reconciles and never issues a second fallback create;
- the authorized M4A passed an isolated Mock two-stage run: final ready, request temp empty, source hash/mode unchanged. This did not call a supplier or create a real voice;
- backend Ruff/mypy and full pytest pass: 70 tests, comprising the prior 28, M07 10 and M08 32. Existing warnings are one Starlette/httpx deprecation and Python 3.12 SQLite datetime-adapter warnings in migration evidence;
- frontend Prettier/ESLint/TypeScript/Vitest/production build pass: 10 files/40 tests. jsdom reports expected non-failing canvas `getContext` notices;
- fresh/repeated and populated migration reaches `0003_wave1b_avatar_voice`; prior Wave 0/1A fingerprint and rows remain unchanged. The general migration script's 13-table/43-constraint count remains Wave 1A evidence; the dedicated M08 test separately reflects all three `voice_*` tables and their named checks, unique/partial indexes and foreign keys;
- the current Docker build serves a real Three.js r185 canvas at desktop and 360px. The student workbench exposes all three presets, applying Civic Observer's olive/gray/serious/active defaults; `speaking` changes the authoritative canvas state. Login, workbench and teacher pages have zero horizontal overflow and no browser warning/error, while all native enabled controls remain keyboard-focusable;
- frozen OpenAPI/hash/generated client/Redocly/response/WS checks, route positive+12 negatives, repository/secret probes and Compose config pass. Live FastAPI matches 40 implemented operations with 27 later-wave placeholders;
- all provider selectors remained Mock and real external call count is zero at G1.5. The real fallback enrollment/TTS acceptance remains a separate G3 operation after all G2 reviewers pass.

## 14. G2 live evidence

- focused M08 security/provider audit, final frontend audit and cross-contract/migration audit independently returned `PASS` after bounded corrections;
- the accepted corrections cover profile-CAS plus one-delete-ledger concurrency, complete provider pagination, IP-pinned supplier download with DNS/connect/read total deadlines, TTS timeout retry accounting, file-lock temp leases, frozen negative HTTP statuses, loaded-workbench error preservation and locale/preset/publish behavior;
- main reran the full deterministic suite and current Docker/browser matrix after the final corrections. No real supplier call occurred during G2.

## 15. G3 main sign-off

- `WAVE_1B_G3_PASS` applies to the complete Mock/local product contract. In an isolated Docker data root, the 8080 chain passed Agent creation, Mock voice enrollment, decodable preview, confirmation, Avatar/voice binding, Markdown snapshot publication, teacher safe projection, preview expiry, voice deletion, automatic fallback semantics, other-group 404 and backend-restart persistence. The delete ledger issued exactly one provider command, retained zero preview WAVs and left zero enrollment request directories;
- the isolated G3 data root and private HTTP cookie/audio scratch directory were moved to the user's Trash after verification. The normal Demo database was restored at migration head `0003`; all three containers are healthy;
- the three selectable Avatar parameter presets use one honestly reported compatible GLB. A real Three.js r185 canvas rendered in the browser at desktop and 360px, with preset defaults and state controls verified;
- the real system voice enrollment stage made exactly one charged create and succeeded. The source hash/mode remained unchanged and request temp count returned to zero. The supplier-side cloned voice remains present by design;
- the separate real TTS technical preview made two authorized attempts and both failed. The platform profile remains `preview_ready` with a safe `provider_unavailable` status; `FALLBACK_VOICE_PROFILE_ID` was intentionally not activated. No additional real retry, invented silence or browser speech was used;
- real external counts: Voice enrollment `1`, TTS preview `2`, LLM `0`, Embedding `0`, translation `0`. Estimated supplier cost remains below CNY 0.03 before any account free quota. This unresolved real TTS acceptance is explicit and does not invalidate the user-authorized Mock Wave 2 path.
