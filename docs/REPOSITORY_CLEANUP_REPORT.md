# Repository Cleanup Report

## 1. Objective

This cleanup converts `maya-platform` from a private handoff snapshot containing local runtime state into a private source repository that can be continued and audited.

Requested policy:

- retain Demo accounts and passwords;
- retain product code, tests, contracts, project documents and the development workbook;
- remove runtime records and locally created Agents/Debates;
- remove databases, snapshots, generated audio, personal audio and `.env`;
- clearly label large Wave 3 areas that have not received Full audit;
- rewrite README and synchronize Project/development status.

## 2. Removed from current HEAD

- `.env`;
- `data/`;
- `backend/data/`;
- all SQLite, WAL and SHM files;
- runtime Agent, AgentVersion, KnowledgeSnapshot, Debate, Turn, Report, Interaction and Translation records;
- group runtime Markdown and generated debate audio;
- `private-inputs/` and the personal voice sample;
- runtime locks, backups and temporary state;
- `archive/`;
- `outputs/`.

The cleanup changes current and future HEAD only. Old Git history was not rewritten.

## 3. Retained

- `backend/config/demo-accounts/accounts.private.md`;
- `backend/config/demo_users.yaml`;
- all backend, frontend and migration code;
- all automated tests;
- `contracts/` and generated API types;
- `manual-tests/`;
- original requirements and current Gate documents;
- updated `README.md`, `Project.md`, `docs/FILE_MAP.md`, `docs/PROJECT_STATUS.md`;
- root `开发文档.xlsx`.

## 4. Repository organization completed

- README now explains the product, five Waves, installation, usage, file map, current CI, unaudited code and future Demo goal.
- Project was reduced from an accumulated historical notebook into a current authoritative project manual.
- `AGENTS.md` defines Sol/Luna responsibilities and current data boundaries.
- `UPLOAD_SCOPE.md` records that Demo credentials may remain, while runtime data and personal audio may not.
- `.gitignore` and repository boundary checks prevent re-adding `.env`, databases, runtime data or personal inputs.
- `quality.yml` is now a Wave 3 multi-job matrix instead of the old Wave 2 serial workflow.
- Python/TypeScript files were mechanically formatted where needed. Mechanical formatting is not recorded as functional audit.
- `开发文档.xlsx` was rebuilt as a current status workbook with project overview, Wave progress, M01–M18 alignment, unaudited code, CI results and next steps.

## 5. Final mechanical verification snapshot

Evidence baseline: `e8a4124`.

### Passed

- Repository policy;
- Formatting and frozen contracts;
- OpenAPI, generated client, Redocly, response and WebSocket/route checks;
- Wave 1–3 migration chain;
- Compose configuration;
- frontend ESLint and TypeScript;
- backend Ruff format/lint and strict mypy.

### Not passed

Frontend:

- Vitest: `157/162` passed, 5 failed.
- 1 legacy playback/manual-reconnect test;
- 1 stale Stop/Continue test that conflicts with the accepted Pause/Resume copy;
- 3 report UI/projection tests.

Backend:

- pytest: `375/382` passed, 7 failed.
- 1 credential permission issue in CI;
- 5 WebSocket Origin/config mismatches;
- 1 stale paused-restart expectation.

The aggregate quality gate remains failed. This is intentionally reported rather than hidden by cleanup documentation.

## 6. Large code retained without Full audit

- M13 classroom interaction: `backend/app/modules/interactions/**` and audience/teacher interaction UI.
- M14 anonymous insight and Maya report: `backend/app/modules/reports/**` and report UI.
- M15 history/translation: `backend/app/modules/translations/**`, history and translation UI.
- Playback Wave 3 delta: persistent Pause/Resume, Full/Partial Finish, manual Reconnect and Replay catalog.
- Shared integration: migration 0007, OpenAPI, WebSocket schemas/fixtures, generated client and application startup recovery.

These implementations are retained because they are the intended Wave 3 product work. They are not marked complete until the full test matrix and independent audit pass.

## 7. Known priority issue

Translation shared-entry follower liveness remains the clearest P1: a follower batch reusing an active Translation Entry can remain pending after the owner resolves. The fix must propagate ready/failed terminal state, recompute follower batches, enqueue runnable work after commit, avoid duplicate provider/event execution and cover restart/concurrency.

## 8. Work deliberately not done

This cleanup did not:

- fix the Translation follower P1;
- redesign Playback;
- change migration 0007 semantics;
- call any real Provider;
- promote the historical narrow audit to Full G2;
- claim that Wave 3 or the complete Demo is finished.

## 9. Accurate completion statement

```text
Source repository cleanup   complete
Runtime data removal        complete for current HEAD
Demo credentials            retained
README/Project/workbook      synchronized
Wave 3 code preservation    complete
Wave 3 Full CI              not passed
Wave 3 Full Sol G2          not passed
Wave 3 browser G3           not passed
Wave 4                      not started
Complete Demo               not complete
```
