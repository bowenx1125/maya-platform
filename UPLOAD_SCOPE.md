# Repository Upload Scope

This private repository is a clean source-code and contract checkpoint for the Maya Demo.

## Included

- backend and frontend source code;
- migrations, tests, OpenAPI, WebSocket schemas, and deterministic fixtures;
- current project documentation;
- `开发文档.xlsx` as the single development workbook;
- `backend/config/demo-accounts/accounts.private.md`;
- `backend/config/demo_users.yaml`;
- manual Agent/RAG test fixtures;
- approved voice input files under `private-inputs/voice/`;
- checked-in Demo Avatar assets and their notices/licenses.

The two Demo credential files intentionally contain private-team Demo usernames/passwords. They are included by user decision and must not be used for a public deployment.

## Excluded

- `.env` and any `.env.*` file other than `.env.example`;
- provider API keys, session secrets, access tokens, or machine-specific addresses;
- runtime SQLite databases, database backups, WAL/SHM files;
- locally created Agents, Debates, Turns, votes, barrages, reports, translations, and sessions;
- generated debate audio and runtime knowledge/snapshot directories;
- logs, temporary locks, caches, dependency folders, and build outputs;
- old `archive/` and `outputs/` directories;
- private provider diagnostic scripts that depend on one developer environment;
- unrelated reference repositories.

## Runtime behavior

A clone starts without committed runtime state. The application recreates local runtime files under ignored `data/` directories. Developers create a local `.env` from `.env.example`.

The approved Demo credential catalogs are mounted from `backend/config/`. CI uses explicit Mock-only variables and must not call real providers.

## Public-release boundary

Before this repository is made public or distributed outside the intended team:

1. remove or replace the Demo credential files;
2. remove the personal voice sample;
3. review Avatar and third-party asset licenses;
4. confirm no credentials exist in reachable Git history;
5. rerun repository policy and generated-source scans.
