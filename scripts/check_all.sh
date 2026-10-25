#!/usr/bin/env bash
# Every deterministic gate CI runs, in one command, failing on the first miss.
#
# The formatters are separate gates from the linters and are easy to skip by
# hand; a red CI on a formatting-only diff costs more than running them here.
set -euo pipefail
cd "$(dirname "$0")/.."

step() { printf '\n\033[1m== %s\033[0m\n' "$1"; }

step "backend lint"
(cd backend && uv run ruff check .)
step "backend format"
(cd backend && uv run ruff format --check .)
step "backend types"
(cd backend && uv run mypy app)
step "backend tests"
# PostgreSQL only: each test gets its own database on this server.
: "${MAYA_TEST_POSTGRES_URL:?Set MAYA_TEST_POSTGRES_URL to a PostgreSQL server for the backend tests}"
(cd backend && uv run pytest -q)

step "repository format"
pnpm exec prettier --check .
step "frontend lint"
pnpm frontend:lint
step "frontend types"
pnpm frontend:typecheck
step "frontend tests"
pnpm frontend:test

step "documents"
pnpm docs:check
pnpm latin-script:check

step "contracts"
pnpm exec redocly lint --config contracts/redocly.yaml contracts/openapi-v0.1.yaml
node scripts/check_generated_contracts.mjs
node scripts/check_generated_ws.mjs
node scripts/check_frozen_openapi.mjs
node scripts/check_openapi_responses.mjs
node scripts/check_repo_boundary.mjs
node scripts/test_frozen_openapi.mjs
node scripts/test_openapi_responses.mjs
node scripts/test_ws_events.mjs
node scripts/test_ws_commands.mjs
node scripts/test_repo_boundary.mjs

step "scripts"
uv run --directory backend python ../scripts/test_bootstrap_local_demo.py
uv run --directory backend python ../scripts/test_reset_demo_runtime.py

step "route surface"
uv run --directory backend python ../scripts/export_fastapi_openapi.py /tmp/maya-openapi.json
node scripts/compare_route_surface.mjs --server-openapi /tmp/maya-openapi.json
node scripts/test_route_surface.mjs

step "production build"
pnpm --filter @maya/frontend build
node scripts/check_production_routes.mjs

printf '\n\033[32mAll deterministic gates passed.\033[0m\n'
