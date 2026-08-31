# Real-Core Demo

This isolated packet currently covers the full-Mock preparation boundary:

`Bowen baseline A + one student target B -> zero Provider calls`.

TTS, Voice, Translation and Report remain Mock. The packet contains only
fictional, identity-free text. It never prints a credential, raw Provider
response, endpoint, model/resource identifier or student data.

Run the offline fixture checks first:

```bash
uv run --project backend python manual-tests/real-core-demo/scripts/acceptance.py check
uv run --project backend pytest -q manual-tests/real-core-demo/scripts/test_acceptance.py
```

The application startup creates and verifies the immutable Bowen Demo baseline.
Prepare only the student target Agent B while the application is in its all-Mock
composition; the driver reads `/api/v1/demo/baseline`, verifies its usable
stable IDs and uses that published version as participant A. It does not create
or mutate a second control Agent. The command stores a mode-0600 checkpoint and
leaves the target version unpublished:

```bash
MAYA_BASE_URL=http://127.0.0.1:18080 \
MAYA_STUDENT_PASSWORD='...' \
uv run --project backend python manual-tests/real-core-demo/scripts/acceptance.py \
  prepare --checkpoint /private/path/real-core-demo.json
```

`prepare` is fail-closed unless `/api/v1/demo/status` reports the same usable
baseline, zero dirty Agents/Debates/interactions, and an all-Mock composition.
It writes a new `real-core-demo-checkpoint-v3` with one opaque
`acceptance_run_id`; an existing checkpoint path is rejected so a run cannot be
silently reused.

On a fresh database, import the two separately reviewed, endpoint-bound policy
files in this order, one command at a time, before enabling either real
selector. Keep both JSON files outside the repository; they contain only
non-secret controls, review timestamps and hashes:

```bash
uv run --project backend python scripts/import_provider_policy.py \
  --policy-file /private/path/provider-policy-embedding.json \
  --database-url "$MAYA_DATABASE_URL" --acknowledge-reviewed
uv run --project backend python scripts/import_llm_policy.py \
  --policy-file /private/path/provider-policy-llm.json \
  --database-url "$MAYA_DATABASE_URL" --acknowledge-reviewed
```

The first command persists the fixed Embedding policy and the second persists
the fixed LLM policy in the same fresh DB. Re-running either exact file is
idempotent (`already_present`); a missing, unreviewed, hash-mismatched,
secret-shaped, wrong-model or wrong-endpoint file stops before DB access. Do
not run two service processes against separate policy DBs or import the files
concurrently.

Before restarting the isolated Compose application, put the dual-Real values
in the ignored root `.env`. These names are passed to the backend service by
`docker-compose.yml`; keep the legacy `PROVIDER_POLICY_HASH` empty for this
dual-Real path because the two endpoint-bound hashes must remain separate:

```dotenv
LLM_PROVIDER=dashscope
EMBEDDING_PROVIDER=dashscope
TTS_PROVIDER=mock
VOICE_PROVIDER=mock
TRANSLATION_PROVIDER=mock
EMBEDDING_PROVIDER_POLICY_HASH=<embedding-policy-sha256>
LLM_PROVIDER_POLICY_HASH=<llm-policy-sha256>
PROVIDER_POLICY_HASH=
LLM_PRICE_CARD_VERSION=<reviewed-price-card-version>
LLM_INPUT_PRICE_CNY_PER_MILLION=<reviewed-input-rate>
LLM_CACHED_INPUT_PRICE_CNY_PER_MILLION=<reviewed-cached-input-rate>
LLM_OUTPUT_PRICE_CNY_PER_MILLION=<reviewed-output-rate>
LLM_PRICE_CARD_RETRIEVED_AT=<rfc3339-timestamp-with-timezone>
LLM_PRICE_CARD_SOURCE_CONTENT_SHA256=<reviewed-source-sha256>
```

The six price-card values are reviewed accounting metadata, not current prices
embedded in the application; supply them from the approved price-card source.
The timestamp must include a timezone, and the configured worst-case request
must remain within the fixed CNY 0.15 single-request cap.

The prior seven-request `execute`/`verify` path is intentionally disabled:
the replacement Real plan (including Call 2 and Report) is not frozen, so these
commands return `real_plan_not_frozen` and make no Provider request. Do not
reuse this checkpoint for a later Real run; a new plan-specific driver will
define its own call budget and evidence contract.
