# Wave 1A deterministic checks (M05/M06/M09)

Run these commands from the Git root, `maya-platform`. Wave 1A remains
Mock-only and provider-neutral: no supplier key, model call, external voice
ID, or network retrieval is permitted. The frozen OpenAPI product copy is
still checked byte-for-byte against its committed SHA-256 manifest before any
route comparison.

## Required checks

| Check                            | Command                                                                                                                                                                                                                               | Acceptance                                                                                                                                                                                                         |
| -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Frozen OpenAPI copy/hash         | `node scripts/check_frozen_openapi.mjs`                                                                                                                                                                                               | The 60,210-byte product copy equals `contracts/openapi-v0.1.sha256` and the local parent copy when present.                                                                                                        |
| Frozen clean-checkout simulation | `node scripts/test_frozen_openapi.mjs`                                                                                                                                                                                                | An isolated copy verifies without the parent checkout and a mutated copy is rejected.                                                                                                                              |
| Generated TypeScript/client      | `node scripts/check_generated_contracts.mjs`                                                                                                                                                                                          | The existing exact `openapi-typescript` output is byte-identical and the provider-neutral `openapi-fetch` wrapper is present. Regenerate only if this check reports a real diff.                                   |
| OpenAPI lint                     | `CI=1 pnpm exec redocly lint --config contracts/redocly.yaml contracts/openapi-v0.1.yaml`                                                                                                                                             | Frozen contract passes Redocly structural/security checks.                                                                                                                                                         |
| Frozen response contract         | `node scripts/check_openapi_responses.mjs && node scripts/test_openapi_responses.mjs`                                                                                                                                                 | Every frozen response remains required; only the documented 101/4xx exceptions are accepted.                                                                                                                       |
| WebSocket contract               | `node scripts/test_ws_events.mjs && node scripts/check_generated_ws.mjs`                                                                                                                                                              | Existing 29 positive/11 negative fixtures and generated clean-diff remain green.                                                                                                                                   |
| Route comparator fixtures        | `node scripts/test_route_surface.mjs`                                                                                                                                                                                                 | The 33-operation positive fixture is deterministic; nullable `type` array order is equivalent; property, status, required-field, security/request, and forbidden provider/model/key/voice-field drift is rejected. |
| Wave 1A backend tests            | `uv run --directory backend pytest tests/test_wave1_agents_knowledge.py`                                                                                                                                                              | Wave 1A domain/route tests pass.                                                                                                                                                                                   |
| Backend quality                  | `uv run --directory backend ruff check app tests && uv run --directory backend mypy app && uv run --directory backend pytest`                                                                                                         | Backend lint, types and the full test suite pass.                                                                                                                                                                  |
| Empty database migration smoke   | `empty_root="$(mktemp -d)" && DATABASE_URL="sqlite:///$empty_root/maya.sqlite3" uv run --directory backend alembic upgrade head && DATABASE_URL="sqlite:///$empty_root/maya.sqlite3" uv run --directory backend alembic upgrade head` | A fresh empty database upgrades to `0002_wave1_agents_rag`; repeating the deployment command is a no-op.                                                                                                           |
| Populated migration preservation | `uv run --directory backend python ../scripts/test_wave1_migration.py`                                                                                                                                                                | A temporary database stops at exactly `0001_wave0_baseline`, preserves the seeded Wave 0 rows/relationships/fingerprint through `0002` and a repeat head upgrade, and proves Wave 1A tables/constraints.           |
| FastAPI export                   | `uv run --directory backend python ../scripts/export_fastapi_openapi.py /tmp/maya-wave1-fastapi-openapi.json`                                                                                                                         | The live app exports after frozen `uv sync --directory backend --frozen`; no missing backend input is silently treated as a placeholder.                                                                           |
| Strict route/schema comparison   | `node scripts/compare_route_surface.mjs --server-openapi /tmp/maya-wave1-fastapi-openapi.json`                                                                                                                                        | Exactly 33 implemented operations match operationId/method/path, security, parameters, request bodies, statuses and schemas; exactly 34 later-wave placeholders retain owners/reasons.                             |
| Repository/secret boundary       | `node scripts/check_repo_boundary.mjs && node scripts/test_repo_boundary.mjs`                                                                                                                                                         | Generated API source remains covered and no runtime/secret/private reference enters the product repository.                                                                                                        |
| Frontend quality                 | `CI=1 pnpm --filter @maya/frontend lint && CI=1 pnpm --filter @maya/frontend typecheck && CI=1 pnpm --filter @maya/frontend test && CI=1 pnpm --filter @maya/frontend build`                                                          | Wave 1A UI and generated-client consumers pass the existing frontend quality gates.                                                                                                                                |
| Compose structure                | `docker compose config --quiet`                                                                                                                                                                                                       | The local three-service structure remains valid.                                                                                                                                                                   |

The route comparator treats OpenAPI 3.1 multi-type `type` arrays as sets for
semantic comparison, so `type: [string, null]` and `type: [null, string]`
compare equal. This representation normalization does not relax exact
property, required-field, enum, format, bounds, request/response status,
security, or forbidden browser-visible provider/model/key/external-voice
checks. Response schema supersets remain disallowed unless an explicit,
reviewed entry exists in `contracts/response-contract-allowlist.json` (the
current allow-list is empty).

The frozen product OpenAPI is unchanged in Wave 1A. The 24 implemented IDs
listed in `docs/gates/wave1/GATE_PACKET.md` are removed from
`contracts/route-surface-placeholders.json`; the remaining 34 later-wave IDs
keep their existing M07/M08/M10-M15 owner and reason. The route fixture is
generated from the frozen copy by `scripts/generate_route_fixture.mjs`, so it
must be regenerated whenever the implemented operation set changes and then
checked for a clean diff on a fresh run.

## CI boundary

`.github/workflows/wave0.yml` is the current quality workflow and is named for
the Wave 1A gate while retaining the historical filename. It asserts the
Wave 1A migration/tests/modules, installs with frozen Node/pnpm and uv locks,
runs the targeted and full backend suites, keeps an empty-database repeated-head
smoke, runs populated `0001 → 0002` preservation evidence, exports FastAPI
OpenAPI, and invokes the strict 33-operation comparator. All quality steps use
Mock providers and no supplier credentials.

## Current main-agent G3 run — 2026-08-27 02:33 Asia/Shanghai

The complete Wave 1A deterministic suite passed against the final post-G2
checkout:

- `CI=1 pnpm install --frozen-lockfile` and `CI=1 pnpm format:check` passed;
- frontend lint, TypeScript, production build, and Vitest passed: 6 files and
  22 tests;
- backend Ruff and mypy passed; the full pytest suite passed: 28 tests;
- empty temporary database upgraded to `0002_wave1_agents_rag` twice;
- populated migration evidence passed: exact `0001_wave0_baseline` seed,
  fixed-row/relationship preservation, seed fingerprint
  `732a9ee8a8a4f35277d97f2038cf2f53d532c28c565f8bae31e0f2fb59e7f499`, head
  `0002_wave1_agents_rag`, 13 new tables, and 43 checked constraints;
- frozen OpenAPI/hash and clean-checkout drift probe passed (60,210 bytes),
  generated types/client clean-diff passed, Redocly passed, response checks
  passed, WebSocket 29-positive/11-negative fixtures and generator clean-diff
  passed, and Compose configuration passed;
- route fixtures passed with the positive case and 12 negative cases,
  including nullable type-order equivalence; the live FastAPI export passed
  strict comparison with exactly 33 implemented operations and 34 later-wave
  placeholders;
- repository boundary, generated-source secret, and force-tracked private
  credential probes passed; Prettier and diff checks passed.

The backend test run emitted one upstream
`StarletteDeprecationWarning`: Starlette's `TestClient` currently uses
`httpx`, and recommends `httpx2`. It did not affect the result (`28 passed,
1 warning`).

## Main Docker/browser integration

- cold no-cache frontend/backend builds passed using the frozen image/runtime
  inputs; FFmpeg 5.1.9 remains installed in the backend image;
- gateway, frontend and backend became healthy on the single 8080 origin;
- an isolated mode-0700 Docker data root completed the student
  Agent/AGENT.md/Markdown/index/matched+no_match/publish flow, teacher
  published-only snapshot inspection/download, and other-group 404 checks;
- a backend restart preserved the exact published AgentVersion,
  KnowledgeSnapshot and RAG bytes; database/source/snapshot/WAL files were
  mode 0600, journals were committed, and the application SQLite connection
  reported foreign keys on, WAL, busy timeout 5000 and no FK violations;
- the isolated smoke dataset was moved to Trash and the backend was recreated
  against the normal local database. Normal data migrated to
  `0002_wave1_agents_rag`, contains no smoke Agent and all three services remain
  healthy;
- the actual login page rendered without console warning/error at desktop and
  360x800. Mobile scroll width equalled 360, the card width was 328 and the
  login button met the 44px touch target.

Main signs M05/M06/M09 and Wave 1A G3. This evidence is Mock-only and does not
claim M02/M07/M08, debate/interaction/Maya report, real supplier calls or final
TikTok RAG teaching quality.
