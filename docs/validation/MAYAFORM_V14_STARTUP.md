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
   does not. Preserve `.env`, private configuration, mounted data, voices,
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
   repeat an `acceptance_unknown` request. In Teacher Knowledge Sets, use
   **Create AI Knowledge**, select the synthetic Source in the Agent workbench
   and press Done once. Check that the same Set appears in global and Agent
   Knowledge, the owner-only Job reports accepted/materialized/failed item
   counts, and each saved Concept/Question/Note becomes readable immediately.
   Then use **Update AI Knowledge** from that Set, change Agent.md or its
   Source selection, and verify the same Set ID while preserving a manually
   edited current asset head. Compare actual saved assets and browser behavior
   with the account/Source ACL and the S01–S22 evidence map.

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
