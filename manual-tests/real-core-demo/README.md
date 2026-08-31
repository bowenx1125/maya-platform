# Real-Core Demo acceptance packet

This packet drives the reviewed Real-Core composition with a bounded acceptance
run. The product semantics are one real Snapshot embedding call, two independent
real participant query calls, four real debate-turn LLM calls, and one real Maya
Report call: `1 + 2 + 4 + 1 = 8` for this fixture's happy path. The runtime hard
ceiling is also eight; the first seven calls are only the debate-stage count.

TTS, Voice and Translation remain Mock. The Report stage opens and closes a
zero-data classroom interaction so the existing Mock insight job can produce the
immutable input for the one-shot Real Report revision. The driver waits for the
Report revision to become `generating`, confirms its exact teacher disclosure,
binds it as acceptance call 8, continues the same prepared operation, and checks
the final 600–900-word English-safe revision.

The packet contains only fictional, identity-free text. It never prints a
credential, raw Provider response, endpoint, model/resource identifier or student
data. Pending manifests expose only immutable hashes and the Report revision ID;
provider operation IDs and the raw ledger stay server-side.

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

## Execute the complete bounded path

Import separately reviewed, endpoint-bound Embedding, debate-LLM and Report
policy files before enabling the corresponding real selectors. Keep all JSON files
outside the repository and import them one command at a time. Before restarting
the isolated Compose application, put the three policy hashes and Real-Core selector
values in the ignored root `.env`.

The reviewed Real-Core composition uses the following selector and policy names.
Keep the legacy `PROVIDER_POLICY_HASH` empty so the Embedding, debate-LLM and
Maya Report policies remain endpoint-bound independently. The price-card fields
are the existing server-only accounting inputs and must be populated from the
reviewed card before enabling a real LLM-backed selector.

```dotenv
LLM_PROVIDER=dashscope
MAYA_REPORT_PROVIDER=dashscope
EMBEDDING_PROVIDER=dashscope
TTS_PROVIDER=mock
VOICE_PROVIDER=mock
TRANSLATION_PROVIDER=mock
EMBEDDING_PROVIDER_POLICY_HASH=
LLM_PROVIDER_POLICY_HASH=
REPORT_PROVIDER_POLICY_HASH=
PROVIDER_POLICY_HASH=
LLM_PRICE_CARD_VERSION=
LLM_INPUT_PRICE_CNY_PER_MILLION=
LLM_CACHED_INPUT_PRICE_CNY_PER_MILLION=
LLM_OUTPUT_PRICE_CNY_PER_MILLION=
LLM_PRICE_CARD_RETRIEVED_AT=
LLM_PRICE_CARD_SOURCE_CONTENT_SHA256=
```

```bash
MAYA_BASE_URL=http://127.0.0.1:18080 \
MAYA_STUDENT_PASSWORD='...' \
MAYA_TEACHER_PASSWORD='...' \
uv run --project backend python manual-tests/real-core-demo/scripts/acceptance.py \
  execute --checkpoint /private/path/real-core-demo.json \
  --embedding-policy-hash <embedding-policy-sha256> \
  --llm-policy-hash <debate-llm-policy-sha256> \
  --report-policy-hash <report-policy-sha256>
```

Before the first real request, the teacher creates
`POST /api/v1/demo/acceptance-runs` with the fresh target/version and fixture
hash, then verifies `starting_charged_requests=0`, `call_count=0` and
`charged_request_count=0`. After the Debate is created, it is bound with
`POST /{run_id}/debate` before playback starts.

For each Snapshot, query and debate-LLM manifest, the driver reads its
`manifest_hash`, attaches the next ordinal with
`POST /{run_id}/calls` using `{ "manifest_hash": "...", "call_no": N }`,
checks the run summary, confirms the exact disclosure, and invokes the explicit
preparation continuation. The server resolves the unique prepared operation by
manifest hash. Duplicate hashes and non-sequential ordinals stop the run.

After Debate `finish`, the driver opens and closes the interaction with zero
submissions, then waits for Mock insight and the paused Real Report revision. It
finds the unique `report_revision_id` + `manifest_hash` from
`GET /api/v1/provider/data-call/pending/reports/{debate_id}`, confirms the Report
disclosure, binds the revision with `POST /{run_id}/report`, attaches call 8, and
continues via
`POST /api/v1/debates/{debate_id}/report/revisions/{revision_id}/continue` with
the same hash and `call_no=8`. Any HTTP error, `acceptance_unknown` or Provider
failure stops immediately; no Provider request is retried.

The driver reads transcript, debate and Report revision history projections
before and after Report continuation and verifies the acceptance run's
`call_count` remains 7 before the Report call and is exactly 8 afterward. These
read-only projections do not inspect or bypass the raw ledger.

## Verify

Verification performs the final offline SQL evidence check only after the product
API flow has completed. It validates immutable Snapshot identity, participant
bindings, independent B-slot queries, four final-ready English-safe turns,
Evidence Trace lineage, the Report's 600–900 English words with no winner/nickname
terms or CJK, Report policy binding, and eight charged calls.

```bash
uv run --project backend python manual-tests/real-core-demo/scripts/acceptance.py \
  verify --checkpoint /private/path/real-core-demo.json \
  --database-url "$MAYA_DATABASE_URL" \
  --embedding-policy-hash <embedding-policy-sha256> \
  --llm-policy-hash <debate-llm-policy-sha256> \
  --report-policy-hash <report-policy-sha256>
```

Do not run this packet against the shared port, a non-empty runtime root, an
unreviewed Provider policy, or GitHub CI.
