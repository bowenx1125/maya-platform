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
(cd backend && uv run pytest -q)

step "repository format"
pnpm exec prettier --check .
step "frontend lint"
pnpm frontend:lint
step "frontend types"
pnpm frontend:typecheck
step "frontend tests"
pnpm frontend:test

step "contracts"
pnpm exec redocly lint --config contracts/redocly.yaml contracts/openapi-v0.1.yaml
node scripts/test_frozen_openapi.mjs
node scripts/test_openapi_responses.mjs
node scripts/test_ws_events.mjs
node scripts/test_ws_commands.mjs
node scripts/test_repo_boundary.mjs

step "route surface"
uv run --directory backend python ../scripts/export_fastapi_openapi.py /tmp/maya-openapi.json
node scripts/compare_route_surface.mjs --server-openapi /tmp/maya-openapi.json
node scripts/test_route_surface.mjs

printf '\n\033[32mAll deterministic gates passed.\033[0m\n'
