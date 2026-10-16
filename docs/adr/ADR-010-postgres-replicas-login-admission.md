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
Each replica keeps a pool of 10 connections plus 20 overflow. The Postgres
service starts with `max_connections=200`, which covers that pool, the
background-leader connection, and a third replica. The import role must be
allowed to `SET LOCAL session_replication_role` (the Compose role is a
superuser) because `courses` and `debates` reference each other.
Sessions already live in the database. Caddy resolves `backend` through Docker's
DNS and pins a browser to one replica with a load-balancer cookie so in-memory
playback stays on the replica that started it. One replica holds a PostgreSQL
advisory lock and is the only process that resumes stranded provider work.
Sign-in admission uses the shared `auth_login_admissions` table.
`AUTH_LOGIN_ADMISSION_LIMIT` (default 8, `0` disables) is how many sign-ins may
check a password at once. Everyone else receives `auth_login_queued` with a
position and `Retry-After`. The login form says it is waiting to enter
(排队等待入列). That code is not a capability outage.

## Consequences

Cutover is backup-first. Stop the writers, snapshot SQLite under
`/srv/maya-production/backups/`, require `PRAGMA integrity_check` = `ok`, set
`POSTGRES_PASSWORD`, then start the production stack. Confirm `/health/ready`,
Alembic head `0065_auth_login_admission`, and a known account before telling
students to sign in. To reverse, point `DATABASE_URL` back at the untouched
SQLite file and set `BACKEND_REPLICAS=1`. Do not delete the SQLite file as part
of the reverse.

Formal Team turns still claim one conversation at a time (`chat_busy`). Debate
cleanup triggers remain SQLite migration objects. Spreading forty simultaneous
model calls across replicas is unchanged by this decision.

## Deploy variables

| Variable                             | Default                   | Role                            |
| ------------------------------------ | ------------------------- | ------------------------------- |
| `POSTGRES_PASSWORD`                  | required                  | PostgreSQL role `maya`          |
| `DATABASE_URL`                       | set by production Compose | PostgreSQL URL                  |
| `MAYA_POSTGRES_IMPORT_SOURCE`        | `/app/data/maya.sqlite3`  | Read-only snapshot              |
| `MAYA_POSTGRES_ALLOW_EMPTY`          | `false`                   | Skip import on a fresh database |
| `BACKEND_REPLICAS`                   | `2`                       | Backend processes behind Caddy  |
| `AUTH_LOGIN_ADMISSION_LIMIT`         | `8`                       | Concurrent password checks      |
| `AUTH_LOGIN_QUEUE_MAX`               | `200`                     | Waiting tickets                 |
| `AUTH_LOGIN_QUEUE_RETRY_SECONDS`     | `2`                       | Client wait between tries       |
| `AUTH_LOGIN_ADMISSION_LEASE_SECONDS` | `60`                      | Slot and ticket lifetime        |
