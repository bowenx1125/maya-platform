# Maya Platform Cleanup and Handoff Report

Date: 2026-08-29  
Cleanup branch: `sol/repository-cleanup-handoff`  
Pull request: `#1`  
Starting commit: `747538c806fd0b9c7d800c74d4a3babab17b2efc`

## Executive summary

The repository was previously a private full-machine handoff snapshot that mixed product source with runtime state: `.env`, multiple SQLite databases and WAL/SHM files, generated debate audio, created Agents/Debates, snapshots, locks, archived workbooks, local diagnostic scripts and old output directories.

The cleanup branch converts the current tree into a clear development checkpoint:

- source, contracts, migrations, tests and current documentation are retained;
- only the two user-approved Demo account/password files remain as private team data;
- `.env`, runtime databases and all created Agent/Debate records are removed from the current tree;
- generated audio, runtime knowledge/snapshots, private input files, locks, backups and old outputs are removed;
- README, Project handbook, file map and development workbook describe the actual current status;
- repository policy prevents the removed data classes from being tracked again;
- Wave 3's large unaudited surface is explicitly inventoried rather than described as complete;
- CI is split into repository, contract, frontend, backend, migration and Compose jobs.

This is a repository-cleanup and handoff result, **not** a claim that Wave 3 or the final Demo is complete.

## Cleanup performed

### Removed from the current Git tree

- `.env`;
- `data/**` and `backend/data/**`;
- SQLite databases, backups, WAL and SHM files;
- created users beyond seed configuration, Agents, AgentVersions, KnowledgeSnapshots, Debates, Turns, interactions, votes, barrages, reports and translations stored in runtime databases;
- runtime group Markdown and published snapshot files;
- generated debate audio;
- temporary/staging files and locks;
- `private-inputs/**`, including personal audio and local provider diagnostics;
- `archive/**` and `outputs/**`;
- duplicate/obsolete development workbooks under old output directories.

### Intentionally retained private files

- `backend/config/demo-accounts/accounts.private.md`;
- `backend/config/demo_users.yaml`.

These files retain Demo-only usernames/passwords for the private team. Passwords must never be returned by normal APIs, bundled in browser code, emitted in WebSocket events/logs/errors, or kept if the repository becomes public.

### Retained engineering assets

- current backend/frontend source code;
- migrations 0001–0007;
- OpenAPI and WebSocket contracts/fixtures;
- backend and frontend tests;
- deterministic manual Agent/RAG fixtures;
- original product requirements;
- current README, `Project.md`, this report, `docs/FILE_MAP.md` and `开发文档.xlsx`.

## Git-history boundary

The cleanup changes the current tree; it does not rewrite Git history or force-push. Earlier commits still contain the old handoff snapshot. A permanent history purge would be a separate operation requiring collaborator coordination and fresh clones.

## Documentation result

### `README.md`

Now explains:

- what Maya is;
- that the final Demo is not complete;
- five top-level Waves and current result of each;
- repository structure;
- data-retention policy;
- first start, daily use and quality commands;
- current unaudited areas;
- target Demo flow and Sol/Luna method.

### `Project.md`

Now serves as a concise operational handbook containing:

- working rules and document precedence;
- target product flow;
- repository cleanup baseline;
- frozen product/technical boundaries;
- Wave 0–4 plan;
- unaudited code inventory;
- Gate definitions, stop conditions and exact recommended next work.

Historical detail remains in Git history, original requirements, pre-code contracts and the Wave 3 Gate packet.

### `docs/FILE_MAP.md`

Explains the purpose of important root files, backend modules, frontend routes/components, contracts, scripts, tests and configuration.

### `开发文档.xlsx`

The rebuilt workbook has four sheets:

1. `项目总览`;
2. `Wave进度`;
3. `未审计代码`;
4. `下一步`.

It is intended to match README/Project/status instead of maintaining many divergent workbook copies.

## Code retained but not fully audited

### 1. M13 classroom interaction

Primary paths:

```text
backend/app/modules/interactions/**
frontend/components/interaction/**
frontend/app/classroom/**
```

Goal:

- signed anonymous classroom access;
- independent vote and barrage submissions;
- teacher live totals and named raw barrages;
- exact close/finalization boundary;
- post-commit WebSocket events.

Current evidence:

- implementation and focused tests exist;
- selected token, idempotency, concurrency and nickname-boundary risks received a narrow review.

Still open:

- full module and every permission branch;
- integrated close-versus-submit races;
- full mobile browser and real WebSocket acceptance;
- Full G2/G3.

### 2. M14 anonymous insight and Maya report

Primary paths:

```text
backend/app/modules/reports/**
frontend/components/report/**
```

Goal:

- freeze post-interaction input;
- remove independent nickname/author fields before insight processing;
- calculate counts from database records;
- use public turns and actually used TurnSources only;
- create immutable report revisions;
- preserve an earlier successful report after a later failure;
- provide safe Markdown downloads.

Current evidence:

- implementation and focused tests exist;
- selected de-identification/input-boundary risks received narrow review.

Still open:

- full task/restart recovery;
- revision/current-success pointer behavior;
- complete download/render boundary;
- integrated browser failure/retry path;
- Full G2.

### 3. M15 history and translation

Primary paths:

```text
backend/app/modules/translations/**
frontend/components/history/**
frontend/components/translation/**
```

Goal:

- exact immutable English source hashes;
- teacher-triggered Chinese test representation;
- translation cache reuse;
- history display without changing authoritative English;
- no translation input to RAG/TTS/report generation.

Known P1:

A follower batch can reuse a TranslationEntry currently owned by another active batch. When the owner reaches ready or failed, the follower's pending item may not receive the terminal state or be rescheduled, leaving the follower permanently pending.

Required correction:

- propagate ready/failed Entry state to every pending follower item;
- recompute follower counts and terminal state;
- complete/fail its typed Job correctly;
- schedule only eligible remaining work after commit;
- avoid polling, duplicate provider calls and duplicate terminal events;
- test owner-ready, owner-failed, mixed, concurrent and restart cases.

### 4. Playback Wave 3 delta

Primary paths:

```text
backend/app/modules/debates/playback/**
frontend/components/debate/stage/**
frontend/app/teacher/debates/**
```

Goal:

- persistent Pause/Resume;
- full and incomplete Finish behavior;
- manual one-shot Reconnect;
- Replay from immutable retained runtime turn catalog;
- no RAG/LLM/TTS call during Replay;
- separate teacher interaction/report page.

Still open:

- refresh/process-restart recovery under integrated runtime;
- complete/partial Finish downstream availability;
- stale controller/media fencing;
- full Replay speech/source restoration;
- page-level responsive/browser validation.

### 5. Migration 0007 and application integration

Primary paths:

```text
backend/migrations/versions/0007_wave3_interaction_report.py
scripts/test_wave3_migration.py
backend/app/main.py
backend/app/core/**
backend/app/modules/debates/schemas.py
backend/app/modules/debates/setup/service.py
```

Goal:

- add Wave 3 tables and typed Job ownership;
- integrate routers, projections and startup recovery;
- preserve 0001–0006 data semantics.

Current evidence:

- the cleanup-branch migration job passes empty upgrade twice and populated Wave 1/2/3 preservation checks.

Still open:

- Full Sol audit of startup/recovery interaction across all Wave 3 jobs;
- integrated runtime evidence on the final Wave 3 SHA.

### 6. Contracts and generated frontend API

Primary paths:

```text
contracts/**
frontend/lib/api/generated/**
frontend/lib/api/platform.ts
scripts/generate_ws_*.mjs
```

Goal:

- keep FastAPI, OpenAPI, WebSocket and generated TypeScript aligned;
- keep DTOs closed and provider-neutral;
- preserve explicit lifecycle errors.

Current evidence:

- Prettier, frozen OpenAPI hash, generated types, Redocly and response-contract checks pass on the cleanup branch.

Still open:

- `scripts/test_route_surface.mjs` currently reports nondeterministic fixture output;
- later WebSocket/Latin checks are skipped after that failure;
- final server route/event conformance remains open.

### 7. Wave 3 frontend composition

Primary paths:

```text
frontend/components/wave3/**
frontend/components/history/**
frontend/components/translation/**
frontend/app/teacher/debates/**
frontend/tests/wave3-*.test.tsx
```

Goal:

- combine interaction, report, history, translation, playback and Replay into one coherent teacher flow.

Current evidence:

- frontend lint and TypeScript pass on the cleanup branch before the test step;
- 157 of 162 tests passed in the last completed cleanup run.

Still open:

- four Wave 2 playback/reconnect/replay tests and one Wave 3 playback control test fail;
- error-state behavior;
- disconnect without losing rendered content;
- translation toggle after failure;
- duplicated translation display;
- desktop/tablet/phone browser acceptance;
- production build after the failing test step.

## Current automated evidence

The latest fully inspected cleanup run before this report showed:

Passed:

- repository boundary;
- Prettier;
- frozen OpenAPI hash and generated types;
- Redocly;
- response contract;
- migration chain, including Wave 3 migration script;
- Compose configuration;
- frontend lint and TypeScript before test failure.

Known failures:

- route fixture generator is nondeterministic;
- backend Ruff has two SQL-string E501 findings, so mypy/full pytest did not run in that job;
- frontend has five playback/reconnect/replay test failures;
- final quality gate is red because those jobs are red.

The cleanup must not be described as a fully green Wave 3 commit.

## Overall progress

Engineering assessment:

- product contracts and architecture: advanced;
- Wave 0–2 Mock implementation: substantially complete historically;
- Wave 3 code volume: largely implemented;
- Wave 3 verified completion: incomplete;
- real-provider readiness: incomplete;
- final Demo readiness: not achieved.

The project is in a **Wave 3 integration/audit phase**, not early development. The main risk is not missing code volume; it is proving the large implementation together on one exact commit.

## Recommended future sequence

1. Merge the cleaned source baseline after review.
2. Fix Translation follower-batch liveness.
3. Fix the two Ruff E501 findings and run mypy/full backend pytest.
4. Fix route-fixture determinism.
5. Reconcile manual Reconnect/Replay behavior with the five failing frontend tests.
6. Re-run OpenAPI, WebSocket, generated client, frontend, backend, migration and Docker checks on one SHA.
7. Perform Full Wave 3 Sol review and close P0/P1.
8. Run the complete teacher and anonymous-phone Mock flow in real browsers.
9. Sign Wave 3 G3 only after those checks.
10. Enter Wave 4 for cross-module integration and separately authorized real providers.

## Claims that remain prohibited

Until Full Wave 3 G2/G3 is signed, do not claim:

- the Demo is complete;
- all Wave 3 code is audited;
- the quality matrix is fully green;
- real LLM/Embedding/TTS/Voice/Translation is accepted;
- Replay/restart/anonymous interaction is production-ready;
- the platform provides one-person-one-vote or public-internet deployment.

## Cleanup result

```text
source/contracts/tests retained
Demo account/password configuration retained
.env and runtime data removed
created Agents/Debates removed from current tree
private input and generated audio removed
historical output clutter removed
README/Project/file map/status synchronized
unaudited code explicitly labelled
future Demo completion path defined
```
