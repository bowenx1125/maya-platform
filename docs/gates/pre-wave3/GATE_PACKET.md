# Pre-Wave 3 Polish Gate Packet

Gate ID: `g0-2026-08-28.7-pre-wave3-polish`

Status: `FROZEN / G0-S PASS / G1 AUTHORIZED 2026-08-28`

This packet records product decisions already made by the user. Independent Sol High G0-S review passed with `P0=0 / P1=0 / P2=0` after closing stable account identity, delete/publish concurrency, description-history separation, Markdown replacement atomicity and replay/API/migration semantics. The user explicitly authorized execution on 2026-08-28 with the exact Gate ID; Luna workers may now start within the ownership and stop conditions below.

## 1. Scope

This delta completes the final Wave 2 usability/data changes before Wave 3:

1. always-visible Demo identity quick login and a user-editable private Markdown account catalog;
2. safe hard deletion of Agents with no published or debate history;
3. authoritative return from Agent detail to its group workspace;
4. empty Agent descriptions render as empty, never as invented fallback copy;
5. inline Agent description editing with CAS and immediate student/teacher projection;
6. a three-button teacher playback Dock and teacher-paced whole replay;
7. teacher navigation reduced to Home and Classroom Debate;
8. responsive login/student-home alignment across desktop, iPad and phone;
9. browser Markdown create/edit with immutable copy-on-write replacement and automatic draft propagation.

## 2. Explicitly Out of Scope

- no Mock/real LLM switch, login-page provider button or placeholder mode;
- no real LLM adapter, model/provider DTO, structured-output integration or paid text call;
- no TTS retry or fallback activation;
- no Wave 3 M13-M15 implementation;
- no public Git push, PR, cloud/public deployment or reference-code copying.

Real LLM adapter, strict structured output, cost controls and debate-level provider freezing remain a separate real-service Gate/Wave 4 concern.

## 3. PW3-A — Demo Auth and Private Accounts

### Product contract

- When both `DEMO_MODE=true` and `DEMO_QUICK_LOGIN=true`, the anonymous login page always lists every active Demo identity and allows passwordless login.
- The user explicitly accepts that every client able to reach the Demo site, including LAN clients, can select teacher or student identities. No localhost-only restriction is added in this Demo.
- Password login remains available as a collapsed fallback.
- With either flag disabled, anonymous identity catalog and quick login return 404.

### Private configuration

`backend/config/demo-accounts/` contains:

- tracked `README.md` and secret-free `accounts.example.md`;
- untracked, Docker-ignored, mode-0600 `accounts.private.md`.

The private Markdown schema is strict: immutable `account_key`, username, display name, plaintext Demo password, `teacher|student`, and group key. `account_key` is a short stable key mapped to the existing seeded User UUID; it is not a browser-facing login field. A new account requires a new unique key. Renaming username or removing/re-adding a row with the same key never changes the historical User UUID. Teacher group is empty; student group is required and must resolve to a seeded group.

`accounts.private.md` is the sole runtime credential/account source after this Gate. Existing `demo_users.yaml` is accepted only as an explicit one-time migration/rollback backup and is never dual-read or allowed to override the Markdown catalog by load order.

Backend restart first parses and validates the complete file into a desired identity/membership graph, then performs one `BEGIN IMMEDIATE` SQLite writer transaction:

- add/change row: upsert User/CourseMember/GroupMember and password credential;
- removed row: revoke sessions, remove current membership and set User inactive;
- re-added same `account_key`: reactivate the original User UUID and apply the desired membership;
- any password, username, role, group or active-state change: revoke all existing sessions for that User;
- never physically delete a User referenced by history;
- duplicate account key/username/user identity, missing fields, invalid role/group or parse error fails closed without partially applying the catalog and prevents application readiness.

Browser-facing identity DTO contains only platform user ID, display name and teacher/student role. It never contains account key, username, password/hash, group key, membership detail, configuration path or raw Markdown. Structured logs and errors have the same exclusion; deterministic tests probe DTOs and logs for every prohibited field and raw source line.

## 4. PW3-B — Agent Metadata and Safe Delete

- Add `Agent.metadata_revision` for CAS-protected description updates.
- Empty/null/whitespace description renders empty on student home and group workspace. No fallback product copy is inserted.
- Inline editing is available to same-group students; cross-group is 404. Successful edits immediately update current student and teacher projections.
- Description is mutable Agent metadata only. Student/group cards and teacher current-Agent cards read it and refresh after a successful CAS. It never mutates AgentVersion revision, frozen AGENT.md, KnowledgeSnapshot, historical DebateParticipant or any debate input.
- Published-version history rows, frozen-download views and existing debate/replay pages do not read or display mutable description. If a teacher page shows the current Agent header while a historical snapshot is selected, it labels that header as current metadata and keeps it visually separate from the frozen version. This Demo does not add `frozen_description` or backfill current text as historical truth.
- Agent detail has an explicit return link to `/student/groups/{group_id}` and warns before discarding dirty edits.
- Replace archive/unarchive with `DELETE /agents/{agent_id}`.
- Hard delete is allowed only if the Agent has never had a published/superseded AgentVersion, KnowledgeSnapshot, DebateParticipant or any other historical reference.
- Eligibility is rechecked and deletion is performed inside one `BEGIN IMMEDIATE` writer transaction. Publish, Debate creation and delete use the same final writer/foreign-key defense; delete versus publish/Debate creation can have only one winner.
- Eligible delete removes Agent, draft AgentVersions, draft associations and Agent-owned test state. It does not delete group KnowledgeDocuments, VoiceProfiles, AuditLogs or other Agents.
- Current Agent drafts store AGENT.md in SQLite and reference group-owned files, so this Gate performs no file deletion. If implementation discovers an Agent-owned file, the Gate stops until a typed file journal/recovery contract is added; DB commit followed by unjournaled file deletion is forbidden.
- Ineligible delete returns stable 409 `agent_history_retained`; cross-group is 404; teacher cannot delete.

Concurrency acceptance includes delete versus publish, delete versus Debate creation, double delete, cross-group, teacher, existing Snapshot, existing DebateParticipant and a formerly published Agent that now also has a draft.

No migration may silently delete the currently archived Agents. The user deletes eligible rows explicitly through the UI.

## 5. PW3-C — Markdown Create and Copy-on-Write Edit

### Create

- Knowledge page accepts filename plus Markdown text.
- Frontend may reuse the existing upload pipeline through a generated `.md` File/Blob.
- New document enters the group library and is not automatically enabled on any Agent draft.

### Edit

- Never overwrite old file bytes, chunks, vectors or hashes.
- Create a new immutable KnowledgeDocument replacement in `staged/pending`; staged data is not visible in the group library, upload candidates or any draft.
- The request names the old document ID and expected old content/index revision or hash. Concurrent edits of the same source can have only one winner.
- Write, chunk and index the staged replacement first through a typed file operation journal that supports promote, rollback and restart recovery.
- On success, atomically replace the old document association in every current `draft` AgentVersion in the group that references it.
- Increment each affected draft revision.
- Validate each resulting draft against the 100,000-character limit.
- Replace both enabled and disabled associations; only enabled associations count toward 100,000 characters.
- Capture the complete referencing-draft set and their revisions before staging. In the final `BEGIN IMMEDIATE` transaction, reread that full set, confirm every captured version is still the current draft with the expected revision, confirm the reference set has not changed, recalculate every enabled total, CAS-update all affected drafts and promote the replacement.
- Publish and another edit share the same final writer/CAS boundary. If any draft was published, its revision/reference set changed, or any result exceeds the limit, the entire switch fails.
- Any indexing, limit, CAS, file or database failure leaves the old workspace document and every draft unchanged; journal recovery removes or finishes staged bytes/chunks/vectors and never exposes an active orphan.
- Agents with no current draft and all published/superseded versions, KnowledgeSnapshots and existing debates remain unchanged.
- If no draft references the document, the successful replacement still becomes the current group-library document. Old workspace document becomes hidden only when no current draft association references it. Published snapshot/source bytes and hashes remain immutable.

### Frozen downloads

Students in the owning group and course teachers can download frozen published `AGENT.md`, combined RAG and source Markdown. Filenames append sanitized Agent name and version, for example:

- `AGENT--Bowen--V1.0.md`
- `RAG--Bowen--V1.0.md`
- `evidence--Bowen--V1.0.md`

For multiple source files, each keeps a sanitized original base name followed by Agent name, version and a stable ordinal, for example `evidence--Bowen--V1.0--01.md`; the ordinal disambiguates duplicate sanitized names. `Content-Disposition` uses a safe ASCII fallback plus RFC 5987 UTF-8 `filename*`, rejects path/control characters and is covered by same-group student/course-teacher authorization. Downloads never mutate or re-enable workspace data.

## 6. PW3-D — Three-Button Playback and Stepwise Replay

The ordinary teacher playback Dock contains exactly:

1. Start Debate;
2. Next;
3. Replay Whole Debate.

Pause, Resume, Skip, Stop, single-turn replay and playback-retry buttons, labels, browser client calls and genuinely unreachable frontend branches are removed.

The final ordinary REST surface retains `startDebate`, `advanceDebatePlayback` and `replayDebate`. It removes ordinary `pauseDebate`, `resumeDebate`, `skipTurnPlayback`, `stopDebate` and `replayDebateTurn` routes plus generated-client methods. Debate read/list/update, transcript, WebSocket, authenticated media and later-Wave placeholder routes are unchanged. WebSocket controller acquire, `media.prepare`, `playback.started_ack`, `playback.ended_ack`, `playback.play_failed`, snapshot/watermark/gap recovery and controller fencing remain protocol primitives; implementation must not delete safety behavior merely to reduce line count.

### Live

- Start exposes/plays only the first planned turn.
- Natural end enters durable live `waiting_next`.
- Next performs CAS and advances exactly one adjacent ready turn.

### Replay

- Replay uses retained text, sources and audio; it never invokes RAG, LLM or TTS.
- Replay resets the visible classroom prefix to the first turn and plays it.
- Each replay turn end enters durable `mode=replay + waiting_next`.
- The same Next control advances exactly one adjacent retained turn.
- Authoritative REST/snapshot state is `status=waiting_next`, `mode=live|replay`, `current_turn_id=<completed turn>`, `control_version` and `next_turn_ready`. `playback.waiting_next` carries the same mode, completed turn, control version and readiness. In replay, readiness is true only when the unique adjacent public turn in the frozen replay list passes current-course audio pointer, active StoredFile, canonical path, size, SHA-256 and decodable-WAV checks.
- A native replay `ended_ack` never prepares the successor. Successful Next CAS alone selects the unique adjacent turn, advances `control_version` and permits exactly one `media.prepare`.
- Refresh, reconnect, process restart, multitab and stale CAS remain at the same replay gate and never auto-advance.
- Final turn end emits replay completed, clears controller epoch, media ticket, replay queue/index and current replay cursor, and restores the complete historical transcript without a new provider call.

Migration `0006` must align PlaybackState constraints/indexes with replay waiting-next without weakening live invariants. Downgrade maps `mode=replay + waiting_next` to a non-playing `mode=live + status=completed`, clears replay queue/index/controller/ticket/cursor, and preserves turn/current-course/history rows; old code must never resume automatic replay after downgrade.

Operator reset has one entry only: a local backend CLI requiring explicit debate ID and confirmation. It is absent from OpenAPI, generated browser client and ordinary UI. Inside one writer transaction it revokes controller epoch/tickets, cancels or fences incomplete tasks, increments control version and writes an AuditLog; an abnormal live run becomes safely stopped, while abnormal replay returns to completed full-history view. Reset versus Next is serialized and only one can win.

## 7. PW3-E — Shell, Teacher Information Architecture and Responsive UI

- Teacher primary navigation is exactly Home and Classroom Debate. Language, account identity and Logout remain account tools.
- Home shows current course and published Agent cards. Agent detail includes producing group, current description, published/history versions, frozen AGENT.md/RAG/source downloads, 3D preview and platform voice state.
- Teacher capability copy explains inspect/create/control/history and explicitly says no student draft editing/viewing.
- Classroom Debate contains create, current/history list and control entry.
- A single student group card spans the available desktop width; two cards may use two columns.
- Login uses a wider Demo-identity/password-fallback composition on desktop and a single column on tablet/mobile.
- Visual Draft V2 typography, color and tone remain unchanged.

Responsive acceptance sizes: 1440×900, 1280×720, 1024×768, 768×1024, 390×844 and 360×800. Every size requires no horizontal overflow, unobscured navigation, at least 44px touch targets, usable long bilingual copy, description editing, Markdown editor and exactly three ordinary playback controls.

## 8. Shared Contract and Migration Delta

Main owns changes to shared OpenAPI/generated client, WebSocket schemas, route-response allowlists, migration `0006`, i18n and CI checks. Workers propose module fragments but do not race on shared files.

Expected contract changes include:

- anonymous Demo identity catalog and quick-login;
- Agent metadata PATCH and safe DELETE; archive/unarchive removal;
- KnowledgeDocument replace operation and frozen filename behavior;
- replay waiting-next REST/WS semantics and operator reset boundary;
- removed ordinary single-turn replay and other unused browser controls.

## 9. Implementation Ownership

- `PW3-A`: Luna Max owns auth/private-account module and focused tests.
- `PW3-B`: Luna Max owns Agent metadata/delete service and Agent UI components/tests.
- `PW3-C`: Luna Max owns a new knowledge editor service/component boundary and tests; do not expand existing large Agent files.
- `PW3-D`: Luna Max owns playback state-machine delta and stage component split/tests.
- `PW3-E`: Luna Max owns AppShell/teacher/student responsive UI and tests.

Each Gate has a dedicated Sol High design/code audit. Main freezes contracts, assigns disjoint files, integrates shared artifacts, runs deterministic checks, audits diffs and performs Docker/browser acceptance.

## 10. Required Gate Sequence

Each module independently executes:

`G0 → G0-S → G1 → G1.5 → G2 → G3`

No Luna implementation starts until this packet is Sol-audited and the user explicitly says it may execute.

## 11. Deterministic Acceptance Minimum

- Auth: anonymous/no-cookie identity cards always visible in Demo; every catalog account can quick-login; disabled flags 404; stable account-key rename/remove/re-add; all material changes revoke sessions; complete parse/desired-graph/sync rollback; deleted account loses login and membership but history UUID remains; old YAML is not dual-read; no account key/username/password/hash/group/path/raw line in DTO/log/Git.
- Agent: empty/filled description desktop/mobile/keyboard; metadata CAS conflict; current teacher/student projection; frozen/history pages never imply current description is historical; dirty-return prompt; eligible delete then 404; published/debate delete 409; delete/publish and delete/Debate races; double delete; cross-group/teacher rejection; FK/history/audit/group files unchanged.
- Knowledge: create; staged replacement invisibility; concurrent-edit single winner; enabled/disabled multi-draft automatic replacement; revision increments; edit/publish race; 100k all-or-nothing; indexing/file/DB/CAS/crash rollback and restart recovery; no active orphan; published snapshot byte/hash/download unchanged; duplicate-name ordinal and safe Content-Disposition.
- Playback: only three controls and only Start/Next/Replay ordinary control operations; live A1/B1/A2/B2 manual Next; replay A1/B1/A2/B2 manual Next; no `ended_ack` auto-prepare and no new generation jobs; refresh/reconnect/restart/multitab/stale CAS; missing/corrupt/old-pointer replay; operator reset versus Next; migration fresh/repeat/populated/downgrade/re-upgrade with replay-waiting downgrade mapping.
- UI: teacher two-link navigation; group name/details; desktop/iPad/mobile matrix; no overflow; 44px targets; no Visual Draft V2 drift.
- Global: frozen install, lint, typecheck, frontend/backend tests, OpenAPI/Redocly/generated clean diff, WS fixtures, strict route semantic comparison, repository/secret boundary, Compose and healthy Docker browsers.

## 12. Stop Conditions

Stop the affected Gate for any unreviewed change to published snapshot immutability, historical deletion, cross-group permissions, Session/CSRF, replay adjacency, provider calls/costs, TTS/LLM selectors, Wave 3/4 scope, public deployment or destructive migration. Other independent Gates may continue.
