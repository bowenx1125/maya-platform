# Real-Core Demo

This isolated packet exercises one fixed product path:

`Mock setup -> one real 1024 Snapshot -> two real query batches for slot A -> four one-shot real LLM turns -> complete two-round Debate`.

TTS, Voice, Translation and Report remain Mock. The packet contains only
fictional, identity-free text. It never prints a credential, raw Provider
response, endpoint, model/resource identifier or student data.

Run the offline fixture checks first:

```bash
uv run --project backend python manual-tests/real-core-demo/scripts/acceptance.py check
uv run --project backend pytest -q manual-tests/real-core-demo/scripts/test_acceptance.py
```

Prepare the fixed Agents while the application is in its all-Mock startup
composition. The command stores a mode-0600 checkpoint and leaves the target
version unpublished:

```bash
MAYA_BASE_URL=http://127.0.0.1:18080 \
MAYA_STUDENT_PASSWORD='...' \
uv run --project backend python manual-tests/real-core-demo/scripts/acceptance.py \
  prepare --checkpoint /private/path/real-core-demo.json
```

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
```

Then restart the isolated application with `docker compose up -d --build` and
execute once. The explicit flag is an operator confirmation of the
seven-request cap; the teacher confirmations for every exact manifest still
occur through the product API:

```bash
MAYA_BASE_URL=http://127.0.0.1:18080 \
MAYA_STUDENT_PASSWORD='...' MAYA_TEACHER_PASSWORD='...' \
uv run --project backend python manual-tests/real-core-demo/scripts/acceptance.py \
  execute --checkpoint /private/path/real-core-demo.json \
  --embedding-policy-hash <sha256> --llm-policy-hash <sha256> \
  --confirm-seven-call-cap
```

Finally verify the immutable Snapshot, the two query ledger rows, four LLM
rows, one-shot manifest settings, full Evidence traces and the four-turn
finished Debate through the local SQLite API-owned runtime:

```bash
uv run --project backend python manual-tests/real-core-demo/scripts/acceptance.py \
  verify --checkpoint /private/path/real-core-demo.json \
  --database-url sqlite:////private/path/maya.sqlite3
```

The driver has no automatic retry. A failed or `executing` checkpoint must be
investigated through the authoritative local ledger and a fresh identity-free
runtime; it is never reused to spend another real request.
