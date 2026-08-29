# Maya Platform Cleanup and Handoff Report

Date: 2026-08-29  
Cleanup branch: `sol/repository-cleanup-handoff`  
Starting commit: `747538c806fd0b9c7d800c74d4a3babab17b2efc`

## Executive summary

The repository was previously a private handoff snapshot that mixed product source code with one developer machine's runtime state: `.env`, multiple SQLite databases and WAL/SHM files, generated debate audio, created Agents and Debates, snapshots, temporary locks, archived spreadsheets, and historical output directories.

This cleanup converts the current tree into a clear development checkpoint:

- source code, contracts, migrations, tests, Demo credentials, and the approved voice sample are retained;
- local runtime databases and all created Agent/Debate records are removed from the current tree;
- generated audio, snapshots, backups, locks, duplicate workbooks, and old output/archive directories are removed;
- README and Project documentation are rewritten around the actual current status;
- the development workbook is rebuilt as a concise tracker;
- repository policy is adjusted to permit only the two approved Demo credential files and the approved voice-sample directory;
- Wave 3's unaudited code is explicitly inventoried instead of being described as complete.

This cleanup does **not** claim that the retained Wave 3 implementation is correct or finished. It deliberately avoids high-risk functional refactoring because formatting/refactoring large unaudited state-machine code would create a larger review surface.

## Files and data removed from the current tree

### Environment and runtime state

- `.env`;
- `data/**`;
- `backend/data/**`;
- SQLite databases and backups;
- SQLite WAL and SHM files;
- previously created Agent, AgentVersion, KnowledgeSnapshot, Debate, Turn, Interaction, Vote, Barrage, Report, and Translation records stored in those databases;
- generated debate audio;
- runtime staging and lock files.

### Historical repository clutter

- `archive/**`;
- `outputs/**`;
- duplicate and obsolete development workbooks under those directories;
- local provider diagnostic scripts under `private-inputs/` that depended on a developer environment.

The old snapshot remains available in Git history at the starting commit. No history rewrite or force push is required for this source-cleanup checkpoint.

## Files intentionally retained

### Demo team credentials

- `backend/config/demo-accounts/accounts.private.md`;
- `backend/config/demo_users.yaml`.

These files intentionally retain Demo usernames/passwords for the private project team. They must not be returned by frontend APIs, copied into generated clients, emitted in logs, or included if the repository is ever made public.

### Voice input

- `private-inputs/voice/**`.

The approved personal voice sample is retained because it is an explicit future voice/TTS integration input. Generated debate audio is not retained.

### Engineering assets

- all current backend/frontend source code;
- migrations 0001–0007;
- OpenAPI and WebSocket contracts/fixtures;
- backend and frontend tests;
- manual RAG/Agent fixtures;
- original product requirements;
- concise `Project.md`, README, this report, and the rebuilt development workbook.

## What was reorganized

### README

The README now explains:

- what Maya is;
- that the Demo is not finished;
- the five top-level Waves and current result of each;
- the complete repository directory map;
- data-retention policy;
- first-start and daily-start instructions;
- quality commands;
- known incomplete areas;
- the target final Demo flow;
- the Sol/Luna development method.

### Project.md

The former very large historical document is replaced in the current tree by a concise project handbook containing:

- working rules and document precedence;
- the target product flow;
- current authoritative status;
- repository cleanup decision;
- frozen product and technical boundaries;
- Wave 0–4 plan;
- unaudited code inventory;
- Gate definitions and stop conditions;
- exact recommended next work.

Historical detail remains in Git history, original requirements, pre-code contracts, and the Wave 3 Gate packet.

### Development workbook

`开发文档.xlsx` is rebuilt with four sheets:

1. `项目总览`;
2. `Wave进度`;
3. `未审计代码`;
4. `下一步`.

It now matches the README and Project status instead of retaining multiple divergent copies.

## Code retained but not fully audited

### 1. M13 classroom interaction

Primary paths:

```text
backend/app/modules/interactions/**
frontend/components/interaction/**
frontend/app/classroom/**
```

Target:

- signed anonymous classroom access;
- independent vote and barrage submissions;
- teacher live totals and named raw barrages;
- exact close/finalization boundary;
- post-commit WebSocket events.

Current evidence:

- implementation and focused tests exist;
- selected token, idempotency, concurrency, and nickname-boundary risks received a narrow review.

Still unaudited/incomplete:

- the complete module and every permission branch;
- all close-versus-submit races in the integrated application;
- full mobile-browser and real WebSocket acceptance;
- current-commit full test evidence.

### 2. M14 anonymous insight and Maya report

Primary paths:

```text
backend/app/modules/reports/**
frontend/components/report/**
```

Target:

- freeze post-interaction input;
- remove independent nickname/author fields before insight processing;
- calculate counts from database records;
- use only public turns and actually used TurnSources;
- create immutable report revisions;
- preserve an earlier successful report when a later attempt fails;
- provide safe Markdown downloads.

Current evidence:

- implementation and focused tests exist;
- selected de-identification and input-boundary risks received a narrow review.

Still unaudited/incomplete:

- full task/restart recovery;
- all revision and current-success pointer behavior;
- complete download/render boundary;
- integrated browser failure/retry path;
- Full G2 review.

### 3. M15 history and translation

Primary paths:

```text
backend/app/modules/translations/**
frontend/components/history/**
frontend/components/translation/**
```

Target:

- exact immutable English source hashes;
- teacher-triggered derived Chinese test representation;
- translation cache reuse;
- history display without changing authoritative English;
- no translation flow into RAG/TTS/report generation.

Known P1:

A follower batch can reuse a TranslationEntry currently owned by another active batch. When the owner finishes ready or failed, the follower's pending item may not receive the terminal state or be rescheduled, leaving the follower batch permanently pending.

Required correction:

- propagate ready/failed Entry state to every pending follower item;
- recompute follower batch counts and terminal state;
- complete/fail its typed Job correctly;
- schedule only eligible remaining work after commit;
- avoid polling, duplicate Provider calls, and duplicate terminal events;
- test owner-ready, owner-failed, mixed, concurrent, and restart cases.

### 4. Playback Wave 3 delta

Primary paths:

```text
backend/app/modules/debates/playback/**
frontend/components/debate/stage/**
frontend/app/teacher/debates/**
```

Target:

- persistent Pause/Resume;
- full and incomplete Finish behavior;
- manual one-shot Reconnect;
- Replay from immutable retained turn catalog;
- no RAG/LLM/TTS call during Replay;
- separate teacher interaction/report page.

Still unaudited/incomplete:

- refresh and process-restart recovery under real integration;
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

Target:

- add Wave 3 tables and typed Job ownership;
- integrate routers, projections, and startup recovery;
- preserve all 0001–0006 objects and historical data semantics.

Still unaudited/incomplete:

- current-commit fresh/repeat/populated migration proof;
- downgrade/re-upgrade proof;
- full data fingerprints;
- zero foreign-key violation proof;
- startup recovery across all Wave 3 jobs.

### 6. Contracts and generated frontend API

Primary paths:

```text
contracts/**
frontend/lib/api/generated/**
frontend/lib/api/platform.ts
scripts/generate_ws_*.mjs
```

Target:

- keep FastAPI, OpenAPI, WebSocket, and generated TypeScript aligned;
- keep DTOs closed and provider-neutral;
- preserve explicit lifecycle errors.

Still unaudited/incomplete:

- current-commit OpenAPI SHA and Redocly pass;
- generated-client clean diff;
- route-surface comparison;
- WebSocket positive/negative fixture pass;
- server event conformance.

### 7. Wave 3 frontend composition

Primary paths:

```text
frontend/components/wave3/**
frontend/components/history/**
frontend/components/translation/**
frontend/app/teacher/debates/**
frontend/tests/wave3-*.test.tsx
```

Target:

- combine interaction, report, history, translation, playback, and Replay into one coherent teacher flow.

Still unaudited/incomplete:

- error-state behavior;
- disconnect without losing rendered content;
- translation toggle after failure;
- avoiding duplicated translation display;
- desktop/tablet/phone layout;
- full production build and browser acceptance.

## Current overall progress

A useful engineering estimate is:

- product contracts and architecture: advanced;
- Wave 0–2 Mock implementation: substantially complete historically;
- Wave 3 code volume: largely implemented;
- Wave 3 verified completion: incomplete;
- real-provider readiness: incomplete;
- final Demo readiness: not yet achieved.

The project is closer to a **Wave 3 integration/audit phase** than to early development. The main risk is not missing code volume; it is that a large amount of code has not been proven together on one clean commit.

## Recommended future sequence

1. Fix Translation follower-batch liveness.
2. Upgrade CI to a Wave 3 multi-job quality matrix.
3. Complete playback/page integration and focused tests.
4. Regenerate and verify OpenAPI, WebSocket schemas, fixtures, and frontend client.
5. Run full backend, frontend, migration, and Docker checks on one exact SHA.
6. Perform Full Wave 3 Sol review with P0/P1 closure.
7. Run the complete teacher and anonymous-phone Mock flow in real browsers.
8. Sign Wave 3 G3 only after those checks.
9. Enter Wave 4 for cross-module integration and separately authorized real providers.

## Claims that remain prohibited

Until Full Wave 3 G2/G3 is signed, do not claim:

- the Demo is complete;
- all Wave 3 code is audited;
- current CI is fully green;
- real LLM/Embedding/TTS/Voice/Translation is accepted;
- Replay, restart recovery, and anonymous interaction are production-ready;
- the platform supports one-person-one-vote or public-internet deployment.

## Final cleanup result

The cleaned branch is intended to become the next trustworthy source baseline:

```text
source and contracts retained
Demo credentials retained
approved voice sample retained
runtime records removed
created Agents/Debates removed
historical output clutter removed
documentation synchronized
unaudited code explicitly labelled
future Demo completion path defined
```
