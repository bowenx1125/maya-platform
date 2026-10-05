# MayaForm v1.4 local startup and acceptance

This is the release procedure for the existing MayaForm checkout and its current
Docker data. It is not evidence that v1.4 has been deployed. Record actual
results in `docs/PROJECT.md` after each run.

1. Run the repository's deterministic checks (`pnpm check` and the generated
   source boundary probe) on the exact revision being deployed. Freeze the
   product file hashes and review the migration against a populated backup.
   Keep the 0033–latest upgrade chain and foreign-key/integrity checks; a
   successful fresh database is not proof that existing data survive.
2. Read the current Maya Compose project and its actual backend/frontend
   override files from the containers' Compose labels. Preserve those overrides
   when building; they may carry image tags or DNS settings that the base file
   does not. If temporary override files are gone, reconstruct the effective
   settings from the running containers into a protected private override and
   compare them before recreation; do not guess or log credential values.
   Preserve `.env`, private configuration, mounted data, voices,
   snapshots and Provider settings. Record the IDs of unrelated containers so
   the release can prove that it did not recreate them.
3. Before touching the running backend, inspect in-flight Provider operations,
   Chat turns and Jobs. A `sending`/unknown billable request is not a reason to
   resend it; first preserve its ledger and choose a safe drain point. Back up
   the active SQLite database **inside the backend container** with Python's
   `sqlite3.Connection.backup()` into its protected mounted backups directory.
   Never copy the live `.sqlite3` file alone while WAL is active.
4. Rebuild/recreate only the Maya services with the base Compose file and the
   recorded override files, using `up -d --build --wait`. Do not reset or
   replace the data directory. `docker compose down` is necessary across a
   deliberate runtime reset, not this normal version update.
5. Verify the backend container's `/health/ready`, the active Alembic head,
   SQLite foreign-key/integrity checks, the gateway at
   `http://localhost:8080/`, and the Teacher/Student routes. Compare the
   unrelated container IDs with step 2. A healthy container is a deployment
   check, not proof of AI behavior or teaching quality.
6. For one real Provider smoke, use a new, minimal synthetic Agent.md and
   synthetic courseware in the authorized scope. Confirm the exact current
   Provider policy, outbound field classes, manifest hash, model/region and
   Teacher disclosure before sending. Record the run ID, request hash,
   charged-request count and result status without logging credentials,
   endpoint, raw response, Source text or private paths. Do not automatically
   repeat an `acceptance_unknown` request. In Teacher Workspace's Agents section, use
   **Create AI Knowledge**, select the synthetic Source in the existing Agent
   workbench and press Done once. Ordinary New Agent Done remains unchanged.
   Brainform's sidebar New creates only Markdown RAG. Check that global and Agent
   Brainform open the same canonical Knowledge ID, successful content is immediately
   usable, and the owner-only generation Job matches the saved content. Edit bound
   RAG to verify automatic updating; also use the Knowledge row's ↻. Successful
   regeneration replaces the manually edited current Markdown while preserving its
   immutable history. Failures retain the last usable document. Compare actual
   saved versions and browser behavior with current account/Source ACL and BF/AT/RS.
   Verify
   Private and Public assessment attempts through the existing General Chat:
   send natural-language start, pause, continue, query submitted records, abandon
   and explicit abandon-and-redo messages. There is no assessment card, progress
   panel, dedicated composer or lifecycle button group. Check that querying or
   abandoning a paused attempt does not first resume grading. Verify
   automatic completion after final Assessment/Boundary saves, Teacher Kaikai
   report/download and Chat withdrawal. Provider authorization reuses
   valid existing grants; missing scope has a recoverable path and is not treated
   as authorization to send another charged request.

Teacher Chat approvals must be checked separately for LLM and query Embedding.
Confirm each exact purpose/policy disclosure once in its valid course scope;
never substitute an LLM confirmation for Embedding or confirm a student's
Private per-query manifest as a Teacher. Exercise at least one successful
authorized send and one revoked-before-send denial. A synthetic transport test
proves this boundary; label it separately from the real Provider observation.

The full PDF/Word and voice test suite requires the pinned Linux dependencies,
including FFmpeg. On macOS, preserve the conversion process memory guard instead
of weakening it to obtain a green test. Run the complete backend suite from a
frozen source copy in an isolated Linux container, with no production data or
network and sufficient private temporary disk space. Run the frontend, contract,
format/type, migration-script and generated-boundary gates against the same
source revision. Save the test count and source fingerprint; environment failures
and product regressions are different results.

For a local Compose invocation, use variables pointing to the **already
reviewed** override files; do not substitute guessed paths or print the
expanded configuration if it contains secrets:

```bash
docker compose -f docker-compose.yml \
  -f "$MAYA_BACKEND_OVERRIDE" -f "$MAYA_FRONTEND_OVERRIDE" \
  up -d --build --wait backend frontend
```

Any failed migration or unhealthy backend means stop the rollout and preserve
the backup/ledger. Do not reset, replay a charged request or describe a Mock
result as a real Provider acceptance.
