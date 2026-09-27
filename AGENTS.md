# Working on Maya Platform

This is the single working agreement for everyone who changes this repository,
human or agent. `docs/PROJECT.md` says what the product is and where it stands;
this file says how to work on it. When the two disagree, the user's latest
explicit decision wins, then `docs/PROJECT.md`, then this file.

`CLAUDE.md` exists only so Claude Code loads this file. Do not maintain a
second copy of these rules anywhere.

## 1. Before you change anything

Read `docs/PROJECT.md`. Read the code you are about to touch. That is usually
enough — this repository has no task-packet ceremony any more.

Work on a branch. Never commit directly to `main` unless the user says so.

For branch integration, fetch remote refs, compare ancestry and preserve dirty
work before merging. Follow the user's selected refs; a newer sibling or revert
branch is not implicitly in scope. Keep a recoverable local checkpoint, resolve
overlapping behavior deliberately, and record exact input refs in `docs/PROJECT.md`.

## 2. How to write code here

**Simplicity first.** Solve the requested problem with the smallest clear change.
Do not add unrequested features, speculative extension points or dependencies
that existing code can reasonably replace. Keep single-use code in place;
introduce an abstraction only for a concrete shared need. UI redesigns preserve
existing wording unless a copy change is explicitly requested.
Teaching and attribution guidance belongs in editable Rulesets; do not silently
reinsert removed guidance through the execution contract.

Shared help must distinguish keyboard focus from mouse-click focus and clear on
pointer leave, navigation, removed targets, scrolling and window blur. Keep
keyboard dismissal and touch behavior when changing hover interactions. For
history-row actions, date and Delete must be mutually exclusive; clicking a row
must not pin Delete after the pointer leaves.
Immerse has no manual barrage pause control. Final input freezing automatically
ends message collection; retain that transactional cutoff.

Voice availability must not gate Debate text publication. Use a configured
fallback, or explicit text-only playback when none is available; never fabricate
audio or weaken supplier-download SSRF checks to hide a DNS/proxy failure.

**Match the surrounding code.** Comment density, naming, error handling and
module layout are already consistent; follow what is next to your change
rather than importing a different style.

**Comments explain why, never what.** A comment earns its place when it
records a constraint, a trade-off or a non-obvious consequence. Do not narrate
the code, do not leave commented-out code, and do not write comments that only
restate the function name.

**Fail closed on anything a provider, a student or a teacher can influence.**
An unexpected value must produce a safe error code and stop, never a guess.

**Never weaken a check to make something pass.** If a test or contract blocks
you, either the code is wrong or the check encodes a rule that is genuinely
wrong. Fix the code, or change the check deliberately and record why in the
same commit. Deleting an assertion to get green is the one thing that is
always wrong here.

**State every rule you enforce.** If the server rejects a provider response
for violating a rule, the prompt that produced that response must state the
rule. Enforcing an unstated rule is a defect, and it is how several real
provider turns were lost.

**Keep diagnosis possible.** A failure path that records only a safe error
code must also log the code and any server-authored pointers. Never log a
provider response body, a credential, a private path or student data.

## 3. Checks you must run

Run these from the repository root before you report a change complete. Keep
the scope proportional: a docs-only change does not need the full battery, and
anything touching `backend/app` or `contracts/` needs all of it.

`pnpm check` runs the complete deterministic suite. Also run the generated-file
boundary probe below. Fix stale fixtures against the current product contract;
retain consent, ownership and charged-request assertions when budgets change.
The owner removed all product request/token/CNY budget ceilings. Legacy max_*
fields are accounting estimates; do not restore budget rejection in code, database
checks, tests or outbound model output caps. Keep explicit retry authorization and
unknown-acceptance recovery separate from budgeting.

```bash
cd backend && uv run pytest -p no:warnings && uv run ruff check . && uv run mypy app
uv run ruff format --check app tests migrations/versions/0004_wave2_debate_playback.py \
  migrations/versions/0006_pre_wave3_polish.py \
  migrations/versions/0007_wave3_interaction_report.py
```

`ruff check` and `ruff format` are separate gates and CI runs both. A change
that lints clean can still be unformatted, so run the formatter check before
you report a change complete.

```bash
pnpm -C frontend test --run && pnpm frontend:typecheck && pnpm frontend:lint
```

```bash
node scripts/check_frozen_openapi.mjs
node scripts/check_generated_contracts.mjs
node scripts/check_generated_ws.mjs
node scripts/check_openapi_responses.mjs
node scripts/check_document_authority.mjs
node scripts/check_latin_script_tables.mjs
node scripts/check_repo_boundary.mjs --probe-generated
node scripts/test_frozen_openapi.mjs
node scripts/test_openapi_responses.mjs
node scripts/test_route_surface.mjs
node scripts/test_ws_events.mjs
node scripts/test_ws_commands.mjs
node scripts/test_repo_boundary.mjs
pnpm exec redocly lint --config contracts/redocly.yaml contracts/openapi-v0.1.yaml
pnpm exec prettier --check .
uv run --project backend python scripts/test_reset_demo_runtime.py
```

The route-surface comparison needs the generated server contract first:

```bash
uv run --directory backend python ../scripts/export_fastapi_openapi.py /tmp/maya-openapi.json
node scripts/compare_route_surface.mjs --server-openapi /tmp/maya-openapi.json
```

Run backend tests from `backend/`. The application reads `.env` relative to
the working directory, so running them from the repository root loads the real
`.env` and fails CSRF-sensitive tests for reasons that have nothing to do with
your change.

`tests/test_wave3_knowledge.py::test_two_database_threads_concurrent_replace_have_one_winner`
is a known flake: it races two writers and loses roughly one run in three.
Re-run it before treating it as a regression.

## 4. Changing a contract

`contracts/openapi-v0.1.yaml` is byte-frozen against `contracts/openapi-v0.1.sha256`.
Changing it is a four-step operation and skipping any step turns CI red:

```bash
pnpm exec openapi-typescript contracts/openapi-v0.1.yaml -o frontend/lib/api/generated/schema.d.ts
node scripts/generate_route_fixture.mjs
shasum -a 256 contracts/openapi-v0.1.yaml | cut -d' ' -f1 \
  | xargs -I{} printf '%s  contracts/openapi-v0.1.yaml\n' {} > contracts/openapi-v0.1.sha256
node scripts/check_frozen_openapi.mjs
```

Express a single-value enum as `const`, not a one-entry `enum`: Pydantic emits
`const` for a one-value `Literal` and the route comparator compares them
literally.

`contracts/llm-turn-output.v1.schema.json` is hash-pinned in
`app/providers/control.py` and `app/providers/llm_output.py`. Editing it means
updating both constants and the documents that quote the digest.

Adding a migration means updating `ALEMBIC_HEAD` in `app/core/db.py`; the
readiness probe compares the database against that constant and the container
stays unhealthy until they agree.

When adding an API operation, update the implemented operation set in
`scripts/generate_route_fixture.mjs`, regenerate its fixture and update the exact
route count in `scripts/test_route_surface.mjs` together.

## 5. Real provider work

A real provider request costs money and is never automatically retried. Before
the first request of a run:

- confirm the run is new and its charged-request count is zero;
- confirm the provider, `LLM_MODEL`, region, dimension and policy hash
  are the reviewed ones;
- confirm the teacher disclosure was confirmed for that exact manifest.

A structure repair is the one exception to "no retry": it re-sends the same
authorized manifest once with frozen feedback, inherits its first attempt's
acceptance run and takes the next ordinal automatically. `acceptance_unknown`
is terminal for a run — preserve the ledger and stop.

Never put a credential, endpoint, workspace id, model id, raw provider
response or private path into a browser-facing DTO, a log, a commit or a
report. The teacher-only provider disclosure may show the supplier display
name, region, purpose, outbound field classes, storage facts and the exact
policy/manifest hashes, and nothing else.

## 6. Running the Demo locally

After an authorized update, back up the active SQLite database using SQLite's
backup API inside the backend container, then rebuild with
`docker compose up -d --build --wait`. Preserve `.env`, private configuration and
runtime assets. Verify Compose health, container `/health/ready`, the schema head
and `http://localhost:8080/`; distinguish these from manual product acceptance.

The committed Compose file publishes `8080`. To run an isolated stack, write an
override **outside** the repository and tag the port list so Compose replaces
it instead of appending:

```yaml
services:
  gateway:
    ports: !override
      - "127.0.0.1:18080:8080"
```

`CLASSROOM_PUBLIC_BASE_URL` must satisfy two independent rules at once: the
classroom QR code rejects loopback and needs a private-LAN address, while the
CSRF origin check compares the port. Use the host's LAN address with the port
the stack actually publishes.

`scripts/reset_demo_runtime.py` renames the runtime directory rather than
deleting it. A container bind mount follows the original inode, so a container
that is only stopped keeps writing into the quarantined copy while host-side
tools act on the new `data`. **Always `docker compose down` before `up -d`
across a reset.** To prove the mount is right:

```bash
docker exec <project>-backend-1 sh -c 'echo probe > /app/data/.mount-probe'
find . -maxdepth 2 -name .mount-probe
```

## 7. Recording progress

`docs/PROJECT.md` is the only place project progress lives. Update it in the same
commit as the work it describes, and only with facts you have observed:

- move an item between **Working**, **In progress** and **Not started** when a
  real run says so, not when the code merely looks finished;
- keep the real-call ledger honest — every charged provider request is counted
  there, including a failed one;
- record a deviation from a frozen contract explicitly, with the reason, rather
  than letting the code and the document drift apart.

Keep `docs/PROJECT.md` below 20,000 bytes by compacting repeated history while
preserving current decisions, acceptance boundaries and charged-call records.
README explains how to use/run the product; AGENTS contains working rules, not a
second progress log. Refresh those documents when their instructions change.

Do not create status files, handoff notes or worklogs beside it. If something
is worth keeping, it belongs in `docs/PROJECT.md`, an ADR under `docs/adr/`, or a
contract under `docs/contracts/`.

## 8. Commits

One commit per coherent change, with its tests and its documentation update.
Write the subject as what the change does, not what you did.

Never commit `.env`, credentials, the private demo account catalog, runtime
data, generated media, quarantined runtimes or provider responses.
`node scripts/check_repo_boundary.mjs --probe-generated` enforces this; run it
before you commit anything that touches configuration or fixtures.
