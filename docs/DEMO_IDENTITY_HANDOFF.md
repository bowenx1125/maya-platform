# Task: replace the Demo identities and the default Agents

You are working in `/Users/xubosmell/Desktop/Maya/maya-platform`. Do not touch
`/Users/xubosmell/Desktop/Maya/maya-platform-demo-ad50` — it is a separate playground.

This is a deliberate change to a frozen Demo boundary. It was requested by the product
owner directly, so it overrides the current wording in `PROJECT.md` §4; part of the task
is to update that wording rather than to work around it.

## 1. Target state

**One** seeded group replaces the current two.

| | Now | After |
| --- | --- | --- |
| Groups | `Group A` (group-bowen), `Group B` (group-kaikai) | one `Demo Group` |
| Teacher | `teacher-demo` / "Demo Teacher" | "Maya" |
| Students | 6 (`student-bowen-1..3`, `student-kaikai-1..3`) | 3: `Bowen` / `Kaikai` / `Jade` |
| Password | generated per install | `123456` for every account |
| Quick login | enabled | unchanged, still enabled |
| Default Agents | 2 (`Maya Demo Guide`, `Maya Demo Companion`) | 3: `Socrates`, `Plato`, `Laozi` |

All three default Agents belong to the single Demo Group, are published, are
persona-confirmed, and have a ready Mock snapshot — exactly like the current baselines.
A teacher must be able to log in and immediately create a 2–5 Agent Debate with no
setup. Keep `publish_blockers` empty for all three.

Everything else about the Demo stays as it is. Do not change the provider composition,
the acceptance chain, the RuleSet, or the Real/Mock labelling.

## 2. Prepared assets — use these files verbatim

The persona and knowledge content is already authored and validated. Do not rewrite it.

```
/Users/xubosmell/Desktop/Maya/demo-agents/socrates/AGENT.md
/Users/xubosmell/Desktop/Maya/demo-agents/socrates/RAG.md
/Users/xubosmell/Desktop/Maya/demo-agents/plato/AGENT.md
/Users/xubosmell/Desktop/Maya/demo-agents/plato/RAG.md
/Users/xubosmell/Desktop/Maya/demo-agents/laozi/AGENT.md
/Users/xubosmell/Desktop/Maya/demo-agents/laozi/RAG.md
/Users/xubosmell/Desktop/Maya/demo-agents/SHA256SUMS
```

Verify integrity first:

```bash
cd /Users/xubosmell/Desktop/Maya/demo-agents && shasum -a 256 -c SHA256SUMS
```

Each file has already been checked against the real product code:

- all three `AGENT.md` compile with `compile_persona()` — `ok=True`, zero diagnostics,
  and the compiled `identity.name` equals the `#` heading (`Socrates`, `Plato`, `Laozi`);
- all three `RAG.md` produce **exactly one** chunk through `build_chunks()`
  (178 / 188 / 202 whitespace tokens);
- all six files are pure ASCII: no CJK, no HTML tags, no Markdown links, no URLs.

Copy the content into the baseline specs the same way the current baselines embed theirs
(Python string constants in `demo_baseline/service.py`), or load them as packaged
fixture files — your choice, but the bytes must not drift, and whichever you pick must
survive `check_repo_boundary.mjs`.

## 3. Exact identifiers to use

`backend/app/seed.py` asserts at **import time** that every `SEED_IDS` entry equals
`uuid5(SEED_NAMESPACE, key)`. These are already computed under the frozen Wave 0
namespace `a7cea9e2-390f-5b48-b129-4f388b0362e3`, so the guard will pass:

```python
SEED_IDS = {
    "demo-course-001": "b1ae79ed-e4a6-5b02-9abd-3a3ae944284b",  # unchanged
    "group-demo": "7813f937-902c-5534-bfb2-ad773a43aeda",
    "maya": "08b9de2d-bb75-5c71-a64b-231b48f9eb25",
    "bowen": "60541c78-30f1-55c5-b2aa-207b6a766883",
    "kaikai": "bc170f51-45fb-5296-a36d-a2edc8f8d315",
    "jade": "89857c76-2d84-5ecf-b680-990815b98680",
}
```

Reserved baseline IDs for the three Agents, derived as
`uuid5(namespace, "demo-baseline-<agent>:<part>")` under the same namespace:

| part | Socrates | Plato | Laozi |
| --- | --- | --- | --- |
| agent | 93c04441-1bae-54b2-8037-78622b88d640 | 9b5d4adf-d82d-578e-9e70-6adf7713715f | 007c71c4-80b8-5168-9721-b8b66a86a1a3 |
| version | e792ee07-7f8b-52d2-817b-d315a3d32445 | 632571be-07c9-5da9-98c8-19da1d044ea4 | 5d69d715-e597-50fb-923b-fcffdf1464f2 |
| document | b3c49aff-9bd2-5106-bb19-df49fefcd57f | 07ffd76c-cca8-5d8d-9305-4acf8e291e48 | c01f183f-ab7a-5f80-8434-6b55e097d61c |
| snapshot | 49985a15-9633-5190-9982-173c7a21d6e7 | 4913e647-0750-5d33-8e79-1bdc39a890f2 | 4be98d3b-f324-5319-ae47-9021e5a78a76 |
| source-file | 85151808-81ad-5c44-87bc-63b7f256ed8b | c5b28abd-fb52-5364-b5ad-41c0753427af | b04fc099-9195-5933-8dfa-e41670afc1b6 |
| snapshot-file | e3e14380-5a80-5cfe-911a-c370577ccd6f | 34b7bef0-bbd8-5486-b679-a26eed7c90c7 | 708f93ec-e2a1-5240-8ff3-84c4675ec7b2 |
| frozen-file | f2cf5047-d385-5268-9546-4891cca2e2e2 | 12c57cc1-956c-52f7-93e5-8297b44c854c | 57472fa4-6cb8-5e15-ad8a-96b2e3c1236e |
| snapshot-document | 46674f4f-7397-56ed-af24-3aca35e54823 | 2732aaff-cb74-5cfd-ac92-8123823111dc | 6014de16-6223-55b7-a6ae-8ee3f136082a |
| chunk | 8930b6e8-c664-5f41-a794-a79e7157c71d | 3c5b2d05-a32c-5883-8bac-08d3911694ab | 7d6f29c5-f446-575c-a83a-c3ebb6b403b4 |
| snapshot-file-reference | 52f7361a-26d9-525a-b995-ac0fc8de2dca | 0843f3b8-d66a-5081-aa42-2dbe81a38118 | 11aaa267-682d-54d6-96bd-927498753d88 |
| frozen-file-reference | 8cd981ac-313c-5123-ad58-92a02dcb7573 | 21fa3a3b-59bd-5960-8297-5d61d4ef5647 | 478f9390-70ac-5702-89b3-1d9d3b92d6b4 |

Assign `confirming_user_id` per Agent so the three students each own one:
Socrates → `bowen`, Plato → `kaikai`, Laozi → `jade`.

## 4. Files to change

`demo_baseline/service.py` was already refactored into a `BaselineSpec` dataclass with
`BASELINE_A` / `BASELINE_B` and a `BASELINE_SPECS` tuple, so adding a third spec is the
natural shape. Replace the two existing specs rather than appending to them.

**Core**

- `backend/app/seed.py` — `SEED_IDS`, `GROUP_*`/`*_STUDENT_IDS` constants, `USERS`,
  `GROUP_SPECS`, course/group membership wiring, and the group-conflict guard.
- `backend/app/modules/demo_baseline/service.py` — three specs; `BASELINE_AGENT_IDS`,
  `BASELINE_VERSION_IDS`, `BASELINE_DOCUMENT_IDS`, `dirty_counts()` and
  `baseline_is_usable()` must all cover **all three**.
- `backend/app/modules/demo_baseline/__init__.py` — exports.
- `backend/app/modules/demo_baseline/router.py` — `/demo/baseline` currently returns one
  primary baseline. Keep that shape (see §5) and point it at Socrates.
- `backend/app/modules/demo_acceptance/service.py` — imports `BASELINE_AGENT_ID` /
  `BASELINE_VERSION_ID` / `BASELINE_SNAPSHOT_ID` and rejects a baseline as the acceptance
  target via `BASELINE_AGENT_IDS` / `BASELINE_VERSION_IDS`.
- `scripts/bootstrap_local_demo.py` — `FIXED_USERS` becomes 4 entries (`maya`, `bowen`,
  `kaikai`, `jade`) in the single `group-demo`.

**Credentials and quick login**

- `backend/config/demo-accounts/accounts.private.md` and `backend/config/demo_users.yaml`
  are regenerated by `bootstrap_local_demo.py`. Both stay ignored and mode `0600`.
- Password is `123456` for all four accounts. `bootstrap_local_demo.py` enforces 6–4096
  characters, so this is accepted unchanged — do not weaken that validator.
- `DEMO_QUICK_LOGIN` stays `true`. Quick login reads the catalog and maps to `User` rows
  by id, so it works automatically once the seed and the catalog agree.

**Tests and drivers that hard-code the old identities** (≈30 files — verify with
`grep -rln "teacher-demo\|student-bowen\|student-kaikai\|GROUP_BOWEN_ID\|GROUP_KAIKAI_ID"`):

- `backend/tests/conftest.py` — the credentials fixture lists 7 users; it becomes 4.
- `scripts/test_bootstrap_local_demo.py` — asserts seven Argon2 hashes; becomes four.
- `backend/tests/test_seed.py`, `test_auth_org.py`, `test_demo_baseline*.py`,
  `test_pw3_*`, `test_wave1*`, `test_wave2*`, `test_wave3*`, `test_wave4*`.
- `manual-tests/real-core-demo/scripts/acceptance.py` — the `prepare` step logs in as
  `student-bowen-1` (the `MAYA_STUDENT_USERNAME` default) and the teacher as
  `teacher-demo`. Both defaults must change, and the group it creates the target Agent in
  is resolved from `/demo/baseline`, so it follows automatically once §5 is respected.

**Documents**

- `PROJECT.md` §4 currently freezes "one seeded course, one teacher and two three-student
  groups". Update it to one course, one teacher and one three-student group, and note the
  three default published Agents.
- `PROJECT_STATUS.md`, `README.md` and the Demo package instructions wherever they name
  the old accounts or the two default Agents.

## 5. Hard constraints — do not break these

1. **Keep `/api/v1/demo/baseline` returning a single primary baseline object with its
   current field set.** The acceptance driver asserts
   `set(value) == BASELINE_FIELDS` and that the four ids are distinct. Adding a list or
   extra keys there breaks the Real-Core acceptance driver. Point it at Socrates and
   expose the other two only through the ordinary published-Agent routes.
2. **`dirty_counts()` must exclude all three baseline Agents.** The acceptance `prepare`
   step fails closed unless a fresh runtime reports
   `dirty_agents=0, dirty_debates=0, dirty_interactions=0`, and reports exactly
   `(1, 0, 0)` after it creates its own target Agent. If a seeded Agent is counted as
   dirty, the whole Real-Core chain stops.
3. **Persona section order is strict.** `_SECTIONS` must appear exactly once each, in
   order: Identity, Cultural lens, Core values, Initial position, Speaking style, Debate
   strategy, Boundaries. The supplied files already satisfy this — if you re-type any of
   them, re-validate.
4. **Each `RAG.md` must produce exactly one chunk**, or the baseline creation raises
   `DemoBaselineConflict`.
5. **Baseline immutability guards must cover all three Agents** —
   `reject_baseline_agent_mutation`, `reject_baseline_version_mutation`,
   `reject_baseline_document_mutation`, `is_system_baseline_agent`.
6. Snapshots stay Mock identity (`embedding_provider="mock"`, `embedding_region="local"`,
   `embedding_policy_version="w4-mock-v1"`). Do not give a seeded Agent a real embedding.
7. Never commit `.env`, `demo_users.yaml`, `accounts.private.md`, or runtime data.
   `123456` is a local Demo password; it still must not appear in a committed file.

## 6. Operational traps (already cost real time in this project)

- **After `scripts/reset_demo_runtime.py`, recreate the containers.** The script renames
  `data/`; a container that is only `stop`ped and started again keeps its bind mount on
  the *renamed* inode, so the app writes to the quarantined copy while host-side tools act
  on the new `data/`. Always `docker compose down` then `up -d`. Confirm with:
  `docker exec <project>-backend-1 sh -c 'echo probe > /app/data/.mount-probe'` and check
  where it lands on the host.
- An external Compose port override must use `ports: !override`; Compose merges sequences
  by default and the container keeps publishing `8080` as well.
- `CLASSROOM_PUBLIC_BASE_URL` must be a **private-LAN** address (loopback is rejected for
  the classroom QR) whose **port matches** the stack's published port (the CSRF origin
  check compares ports).
- Running `pytest` from the repository root loads the real root `.env` into test settings
  (`env_file=".env"` is relative to cwd) and produces spurious `csrf_failed` failures. Run
  the backend suite with `cwd=backend`.

## 7. Verification before you report done

```bash
# from backend/
uv run pytest -p no:warnings
uv run ruff check .
uv run mypy app

# from repository root
node scripts/check_frozen_openapi.mjs
node scripts/test_frozen_openapi.mjs
node scripts/check_generated_contracts.mjs
node scripts/check_generated_ws.mjs
node scripts/check_openapi_responses.mjs
node scripts/test_openapi_responses.mjs
node scripts/check_document_authority.mjs
node scripts/check_latin_script_tables.mjs
node scripts/test_route_surface.mjs
node scripts/test_ws_events.mjs
node scripts/test_ws_commands.mjs
node scripts/check_repo_boundary.mjs --probe-generated
node scripts/test_repo_boundary.mjs
pnpm exec redocly lint --config contracts/redocly.yaml contracts/openapi-v0.1.yaml
pnpm exec prettier --check .
uv run --project backend python scripts/test_reset_demo_runtime.py
uv run --project backend python scripts/test_bootstrap_local_demo.py
uv run --project backend python manual-tests/real-core-demo/scripts/acceptance.py check
uv run --directory backend python ../scripts/export_fastapi_openapi.py /tmp/openapi.json \
  && node scripts/compare_route_surface.mjs --server-openapi /tmp/openapi.json

# frontend
pnpm -C frontend test --run && pnpm frontend:typecheck && pnpm frontend:lint
```

Then prove it in the running product, not only in tests:

1. `docker compose down`, `python3 scripts/reset_demo_runtime.py`, `docker compose up -d`.
2. `python3 scripts/status_demo.py --url <origin>` reports baseline ready and
   `Dirty work: Agents=0 Debates=0 Interactions=0`.
3. Quick-login shows exactly four identities: Maya, Bowen, KaiKai, Jade.
4. Log in as Maya and confirm `GET /api/v1/courses/{course_id}/published-agents` returns
   **three** Agents — Socrates, Plato, Laozi — each with an empty `publish_blockers`.
5. Create a 3-Agent, 2-round `ordered_multi_expert_mutual_learning_v1` Debate and play it
   to the end. Confirm six public turns, correct phases, and that the debate reaches
   `debate_finished` on its own (the last turn auto-finishes; `/finish` is only the early
   termination path and is rejected once playback is `completed`).
6. Open and close the interaction, generate the report, and confirm a 600–900 word English
   report with no winner and no leaked private data.

Report the exact SHA, the four account names, the three Agent names and ids, and the
output of the verification run.
