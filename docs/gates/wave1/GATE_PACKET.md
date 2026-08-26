# Wave 1A Gate Packet

Status: `G0-S PASS — AUTHORIZED FOR G1`
Authorized: `2026-08-26 Asia/Shanghai`
G0-S audit: `/root/wave0_foundation_audit`, `gpt-5.6-sol high`, final verdict `PASS` on `2026-08-27 00:02 Asia/Shanghai` after two bounded correction rounds
Modules: `M05 Agent/version + M06 Markdown RAG + M09 teacher published inspection`
Dependencies: `Wave 0 G3 PASS`, frozen `g0-2026-08-26.4` product/OpenAPI contract
Non-goals: M02 full i18n shell, M07 rendered 3D assets, M08 real voice/TTS, M10-M15 debate/interaction/Maya report, real Bailian/DeepL calls

## 1. Goal and vertical acceptance slice

Deliver one honest, provider-neutral, Mock-only but technically real RAG workflow:

1. a student in one seeded group creates an Agent and its only V1.0 draft;
2. the student edits or uploads free-form `AGENT.md` with optimistic revision control;
3. the student uploads UTF-8 `.md` files, which become immutable group documents and are explicitly enabled only on the selected draft;
4. the backend performs deterministic Markdown chunking, creates float32 embeddings, persists a local vector index and exposes a combined draft `RAG.md` preview;
5. draft test chat performs scoped vector retrieval and returns a visible `matched` or legitimate `no_match` receipt without fabricating sources;
6. publish creates immutable V1.0 + KnowledgeSnapshot S1, frozen source copies, frozen chunks/vectors and one current-version pointer switch;
7. the teacher can list and inspect only published versions/snapshots in their course, including historical published versions and Markdown downloads, but never a draft or unbound workspace document.

Wave 1A must not claim that Mock answer prose proves real LLM quality or that placeholder Markdown proves the final TikTok teaching outcome. Those are later real-service/content gates.

## 2. Frozen public operations

The product OpenAPI copy remains byte-for-byte equal to the frozen parent contract. Wave 1A implements exactly these 24 existing operation IDs and removes only these IDs from the later-wave placeholder allow-list.

### M05 Agent/version

- `listGroupAgents`
- `createAgent`
- `getAgent`
- `archiveAgent`
- `unarchiveAgent`
- `listAgentVersions`
- `createNextAgentVersion`
- `getAgentVersion`
- `updateAgentDraft`
- `uploadAgentMd`
- `publishAgentVersion`

### M06 Markdown RAG/snapshot

- `listKnowledgeDocuments`
- `uploadKnowledgeDocument`
- `getKnowledgeDocument`
- `downloadKnowledgeDocument`
- `reindexKnowledgeDocument`
- `hideKnowledgeDocument`
- `setAgentVersionDocuments`
- `getRagPreview`
- `testAgentDraft`
- `getKnowledgeSnapshot`
- `downloadSnapshotRag`
- `downloadSnapshotDocument`

### M09 teacher read-only projection

- `listPublishedAgentsForTeacher`
- the teacher branch of `getAgent`, `listAgentVersions`, `getAgentVersion` and the three snapshot read/download operations above.

No additional public API operation may be invented. Browser DTOs must not contain provider names, model IDs, API keys, external voice IDs, absolute paths, embedding dimensions/vectors/scores or unpublished generated text.

## 3. Database contract

Migration head becomes `0002_wave1_agents_rag`, upgrades cleanly from the checked-in Wave 0 head and is idempotent at the deployment-command level.

### 3.1 Domain tables

- `agents`: `id`, `group_id`, `name`, `description`, `status`, `current_published_version_id`, timestamps. `status` is `active|archived`. The current pointer is nullable and is validated by the service to reference the same Agent in `published` state.
- `agent_versions`: `id`, `agent_id`, `version_seq`, `state`, `revision`, `agent_md`, `avatar_config_json`, nullable future `voice_profile_id`, nullable `knowledge_snapshot_id`, timestamps and `published_at`. Unique `(agent_id, version_seq)`; `version_seq >= 0`; `revision >= 0`; one partial unique `draft` row per Agent. Published/superseded business fields are immutable.
- `knowledge_documents`: `id`, `group_id`, `source_filename`, `stored_file_id`, `char_count`, `index_status`, `index_revision`, `workspace_state`, `content_hash`, nullable `safe_error_code`, timestamps. Content is immutable; identical names/content are allowed; state is `active|hidden`; index state is `pending|indexing|ready|failed`; every atomic successful chunk replacement increments `index_revision`.
- `knowledge_document_chunks`: draft/library index rows keyed by immutable document, with `chunk_index`, text, normalized-text offsets, float32 embedding BLOB, dimension and internal embedding key. Unique `(document_id, chunk_index)`.
- `agent_version_documents`: selected document relation with `enabled` and `order_index`. Unique `(agent_version_id, document_id)` and unique enabled order per version. Both objects must belong to the same group; only a draft relation may change.
- `knowledge_snapshots`: unique `agent_version_id`, combined stored file, hash, total chars, internal embedding key, chunking JSON and timestamp.
- `snapshot_documents`: stable public `id`, snapshot/document/frozen-file IDs, frozen filename/char count and order. Unique `(snapshot_id, document_id)` and `(snapshot_id, order_index)`.
- `knowledge_chunks`: immutable snapshot-scoped copies of selected document chunks, including snapshot/document relation, offsets, float32 embedding BLOB and dimension. Search is always filtered by one authorized snapshot ID.

### 3.2 Operational tables

- `stored_files`: typed relative path, SHA-256, size and `staged|active|trash|deleted` state. Absolute paths never enter the database or API.
- `file_references`: file-to-owner reference/purpose. A referenced file cannot be physically removed.
- `file_operations`: durable journal for document promotion, snapshot promotion and recovery with only relative source/target paths and safe error codes.
- `jobs`: persistent Wave 1 indexing attempts with `pending|running|completed|failed|interrupted` and a safe error code. Indexing executes synchronously in the single-process Demo request, but still crosses the same Job/Port boundary as a future task runner.
- `idempotency_records`: `id`, actor, operation, key, canonical request hash, `pending|completed|abandoned` state, random claim token, lease expiry, safe status code/serialized result and timestamps. Unique `(actor_user_id, operation, key)`.

Operational foreign keys are mandatory: stored-file references point to `stored_files`; journal rows reference the owning idempotency record when present; document/snapshot stored-file IDs are restrictive; chunks cascade only with their owning document/snapshot; no cascade can remove a published snapshot through a workspace document.

Wave 1A does not create Voice, Debate, Interaction or Report tables.

## 4. Agent/version invariants

1. `Agent` is stable identity; V1.0 is `version_seq=0`, V1.1 is `1`, and so on.
2. Creating an Agent is an explicit student command that atomically creates the Agent and its V1.0 draft. Uploading a document never creates an Agent/version.
3. A draft starts at `revision=0`. Every successful draft business mutation increments revision exactly once. Reads and test chat do not increment it.
4. Every draft save/relation mutation carrying `expected_revision` uses an atomic compare-and-update. A stale request returns `409 stale_revision` and the authoritative current revision; it never overwrites.
5. A published or superseded version cannot be patched, have documents changed or receive an `AGENT.md` upload; return `409 version_immutable`.
6. Creating the next version is allowed only for an active Agent with a current published version and no draft. It clones `AGENT.md`, avatar JSON, future voice reference and the enabled document set into the new draft; it never clones the old snapshot ID as the draft's snapshot.
7. Publishing freezes the draft. The previous current published version becomes `superseded`; old data is retained. The new version becomes the only current `published` version.
8. Archive hides an Agent from the default student list and future teacher candidate list. Archive/unarchive retains all versions and snapshots. Archived Agents cannot create a version or publish.
9. Wave 1A accepts and freezes the OpenAPI `AvatarConfig` JSON even though M07 rendering is not implemented. Empty/sentinel template data yields `avatar_missing`; a non-empty configuration using the reserved Demo template key `wave1-default-head` is accepted for this vertical slice. M07 later replaces the catalog/rendering without changing AgentVersion storage or DTOs.
10. Voice is not a publish blocker. Until M08 exists, `voice_profile_id` must remain null, `effective_voice_profile_id` is null, and `voice_fallback_active=true`; this is an explicit unconfigured fallback state, not a claim that real audio is ready.

## 5. Markdown and draft-index contract

### 5.1 Input and counting

- Accept only a filename whose final extension is `.md` case-insensitively, with no path component/control character.
- Decode strictly as UTF-8, strip one leading BOM if present, normalize CRLF/CR to LF and reject content empty after surrounding-whitespace trim.
- `char_count` is Python Unicode code-point count of that normalized Markdown before any platform source marker. No single-file product byte limit is added.
- Do not detect duplicates and do not overwrite by name/hash.
- An upload must target an authorized draft in the same group and defaults to enabled only on that draft.
- Although the frozen multipart schema leaves `expected_revision` optional for wire compatibility, Wave 1A business logic still requires compare-and-swap. Omission returns the already-frozen `409 stale_revision` with safe `current_revision`; it may not opt out of conflict protection or misuse the 422 business-validation meaning.
- Before any persistent file/DB side effect, calculate current enabled total plus the new document. If it exceeds 100,000 characters, reject the whole operation with `rag_over_limit`; the draft, file system and index remain unchanged.
- Replacing the enabled document set validates in one transaction: no duplicate IDs, every document is active and in the same group, request order becomes the exact `order_index`, aggregate normalized character count is <=100,000, and the draft revision still equals `expected_revision`. Any ownership/limit/revision failure leaves relations and revision byte-for-byte unchanged.

### 5.2 Chunking and embeddings

- Chunk normalized Markdown deterministically. A token is one Python regex `\S+` match with its exact character span. Record end-exclusive token indices for every maximal nonblank paragraph end and every Markdown heading line end. For a chunk starting at token index `start`, set `desired=min(start+600,total)` and `hard=min(start+800,total)`: if `hard==total`, choose `end=total`; otherwise choose the smallest recorded boundary in `[desired,hard]`; if none exists, choose the largest boundary in `(start,desired)`; if none exists, choose `end=hard`. Emit exactly the normalized Markdown slice from the first selected token's character start through token `end-1`'s character end. If more tokens remain, the next `start=max(end-100,start+1)`. Thus each chunk—including overlap—is <=800 tokens, long paragraphs advance by at least 700 tokens, and every input yields one unique boundary sequence. Offsets must reproduce chunk text without rejoining whitespace.
- Save exact normalized-text `start_offset/end_offset`, document ID, source filename and deterministic chunk order. Offsets must slice back to the stored chunk text after the documented join normalization.
- `EmbeddingProvider` is an internal Port. Wave 1 CI/runtime uses this byte-frozen local Mock implementation and makes no network call: Unicode NFKC then lower-case; extract tokens with `[a-z0-9]+(?:'[a-z0-9]+)?`; SHA-256 each UTF-8 token; index is the first four digest bytes interpreted unsigned big-endian modulo 256; sign is `+1` when digest byte 4 is even and `-1` otherwise; add signed token counts; L2-normalize in Python double precision; serialize exactly 256 values with `struct.pack('<256f')`. A tokenless input is 256 positive float32 zeros.
- `VectorStore` is an internal Port. It loads only rows for one authorized draft document set or one authorized snapshot, rejects mixed dimension/key/BLOB length, unpacks little-endian float32 and performs a dot product because stored/query vectors are normalized. Zero-vector similarity is exactly 0. Rank by score descending, then enabled/snapshot document `order_index`, then `chunk_index`, then lexical chunk UUID. No score/vector/dimension is public. The standard-library implementation is frozen for Wave 1; NumPy is not added in this wave.
- `top_k=6`. Mock match thresholds are test-only deterministic settings (`strict=0.20`, one relaxed retry at `0.08`) and are not the future Bailian `min_score`. The real threshold remains blocked on the user's final TikTok Markdown and a real embedding spike.
- A technical embedding/index failure retries once in the same request, then marks only that document/job `failed`; other documents stay valid. Reindex replaces that document's chunk set atomically.

### 5.3 Draft preview and test chat

- Combined `RAG.md` is ordered by the draft relation and inserts `<!-- source: <safe filename>; document_id: <uuid> -->` before each document. Markers do not count toward the 100,000 limit.
- Draft preview is derived from current enabled documents and may be regenerated/cached under `data/groups/{group_id}/drafts/{version_id}/rag-preview.md`; it is not a KnowledgeSnapshot and is never teacher-visible.
- If any enabled document is pending/indexing, preview state is `pending`; if any is failed, it is `failed`; otherwise `ready`.
- Test chat is non-persistent. It requires a visible authorized draft, non-empty `AGENT.md`, at least one enabled ready document and total <=100,000. It uses the draft document index, not a published snapshot.
- `matched`: at least one result meets threshold, `grounding_mode=rag_grounded`, and every returned source names a real enabled file/chunk. The exact Mock answer is a clearly labelled excerpt-only construction from retrieved chunk text: `Mock grounded excerpt from <source_filename>: <first 320 characters of the highest-ranked chunk>`; it may not add a fact absent from that excerpt.
- `no_match`: both attempts miss, `grounding_mode=general_reasoning`, `sources=[]`, and the exact answer is `No relevant passage was found in this draft knowledge base. This Mock test cannot provide a factual answer without evidence.`
- Golden tests freeze normalized text, chunk boundaries/offsets, packed-vector SHA-256, zero-vector bytes, scores, tie-break order and both exact answer forms across fresh processes.

## 6. File lifecycle and permissions

All file access is rooted below configured `DATA_ROOT`; database rows store relative paths only. Resolve-and-containment checks are mandatory before every read/download/promote/delete.

Canonical layout:

```text
data/
  maya.sqlite3
  groups/{group_id}/knowledge/{document_id}/source.md
  groups/{group_id}/drafts/{agent_version_id}/rag-preview.md
  snapshots/{snapshot_id}/rag.md
  snapshots/{snapshot_id}/documents/{snapshot_document_id}.md
  tmp/publish/{request_id}/
```

- Startup enforces mode `0700` on `DATA_ROOT` and private subdirectories, and `0600` on SQLite/source/snapshot/preview files it owns. This is reproducible application behavior, not only a one-time shell `chmod`.
- Upload and snapshot files are written to a same-filesystem temporary path, flushed and `fsync`ed, then atomically promoted. Filename metadata never becomes a filesystem path component.
- `file_operations.state` is exactly `prepared|staged|promoted|committed|cleanup_required|recovered`. It records operation kind, entity/request IDs, relative staging/target paths, expected hash, safe error code and timestamps. State changes are short committed transactions so startup can distinguish each crash boundary.
- Upload protocol: atomically claim idempotency; validate scope/content/limit/revision; persist `prepared`; write/fsync staging and mark `staged`; compute the deterministic index in memory with one retry; atomically promote and mark `promoted`; then one DB transaction rechecks `state=draft AND revision=expected_revision`, enabled total and Agent/group ownership, creates stored file/document/chunks/job/relation/reference, increments revision once, marks operation/idempotency completed and stores the exact response. Stale/DB failure after promotion cleans the target and marks `recovered`; crash recovery does the same before a retry can take the lease. An indexing failure is a committed document/job with no chunks, `failed` status and an enabled relation so it visibly blocks publication.
- Reindex protocol: atomically claim idempotency; set the document/job to `indexing/running`; compute outside the final transaction; then replace that document's chunk set, increment an internal `index_revision`, and set `ready/completed` in one transaction. A crashed running attempt becomes `failed/interrupted` at startup and requires manual retry.
- Publish protocol: atomically claim idempotency; capture the Agent current pointer, draft revision, relation order and every document `index_revision/hash/chunks`; create and verify all snapshot artifacts in `tmp/publish`; persist journal states through `staged`; atomically move to the final UUID directory and mark `promoted`; then one DB transaction conditionally rechecks `agent active`, unchanged current pointer, `version state=draft AND revision=expected_revision`, identical enabled relation/order, and every captured document still `ready` with the same `index_revision/hash`. Only then create snapshot/files/references/chunks, supersede the prior version, publish the draft, switch the Agent pointer, and mark operation/idempotency completed.
- A failure before DB commit leaves the draft/current published pointer unchanged. A promoted but uncommitted directory is an invisible orphan; startup recovery uses `file_operations` to remove it. A committed snapshot is never modified or deleted by workspace hide.
- Distinct idempotency keys racing the same upload draft or publication cannot both commit: the conditional revision/current-pointer checks select one winner; the loser returns `409 stale_revision|invalid_state` and recovers its promoted orphan.
- `hideKnowledgeDocument` returns `409 invalid_state` while the document is enabled by any active draft. After deselection it changes only workspace visibility. Published snapshot copies/references remain readable.

### 6.1 Idempotency claim protocol

Every OpenAPI-keyed Wave 1A command—create, upload, reindex, hide, archive, unarchive, create-next-version and publish—uses the same protocol:

1. Canonical SHA-256 covers operation ID, actor ID, scoped path IDs and canonical normalized body; upload additionally includes safe filename and source SHA-256. Cookie, CSRF and absolute paths are excluded.
2. An immediate transaction inserts `pending + claim_token + lease_expiry`. Existing different hash always returns `409 idempotency_conflict`, regardless of state.
3. Existing same-hash `completed` returns the stored original status/body without rerunning. Existing same-hash unexpired `pending` waits/polls for at most 10 seconds in this single-process Demo and returns the completed result; if still in flight it returns `409 invalid_state` with only a retry hint.
4. An expired same-hash claim can be atomically taken over with a new token only after journal recovery. Every side-effect/final transaction verifies the current claim token, so an expired worker cannot later commit.
5. Business success and `idempotency=completed` are committed in the same final DB transaction. A crash before it leaves no business commit and becomes recoverable; a crash after it always replays the stored response.
6. Validation failures before side effects abandon/remove the claim safely. Once a journal exists, cleanup/recovery completes before abandonment or takeover.

## 7. Authorization contract

Every object read/write begins from the authenticated session and adds scope in the repository query; loading by unscoped ID and checking later is forbidden.

- Same-group students: full Wave 1A student operations on their group's drafts/library/history. Demo group roles are equivalent for content work.
- Other-group or outside-course students: all target Agent/document/version/snapshot list/detail/download/mutation requests return uniform `404 not_found`.
- Course teacher: list/read all published and superseded Agent versions and immutable snapshot downloads in that course. Drafts, draft relations, draft preview and unbound workspace Markdown return `404 not_found`. Teachers cannot mutate student Agent/RAG and receive `403 forbidden` only when the visible object/action distinction is contractually safe; otherwise 404.
- Teacher candidate list contains only non-archived Agents' current published version. Historical published/superseded versions remain visible from the Agent detail/history route.
- Anonymous users: no Wave 1A access.
- All authenticated mutations require same-origin plus CSRF. OpenAPI-required idempotency keys are authoritative.

## 8. Publication blockers and atomic outcome

`publish_blockers[]` is computed by the backend on every AgentVersion projection. Publishing is allowed only when it is empty:

- `agent_md_missing`
- `agent_md_too_large`
- `rag_missing`
- `rag_over_limit`
- `rag_index_pending`
- `rag_index_failed`
- `avatar_missing`

The exact successful publish outcome is:

1. one immutable KnowledgeSnapshot and frozen file set exists;
2. all snapshot chunks reference only enabled ready documents and preserve their order/source names;
3. the draft becomes `published`, prior current becomes `superseded`, and `current_published_version_id` points to the new version in one transaction;
4. the response can be replayed by the same idempotency key without creating another snapshot or changing revision;
5. the teacher projection becomes visible only after this commit.

## 9. UI slice and V2 visual boundary

Wave 1A adds functional English-first screens while preserving the frozen V2 visual language and current provider-neutral API wrapper:

- student home/group Agent and knowledge lists;
- create Agent;
- Agent/version workspace with AGENT.md editor/upload, enabled Markdown controls, revision conflict recovery, RAG preview, test chat and publish blockers;
- teacher published-Agent list and read-only current/history/snapshot detail/download;
- visible teaching explanations for Agent prompt, RAG retrieval, immutable version and matched/no-match behavior.

M02 still owns the final shared navigation/i18n framework. Wave 1A must keep text in a small translation dictionary/component boundary and must not redesign V2 typography, spacing, stage visuals or invent debate pages.

## 10. File ownership

### Main/contract owner

- `docs/gates/wave1/**`
- frozen/product OpenAPI drift decision, generated client regeneration and route-placeholder removal after backend routes are stable
- shared integration fixes and final Project/V2 status update

### Luna backend owner (M05/M06/M09 backend)

- `backend/app/core/models.py`, database/file permission helpers needed by this wave
- `backend/app/main.py` only for registering Wave 1 routers and preserving the explicit frozen 422 operation allow-set while suppressing uncontracted framework 422s
- `backend/app/modules/agents/**`
- `backend/app/modules/knowledge/**`
- internal provider/vector/file ports/adapters under a new clearly scoped backend subtree
- `backend/migrations/versions/0002_wave1_agents_rag.py`
- Wave 1 backend tests

Must not edit frontend, generated API, parent contracts, root package/lock, Project or V2 workbook. A new backend dependency requires main approval before lock changes.

### Luna frontend owner (M05/M06/M09 UI)

- business pages/components/styles under `frontend/app/**` and new non-generated `frontend/components/**`, `frontend/lib/**`
- frontend tests for the owned slice

Must not edit `frontend/lib/api/generated/**`, backend, parent contracts, root package/lock, Project or V2 workbook. It must tolerate generated types changing later in the same wave through the thin wrapper boundary and must not hand-copy DTOs.

### Contract/quality owner

- `contracts/**`, `scripts/**`, `.github/**`, `frontend/lib/api/generated/**`
- removes exactly the 24 implemented Wave 1A operation placeholders, regenerates the client and proves semantic route equivalence

This ownership is assigned only after application routes stabilize; it must not alter backend/frontend business behavior.

All workers share one checkout, are not alone, and must not reset/revert/reformat other owners' changes.

## 11. Deterministic acceptance

### G1.5 backend/domain

- clean upgrade `0001 -> 0002`, empty database upgrade, repeated deployment upgrade and exact new constraints/indexes;
- startup permission test proves `DATA_ROOT=0700`, owned SQLite/Markdown/snapshot files `0600`;
- create Agent + V1.0 draft; single-draft partial uniqueness; create V1.1 only after publish;
- stale revision loses no content; published/superseded mutation rejected;
- same-group reuse and cross-group Agent/document/version/snapshot list/detail/download/bind matrix, with uniform 404;
- teacher sees all and only published/superseded history; teacher draft/unbound workspace access 404;
- UTF-8/newline/character count, empty/non-MD rejection, same-name/duplicate-content acceptance, aggregate 100,000 atomic rejection;
- document-set replacement rejects duplicate/hidden/cross-group/over-limit/stale input atomically; upload missing `expected_revision` returns `409 stale_revision` and cannot bypass CAS;
- per-document indexing failure isolation and manual reindex; ready/failed/pending blockers;
- deterministic chunk offsets/vector BLOB round-trip and snapshot-filtered cosine search;
- matched/no-match test chat with real source IDs/names and empty no-match sources;
- immutable source/snapshot downloads and workspace hide behavior;
- upload and publish crash injection at prepared, staged, promoted, before/after final DB commit and startup recovery; no committed document/published pointer can target missing files;
- concurrent same-key/same-hash, same-key/different-hash, lease expiry/takeover and crash/retry tests for create, upload, reindex, hide, archive/unarchive, next-version and publish; distinct-key publish race has one winner and no orphan;
- V1.1 publish preserves V1.0/S1 bytes/chunks/hash while teacher current pointer moves;
- provider/model/key/external voice/absolute path fields absent from public schemas and responses.

### G1.5 contracts/frontend/repository

- strict FastAPI/OpenAPI route semantic comparison passes with 33 implemented operations total (`9 Wave 0 + 24 Wave 1A`) and only the remaining later-wave placeholders;
- FastAPI's generated generic 422 is suppressed only where the frozen operation omits it; the six Wave 1A business-validation 422 responses remain present with the frozen Error schema. `backend/app/main.py` integration is backend-owner work before semantic comparison, not contract-tool loosening;
- frozen OpenAPI copy/hash, Redocly, generated client clean-diff, response allow-list, WebSocket fixtures and repository/secret/boundary scans remain green;
- frontend ESLint, TypeScript, Vitest and production build;
- backend Ruff, mypy, pytest and Alembic smoke;
- Docker Compose config and existing Wave 0 auth/seed smoke remain green.

### G3 runtime slice

Through `http://localhost:8080` on a fresh migrated Demo data root: login as one group student, create/edit/upload/index/test/publish, switch to teacher, inspect/download the frozen result, switch to the other group and prove 404. Restart services and prove the published snapshot and permissions survive.

## 12. Stop conditions

Stop and return to the main agent if implementation would require:

- changing frozen public DTO fields/status/error semantics;
- adding PDF/TXT/OCR/editor input, public deployment, real supplier calls or real secrets;
- weakening group scoping, immutable snapshot/published-version semantics, CSRF/idempotency or file containment;
- copying any source fragment from OpenMAIC, Parallax, TalkingHead, MotionEngine or another reference;
- silently selecting a real embedding threshold/model before the user's final TikTok Markdown exists;
- treating the temporary Wave 1 avatar/fallback state as finished M07/M08 functionality.

## 13. Reference originality boundary

`reference_question`: how mature systems separate mutable workspace content, immutable release snapshots, retrieval receipts and teacher read-only projections.

`allowed_principles`: ports/adapters, scoped repositories, atomic promotion, versioned immutable snapshots, state-to-view mapping, deterministic contract tests.

`forbidden_reuse`: any reference source file, component tree, domain model, schema, prompt, Provider request code, test body, comments or naming copied into Maya.

`originality_check`: main reviews new code structure/names/comments and repository scan results; a reference-like large component or copied domain vocabulary fails the Gate even if tests pass.

## 14. Gate sequence

`G0-S Sol design challenge -> G1 Luna implementation -> G1.5 deterministic checks -> G2 Sol code/risk audit -> G3 main sign-off -> cross-module Docker slice`

G0-S and G2 output: `PASS | CHANGES_REQUIRED`, no more than five blocking findings, each tied to this packet or the frozen parent contract. Workers cannot approve their own Gate.
