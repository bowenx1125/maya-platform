# Maya Teaching Platform

Maya is a local-first classroom platform for building culture-focused agents and running a structured, evidence-aware debate.

Wave 0 provides the runnable shell:

- `gateway`: Caddy single-origin proxy on port `8080`;
- `frontend`: Next.js shell with a V2 visual baseline and a health/environment view;
- `backend`: FastAPI image boundary with Python 3.12, FFmpeg, and a real readiness probe.

Wave 0 now includes the FastAPI application, Alembic baseline, exact Demo seed,
server-side Session/CSRF flow, read-only course/group APIs, frozen contracts and
quality gates. The audited three-service foundation is runnable; Agent/RAG, 3D,
voice, debate, classroom interaction and Maya report features remain later Waves.

The frontend follows the Wave 0 frozen dependency set: TypeScript `5.9.3`, ESLint `9.39.1`, Next.js `16.3.3`, React `19.2.8`, Vitest `4.1.11`, Vite `8.2.2`, jsdom `29.0.1`, and the pinned type/test tooling listed in the gate packet. ESLint 9 is the approved compatibility override because ESLint 10 currently crashes inside the Next.js 16.3.3 transitive parser/plugin before linting source files; the lint command still covers TypeScript and TSX with the full Next ruleset. TypeScript 5.9.3 is required by openapi-typescript 7.13.0, and jsdom 29.0.1 matches the frozen Node 24.14 runtime.

## First local start

1. Run `pnpm bootstrap:local`. The initializer asks once for the shared local
   Demo password, generates a random session secret, and creates the ignored
   `.env` and `backend/config/demo_users.yaml` with restrictive permissions. It
   refuses to replace existing local credentials unless explicitly requested.
2. Start the three-service stack with `docker compose up --build` and open
   `http://localhost:8080`.

The backend applies the checked-in Alembic migration, verifies/creates the exact
Demo seed, and then becomes ready. The credential file is mounted read-only at
runtime and is excluded from Git and Docker build contexts. Without that local
file the health endpoints still work, but login intentionally fails closed.
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
`.env`, `backend/config/demo_users.yaml`, supplier credentials, or runtime data.

## Runtime boundary

The browser calls platform-owned `/api/v1` routes through the same origin. Supplier names, model IDs, external voice IDs, API keys, and absolute storage paths stay on the server side. Caddy sends `/api/*` and `/ws/*` to FastAPI and all other paths to Next.js.
