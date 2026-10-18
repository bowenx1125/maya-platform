# ADR-010: PostgreSQL, backend replicas, and login admission

Status: ACCEPTED

## Context

About forty students signing in for a Formal Team assessment hit a single
backend and a SQLite file. Unhandled database errors become HTTP 503
`provider_unavailable`. The client renders that code as "A platform capability
is temporarily unavailable." SQLite's single writer and one backend process are
the constraint. The live `maya.sqlite3` file is the production record and must
not be deleted or edited in place.

## Decision

Production Compose runs PostgreSQL 16. `DATABASE_URL` is
`postgresql+psycopg://maya:${POSTGRES_PASSWORD}@postgres:5432/maya`. Local tests
stay on SQLite. An empty PostgreSQL database is created from the current models
and stamped at the Alembic head, because the historical migrations are
SQLite-shaped. Later revisions go through Alembic and must stay dialect-neutral.
SQLite JSON helpers used in existing SQL are installed as PostgreSQL functions.

The first startup copies `MAYA_POSTGRES_IMPORT_SOURCE` (default
`/app/data/maya.sqlite3`) into an empty PostgreSQL database. The source is
opened read-only. A backup uses SQLite's backup API and writes a new file.
Import refuses to run when PostgreSQL already has accounts, and it refuses to
continue when accounts exist without an import receipt. `MAYA_POSTGRES_ALLOW_EMPTY=true`
is the only way to boot a fresh database with no snapshot. Dropping the
PostgreSQL volume and importing again is the retry. The SQLite file is not a
cleanup target.

`BACKEND_REPLICAS` (default 2) runs more than one backend against that database.
Each replica keeps a pool of 15 connections plus 25 overflow (since 2026-10-17). The Postgres
service starts with `max_connections=200`, which covers that pool, the
background-leader connection, and a third replica. The import role must be
allowed to `SET LOCAL session_replication_role` (the Compose role is a
superuser) because `courses` and `debates` reference each other.
Sessions already live in the database. Caddy resolves `backend` through Docker's
DNS and pins a browser to one replica with a load-balancer cookie so in-memory
playback stays on the replica that started it. One replica holds a PostgreSQL
advisory lock and is the only process that resumes stranded provider work.
Sign-in admission first used the shared `auth_login_admissions` table; it was
replaced by the per-process admission queue described under "Status on
2026-10-17" and the table stays only for migrations. A sign-in that meets a
database overload (pool timeout or lock) receives `auth_login_queued` with
`Retry-After`; the login form says it is waiting to enter (排队等待入列). That
code is not a capability outage.

## Consequences

Cutover is backup-first. Stop the writers, snapshot SQLite under
`/srv/maya-production/backups/`, require `PRAGMA integrity_check` = `ok`, set
`POSTGRES_PASSWORD`, then start the production stack. Confirm `/health/ready`,
Alembic head `0065_auth_login_admission`, and a known account before telling
students to sign in. To reverse, point `DATABASE_URL` back at the untouched
SQLite file and set `BACKEND_REPLICAS=1`. Do not delete the SQLite file as part
of the reverse.

Formal Team turns still claim one conversation at a time (`chat_busy`). Debate
cleanup triggers remain SQLite migration objects.

## Status on 2026-10-17

Classroom load is supported on PostgreSQL only. SQLite (one writer, 5 s busy
timeout) is for local work and the rollback above; a production process
started on it logs a warning (#111). A 40- and 60-student run (sign in, Team
create, Team chat, formal answers) passes on PostgreSQL in
`backend/tests/test_classroom_concurrency.py`.

No send holds a database session across a model call any more: Chat and Team
messages go only through `messages:stream`, which commits its claim and closes
the request session before the model runs (the JSON send route was removed).

Admission is per process, by design (#113). Each replica runs one adaptive
queue (`core/adaptive_admission.py`) in front of sign-in, creates, writes and
model calls, with an LLM backstop of 20 calls. Its budget starts at 72 units,
may reach 128 (a chat turn costs 6) and 48 requests in flight, and admits
nothing while the host is in danger (load >= 6 or less than 500 MiB free). The
signals are host-wide (`/proc/loadavg`, `/proc/meminfo`), so both replicas
shrink and grow together without shared state. Two replicas therefore admit
up to 40 model calls at once; more students wait in a FIFO queue (200 per
replica, 180 s) rather than fail. A busy refusal is a retryable 503
(`adaptive_admission_busy`, `llm_admission_busy`) or 409 `chat_busy`: nothing
is stored, the box keeps the text, and the student presses Send again.
Argon2 checks are limited to 3 per process. More simultaneous model calls
need more replicas or a larger host, not a shared quota.

## Deploy variables

| Variable                           | Default                   | Role                            |
| ---------------------------------- | ------------------------- | ------------------------------- |
| `POSTGRES_PASSWORD`                | required                  | PostgreSQL role `maya`          |
| `DATABASE_URL`                     | set by production Compose | PostgreSQL URL                  |
| `MAYA_POSTGRES_IMPORT_SOURCE`      | `/app/data/maya.sqlite3`  | Read-only snapshot              |
| `MAYA_POSTGRES_ALLOW_EMPTY`        | `false`                   | Skip import on a fresh database |
| `BACKEND_REPLICAS`                 | `2`                       | Backend processes behind Caddy  |
| `AUTH_LOGIN_QUEUE_RETRY_SECONDS`   | `2`                       | Client wait between tries       |
| `AUTH_HASH_CONCURRENCY`            | `3`                       | Argon2 checks per process       |
| `LLM_ADMISSION_LIMIT`              | `8`                       | Model calls per process         |
| `ADAPTIVE_ADMISSION_MAX_IN_FLIGHT` | `48`                      | Admitted requests per process   |
| `ADAPTIVE_ADMISSION_QUEUE_MAX`     | `200`                     | Waiters per process             |
