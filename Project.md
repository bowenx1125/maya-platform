# Maya Platform Project Handbook

Last updated: 2026-08-29

This file is the concise operational authority for the Maya Platform repository. The original teacher requirements remain in `AI文化互鉴教学平台-需求文档.md`; historical design detail remains in `docs/pre-code-contracts/` and Git history.

## 1. Working rules

1. Read this file before changing the repository.
2. Confirm the active Wave, scope, contracts, file ownership, and acceptance criteria before implementation.
3. Prefer the smallest verifiable change. Do not perform broad refactors while high-risk Wave 3 code remains unaudited.
4. Never copy source code from reference repositories. References may inform interaction, architecture, state-machine, and testing ideas only.
5. Browser-facing DTOs must remain provider-neutral. API keys, supplier URLs, external voice IDs, local paths, passwords, and session secrets must not enter frontend responses or logs.
6. CI and ordinary automated tests use Mock providers only. Real-provider calls require a separate explicit Gate and cost authorization.
7. Luna implements; Sol performs independent risk review and coordinates Gate decisions. An implementation worker cannot approve its own Gate.
8. Update this file, `docs/PROJECT_STATUS.md`, and `开发文档.xlsx` when the authoritative project state changes.

## 2. Document precedence

When documents conflict, use this order:

1. explicit latest user decision;
2. this `Project.md`;
3. the active Wave Gate packet, currently `docs/gates/wave3/GATE_PACKET.md`;
4. frozen OpenAPI/WebSocket contracts in `contracts/`;
5. historical pre-code contracts;
6. original requirements and historical work notes.

History is evidence, not current scope.

## 3. Project goal

Maya is a teaching platform where students create culture-focused AI Agents and teachers use published Agent versions in a structured classroom debate.

The target Demo demonstrates visible causality:

- students write an `AGENT.md` identity/behavior contract;
- students select Markdown evidence for an Agent-specific RAG snapshot;
- published Agent versions are immutable;
- teachers choose 2–5 published Agents and define an English debate topic;
- a deterministic rule engine controls two rounds and speaking order;
- each turn records whether RAG matched and which sources were actually used;
- teachers control playback and Replay;
- after the debate, an anonymous audience can vote and send a named barrage;
- the teacher closes collection, Maya receives de-identified validated insight, and a mutual-learning report is generated;
- English remains authoritative; Chinese is an optional derived test representation.

The product is a local/private Demo first, not a production multi-tenant service.

## 4. Current repository state

### 4.1 Overall status

```text
Wave 0                 historical G3 PASS
Wave 1A                historical Mock G3 PASS
Wave 1B                Mock path passed; real TTS FAILED-DEFERRED
Wave 1C                historical G3 PASS
Wave 2                 historical Mock G3 PASS
Wave 3 implementation  substantial code present
Wave 3 narrow G2       historical PASS for selected high-risk boundaries
Wave 3 Full G2         NOT SIGNED
Wave 3 G3              NOT SIGNED
Wave 4                 NOT STARTED
Complete Demo          NOT COMPLETE
```

There are five top-level Waves: **0, 1, 2, 3, and 4**. Wave 1 is split into 1A, 1B, and 1C.

### 4.2 Why Wave 3 is not complete

The repository contains M13/M14/M15 implementations and focused tests, but the current code still lacks:

- a complete independent audit of all Wave 3 paths;
- a fix for Translation follower-batch liveness;
- complete verification of the latest Pause/Resume, Full/Partial Finish, manual Reconnect, and Replay changes;
- full current-commit OpenAPI, WebSocket, generated-client, migration, frontend, backend, and Docker evidence;
- a complete desktop/tablet/mobile browser acceptance run.

Historical or narrow passes must not be reported as Full Wave 3 G2/G3.

## 5. Repository cleanup decision

On 2026-08-29, the repository was converted from a private runtime handoff snapshot into a clean source-and-contract repository.

### 5.1 Retained in Git

- product source code;
- tests, migrations, OpenAPI, WebSocket schemas, and deterministic fixtures;
- current documentation and `开发文档.xlsx`;
- `backend/config/demo-accounts/accounts.private.md`;
- `backend/config/demo_users.yaml`;
- manual Agent/RAG fixtures;
- the approved voice sample under `private-inputs/voice/`.

Demo account passwords are intentionally retained because this is a private team Demo repository. They remain forbidden from ordinary API responses, generated browser code, logs, and public deployment.

### 5.2 Removed from the current Git tree

- `.env` and all real environment values;
- runtime SQLite databases, WAL/SHM files, and database backups;
- previously created users beyond seed configuration, Agents, Debates, Turns, interactions, reports, votes, barrages, and translations stored in runtime databases;
- generated debate audio and runtime snapshots;
- runtime locks, caches, old output directories, duplicate workbooks, and archival handoff material;
- private provider diagnostic scripts that depended on local environment values.

Git history still records the earlier handoff snapshot. The current tree is the clean development baseline.

### 5.3 Runtime policy

Runtime state is created locally under `data/` and is ignored by Git. A developer may create Agents and Debates locally without changing repository history.

`.env` is created from `.env.example` and remains local. CI supplies explicit Mock-only environment values and must not inherit real provider credentials.

## 6. Frozen Demo product boundaries

### 6.1 Identity and organization

- one seeded course;
- one teacher and two student groups for the Demo;
- Demo membership is read-only;
- students access only their own group workspace;
- teachers access published Agent history for their course, not unpublished student drafts;
- audience interaction is anonymous and separate from user accounts;
- Demo quick login may expose safe identity choices, never passwords.

### 6.2 Agent and version model

- a group may create multiple Agents;
- Agent description is mutable Agent-level metadata and is not part of an immutable historical version;
- each Agent has at most one editable draft;
- publishing freezes `AGENT.md`, selected knowledge, Avatar configuration, and voice reference into an immutable AgentVersion/KnowledgeSnapshot boundary;
- later edits require a new version;
- a never-published, never-used Agent may be deleted;
- an Agent with published or Debate history must be retained.

### 6.3 Knowledge and RAG

- Demo knowledge input is Markdown only;
- `AGENT.md` defines identity/style/strategy and is separate from evidence documents;
- knowledge documents belong to the group library and may be selected independently by Agent drafts;
- published knowledge snapshots are immutable;
- each formal turn performs retrieval against the frozen snapshot;
- matched evidence produces structured sources;
- no match is valid and produces general reasoning with an empty source list;
- the platform must not invent citations or silently borrow another Agent's evidence;
- `AGENT.md` maximum: 12,000 characters;
- selected RAG Markdown maximum per draft: 100,000 characters.

### 6.4 Debate rules

- teacher selects 2–5 current published Agents in click order;
- slots are assigned A–E continuously;
- the Demo uses one deterministic two-round rule set;
- teacher topic and authoritative speeches are English;
- each turn is 80–200 English words, targeting roughly 160–185;
- the backend determines order, phase, and completion;
- the browser never decides who speaks next;
- generated turns, sources, and position history remain auditable.

### 6.5 Playback

The latest accepted visible wording is **Pause / Resume**.

- Pause means persistent, recoverable `PlaybackState.status=paused`;
- Pause does not cancel the Debate or convert it to terminal `stopped`;
- refresh or process restart must revoke stale controller authority while preserving recoverable state;
- teacher-paced Next controls publication/playback of the adjacent turn;
- Replay uses retained immutable text/sources/audio and must not call RAG, LLM, or TTS again;
- manual Reconnect attempts once and preserves already rendered state on failure;
- a full Finish allows interaction/history/report/Replay;
- an incomplete Finish preserves generated turns for audit but fails closed for interaction, Maya, history, and Replay.

### 6.6 Classroom interaction

- interaction opens only after a fully completed Debate;
- teacher explicitly opens and closes collection;
- audience uses a signed anonymous access token, not a user session;
- vote and barrage are independent submissions with independent client IDs;
- vote does not store nickname;
- barrage stores nickname and original text for teacher display/history;
- closing collection freezes exact message IDs and vote aggregates;
- submissions after finalization fail closed;
- a WebSocket never holds one SQLAlchemy Session for its entire lifetime;
- events broadcast only after the authoritative transaction commits.

### 6.7 Maya insight and report

- raw named barrages remain visible to the teacher;
- the insight policy receives message ID and raw text without an independent nickname/author field;
- counts come from database rows, not model output;
- Maya reads only frozen public turns, actually used TurnSources, final vote aggregates, and validated anonymous insight;
- Maya does not read unused/full RAG, private drafts, or a raw named barrage list;
- report revisions are immutable;
- a later failed attempt must not hide the previous successful revision;
- the Mock report is deterministic and 600–900 English words;
- the report does not announce a winner.

### 6.8 Translation and history

- English text remains authoritative;
- translation is teacher-triggered derived content;
- Mock translation is visibly labelled as test representation;
- translation never flows into RAG, future turns, TTS, voting, insight, or report inputs;
- cache identity includes content identity, exact source hash, target language, policy, and quality;
- history retains text, sources, vote aggregates, named teacher-visible barrages, report revisions, and successful translations;
- audio availability follows the course's current retained-audio pointer.

## 7. Technical architecture

```text
browser
  ↓ same-origin HTTP/WebSocket
gateway (Caddy :8080)
  ├── frontend (Next.js :3000)
  └── backend (FastAPI :8000)
        ├── SQLite WAL runtime database
        ├── local controlled files
        ├── in-process bounded task managers
        └── provider adapters (Mock by default)
```

No Redis, Celery, PostgreSQL, cloud object storage, or external vector database is required for the Demo.

Core principles:

- FastAPI/OpenAPI is the browser contract;
- generated frontend types must match the frozen contract;
- providers are server-side adapters;
- business state is authoritative on the backend;
- critical writes use revision/control-version fences and short transactions;
- expensive or ambiguous commands use idempotency keys;
- database/file transitions require recoverable ordering;
- immutable historical objects are not silently rewritten.

## 8. Wave plan

### Wave 0 — foundation

Modules: runtime skeleton, auth/session, seed data, database base, contracts, and quality tools.

Result: historical G3 pass. Must still be re-run against the final Demo commit.

### Wave 1A — Agent, version, RAG, teacher inspection

Result: historical Mock G3 pass.

### Wave 1B — Avatar and voice/TTS boundary

Result: Mock boundary passed. Real TTS attempt failed validation and remains `FAILED-DEFERRED`; it must not be retried without a new Gate.

### Wave 1C — UI and i18n foundation

Result: historical G3 pass.

### Wave 2 — debate setup, generation, and playback

Result: historical Mock G3 pass. Latest playback deltas remain part of the Wave 3 completion audit.

### Wave 3 — interaction, Maya report, history, translation

Current result: substantial G1 implementation, focused tests, and a historical narrow G2 pass. Full G2/G3 remains open.

### Wave 4 — final integration and real services

Not started. Wave 4 includes cross-module integration, separately authorized real-provider spikes, final browser/LAN acceptance, and complete Demo certification.

## 9. Unaudited or incompletely audited code

### 9.1 M13 classroom interaction

Paths:

- `backend/app/modules/interactions/**`
- `frontend/components/interaction/**`
- `frontend/app/classroom/**`

Goal: signed anonymous access, independent vote/barrage submission, teacher totals/raw barrage view, and exact finalization.

Status: implemented; selected token/idempotency/concurrency boundaries received narrow review. The full module, all permission branches, and mobile browser path have not completed Full G2/G3.

### 9.2 M14 insight and Maya reports

Paths:

- `backend/app/modules/reports/**`
- `frontend/components/report/**`

Goal: immutable de-identified insight inputs, deterministic Mock insight/report, report revisions, safe failure, and downloads.

Status: implemented; selected input-boundary risks received narrow review. The full task/recovery/revision/download surface remains incompletely audited.

### 9.3 M15 history and translation

Paths:

- `backend/app/modules/translations/**`
- `frontend/components/history/**`
- `frontend/components/translation/**`

Goal: immutable English history and on-demand derived translation batches.

Known P1: a follower batch reusing a TranslationEntry owned by another active batch may remain pending after the owner reaches ready/failed. Terminal state must propagate to followers, counts/jobs must be recomputed, and eligible followers must be scheduled without polling or duplicate provider calls.

### 9.4 Playback Wave 3 delta

Paths:

- `backend/app/modules/debates/playback/**`
- `frontend/components/debate/stage/**`
- teacher Debate control/interaction pages

Goal: Pause/Resume, full/partial Finish, manual Reconnect, Replay catalog restoration, and correct downstream availability.

Status: partially implemented after earlier manual feedback; final state-machine audit and real-browser verification are incomplete.

### 9.5 Migration and integration

Paths:

- `backend/migrations/versions/0007_wave3_interaction_report.py`
- `scripts/test_wave3_migration.py`
- `backend/app/main.py`
- shared core/debate model and projection changes

Goal: integrate Wave 3 tables, typed Job owners, projections, startup recovery, and routes without damaging 0001–0006 data.

Status: migration and tests exist; the current commit has not completed the full fresh/repeat/populated/downgrade/re-upgrade/fingerprint/FK matrix.

### 9.6 Contracts and frontend integration

Paths:

- `contracts/**`
- `frontend/lib/api/generated/**`
- `frontend/lib/api/platform.ts`
- `frontend/components/wave3/**`
- `frontend/app/teacher/debates/**`
- `scripts/generate_ws_*.mjs`

Goal: one closed OpenAPI/WS contract and a complete teacher workflow.

Status: implementation exists; current-commit generated clean-diff, error states, responsive behavior, and browser acceptance are incomplete.

## 10. Quality and Gate method

```text
G0   contract/scope frozen
G0-S high-risk design challenge
G1   Luna implementation and focused self-tests
G1.5 deterministic repository/contract/frontend/backend/migration checks
G2   independent Sol risk audit
G3   integrated runtime and browser acceptance
G4   cross-module/real-service integration
G5   final Demo acceptance
```

Full Wave 3 completion requires:

- repository policy pass;
- OpenAPI/Redocly/response/route/generated-client pass;
- WebSocket positive/negative fixtures and clean generation;
- frontend lint/type/full Vitest/production build;
- backend Ruff/mypy/full pytest;
- migration 0007 full matrix and zero foreign-key violations;
- Docker Compose configuration and healthy local stack;
- complete teacher and anonymous-phone browser paths;
- no new RAG/LLM/TTS call during Replay;
- P0=0 and P1=0 in the independent Sol audit.

## 11. Recommended next work

1. Fix M15 Translation follower terminal propagation and add owner-ready, owner-failed, mixed, concurrent, and restart tests.
2. Upgrade GitHub Actions from the old Wave 2-shaped serial job to a Wave 3 matrix so unrelated checks still run when one job fails.
3. Complete Pause/Resume, Full/Partial Finish, Reconnect, Replay, and translation-display integration tests.
4. Re-run and synchronize OpenAPI, WebSocket schemas/fixtures, generated TypeScript client, and route comparison.
5. Run the full backend/frontend/migration/Docker suite on one exact commit SHA.
6. Perform a Full Wave 3 Sol audit.
7. Perform real browser acceptance across desktop, tablet, and phone.
8. Only then begin Wave 4 or any real-provider work.

## 12. Stop conditions

Stop the affected Gate if work would:

- change published Agent/Snapshot/Turn history in place;
- open interaction before complete Debate or accept a submission after close;
- connect vote identity to nickname/user/device;
- send independent nickname/author fields or raw named lists into Maya;
- read unused/full RAG into the report;
- broadcast durable events before commit;
- hold a request database session for a socket lifetime;
- create unbounded retries or duplicate paid/provider work;
- modify historical migrations 0001–0006;
- call a real provider without explicit authorization;
- hide a P0/P1 failure behind a documentation status change.

## 13. Current handoff

This cleaned repository is a source-code and contract checkpoint, not a claim that Wave 3 is complete. Runtime records have intentionally been removed. Demo credentials remain for private team use. The next implementation session should start from the unaudited-code inventory above, not from old runtime data or historical success claims.
