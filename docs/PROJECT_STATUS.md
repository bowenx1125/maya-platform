# Maya Platform Current Status

> Updated: 2026-08-29  
> Product target: a repeatable local/private Mock teaching Demo  
> Current stage: Wave 3 code handoff, deterministic repair and Full audit

## 1. Executive status

The repository has been cleaned into a source-oriented private project:

- product code, tests, contracts, migrations, documentation and the development workbook are retained;
- Demo account/password files are retained as the only private repository exception;
- `.env`, databases, runtime-created Agents/Debates, snapshots, generated audio, personal audio and other runtime records have been removed from current HEAD;
- old Git history was not rewritten.

The product is not complete. Wave 0–2 have historical Mock Gate evidence. Wave 3 contains substantial implementation but has not passed current Full CI, Full Sol G2 or browser G3.

## 2. Five-Wave status

| Wave | Scope | Status |
| --- | --- | --- |
| 0 | runtime, DB, sessions, seed, contracts, quality foundation | historical Mock pass |
| 1 | Agent/version, Markdown RAG, 3D, voice, UI/i18n | historical Mock pass |
| 2 | debate setup, generation, evidence, playback, WebSocket, Replay | historical Mock pass |
| 3 | interaction, anonymous insight, Maya report, history, translation, playback delta | substantially implemented; Full G2/G3 not passed |
| 4 | cross-module integration, real providers, LAN and complete E2E | not started |

## 3. Cleanup result

Removed from current HEAD:

- `.env`;
- `data/` and `backend/data/`;
- SQLite/WAL/SHM;
- runtime Agent, AgentVersion, KnowledgeSnapshot, Debate, Turn, Interaction, Report and Translation records;
- generated debate audio and personal voice input;
- `private-inputs/`, runtime locks/backups, `archive/` and `outputs/`.

Retained:

- all source code, tests and migrations;
- `contracts/` and generated API types;
- original requirements, current Gates and manual test fixtures;
- `README.md`, `Project.md`, this status file and the cleanup report;
- root `开发文档.xlsx`;
- `backend/config/demo-accounts/accounts.private.md`;
- `backend/config/demo_users.yaml`.

## 4. Current mechanical evidence

Evidence baseline: `e8a4124`.

### Passed

- Repository policy;
- Prettier;
- frozen OpenAPI, generated client, Redocly, response and WebSocket/route contracts;
- Wave 1–3 migration chain;
- Compose configuration;
- frontend ESLint and TypeScript;
- backend Ruff format, Ruff lint and strict mypy.

### Failed

Frontend:

- Vitest: `157/162` passed; 5 failed.
- 1 legacy playback sequence/manual reconnect test;
- 1 stale Stop/Continue test while product copy now accepts Pause/Resume;
- 3 report UI/projection tests covering current successful revision, failed state and no-interaction copy.

Backend:

- pytest: `375/382` passed; 7 failed.
- 1 CI checkout permission issue for the Demo credential file (`0600` required);
- 5 WebSocket tests use `Origin=http://testserver` while CI config uses `CLASSROOM_PUBLIC_BASE_URL=http://127.0.0.1:8080`;
- 1 stale restart test expects paused playback to become ready, while the current contract requires persistent paused state.

Aggregate quality gate failed because frontend and backend were not fully green.

Most backend failures are clearly environment/test-expectation issues. The three report UI failures still require code/contract triage and must not be dismissed as test drift without review.

## 5. Large unaudited or incompletely audited areas

### M13: classroom interaction

Paths:

- `backend/app/modules/interactions/**`
- `frontend/components/interaction/**`
- `frontend/app/classroom/**`

Goal:

- signed anonymous access token;
- independent vote and barrage submission;
- teacher open/close lifecycle;
- live aggregates and raw named barrage display.

Audit focus:

- token exposure;
- vote/nickname separation;
- idempotency and submit-vs-close races;
- permission boundaries;
- post-commit events and per-delivery teacher reauthorization.

### M14: anonymous insight and Maya report

Paths:

- `backend/app/modules/reports/**`
- `frontend/components/report/**`

Goal:

- structurally remove independent nickname fields before insight/report processing;
- freeze exact inputs and hashes;
- create a deterministic 600–900-word report;
- retain immutable revisions and safe downloads.

Audit focus:

- nickname/raw-list leakage into Maya;
- invented votes, evidence or winner semantics;
- current-success pointer preservation;
- repair/restart behavior;
- report UI ready/failed/no-interaction states.

### M15: history and on-demand translation

Paths:

- `backend/app/modules/translations/**`
- `frontend/components/history/**`
- `frontend/components/translation/**`

Goal:

- retain authoritative English history;
- generate explicitly labelled test Chinese representation on demand;
- cache by exact source hash and recover jobs safely.

Known P1:

- when multiple batches share one active Translation Entry, a follower batch can remain pending after the owner reaches ready/failed. It needs terminal-state propagation, deterministic re-enqueue and ready/failed/restart/concurrency tests.

### Playback Wave 3 delta

Paths:

- `backend/app/modules/debates/playback/**`
- `frontend/components/debate/stage/**`
- teacher debate control and interaction pages.

Goal:

- persistent Pause/Resume;
- Full and Partial Finish;
- manual single-attempt Reconnect;
- immutable Replay catalog with per-turn Next.

Audit focus:

- control-version CAS;
- refresh/restart recovery;
- partial-finish downstream fail-closed behavior;
- no future-turn disclosure;
- no RAG/LLM/TTS work during Replay.

### Shared integration

Paths:

- `backend/migrations/versions/0007_wave3_interaction_report.py`
- `contracts/**`
- `frontend/lib/api/generated/**`
- `backend/app/main.py` and task startup/recovery.

The contract and migration jobs pass mechanically, but a final functional diff still needs clean generation, migration fingerprints and independent audit.

## 6. Next work order

1. Fix CI mechanics: credential `0600`, one canonical WebSocket test origin and stale paused-restart expectation.
2. Update the stale Stop/Continue frontend test and triage legacy manual-reconnect behavior.
3. Fix/audit the three report UI tests.
4. Fix Translation shared-entry follower liveness with terminal propagation and concurrency/restart coverage.
5. Run the full backend/frontend/contract/migration/Compose matrix on one SHA.
6. Perform Full Sol G2 for M13, M14, M15 and Playback.
7. Run the real browser path on a clean local DB: teacher debate → interaction → phone vote/barrage → close → report → translation → Replay, plus Partial Finish.
8. Sign Wave 3 G3 only after P0/P1 are closed.
9. Start Wave 4 real-provider/LAN work only after a separate authorization.

## 7. Accurate status card

```text
Repository cleanup          complete
Runtime records in HEAD     removed
Demo credentials            retained
Documentation/workbook      synchronized
Wave 0–2                    historical Mock baseline
Wave 3 implementation       substantial
Wave 3 Full CI              not passed
Wave 3 Full Sol G2          not passed
Wave 3 browser G3           not passed
Wave 4                      not started
Complete Demo               not complete
```
