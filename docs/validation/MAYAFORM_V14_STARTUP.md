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
6. Execute the authorized real acceptance workflow with dedicated synthetic
   data: create four Agents through Studyform and one synthetic Brainform RAG.
   In Teacher Maya Agent Chat actually call `generate_agent_knowledge`; record
   the accepted Tool receipt, canonical Set/job and final successful saved version.
   Bind the other three Agents to that same canonical object, configure the
   legitimate Leader/evaluator/summarizer recipe, and save an own-course Public
   Team through Studyform. Confirm its exact published-version data-use scope.
   Several separately authenticated synthetic students must select it from
   Chats → New → Maya Team and submit real Public/Private answers. Verify actual
   DB attempt/answer/evaluation/Boundary relationships, then ask Teacher Maya
   Agent Chat for statistics and a downloadable report targeted only to that
   synthetic activity. Private contributes neither content nor count; never
   query unrelated real students or Private histories as test data.

   Record request hashes, receipts, job/attempt/report identities, actual billing
   and result state without credentials or private response bodies. HTTP 200,
   model prose or enqueue success alone is not completion. Unknown acceptance
   is never resent automatically. Teacher Knowledge generation needs no separate
   Provider confirmation screen, but current source/target ACL and reviewed
   policy still apply. Team and Chat purposes retain their actual authorization.

   Check canonical reference equality, usable generated content, bound RAG
   auto-update and explicit ↻. Successful latest generation may replace manual
   current while preserving history; failed/partial/old results cannot clear or
   replace usable current. Relevant active/paused rounds receive the ordinary
   reanswer message; stale answers/results do not enter the new selection and
   completed history stays unchanged. RAG New supports the existing Markdown,
   PDF and DOCX import, with common editor/view/download/delete operations.

   Test natural-language start, pause, continue and query in the ordinary General
   Chat; no assessment card, panel, dedicated composer or lifecycle button group.
   Private participation completes normally but stays excluded from Teacher
   statistics/report/download. The latest abandoned-record disposition is a
   separately deferred Tool/prompt change; do not claim current retention meets
   it or delete billing/history while testing. Missing permission affects only
   that operation and leaves lawful subsequent messages available.

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
