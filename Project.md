# Maya Platform Project Handbook

Last updated: 2026-08-29

This file is the concise operational authority for Maya Platform. The original teacher requirements remain in `AI文化互鉴教学平台-需求文档.md`; historical design detail remains in `docs/pre-code-contracts/`, `docs/gates/`, and Git history.

## 1. Working rules

1. Read this file before changing the repository.
2. Confirm the active Wave, scope, contracts, file ownership, acceptance criteria and stop conditions before implementation.
3. Prefer the smallest verifiable change. Do not broadly refactor high-risk Wave 3 code before Full G2.
4. Never copy source-code fragments from reference repositories. References may inform interaction, architecture, state machines and tests only.
5. Browser-facing DTOs must remain provider-neutral. Keys, supplier URLs, external IDs, local paths, passwords and Session secrets must not enter normal frontend responses, generated clients, WebSocket events, logs or errors.
6. Ordinary tests and CI use Mock providers only. Real-provider calls require a separate explicit Gate and cost authorization.
7. Luna implements and self-tests. Sol coordinates the project and performs independent high-risk review. An implementation worker cannot approve its own Gate.
8. Update this file, `docs/PROJECT_STATUS.md` and `开发文档.xlsx` whenever authoritative scope, status, risk or next steps change.

## 2. Document precedence

When documents conflict, use this order:

1. latest explicit user decision;
2. this `Project.md`;
3. the active Gate packet, currently `docs/gates/wave3/GATE_PACKET.md`;
4. frozen OpenAPI/WebSocket contracts in `contracts/`;
5. historical pre-code contracts;
6. original requirements and historical work notes.

History is evidence, not current scope.

## 3. Project goal

Maya is a local/private teaching platform where students build culture-focused AI Agents and teachers use published Agent versions in a structured classroom debate.

The target Demo should make causality visible:

- students write an `AGENT.md` identity/behavior contract;
- students upload/edit Markdown evidence and choose an Agent-specific RAG set;
- publishing freezes an immutable AgentVersion and KnowledgeSnapshot;
- teachers choose 2–5 current published Agents and an English topic;
- one deterministic rule engine controls two rounds and speaking order;
- every turn records whether RAG matched and which sources were actually used;
- teachers control playback, Pause/Resume, Next and Replay;
- after a complete debate, an anonymous audience votes and sends named barrages;
- the teacher closes collection, the backend creates validated anonymous insight, and Maya produces a mutual-learning report;
- English remains authoritative; Chinese is an optional derived test representation.

The current objective is a reliable Mock Demo, not a production multi-tenant service.

## 4. Current authoritative status

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

There are five top-level Waves: **0, 1, 2, 3 and 4**. Wave 1 is split into 1A, 1B and 1C.

Wave 3 is not complete because the current code still lacks:

- a complete independent audit of all M13/M14/M15 and playback paths;
- a fix for Translation follower-batch liveness;
- complete verification of Pause/Resume, Full/Partial Finish, manual Reconnect and Replay;
- one exact commit with all contract, frontend, backend, migration and Docker checks green;
- complete desktop/tablet/phone browser acceptance.

Historical or narrow passes must not be reported as Full Wave 3 G2/G3.

## 5. Repository cleanup baseline

On 2026-08-29 the current tree was converted from a full-machine handoff snapshot into a clear source-and-contract baseline.

### 5.1 Retained in Git

- product source code;
- tests, migrations, OpenAPI, WebSocket schemas and deterministic fixtures;
- current documentation and `开发文档.xlsx`;
- original requirements and historical/manual test material;
- `backend/config/demo-accounts/accounts.private.md`;
- `backend/config/demo_users.yaml`.

The two account files intentionally retain Demo usernames/passwords for the private project team. Passwords remain forbidden from normal API responses, browser code, generated clients, WebSocket events, logs, errors and public documentation.

### 5.2 Removed from the current tree

- `.env` and real environment values;
- runtime SQLite databases, WAL/SHM and backups;
- previously created Agents, AgentVersions, Debates, Turns, interactions, votes, barrages, reports and translations stored in runtime databases;
- runtime Markdown, KnowledgeSnapshots and generated debate audio;
- personal/private input files and local provider diagnostic scripts;
- runtime locks, caches, old output directories, duplicate workbooks and archival handoff material.

Earlier Git history still contains the old snapshot. This cleanup does not rewrite history or force-push. The current tree is the new development baseline.

### 5.3 Runtime policy

Runtime state is generated locally under ignored `data/` paths. Creating an Agent or Debate locally must not modify the Git worktree.

`.env` is created from `.env.example` and remains local. CI supplies explicit Mock-only values and never inherits real provider credentials.

## 6. Frozen Demo product boundaries

### 6.1 Identity and organization

- one seeded course;
- one teacher and two student groups for the Demo;
- Demo membership is read-only;
- students access only their own group workspace;
- teachers see published Agent history for their course, not unpublished drafts;
- audience interaction is anonymous and separate from user accounts;
- Demo quick login may expose safe identity choices, never passwords.

### 6.2 Agent and version model

- a group may create multiple Agents;
- Agent description is mutable Agent-level metadata, not immutable historical content;
- each Agent has at most one editable draft;
- publishing freezes `AGENT.md`, selected evidence, Avatar configuration and voice reference into an immutable AgentVersion/KnowledgeSnapshot boundary;
- later edits require a new version;
- a never-published, never-used Agent may be deleted;
- an Agent with published or Debate history must be retained in runtime storage.

### 6.3 Knowledge and RAG

- Demo knowledge input is Markdown only;
- `AGENT.md` defines identity/style/strategy and is separate from evidence documents;
- KnowledgeDocuments belong to the group library and are selected independently by drafts;
- published snapshots are immutable;
- each formal turn retrieves from the frozen snapshot;
- matched evidence produces structured sources;
- `no_match` is valid and produces general reasoning with an empty source list;
- the platform must not invent citations or borrow another Agent's evidence;
- `AGENT.md` maximum: 12,000 characters;
- selected RAG Markdown maximum per draft: 100,000 characters.

### 6.4 Debate rules

- teacher selects 2–5 current published Agents in click order;
- slots are assigned A–E continuously;
- the Demo uses one deterministic two-round rule set;
- topic and authoritative speeches are English;
- each turn is 80–200 English words, targeting roughly 160–185;
- the backend determines order, phase and completion;
- the browser never decides who speaks next;
- turns, sources and position history remain auditable.

### 6.5 Playback

The accepted visible wording is **Pause / Resume**.

- Pause means persistent, recoverable `PlaybackState.status=paused`;
- Pause does not cancel the Debate or convert it to terminal `stopped`;
- refresh/process restart must revoke stale controller authority while preserving recoverable state;
- teacher-paced Next controls publication/playback of the adjacent turn;
- Replay uses retained immutable runtime text/sources/audio and must not call RAG, LLM or TTS again;
- manual Reconnect attempts once and preserves already rendered state on failure;
- a full Finish allows interaction/history/report/Replay;
- an incomplete Finish preserves generated runtime turns for audit but fails closed for interaction, Maya, history and Replay.

### 6.6 Classroom interaction

- interaction opens only after a fully completed Debate;
- teacher explicitly opens and closes collection;
- audience uses a signed anonymous access token, not a user Session;
- vote and barrage are independent submissions with independent client IDs;
- vote does not store nickname;
- barrage stores nickname and original text for teacher display/history;
- closing freezes exact message IDs and vote aggregates;
- submissions after finalization fail closed;
- a WebSocket never holds a SQLAlchemy Session for its entire lifetime;
- durable events broadcast only after the authoritative transaction commits.

### 6.7 Maya insight and report

- raw named barrages remain visible to the teacher;
- insight input has message ID and raw text without an independent nickname/author field;
- counts come from database rows, not model output;
- Maya reads only frozen public turns, actually used TurnSources, final votes and validated anonymous insight;
- Maya does not read unused/full RAG, private drafts or a raw named barrage list;
- report revisions are immutable;
- a later failed attempt must not hide the previous successful revision;
- the Mock report is deterministic and 600–900 English words;
- the report does not announce a winner.

### 6.8 Translation and history

- English remains authoritative;
- translation is teacher-triggered derived content;
- Mock translation is visibly labelled as test representation;
- translation never flows into RAG, future turns, TTS, voting, insight or report inputs;
- cache identity includes content identity, exact source hash, target language, policy and quality;
- runtime history retains text, sources, votes, named teacher-visible barrages, report revisions and successful translations;
- audio availability follows the course's current retained-audio pointer.

## 7. Technical architecture

```text
browser
  ↓ same-origin HTTP/WebSocket
gateway (Caddy :8080)
  ├── frontend (Next.js :3000)
  └── backend (FastAPI :8000)
        ├── SQLite WAL runtime database
        ├── controlled local files
        ├── bounded in-process task managers
        └── provider adapters (Mock by default)
```

The Demo does not require Redis, Celery, PostgreSQL, cloud object storage or an external vector database.

Core principles:

- FastAPI/OpenAPI is the browser contract;
- generated frontend types must match the frozen contract;
- providers are server-side adapters;
- business state is authoritative on the backend;
- critical writes use revision/control-version fences and short transactions;
- expensive/ambiguous commands use idempotency keys;
- database/file transitions require recoverable ordering;
- immutable historical objects are never silently rewritten.

## 8. Wave plan and results

### Wave 0 — foundation

Runtime skeleton, auth/Session, seed data, base database, contracts and quality tools.

Result: historical G3 pass. Final Demo still requires current-commit regression.

### Wave 1A — Agent, version, RAG, teacher inspection

Result: historical Mock G3 pass.

### Wave 1B — Avatar and voice/TTS boundary

Result: Mock boundary passed. Real TTS validation failed and remains `FAILED-DEFERRED`; do not retry without a new Gate.

### Wave 1C — UI and i18n foundation

Result: historical G3 pass.

### Wave 2 — debate setup, generation and playback

Result: historical Mock G3 pass. Latest playback deltas remain in the Wave 3 completion audit.

### Wave 3 — interaction, Maya report, history and translation

Current result: substantial G1 implementation, focused tests and historical narrow G2. Full G2/G3 remains open.

### Wave 4 — final integration and real services

Not started. Wave 4 includes cross-module integration, separately authorized real-provider spikes, final LAN/browser acceptance and complete Demo certification.

## 9. Unaudited or incompletely audited code

### 9.1 M13 classroom interaction

Paths:

- `backend/app/modules/interactions/**`
- `frontend/components/interaction/**`
- `frontend/app/classroom/**`

Goal: signed anonymous access, independent vote/barrage submission, teacher totals/raw barrage view and exact finalization.

Status: implemented; selected token/idempotency/concurrency boundaries received narrow review. Full module permissions, integrated races and mobile WebSocket behavior have not completed Full G2/G3.

### 9.2 M14 insight and Maya report

Paths:

- `backend/app/modules/reports/**`
- `frontend/components/report/**`

Goal: immutable de-identified insight input, deterministic Mock insight/report, report revisions, safe failure and downloads.

Status: implemented; selected input-boundary risks received narrow review. Full task recovery, revision/current-success pointer, download and browser failure paths remain incompletely audited.

### 9.3 M15 history and translation

Paths:

- `backend/app/modules/translations/**`
- `frontend/components/history/**`
- `frontend/components/translation/**`

Goal: immutable English history, on-demand derived translation batches and exact cache reuse.

Known P1: a follower batch reusing a TranslationEntry owned by another active batch may remain pending after the owner reaches ready/failed. Terminal state must propagate to followers, counts/jobs must be recomputed and eligible followers must be scheduled without polling, duplicate provider calls or duplicate terminal events.

### 9.4 Playback Wave 3 delta

Paths:

- `backend/app/modules/debates/playback/**`
- `frontend/components/debate/stage/**`
- teacher Debate control/interaction pages

Goal: Pause/Resume, Full/Partial Finish, manual Reconnect, Replay catalog restoration and correct downstream availability.

Status: partially implemented after manual feedback; final state-machine audit, current tests and real-browser verification remain incomplete.

### 9.5 Migration and application integration

Paths:

- `backend/migrations/versions/0007_wave3_interaction_report.py`
- `scripts/test_wave3_migration.py`
- `backend/app/main.py`
- shared core/debate projection changes

Goal: integrate Wave 3 tables, typed Job owners, routes, projections and startup recovery without damaging 0001–0006 semantics.

Status: cleanup-branch migration chain passes. Full startup/job integration audit is still open.

### 9.6 Contracts and frontend composition

Paths:

- `contracts/**`
- `frontend/lib/api/generated/**`
- `frontend/lib/api/platform.ts`
- `frontend/components/wave3/**`
- `frontend/app/teacher/debates/**`
- `scripts/generate_ws_*.mjs`

Goal: one closed HTTP/WS contract and one coherent teacher workflow.

Status: OpenAPI SHA, generated client and Redocly pass on the cleanup branch; route-fixture determinism and several playback tests are still unresolved.

## 10. Gate method

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
- WebSocket fixtures and clean generation;
- frontend lint/type/full Vitest/production build;
- backend Ruff/mypy/full pytest;
- migration 0007 matrix and zero foreign-key violations;
- Docker configuration and healthy local stack;
- complete teacher and anonymous-phone browser paths;
- no new RAG/LLM/TTS call during Replay;
- P0=0 and P1=0 in independent Sol review.

## 11. Recommended next work

1. Fix M15 Translation follower terminal propagation and add owner-ready, owner-failed, mixed, concurrent and restart tests.
2. Fix the two remaining backend Ruff line-length findings, then run mypy and full pytest.
3. Investigate route-fixture nondeterminism in `scripts/test_route_surface.mjs`.
4. Reconcile manual Reconnect/Replay behavior with four stale/failing Wave 2 tests and one Wave 3 playback test.
5. Re-run/synchronize OpenAPI, WebSocket, generated Client and route comparison.
6. Run the full backend/frontend/migration/Docker suite on one exact SHA.
7. Perform Full Wave 3 Sol review.
8. Perform real browser acceptance across desktop, tablet and phone.
9. Begin Wave 4 only after Wave 3 G3.

## 12. Stop conditions

Stop the affected Gate if work would:

- rewrite published Agent/Snapshot/Turn history in place;
- open interaction before complete Debate or accept submissions after close;
- connect vote identity to nickname/user/device;
- send independent nickname/author fields or raw named lists into Maya;
- read unused/full RAG into reports;
- broadcast durable events before commit;
- hold request DB Sessions for socket lifetime;
- destroy migration data or modify 0001–0006 to hide a problem;
- call a real provider without an explicit Gate;
- copy reference source code;
- claim Full G2/G3 from Mock, historical or narrow evidence.

## 13. Current next milestone

The next trustworthy milestone is:

```text
clean source baseline merged
→ M15 liveness fixed
→ mechanical quality matrix green on one SHA
→ Full Wave 3 Sol G2
→ complete Mock browser G3
→ Wave 4
```
