# Maya Platform

Maya is a local-first teaching platform for building culture-focused AI Agents and running structured, evidence-aware classroom debates.

The project is **not a finished Demo yet**. Wave 0–2 have historical Mock-scope passes. Wave 3 contains substantial implementation for classroom interaction, Maya reports, history, translation, and playback recovery, but the current code has not completed Full Wave 3 G2/G3 audit and end-to-end acceptance.

## Current status

| Area | Status |
| --- | --- |
| Wave 0 — foundation | Historical G3 pass |
| Wave 1A — Agent/version/RAG | Historical Mock G3 pass |
| Wave 1B — 3D/voice boundary | Mock path passed; real TTS is `FAILED-DEFERRED` |
| Wave 1C — UI/i18n shell | Historical G3 pass |
| Wave 2 — debate generation/playback | Historical Mock G3 pass |
| Wave 3 — interaction/report/history/translation | Implemented in large part; narrow G2 passed; Full G2/G3 not signed |
| Wave 4 — cross-module integration/real providers/final E2E | Not started |

There are **five top-level Waves: 0, 1, 2, 3, and 4**. Wave 1 is split into 1A, 1B, and 1C.

The authoritative status and remaining work are recorded in:

- [`Project.md`](Project.md) — concise project contract and current truth;
- [`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md) — cleanup report, unaudited-code inventory, and next steps;
- [`docs/gates/wave3/GATE_PACKET.md`](docs/gates/wave3/GATE_PACKET.md) — frozen Wave 3 implementation contract;
- [`开发文档.xlsx`](开发文档.xlsx) — project overview, Wave progress, unaudited code, and delivery plan.

## What already exists

The repository currently contains working or partially working implementations for:

- Demo authentication and password/quick-login flows;
- course/group boundaries and student/teacher roles;
- Agent creation, immutable versions, description metadata, and safe deletion rules;
- Markdown knowledge documents, per-draft selection, RAG snapshots, and source receipts;
- 3D head/shoulder Avatar previews and state-driven classroom presentation;
- fixed two-round, teacher-paced multi-Agent debates;
- WebSocket playback control, source display, Replay, Pause/Resume, and Finish variants;
- anonymous post-debate voting and barrage submission;
- teacher-side live interaction totals and named raw barrages;
- anonymous barrage insight and deterministic Mock Maya reports;
- report revisions, history, Markdown downloads, and on-demand Mock Chinese representation.

Some of these features are covered only by historical or narrow audits. They must not be described as a completed production system.

## Repository map

```text
maya-platform/
├── backend/                         FastAPI application, services, migrations, tests
│   ├── app/core/                    configuration, database, errors, shared models
│   ├── app/modules/auth/            sessions, password login, Demo quick login
│   ├── app/modules/agents/          Agent identity and version endpoints
│   ├── app/modules/knowledge/       Markdown documents, RAG, snapshots
│   ├── app/modules/avatars/         Avatar configuration
│   ├── app/modules/voices/          voice-profile lifecycle and provider boundary
│   ├── app/modules/debates/         setup, generation, playback, WebSocket control
│   ├── app/modules/interactions/    Wave 3 anonymous vote/barrage workflow
│   ├── app/modules/reports/         Wave 3 insight and Maya report workflow
│   ├── app/modules/translations/    Wave 3 derived translation batches/cache
│   ├── migrations/                  Alembic migration chain, currently through 0007
│   └── tests/                       backend unit/integration/contract tests
├── frontend/                        Next.js application
│   ├── app/                         student, teacher, classroom routes
│   ├── components/                  reusable UI and domain components
│   ├── lib/api/                     platform API boundary and generated client types
│   ├── public/avatars/              checked-in Demo Avatar assets
│   └── tests/                       Vitest component/integration tests
├── contracts/                       frozen OpenAPI, WebSocket schemas, fixtures
├── scripts/                         generation, migration, boundary, and validation tools
├── docs/
│   ├── pre-code-contracts/          historical frozen design contracts
│   ├── gates/wave3/                 Wave 3 Gate packet
│   └── PROJECT_STATUS.md            current handoff and unaudited-code report
├── manual-tests/                    explicit manual RAG/Agent fixtures
├── private-inputs/voice/            approved team voice sample for future voice work
├── infra/                           Caddy gateway configuration
├── docker-compose.yml               local three-service topology
├── Project.md                       current project authority
└── 开发文档.xlsx                    structured development tracker
```

## Data policy after repository cleanup

The Git repository intentionally keeps:

- source code, tests, contracts, and documentation;
- `backend/config/demo-accounts/accounts.private.md`;
- `backend/config/demo_users.yaml`;
- the approved voice sample under `private-inputs/voice/`;
- deterministic manual test fixtures.

The Git repository no longer keeps:

- `.env` or provider/session keys;
- SQLite databases, WAL/SHM files, or prior runtime records;
- previously created Agents, Debates, Turns, reports, votes, or barrages;
- generated debate audio;
- runtime locks, logs, build outputs, caches, archived workbooks, or old output folders.

Runtime data is recreated locally under `data/` and remains ignored. Demo account credentials are committed only because this is a private team Demo repository; they must never be returned by browser APIs or logs.

## Prerequisites

Recommended local environment:

- Docker Desktop;
- Node.js `24.14.x`;
- pnpm `11.19.0` through Corepack;
- Python `3.12` and `uv` for direct backend checks;
- FFmpeg for voice-related backend tests.

## First start

From the repository root:

```sh
corepack enable
corepack prepare pnpm@11.19.0 --activate
pnpm install --frozen-lockfile
cp .env.example .env
```

Edit the local `.env` and provide at least a random `SESSION_SECRET`. Keep every value local. For the current Mock Demo, retain the Mock provider selectors from `.env.example`.

Then start the application:

```sh
docker compose up -d --build
docker compose ps
```

Open:

```text
http://localhost:8080
```

The tracked Demo account catalogs are mounted from `backend/config/`. Runtime users, courses, groups, Agents, and Debates are created or persisted in the local ignored `data/` directory.

For phone/QR testing, set `CLASSROOM_PUBLIC_BASE_URL` in `.env` to the computer's private-LAN origin, such as `http://192.168.x.x:8080`, and access the teacher page through the same origin.

## Daily use

```sh
docker compose up -d
docker compose ps
```

Use `--build` when source files, dependencies, Dockerfiles, or build-time settings changed.

Stop without deleting local data:

```sh
docker compose stop
```

Do not use `docker compose down -v` unless local runtime data is intentionally disposable.

## Quality checks

JavaScript and contracts:

```sh
pnpm install --frozen-lockfile
pnpm exec prettier --check .
node scripts/check_repo_boundary.mjs
node scripts/test_repo_boundary.mjs
node scripts/check_frozen_openapi.mjs
node scripts/test_frozen_openapi.mjs
node scripts/check_generated_contracts.mjs
pnpm exec redocly lint --config contracts/redocly.yaml contracts/openapi-v0.1.yaml
node scripts/test_ws_events.mjs
node scripts/test_ws_commands.mjs
```

Frontend:

```sh
pnpm --filter @maya/frontend lint
pnpm --filter @maya/frontend typecheck
pnpm --filter @maya/frontend test
pnpm --filter @maya/frontend build
```

Backend:

```sh
uv sync --directory backend --frozen
uv run --directory backend ruff format --check app tests migrations
uv run --directory backend ruff check app tests migrations
uv run --directory backend mypy app
uv run --directory backend pytest
```

Migrations:

```sh
uv run --directory backend python ../scripts/test_wave1_migration.py
uv run --directory backend python ../scripts/test_wave2_migration.py
uv run --directory backend python ../scripts/test_wave3_migration.py
```

The GitHub workflow is intended to run repository policy, contracts, frontend, backend, migrations, and Compose checks independently so one formatting error does not hide every other result.

## Known incomplete or unaudited areas

The largest remaining areas are:

1. full M13 classroom-interaction audit;
2. full M14 insight/report audit;
3. M15 Translation follower-batch liveness fix and audit;
4. latest playback Pause/Resume, Full/Partial Finish, manual Reconnect, and Replay integration;
5. migration 0007 full current-SHA evidence;
6. OpenAPI/WebSocket/generated-client current-SHA proof;
7. desktop/tablet/mobile browser acceptance for the complete Mock vertical slice.

See [`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md) for exact paths and risks.

## Target Demo flow

The final Mock Demo should support this complete path:

```text
student builds and publishes Agent
→ teacher selects 2–5 published Agents
→ fixed two-round evidence-aware debate
→ teacher-paced playback and Replay
→ teacher opens classroom interaction
→ anonymous vote and named barrage submission
→ teacher closes collection
→ anonymous insight
→ Maya mutual-learning report
→ history/download
→ optional test Chinese representation
```

Wave 4 and real providers begin only after Full Wave 3 G2/G3 is complete.

## Development method

- `Project.md` defines current scope and status.
- Luna implements and runs local checks.
- Sol performs independent risk review and coordinates Gate decisions.
- An implementation worker never approves its own Gate.
- Mock success is never presented as real-provider acceptance.
- Changes to permissions, migrations, state machines, provider boundaries, or immutable history require focused review.

## License and distribution

This repository is private and contains Demo account passwords and an approved personal voice sample. Do not make it public or redistribute those files without replacing/removing them and completing the relevant privacy and asset-license review.
