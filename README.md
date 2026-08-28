# Maya Teaching Platform

Maya is a local-first classroom platform for building culture-focused agents and running a structured, evidence-aware debate.

The current private Demo provides:

- `gateway`: Caddy single-origin proxy on port `8080`;
- `frontend`: Next.js student, teacher and classroom interfaces using the frozen V2 visual language;
- `backend`: FastAPI image boundary with Python 3.12, FFmpeg, and a real readiness probe.

The audited local candidate includes Demo quick login, Agent/version workflows,
Markdown RAG and immutable snapshots, teacher inspection, 3D avatar previews,
two-round Mock debate generation and teacher-paced classroom playback. Real
LLM/Embedding/TTS acceptance and the later classroom interaction/Maya report
modules are intentionally not claimed as complete.

The frontend follows the Wave 0 frozen dependency set: TypeScript `5.9.3`, ESLint `9.39.1`, Next.js `16.3.3`, React `19.2.8`, Vitest `4.1.11`, Vite `8.2.2`, jsdom `29.0.1`, and the pinned type/test tooling listed in the gate packet. ESLint 9 is the approved compatibility override because ESLint 10 currently crashes inside the Next.js 16.3.3 transitive parser/plugin before linting source files; the lint command still covers TypeScript and TSX with the full Next ruleset. TypeScript 5.9.3 is required by openapi-typescript 7.13.0, and jsdom 29.0.1 matches the frozen Node 24.14 runtime.

## Daily start on this Mac

1. Start Docker Desktop and wait until the engine is running.
2. In Terminal:

   ```sh
   cd /Users/xubosmell/Desktop/Maya/maya-platform
   docker compose up -d
   docker compose ps
   ```

3. Confirm `backend` and `frontend` are `healthy`, then open
   `http://localhost:8080`.

Use `docker compose up -d --build` instead when application code, dependencies,
Dockerfiles or build-time settings changed.

## First start on a new machine

From the repository root:

```sh
pnpm install --frozen-lockfile
pnpm bootstrap:local
docker compose up -d --build
docker compose ps
```

`pnpm bootstrap:local` asks once for the shared local Demo password, creates a
random session secret, and writes only the ignored mode-0600 `.env` and
`backend/config/demo-accounts/accounts.private.md`. It refuses to overwrite
existing local credentials unless an operator explicitly requests replacement.
Do not rerun it during an ordinary daily start.

The backend applies the checked-in Alembic migration, verifies/creates the exact
Demo seed, and then becomes ready. The private account catalog is mounted
read-only at runtime and is excluded from Git and Docker build contexts. Without
that local file the health endpoints still work, but Demo login intentionally
fails closed.
`LLM_PROVIDER`, `EMBEDDING_PROVIDER`, `TTS_PROVIDER`, and `VOICE_PROVIDER`
default to `mock`; real supplier keys remain optional and must stay local.

## Local checks

From this directory:

```text
pnpm install --frozen-lockfile
pnpm --filter @maya/frontend lint
pnpm --filter @maya/frontend typecheck
pnpm --filter @maya/frontend test
docker compose config
```

For a local browser shell without containers:

```text
pnpm --filter @maya/frontend dev
```

The complete local stack is exposed at `http://localhost:8080`. Never commit
`.env`, `backend/config/demo-accounts/accounts.private.md`, supplier credentials,
or runtime data.

## Logs and shutdown

```sh
docker compose logs -f --tail=100
docker compose stop
```

`docker compose stop` preserves the local SQLite database and files. Avoid
`docker compose down -v` unless you deliberately intend to remove Docker
volumes; Maya's normal runtime data is bind-mounted under the ignored local
`data/` directory.

## Runtime boundary

The browser calls platform-owned `/api/v1` routes through the same origin. Supplier names, model IDs, external voice IDs, API keys, and absolute storage paths stay on the server side. Caddy sends `/api/*` and `/ws/*` to FastAPI and all other paths to Next.js.
