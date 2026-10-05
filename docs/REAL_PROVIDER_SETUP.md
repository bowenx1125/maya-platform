# Turning on the real providers

The Demo ships in Mock mode. `LLM_PROVIDER`, `MAYA_REPORT_PROVIDER` and
`EMBEDDING_PROVIDER` can run against DashScope. `TTS_PROVIDER` and
`VOICE_PROVIDER` stay `mock` unless set to `dashscope`, and then they use the
same `DASHSCOPE_API_KEY` as those slices. There is no separate speech key.
Provider modes, credentials and connectivity checks are maintained by the
operator; the teacher Home has no Components controls.

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
is an attestation that a person reviewed those documents. Policies imported by
the reviewing helper are also saved under the ignored
`backend/config/provider-policies/` directory and restored on startup. A policy
imported only into the database must be backed up separately before resetting data.

Keep your reviewed policy JSON outside the repository and back it up.

## Writing the policy file

Start from a template and replace every `REPLACE_WITH_...` with what you
actually read:

- `docs/templates/llm-policy.template.json`
- `docs/templates/embedding-policy.template.json`

The `*_retrieved_at` fields are the UTC timestamps when you opened those pages,
and the `*_sha256` fields are the SHA-256 of the pages as you read them
(`curl -s <url> | shasum -a 256`). `no_training_basis` and `retention_setting`
record the clause and the setting you relied on.

The importer refuses a document whose `policy_hash` does not match its own
fields, so compute it once the values are final:

```bash
python scripts/compute_provider_policy_hash.py my-llm-policy.json --write
```

That helper reviews nothing — it only hashes what you wrote. Put the value it
prints into `.env` as `LLM_PROVIDER_POLICY_HASH` (and
`REPORT_PROVIDER_POLICY_HASH`, which uses the same LLM policy), or
`EMBEDDING_PROVIDER_POLICY_HASH` for the embedding policy.

## The reviewing importer

`scripts/import_provider_review.py` does the reading for you: it fetches each
published supplier document, records its SHA-256 and the UTC time it was read,
and stores the supplier's own statements as the recorded basis. Those are
evidence — the supplier editing a page changes the hash.

```sh
docker compose stop backend && uv run --directory backend python ../scripts/import_provider_review.py --accept-account-settings && docker compose up -d
```

It cannot inspect your supplier console, so the four account switches stay an
explicit assertion behind `--accept-account-settings`.

The reviewed documents are written to `backend/config/provider-policies/`
(git-ignored, mode 0600) and reinstalled on startup whenever their row is
missing, so resetting the runtime no longer removes the review.

## Importing a policy you wrote yourself

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

1. Set the three selectors to `dashscope` in `.env`. Optionally set
   `TTS_PROVIDER=dashscope` and `VOICE_PROVIDER=dashscope` as well; they use the
   same `DASHSCOPE_API_KEY` and there is no separate speech key. Leave them
   `mock` when speech is not needed.
2. Back up SQLite, preserve the effective environment and saved settings, then
   recreate only the affected Maya services. Verify readiness and effective
   provider configuration in the maintenance layer; these checks do not prove
   successful provider calls.
3. Publish a new Agent version with a real knowledge snapshot, then create a
   new Preview. Complete the teacher disclosure for that publication/debate;
   the UI opens the exact manifest requiring confirmation. Generate Report
   explicitly after the final classroom round and Conclude.

Seeded Agents keep Mock embedding identity by design. A real Snapshot embedding
belongs to an Agent a student publishes, never to a seeded one.

## Rotating `DASHSCOPE_API_KEY`

LLM, Embedding, Report, TTS and voice clone share one server-side key. A cloned
voice belongs to the Alibaba Cloud workspace (`DASHSCOPE_WORKSPACE_ID` in
`cn-beijing`), not to the key. The voice row stores an encrypted supplier
voice id. The encryption key is derived from `SESSION_SECRET`. The API key is
not stored on the profile, not hashed into it, and is not returned by the API.

To rotate:

1. Put the new key in `DASHSCOPE_API_KEY`. Leave `DASHSCOPE_WORKSPACE_ID`,
   `DASHSCOPE_REGION` and `SESSION_SECRET` unchanged. Changing the secret makes
   existing voice envelopes undecryptable. Changing the workspace strands the
   cloned voices.
2. After backing up SQLite and checking for active requests, recreate the
   backend with the reviewed environment. The process reads the key at startup;
   a plain restart does not apply changed Compose environment values. There is
   no migration.
3. When `DASHSCOPE_API_KEY` is set, it wins over a key previously saved in the
   former teacher Components dialog. Existing encrypted settings are preserved
   and used only while the environment variable is empty. The maintenance API
   never returns the credential. Logs must not contain the key.

## Baseline character voices

Socrates, Plato and Laozi are immutable (`demo_baseline_immutable` on any
edit). Give a character a voice without writing its row:

```dotenv
BASELINE_DEFAULT_VOICES=socrates=<voice-profile-uuid>,laozi=<voice-profile-uuid>
FALLBACK_VOICE_PROFILE_ID=<system-fallback-uuid>
```

Each value is a ready voice profile id. A group profile must belong to the
character's group. A system profile is accepted when it has no group. Omit a
name, or point it at a profile that is missing, not ready, or in another
group, and that character uses `FALLBACK_VOICE_PROFILE_ID`. That fallback has
to be a ready system profile. Plato is omitted above so it speaks with that
system voice. The ids stay in the environment; they are not compiled into the
application. The baseline integrity check still compares the frozen Agent text
and does not read this map.

## Maintenance configuration

For a published Maya Team, open the teacher Home personal Agents disclosure link
and confirm that Team version's Chat reply and Knowledge retrieval resource
bindings. Publishing alone does not create these grants; a course-wide disclosure
does not substitute for a current Team grant. Changing the bound Team version or
its authorization invalidates obsolete grants. Missing authorization stops before
dispatch, with no paid request.
After confirmation, send a new message explicitly; the old failed turn is not
restarted or silently retried. Confirmation does not expose student messages.
Chats remains text-only; TTS configuration applies to other voice features.

Components, API Key editing, Real/Mock switches, Check and readiness labels are
absent from the user interface. Operators manage these through the existing
maintenance configuration and APIs; no replacement settings panel is added.
Existing saved preferences still override their environment selectors and survive
restarts. Removing the UI neither changes them nor sends provider requests.

Active classroom/generation/chat work still blocks configuration changes. The
server encrypts saved credentials and never returns them; reviewed policies,
region, model selection, resource permissions and exact disclosure requirements
remain in force. Connectivity checks retain explicit authorization, idempotency
and accounting. A successful connectivity check does not establish content or
report quality.
