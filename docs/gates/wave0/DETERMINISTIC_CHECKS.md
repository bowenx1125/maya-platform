# Wave 0 deterministic checks (M17/M18)

Run these commands from the Git root, `maya-platform`. They are mock-only and
must not call a supplier. The product copy is always checked against the
committed SHA-256 manifest at `contracts/openapi-v0.1.sha256`. When the Maya
parent checkout is available at `../docs/pre-code-contracts/openapi-v0.1.yaml`,
the checker also performs a byte-for-byte comparison; an isolated product
checkout does not require that parent path.

## Current run — 2026-08-26 22:38 Asia/Shanghai

| Check                            | Command                                                                                                                                                                                               | Result                                                                                                                                                 |
| -------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Frozen OpenAPI copy              | `node scripts/check_frozen_openapi.mjs`                                                                                                                                                               | PASS — 60,210 bytes equal to the in-repo SHA-256 manifest and local parent when present                                                                |
| Frozen clean-checkout simulation | `node scripts/test_frozen_openapi.mjs`                                                                                                                                                                | PASS — isolated product copy verifies without `../docs`; mutated copy is rejected                                                                      |
| Generated TypeScript and client  | `node scripts/check_generated_contracts.mjs`                                                                                                                                                          | PASS — openapi-typescript 7.13.0 clean diff; openapi-fetch 0.17.0 wrapper present                                                                      |
| Redocly lint                     | `CI=1 pnpm exec redocly lint --config contracts/redocly.yaml contracts/openapi-v0.1.yaml`                                                                                                             | PASS                                                                                                                                                   |
| Explicit response contract       | `node scripts/check_openapi_responses.mjs` and `node scripts/test_openapi_responses.mjs`                                                                                                              | PASS — every frozen response is required; only documented 101/4xx exceptions pass, invalid 2xx exception is rejected                                   |
| WebSocket Ajv contract           | `node scripts/test_ws_events.mjs`                                                                                                                                                                     | PASS — 29 positive and 11 negative fixtures, including speech/provider/model/key/external-voice leakage                                                |
| WebSocket generator clean diff   | `node scripts/check_generated_ws.mjs`                                                                                                                                                                 | PASS — schema and both fixture files regenerate byte-identically in a temporary directory                                                              |
| FastAPI semantic route contract  | `uv run --directory backend python ../scripts/export_fastapi_openapi.py /tmp/maya-fastapi-openapi.json` then `node scripts/compare_route_surface.mjs --server-openapi /tmp/maya-fastapi-openapi.json` | PASS — 9 implemented operations match operationId/method/path, security, params, request bodies, statuses and schemas; 58 placeholders remain explicit |
| Comparator fixtures              | `node scripts/test_route_surface.mjs`                                                                                                                                                                 | PASS — generated fixture is deterministic; 11 missing/security/request/response/schema/forbidden-field negatives are rejected                          |
| Product boundary and secret scan | `node scripts/check_repo_boundary.mjs` and `node scripts/test_repo_boundary.mjs`                                                                                                                      | PASS — Git root is `maya-platform`; generated API subtree is scanned; simulated key/supplier URL probe is detected                                     |
| Local Demo initializer probe     | `uv run --directory backend python ../scripts/test_bootstrap_local_demo.py`                                                                                                                           | PASS — seven Argon2 hashes, random secret, mode 0600, blank supplier keys and overwrite refusal                                                        |
| Compose structure                | `docker compose config --quiet`                                                                                                                                                                       | PASS                                                                                                                                                   |
| Final application images         | `docker compose build --no-cache frontend backend`                                                                                                                                                    | PASS — unchanged retry after one transient Debian mirror 502; frontend production image and backend FFmpeg/uv locked image built                       |
| Three-service startup            | `docker compose up -d --wait`                                                                                                                                                                         | PASS — gateway started; frontend and backend healthy                                                                                                   |
| Port 8080 runtime/auth smoke     | frontend root/health plus `/api/v1/auth/*` login, me, identity list, switch, logout                                                                                                                   | PASS — 200/401 boundaries, seven identities, CSRF recovery, session rotation to student and logout invalidation verified                               |
| Container runtime/data smoke     | backend FFmpeg/ffprobe, Alembic current, live/ready health and SQLite seed/pragma checks                                                                                                              | PASS — FFmpeg 5.1.9, migration head, exact 7/1/7/2/6 seed counts, WAL and no foreign-key violations                                                    |
| Frozen JavaScript install        | `CI=1 pnpm install --frozen-lockfile`                                                                                                                                                                 | PASS                                                                                                                                                   |
| Frontend lint                    | `CI=1 pnpm --filter @maya/frontend lint`                                                                                                                                                              | PASS                                                                                                                                                   |
| Frontend typecheck               | `CI=1 pnpm --filter @maya/frontend typecheck`                                                                                                                                                         | PASS                                                                                                                                                   |
| Frontend tests                   | `CI=1 pnpm --filter @maya/frontend test`                                                                                                                                                              | PASS — 1 file, 3 tests                                                                                                                                 |
| Frontend production build        | `CI=1 pnpm --filter @maya/frontend build`                                                                                                                                                             | PASS                                                                                                                                                   |
| Backend Ruff                     | `uv run --directory backend ruff check app tests`                                                                                                                                                     | PASS                                                                                                                                                   |
| Backend mypy                     | `uv run --directory backend mypy app`                                                                                                                                                                 | PASS                                                                                                                                                   |
| Backend pytest                   | `uv run --directory backend pytest`                                                                                                                                                                   | PASS — 14 tests; one upstream Starlette/httpx deprecation warning                                                                                      |
| Alembic empty-database smoke     | `mkdir -p backend/data && uv run --directory backend alembic upgrade head`                                                                                                                            | PASS                                                                                                                                                   |

The route export must run after `uv sync --directory backend --frozen`. The
FastAPI app emits `/api/v1/...` paths; the comparison removes exactly that one
configured API prefix because the frozen OpenAPI declares `/api/v1` as its
server URL. It does not ignore arbitrary path drift.

The semantic comparator checks every implemented Wave 0 operation for the
exact operationId/method/path, inherited `SessionCookie` security (including
login's explicit `security: []`), required parameters and their schemas,
request-body presence/requiredness/media/schema, every frozen response status,
and success/error response schema compatibility. Response DTO property and
required sets are exact after local `$ref`/`allOf` normalization; only a
narrowly reviewed entry in `allow_response_schema_supersets` could relax that
rule (the current allow-list is empty). Browser-visible response schemas also
unconditionally reject `provider`, `model`, `key`, `api_key`, and
`external_voice_id` field names at any nesting level. A harmless FastAPI 422 is
accepted only with an operation-specific reason in
`contracts/response-contract-allowlist.json`; frozen statuses and security may
never be absent. Health probes are explicitly classified as infrastructure
extras. The remaining 58 entries in
`contracts/route-surface-placeholders.json` are later-wave operations only;
adding a new missing operation without an owner and reason fails the
comparison.

For local scaffold work only,
`node scripts/compare_route_surface.mjs --allow-missing-server-openapi` records
an explicit developer skip. The flag is rejected in CI. CI unconditionally
asserts backend inputs, runs frozen `uv sync`, quality checks, migrations,
exports FastAPI OpenAPI, and performs the semantic comparison, so a missing
server document cannot silently become a placeholder in CI.

## Redocly configuration boundary

`contracts/redocly.yaml` extends Redocly's `recommended` preset. Structural and
security checks remain enabled, including schema validity, operationId
uniqueness, path parameter correctness, security and `$ref` resolution. The
following generic presentation/completeness preferences are disabled narrowly:

- `operation-summary`, `info-license`, and `tag-description`: the frozen parent
  contract intentionally has no presentation-only summary/license/tag copy;
  adding it to the product copy would violate the byte-for-byte drift guard.
- `operation-4xx-response`: selected operations intentionally rely on the
  platform error envelope without repeating every error response in this
  contract snapshot. `scripts/check_openapi_responses.mjs` requires an
  explicit operation/reason entry for every such frozen omission.
- `operation-2xx-response`: the WebSocket handshake is intentionally modeled as
  `101 Switching Protocols`, not a conventional HTTP `2XX` response. The same
  checker permits this exception only for frozen `connectDebateEvents` and
  rejects any other missing-2xx exception.

These exceptions do not disable operationId, `$ref`, schema, path, security or
request/response structural validation. Any further disabled rule requires a
contract review.

## WebSocket validation boundary

`contracts/ws-events.v1.schema.json` is generated by
`scripts/generate_ws_schema.mjs`; `scripts/check_generated_ws.mjs` regenerates
the schema and fixtures into temporary paths, byte-compares every output, and
runs the temporary outputs through Ajv. It contains a closed discriminated
`oneOf` for `snapshot` plus every frozen version-1 event type. Envelope and
event-specific payload objects reject additional properties. `turn.ready` does
not define `speech`; full speech is only present in `playback.started` and
published transcript data. Provider/model/key/external-voice fields are absent
from every event schema. Negative fixtures cover speech leakage, provider,
model, `api_key`, `external_voice_id`, unknown type/version, malformed payloads,
invalid/missing sequence and additional properties.

Duplicate-key JSON is not used as a negative fixture: ordinary JSON parsers
discard an earlier duplicate key before Ajv sees the document. Sequence shape
and schema-invalid values are therefore tested in a parser-independent way.

## Local Demo initializer

The one-command local initializer is
`uv run --directory backend python ../scripts/bootstrap_local_demo.py`. It
prompts with `getpass` (or accepts `--generate-password` and displays the
generated password once), writes only ignored `.env` and
`backend/config/demo_users.yaml`, uses random 48-byte session-secret entropy,
hashes all seven fixed identities with Argon2, sets both files to mode 0600,
and refuses replacement without `--force`. It never writes supplier keys or
logs a prompted password. The deterministic probe uses a temporary root and
does not create product credentials.

## CI boundary

`.github/workflows/wave0.yml` pins the frozen Node/pnpm toolchain, installs with
`--frozen-lockfile`, sets mock provider modes, runs the checks above, and runs
frontend/backend quality gates plus Compose config. Backend existence checks,
frozen `uv sync`, Ruff, mypy, pytest, Alembic, FastAPI export and semantic route
comparison are unconditional in CI. GitHub Actions are pinned to immutable
full commit SHAs with readable release comments. No CI step is allowed to use
supplier credentials or make supplier calls. Docker image digest changes remain
reviewed dependency changes; a network-blocked image pull must be reported as
an environment limitation rather than weakened by changing a digest.

## Runtime sign-off and intentional exclusions

- Final G2 backend and foundation Sol re-audits both returned `PASS`; main signed
  M01/M03/M04/M16/M17/M18 G3. Root package integration uses the product OpenAPI
  copy and `contracts/redocly.yaml`, and `pnpm format:check` passes.
- Docker Desktop recovered to `running`. The final hardened images, three-service
  startup, port 8080 frontend/backend path, authentication/CSRF/session rotation,
  container FFmpeg, migration and exact seed checks all pass. The earlier Desktop
  condition is closed and Wave 0 has no remaining Gate blocker.
- Real suppliers, keys, real TTS/voice, formal TikTok RAG data, 3D assets and
  full Wave 1-3 routes are intentionally outside this Wave 0 quality check.
