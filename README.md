# Maya Teaching Platform

Maya is a local-first classroom platform. Student groups build culture-focused
agents from an authored persona and an immutable Markdown knowledge snapshot. A
teacher picks 2–5 published agents, runs a structured multi-round English
mutual-learning debate with claim-level evidence, opens anonymous classroom
interaction, and generates a mutual-learning report.

- [PROJECT.md](PROJECT.md) — what the product is and where it stands, including
  the real-provider state and what is still open.
- [AGENTS.md](AGENTS.md) — the working agreement for changing this repository.

> **Private local Demo.** Git holds source and non-secret fixtures only. The
> ignored mode-0600 `.env` and `backend/config/demo-accounts/accounts.private.md`
> are the only private runtime materials. The runtime `data/` directory is
> disposable and never part of the repository.

## What runs

| Service    | Role                                                                  |
| ---------- | --------------------------------------------------------------------- |
| `gateway`  | Caddy single origin on port `8080`; `/api/*` and `/ws/*` to FastAPI   |
| `frontend` | Next.js student, teacher and classroom interfaces                     |
| `backend`  | FastAPI on Python 3.12 with SQLite, FFmpeg and a real readiness probe |

The browser only ever calls platform-owned `/api/v1` routes on the same origin.
Supplier names, model ids, external voice ids, API keys and absolute paths stay
server-side; the teacher-only provider disclosure is the single exception and
shows only the reviewed supplier display name, region, purpose, outbound field
classes and the exact policy hashes.

## First start on a new machine

```sh
pnpm install --frozen-lockfile
pnpm bootstrap:local
docker compose up -d --build
docker compose ps
```

`pnpm bootstrap:local` asks once for a shared local Demo password, generates a
session secret, and writes only the two ignored mode-0600 private files. It
refuses to overwrite existing credentials, so it is not part of a daily start.

The backend applies the checked-in Alembic migrations, verifies or creates the
Demo seed, and only then reports ready. All six provider selectors default to
`mock`; real supplier keys are optional and stay local.

Two demo agents are seeded automatically — a guide in Group A and a companion
in Group B — so a teacher can open a two-agent debate immediately, with no
student setup.

## Daily start

```sh
cd /Users/xubosmell/Desktop/Maya/maya-platform
docker compose up -d
docker compose ps
```

Wait for `backend` and `frontend` to report `healthy`, then open
`http://localhost:8080`.

Use `docker compose up -d --build` when application code, dependencies,
Dockerfiles or build-time settings changed.

For QR, phone or live classroom checks, set `CLASSROOM_PUBLIC_BASE_URL` in the
ignored `.env` to this machine's private-LAN origin and restart. That value has
to satisfy two rules at once: the QR code rejects loopback and needs a
private-LAN address, while the CSRF origin check compares the port. Use the LAN
address with the port the stack actually publishes.

## Resetting the runtime

```sh
docker compose down
uv run --project backend python scripts/reset_demo_runtime.py
docker compose up -d
```

The reset renames the runtime directory instead of deleting it. **Always
`down` before `up -d` across a reset**: a bind mount follows the original
inode, so a container that was only stopped keeps writing into the quarantined
copy while host-side tools act on the new `data`.

## Local checks

```sh
cd backend && uv run pytest -p no:warnings && uv run ruff check . && uv run mypy app
```

```sh
pnpm -C frontend test --run && pnpm frontend:typecheck && pnpm frontend:lint
```

```sh
pnpm docs:check
pnpm exec prettier --check .
node scripts/check_frozen_openapi.mjs
node scripts/check_generated_contracts.mjs
node scripts/check_repo_boundary.mjs --probe-generated
```

Run backend tests from `backend/`. The application reads `.env` relative to the
working directory, so running them from the repository root loads the real
`.env` and fails CSRF-sensitive tests for reasons unrelated to your change.
[AGENTS.md](AGENTS.md) lists the complete battery and the contract-change
procedure.

## Real provider runs

The Demo composition is real DashScope embedding, real Qwen debate turns and a
real Qwen report, with Mock TTS, Voice and Translation. Every delivery surface
labels that split honestly.

A real run is bounded by an acceptance ledger whose call plan is derived from
the debate's own shape rather than a fixed number, and no provider request is
ever retried automatically. Every real request is disclosed to the teacher and
confirmed before it is sent, so a real session is exercised through the product
itself: log in, create a debate between the seeded Agents, and confirm each
disclosure as it appears.

## Logs and shutdown

```sh
docker compose logs -f --tail=100
docker compose stop
```

`stop` preserves the local SQLite database and files. Avoid
`docker compose down -v`, which removes Docker volumes; ordinary runtime data
is bind-mounted under the ignored `data/` directory.

## Frozen frontend toolchain

TypeScript `5.9.3`, ESLint `9.39.1`, Next.js `16.3.3`, React `19.2.8`, Vitest
`4.1.11`, Vite `8.2.2`, jsdom `29.0.1`. ESLint 9 is a deliberate override:
ESLint 10 crashes inside the Next.js 16.3.3 transitive parser before it lints
any source. TypeScript 5.9.3 is required by openapi-typescript 7.13.0, and
jsdom 29.0.1 matches the frozen Node 24.14 runtime.
