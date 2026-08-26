# Wave 0 Gate Packet

Status: `G2 PASS / G3 PARTIAL — M01 THREE-SERVICE RUNTIME PENDING`
Authorized: `2026-08-26 19:06 Asia/Shanghai`
G0-S audit: `/root/wave0_design_audit`, `gpt-5.6-sol high`, final verdict `PASS` on 2026-08-26
G2 audits: `/root/wave0_backend_audit` and `/root/wave0_foundation_audit`, `gpt-5.6-sol high`, final verdicts `PASS` on 2026-08-26
Modules: `M01 M03 M04 M16 M17 M18`
Non-goal: Wave 1-3 business completion

## Outcome

Create a minimal, runnable and independently testable foundation for the Maya Demo:

- isolated Git repository at `Maya/maya-platform/`;
- Next.js frontend, FastAPI backend and Caddy single origin on port 8080;
- SQLite/Alembic baseline with one course, one teacher, six students and two groups;
- server-side session/CSRF boundary and Demo-only identity switch contract;
- frozen OpenAPI snapshot, generated frontend types and machine-checkable WebSocket event envelope/schema;
- Mock-only CI/quality gates; no real supplier call or key.

## Frozen direct dependency set

Registry checks on 2026-08-26 are frozen for Wave 0:

- runtime: Node 24.14.0, pnpm 11.19.0, Python 3.12.12, uv 0.12.0, Caddy 2.10.2;
- frontend runtime: Next.js 16.3.3, React 19.2.8, React DOM 19.2.8;
- frontend tooling: TypeScript 5.9.3, ESLint 9.39.1, eslint-config-next 16.3.3, Vitest 4.1.11, Vite 8.2.2, jsdom 29.0.1, `@types/node` 24.13.3, `@types/react` 19.2.18, `@types/react-dom` 19.2.5, `@testing-library/react` 16.3.2, `@testing-library/dom` 10.4.1, `@testing-library/jest-dom` 7.0.1;
- contract tooling: openapi-typescript 7.13.0, openapi-fetch 0.17.0, `@redocly/cli` 2.48.0, Ajv 8.20.0, ajv-formats 3.0.1, Prettier 3.9.6;
- backend runtime: FastAPI 0.141.1, `uvicorn[standard]` 0.52.4, SQLAlchemy 2.0.52, Alembic 1.19.1, pydantic-settings 2.15.0, PyYAML 6.0.3, `pwdlib[argon2]` 0.3.1;
- backend test/quality: Ruff 0.16.4, mypy 2.3.1, pytest 9.1.1, pytest-asyncio 1.4.0, HTTPX 0.28.1.

Workers must commit `pnpm-lock.yaml` and `uv.lock`. No range or `latest` is allowed for direct dependencies. A compatibility change requires main-agent approval and a recorded reason before lockfile update.

Compatibility overrides:

- registry-current ESLint 10.9.1 reaches `scopeManager.addGlobals is not a function` inside the eslint-config-next 16.3.3 transitive parser/plugin before linting any Maya source. ESLint 9.39.1 executes the same Next/TypeScript configuration successfully, so Wave 0 freezes 9.39.1. Excluding TS/TSX or weakening rules is forbidden; a future ESLint 10 upgrade requires an actual green lint run;
- openapi-typescript 7.13.0 declares TypeScript `^5.x`, so Wave 0 freezes TypeScript 5.9.3 instead of 6/7;
- jsdom 30.0.1 requires Node `^24.15.0` but the frozen runtime is 24.14.0, so Wave 0 freezes jsdom 29.0.1;
- Vite 8.2.2 and `@testing-library/dom` 10.4.1 are direct pins rather than pnpm auto-installed peers, making the claimed dependency closure reproducible.

### Container image locks

- `caddy:2.10.2-alpine@sha256:4c6e91c6ed0e2fa03efd5b44747b625fec79bc9cd06ac5235a779726618e530d`;
- `node:24.14.0-alpine@sha256:7fddd9ddeae8196abf4a3ef2de34e11f7b1a722119f91f28ddf1e99dcafdf114`;
- `python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c`.

These are multi-architecture index digests resolved from Docker Hub on 2026-08-26. Dockerfiles/Compose must use the tag plus digest; changing a digest is a reviewed dependency update.

## Frozen invariants

### Repository and runtime

- Git root is exactly `Maya/maya-platform/`; never initialize or scan the Maya parent as a repository.
- Three services only: `gateway`, `frontend`, `backend`; no Redis, Celery, PostgreSQL, Nginx or cloud storage.
- Caddy exposes `http://localhost:8080`; `/api/*` and `/ws/*` go to FastAPI, everything else to Next.js.
- Backend is a single Uvicorn worker. SQLite uses WAL, foreign keys and a bounded busy timeout.
- FFmpeg must be present inside the backend image even if installed on the host.

### Auth and permissions

- Opaque database-backed session ID in HttpOnly SameSite=Lax cookie; 12-hour expiry and rotation on login/switch.
- Raw session token is 32 random bytes encoded URL-safe; database stores only SHA-256 hash. CSRF token is URL-safe HMAC-SHA256 of the raw session token under a `SESSION_SECRET` of at least 32 bytes; database stores only the CSRF SHA-256 hash. `/auth/me` recomputes the same raw CSRF from the presented cookie, so refresh recovery does not store plaintext or invalidate another tab.
- Passwords are salted hashes in ignored `backend/config/demo_users.yaml`; repository contains example only.
- `DEMO_MODE=true` enables server-controlled switch; when false the route does not exist or consistently returns not found.
- All authenticated write commands require same-origin/CSRF validation. Anonymous classroom tokens are separate and not implemented beyond contract placeholders in Wave 0.
- Frozen OpenAPI v0.1-g0.4 includes required `X-CSRF-Token` on every authenticated mutation. `GET /auth/me` returns `AuthSession`, including a response-readable CSRF token and expiry so refresh can restore the in-memory token.
- Business services derive course/group scope from the current session; never trust a request `group_id` alone.

### Seed and database

- One course, one teacher, six students, two groups of three. Seed is deterministic and idempotent.
- UUIDv5 namespace is exactly `a7cea9e2-390f-5b48-b129-4f388b0362e3`; exact seed keys and IDs are frozen in C02.5 and must be asserted by tests.
- Organization relationships are database rows, not frontend constants.
- Migrations upgrade from an empty database and can run twice safely at the deployment layer.
- Seed rerun checks exact IDs, relationships and fixed-row fingerprints. A conflicting existing fixed row aborts the transaction; it is never deleted/reinserted or overwritten.
- Tests inspect every connection/migrated database for `foreign_keys=ON`, `journal_mode=WAL`, bounded busy timeout and the C02 required unique indexes/partial unique draft constraint.
- Files/data live under the gitignored `data/`; no API key or original voice sample enters SQLite.

### Contracts and quality

- `../docs/pre-code-contracts/openapi-v0.1.yaml` is the frozen source. Product copy must be byte-for-byte or generated-diff checked.
- Public participant slots are `A|B|C|D|E`; numeric `order_index=0..4` is internal ordering.
- Frontend types are generated from OpenAPI, not hand-maintained duplicates.
- The exact frontend contract stack is `openapi-typescript 7.13.0` → `frontend/lib/api/generated/schema.d.ts` plus `openapi-fetch 0.17.0` → the owned `frontend/lib/api/generated/client.ts` platform wrapper. Application code does not handwrite duplicate DTOs.
- WebSocket envelope contains `event_id,event_type,event_version,debate_id,sequence,occurred_at,payload`; event schema is versioned.
- `contracts/ws-events.v1.schema.json` is a closed discriminated `oneOf` union for every frozen event type, with event-specific payload schemas and `additionalProperties: false` at envelope/payload levels unless a field is explicitly open.
- Negative fixtures must reject: `turn.ready` containing `speech`, any provider/model/key/external voice field, unknown event type/version, missing/duplicate-invalid sequence shape and malformed event-specific payload.
- Error envelope is `code,message,details,request_id`; provider errors never leak raw supplier fields.
- `.env.example` contains names only, no values resembling secrets. Secret scan includes the whole product repository.

## File ownership

### Luna M01 scaffold

Owns:

- repository-root `README.md`, `.gitignore`, `.env.example`, `docker-compose.yml`, workspace/package-manager files;
- `infra/**`;
- `frontend/**`;
- except `frontend/lib/api/generated/**`, which is exclusively owned by M17;
- `backend/Dockerfile` only.

Must not edit backend application, migrations, frozen contracts or this Gate packet.

### Luna M03/M04/M16 backend

Assigned only after G0-S design audit. Owns:

- `backend/pyproject.toml`, backend lock file and Alembic configuration;
- `backend/app/core/**`, `backend/app/modules/auth/**`, `backend/app/modules/org/**`;
- `backend/migrations/**`, `backend/config/demo_users.example.yaml`, backend tests for owned modules.

Must not edit frontend, root/infra, contract generation or backend Dockerfile.

### Luna M17/M18 contract-quality

Assigned only after G0-S design audit. Owns:

- `contracts/**`, `.github/**`, `scripts/**`;
- `frontend/lib/api/generated/**` and only that frontend subtree;
- contract/secret/quality checks that do not modify application modules;
- `docs/gates/wave0/DETERMINISTIC_CHECKS.md`.

Must not edit frontend, backend application/migrations, root runtime files or the frozen parent contracts.

## Required checks before G2 audit

- Docker Compose config and three-service health startup;
- backend Ruff, mypy, pytest and Alembic empty-database upgrade smoke;
- frontend ESLint, TypeScript and Vitest;
- OpenAPI lint/parse, generated-client clean diff and server-route comparison scaffold;
- WebSocket JSON Schema validation tests;
- seed run twice with exact UUIDs/relationships and unchanged fixed-row fingerprints; conflicting fixed data aborts transactionally;
- SQLite pragma/index inspection verifies foreign keys, WAL, busy timeout and all Wave 0 unique/partial unique constraints;
- session rotation, expiry, CSRF failure and `DEMO_MODE=false` tests;
- no Git-tracked `.env`, database, audio, private reference path or supplier secret;
- git root and tracked-file boundary prove no parent/reference file is included.

## Gate sequence

`G0-S Sol design challenge → G1 Luna implementation → G1.5 deterministic checks → G2 Sol code audit → G3 main-agent sign-off`

Sol output format: `PASS | CHANGES_REQUIRED`, at most five blocking findings with contract evidence. Workers cannot self-sign.

## Live gate evidence

- `G0-S`: `PASS` from `/root/wave0_design_audit` (`gpt-5.6-sol high`) after the g0.4 corrections.
- `M01 G1`: implemented and self-tested by `/root/wave0_m01_scaffold`; frozen install, ESLint, TypeScript, Vitest `3/3`, Next production build and Compose config passed before M17 generated-client integration.
- Container inputs: all three frozen images are present locally at the exact approved digests. Docker Desktop's configured credential helper hung during anonymous pulls; main used a task-local Docker config without changing global credentials, then pulled the images successfully.
- `G1`: all assigned M01/M03/M04/M16/M17/M18 workers completed their owned implementation and self-tests. Review fixes removed the interim generated-client error, Alembic bypass, unscoped organization reads, incomplete error envelope, shallow API comparison, CI skips, generated-code scan gap, WebSocket drift gap and insecure manual bootstrap gap.
- `G1.5`: main-agent final run passed frozen pnpm install, Prettier, ESLint, TypeScript, Vitest `3/3`, Next production build, Ruff, mypy, pytest `14/14`, Alembic upgrade, migrated seed twice, strict 9-operation API semantic comparison, frozen OpenAPI/response checks, 29 positive and 11 negative WebSocket fixtures, generator clean diff, 11 route-comparator negatives, local initializer safety probe, repository/secret boundary scan and Compose config.
- `G2`: the backend and foundation Sol audits initially returned bounded `CHANGES_REQUIRED`; their original blockers were fixed and both final narrow re-audits returned `PASS`.
- `G3 module status`: M03/M04/M16/M17/M18 are signed off by main. M01 source, dependency locks, Compose config and both application image builds passed, but the final hardened backend image rebuild and three-service health startup remain pending because Docker Desktop became stuck in `starting` after the first successful image builds. A minimal no-volume Caddy container also hung, proving this is a Desktop engine condition rather than a Maya health-check failure. The Mac UI was locked, so the Desktop error dialog could not be inspected. Do not mark Wave 0 complete until Docker Desktop is recovered and the final stack is started through port 8080.
