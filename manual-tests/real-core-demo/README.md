# Real-Core Demo acceptance packet

This packet drives the reviewed Real-Core composition with a bounded acceptance
run. The product semantics are preserved: one real Snapshot embedding call, two
independent real participant query calls, and four real debate-turn LLM calls.
Those seven calls are the debate-stage count only. The accepted happy-path budget
and hard ceiling are both eight, reserving ordinal 8 for the later Report call.

TTS, Voice and Translation remain Mock. Report is not wired in this packet yet;
the driver exposes `report_acceptance_adapter(...)` as the small integration seam
for the Report worker. It must eventually attach the Report manifest as call 8
before confirmation/send, then bind the resulting Report revision to the run.
No Report endpoint is guessed here.

The packet contains only fictional, identity-free text. It never prints a
credential, raw Provider response, endpoint, model/resource identifier or student
data. Pending manifests expose only their immutable `manifest_hash`; provider
operation IDs and the raw ledger stay server-side.

Run the offline checks first:

```bash
uv run --project backend python manual-tests/real-core-demo/scripts/acceptance.py check
uv run --project backend pytest -q manual-tests/real-core-demo/scripts/test_acceptance.py
uv run --project backend ruff check manual-tests/real-core-demo/scripts/acceptance.py manual-tests/real-core-demo/scripts/test_acceptance.py
```

## Prepare a fresh target

The application startup creates and verifies the immutable Bowen Demo baseline.
Prepare only the student target Agent B while the application is in its all-Mock
composition. The driver reads `/api/v1/demo/baseline`, verifies stable IDs and
uses that published version as participant A. It does not create or mutate a
second control Agent.

```bash
MAYA_BASE_URL=http://127.0.0.1:18080 \
MAYA_STUDENT_PASSWORD='...' \
uv run --project backend python manual-tests/real-core-demo/scripts/acceptance.py \
  prepare --checkpoint /private/path/real-core-demo.json
```

`prepare` is fail-closed unless `/api/v1/demo/status` reports the same usable
baseline, zero dirty Agents/Debates/interactions, and an all-Mock composition. It
writes a mode-0600 `real-core-demo-checkpoint-v4`. The checkpoint deliberately
contains no acceptance-run ID: the run is created only by `execute` against this
fresh target/version and the exact fixture hash.

## Execute the bounded stage

Import the separately reviewed, endpoint-bound Embedding and LLM policy files
before enabling either real selector. Keep both JSON files outside the repository
and import them one command at a time. Before restarting the isolated Compose
application, put the dual-Real values in the ignored root `.env`; see the prior
policy-import instructions for the complete environment list.

```bash
MAYA_BASE_URL=http://127.0.0.1:18080 \
MAYA_STUDENT_PASSWORD='...' \
MAYA_TEACHER_PASSWORD='...' \
uv run --project backend python manual-tests/real-core-demo/scripts/acceptance.py \
  execute --checkpoint /private/path/real-core-demo.json \
  --embedding-policy-hash <embedding-policy-sha256> \
  --llm-policy-hash <llm-policy-sha256>
```

Before the first real request, the teacher creates
`POST /api/v1/demo/acceptance-runs` with the fresh target/version and fixture
hash, then verifies `starting_charged_requests=0`, `call_count=0` and
`charged_request_count=0`. After the Debate is created, it is bound with
`POST /{run_id}/debate` before playback starts.

For every pending Snapshot, query or LLM manifest, the driver performs this
ordering:

1. read the pending `manifest_hash`;
2. attach it to the next ordinal with `POST /{run_id}/calls` and
   `{ "manifest_hash": "...", "call_no": N }`;
3. verify the run summary count;
4. confirm the exact disclosure and invoke the existing preparation continuation.

The server resolves the unique prepared operation by manifest hash. The driver
keeps a local set of bound hashes as a duplicate fence and never retries a
provider request. The existing retry-preparation call is only the explicit
continuation of that same already-confirmed prepared operation. Any
`acceptance_unknown` or provider failure stops the run immediately.

The execute result is
`REAL_CORE_DEMO_DEBATE_STAGE_PASS_PENDING_REPORT` after the debate is finished
and its run summary reaches stage count 7. It does not claim the full eight-call
Demo pass until the Report adapter is implemented and Report revision binding is
accepted.

## Verify the debate stage

Verification checks the immutable Snapshot identity, participant bindings,
independent B-slot query semantics, four final-ready English-safe turns and
Evidence Trace lineage. It reports the same pending-Report stage result and
updates the private checkpoint to `verified`.

```bash
uv run --project backend python manual-tests/real-core-demo/scripts/acceptance.py \
  verify --checkpoint /private/path/real-core-demo.json \
  --database-url "$MAYA_DATABASE_URL" \
  --embedding-policy-hash <embedding-policy-sha256> \
  --llm-policy-hash <llm-policy-sha256>
```

Do not run this packet against the shared port, a non-empty runtime root, a real
Provider without the reviewed policy/fixture acceptance, or GitHub CI.
