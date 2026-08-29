# Maya Platform

Maya is a local-first teaching platform for building culture-focused AI Agents and running structured, evidence-aware classroom debates.

The repository is now a **source-and-contract development baseline** rather than a copy of one developer machine. Runtime databases, previously created Agents and Debates, snapshots, generated audio and temporary files have been removed from the current tree. The two private Demo account/password files remain for team use.

> The final Demo is not complete yet. Wave 0–2 have historical Mock-scope passes. Wave 3 contains substantial implementation, but Full Wave 3 G2/G3 audit and browser acceptance are still open.

## Project status

There are **five top-level Waves: 0, 1, 2, 3 and 4**. Wave 1 is divided into 1A, 1B and 1C.

| Wave | Scope | Current result |
| --- | --- | --- |
| Wave 0 | runtime foundation, auth, seed data, database, contracts, quality tools | historical G3 pass |
| Wave 1A | Agent identity/versioning, Markdown RAG, teacher inspection | historical Mock G3 pass |
| Wave 1B | 3D Avatar and voice/TTS boundary | Mock path passed; real TTS is `FAILED-DEFERRED` |
| Wave 1C | UI shell and Chinese/English interface | historical G3 pass |
| Wave 2 | debate setup, generation rules and classroom playback | historical Mock G3 pass |
| Wave 3 | classroom interaction, anonymous insight, Maya report, history and translation | largely implemented; narrow G2 passed; Full G2/G3 not signed |
| Wave 4 | cross-module integration, separately authorized real providers and final E2E | not started |

Authoritative project information:

- [`Project.md`](Project.md) — current scope, architecture, Wave state and Gate method;
- [`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md) — cleanup report and unaudited-code inventory;
- [`docs/FILE_MAP.md`](docs/FILE_MAP.md) — what each important directory/file does;
- [`docs/gates/wave3/GATE_PACKET.md`](docs/gates/wave3/GATE_PACKET.md) — frozen Wave 3 contract;
- [`开发文档.xlsx`](开发文档.xlsx) — structured Wave progress, risk and next-step tracker.

## What is already implemented

The current source contains working or partially working implementations for:

- password login, Session/CSRF and Demo quick login;
- seeded course/group boundaries and teacher/student roles;
- Agent creation, mutable description metadata, drafts, immutable published versions and safe deletion rules;
- Markdown documents, per-draft evidence selection, RAG snapshots, retrieval receipts and source display;
- 3D head/shoulder Avatar configuration and state-driven classroom presentation;
- fixed two-round, teacher-paced debates with 2–5 current published Agents;
- WebSocket playback control, source display, Pause/Resume, Finish variants and Replay;
- anonymous post-debate vote and named barrage submission;
- teacher live interaction totals and raw barrage history;
- de-identified barrage insight and deterministic Mock Maya report revisions;
- report history/download and teacher-triggered Mock Chinese representation.

A large part of Wave 3 is not yet fully audited. “Implemented” means code exists; it does not mean the complete behavior has passed Full G2/G3.

## Repository map

```text
maya-platform/
├── backend/                         FastAPI services, migrations and backend tests
│   ├── app/core/                    configuration, database, errors, shared models
│   ├── app/modules/auth/            login, Session, CSRF and Demo identities
│   ├── app/modules/agents/          Agent identity, metadata and versions
│   ├── app/modules/knowledge/       Markdown documents, RAG and snapshots
│   ├── app/modules/avatars/         Avatar templates/configuration
│   ├── app/modules/voices/          voice-profile business/provider boundary
│   ├── app/modules/debates/         setup, generation and playback state machine
│   ├── app/modules/interactions/    Wave 3 classroom vote/barrage lifecycle
│   ├── app/modules/reports/         Wave 3 anonymous insight and Maya reports
│   ├── app/modules/translations/    Wave 3 derived translation batches/cache
│   ├── config/                      retained private Demo account catalogs
│   ├── migrations/                  Alembic migration chain through 0007
│   └── tests/                       unit, integration and contract tests
├── frontend/                        Next.js application
│   ├── app/                         student, teacher and anonymous classroom routes
│   ├── components/                  domain/UI components
│   ├── lib/api/                     generated types plus platform API wrapper
│   ├── public/avatars/              checked-in Demo Avatar assets
│   └── tests/                       Vitest component/integration tests
├── contracts/                       frozen OpenAPI, WebSocket schemas and fixtures
├── scripts/                         generators, migration checks and boundary tools
├── docs/                            file map, status, contracts and Gate packets
├── manual-tests/                    deterministic Agent/RAG fixtures
├── config/                          repository data-retention policy
├── infra/                           Caddy configuration
├── docker-compose.yml               local three-service topology
├── Project.md                       current project authority
└── 开发文档.xlsx                    structured development tracker
```

See [`docs/FILE_MAP.md`](docs/FILE_MAP.md) for a detailed explanation of individual files.

## Repository data policy

The current Git tree keeps:

- source code, tests, migrations, contracts and documentation;
- deterministic manual test fixtures;
- `backend/config/demo-accounts/accounts.private.md`;
- `backend/config/demo_users.yaml`.

The current Git tree does **not** keep:

- `.env`, API keys or Session secrets;
- runtime SQLite databases, WAL/SHM or backups;
- created Agents, Debates, Turns, interactions, reports or translations;
- runtime Markdown/snapshots or generated classroom audio;
- personal/private input files;
- caches, dependencies, builds, archives and obsolete output workbooks.

The two retained account files contain Demo-only credentials for this private team repository. Passwords must never be returned by ordinary APIs, emitted in logs, bundled into frontend code or copied into public documentation.

Old runtime material still exists in earlier Git history because this cleanup does not rewrite history. The current tree is the new development baseline.

## Prerequisites

Recommended environment:

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

Edit `.env` locally. At minimum provide a random `SESSION_SECRET`. Keep Mock provider selectors for ordinary development and CI.

Start the stack:

```sh
docker compose up -d --build
docker compose ps
```

Open:

```text
http://localhost:8080
```

The backend mounts the tracked Demo account catalogs from `backend/config/`. Local users, Agents, Debates and all other runtime records are created in ignored local storage under `data/`.

For phone/QR testing, set `CLASSROOM_PUBLIC_BASE_URL` in local `.env` to the computer's private-LAN origin, for example `http://192.168.x.x:8080`, and open the teacher page through the same origin.

## Daily use

```sh
docker compose up -d
docker compose ps
```

Use `--build` after source, dependency, Dockerfile or build-time setting changes.

Stop without deleting local data:

```sh
docker compose stop
```

Do not run `docker compose down -v` unless all local runtime data is intentionally disposable.

## Quality checks

Install dependencies:

```sh
pnpm install --frozen-lockfile
uv sync --directory backend --frozen
```

Repository and contracts:

```sh
pnpm exec prettier --check .
node scripts/check_repo_boundary.mjs
node scripts/test_repo_boundary.mjs
node scripts/check_frozen_openapi.mjs
node scripts/test_frozen_openapi.mjs
node scripts/check_generated_contracts.mjs
pnpm exec redocly lint --config contracts/redocly.yaml contracts/openapi-v0.1.yaml
node scripts/check_openapi_responses.mjs
node scripts/test_openapi_responses.mjs
node scripts/test_route_surface.mjs
node scripts/test_ws_events.mjs
node scripts/test_ws_commands.mjs
node scripts/check_generated_ws.mjs
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

GitHub Actions runs repository policy, contracts, frontend, backend, migration and Compose jobs separately so one failure does not hide all other evidence.

## Current known incomplete or unaudited areas

1. **M13 classroom interaction** — full permission/concurrency/mobile-WebSocket audit is incomplete.
2. **M14 insight/report** — full task recovery, revision pointer, download and browser failure-path audit is incomplete.
3. **M15 translation** — a known follower-batch liveness P1 can leave a reused pending entry permanently pending.
4. **Playback Wave 3 delta** — Pause/Resume, Full/Partial Finish, manual Reconnect and Replay integration need full state-machine/browser validation.
5. **Migration/application integration** — 0007 exists and its migration job passes on the cleanup branch, but startup/job integration still requires Full G2 review.
6. **Contracts and frontend composition** — OpenAPI/Redocly pass, while route-fixture determinism and several playback tests remain unresolved on the cleanup branch.

Exact paths, goals and next actions are in [`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md).

## Target final Demo flow

```text
student creates and publishes Agent
→ teacher selects 2–5 current published Agents
→ fixed two-round evidence-aware debate
→ teacher-paced playback, Pause/Resume and Replay
→ teacher opens classroom interaction
→ anonymous vote and named barrage submission
→ teacher closes collection
→ validated anonymous insight
→ Maya mutual-learning report
→ history and Markdown download
→ optional test Chinese representation
```

Wave 4 and real-provider work begin only after Full Wave 3 G2/G3.

## Development method

- `Project.md` defines current scope and status.
- Luna implements and runs local checks.
- Sol coordinates the project and independently reviews high-risk code/Gates.
- An implementation worker never approves its own Gate.
- Mock success is never presented as real-provider acceptance.
- Permission, migration, state-machine, provider-boundary and immutable-history changes require focused review.

## Distribution

The repository is private and retains Demo account passwords. Before any public release, remove both credential files, rotate the Demo passwords and complete privacy/asset/provider review.
