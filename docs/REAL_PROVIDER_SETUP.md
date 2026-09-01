# Turning on the real providers

All six selectors ship as `mock`, and the Demo runs end to end that way. Three
of them can run against DashScope: `LLM_PROVIDER`, `MAYA_REPORT_PROVIDER` and
`EMBEDDING_PROVIDER`. `TTS_PROVIDER` and `VOICE_PROVIDER` stay `mock` for the
Demo. `TRANSLATION_PROVIDER` needs a DeepL key.

## A reviewed policy snapshot is required first

Setting a selector to `dashscope` is not enough. Before any real call, the
runtime requires a `ProviderPolicySnapshotV1` row whose `policy_hash` equals
the configured `*_PROVIDER_POLICY_HASH`. Without it every turn fails closed
with `provider_preflight_blocked` and the server log records:

```
Turn preparation failed ... error_type=PlatformError safe_code=provider_preflight_blocked
```

That row is **operator data, not repository data**. It records which supplier
documents were read and when — the privacy notice, service terms and FAQ URLs,
their retrieval timestamps, and the SHA-256 of each document as retrieved. It
is deliberately not committed: it names a workspace resource, and its content
is an attestation that a person reviewed those documents. It also lives only in
the runtime database, so **deleting `data/` deletes it** and it has to be
imported again.

Keep your reviewed policy JSON outside the repository and back it up.

## Importing

Two separate entry points, one per real slice:

```bash
python scripts/import_llm_policy.py --policy-file <your-llm-policy>.json --database-url "sqlite:///$(pwd)/data/maya.sqlite3" --acknowledge-reviewed
```

```bash
python scripts/import_provider_policy.py --policy-file <your-embedding-policy>.json --database-url "sqlite:///$(pwd)/data/maya.sqlite3" --acknowledge-reviewed
```

`--acknowledge-reviewed` is a human attestation. Nobody may pass it on your
behalf. Neither importer reads a credential, selects a provider, or sends a
network request; each only persists the control row.

The importer recomputes `policy_hash` from the policy fields and refuses the
document if it does not match the supplied hash, so a drifted or hand-edited
policy fails before it reaches the database.

## Then

1. Set the three selectors to `dashscope` in `.env`.
2. `docker compose up -d` and confirm the composition strip reports `REAL` for
   Embedding, Debate LLM and Maya Report.
3. Run one debate. The provider disclosure the teacher confirms is reached
   through `/provider/data-call/pending`, keyed by the manifest the turn
   creates.

Seeded Agents keep Mock embedding identity by design. A real Snapshot embedding
belongs to an Agent a student publishes, never to a seeded one.
