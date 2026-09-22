# Maya Platform Architecture

## Runtime topology

Maya runs locally as three containers behind one same-origin gateway:

- Caddy gateway on port 8080;
- Next.js frontend;
- single-worker FastAPI backend with SQLite WAL and local controlled files.

The Demo intentionally excludes Redis, Celery, PostgreSQL, cloud object storage and a
separate vector database. Future infrastructure replaces adapters rather than browser
DTOs or domain identities.

## Frontend boundary

The browser calls only platform-owned REST/WebSocket contracts. It may receive Agent,
version, snapshot, retrieval state, source, playback and report DTOs. Supplier names,
model IDs, API keys, external voice IDs, supplier URLs and private paths stay on the
backend.

## Domain modules

- `auth` and `org`: Session/CSRF/Origin and course/group scoping.
- `agents`: stable Agent identity, mutable draft, immutable published versions.
- `knowledge`: group Markdown, draft associations, chunking/indexing and immutable
  KnowledgeSnapshots.
- `avatars` and `voices`: constrained visual configuration, uploader-owned cloned
  voices and a provider-isolated voice lifecycle.
- `debates/setup`: participant/version/snapshot freeze and deterministic rule plan.
- `debates/generation`: typed retrieval, closed structured turn generation, validation
  and generation fences.
- `debates/playback`: authoritative controller/media state, events, recovery and Replay.
- `interactions`: independent public vote and named raw barrage.
- `reports`: anonymized insight and immutable Maya report revisions.

## Immutable version chain

`Agent -> AgentVersion -> KnowledgeSnapshot -> SnapshotDocument/KnowledgeChunk`

Publishing never edits an earlier version or snapshot. A DebateParticipant freezes the
exact AgentVersion and KnowledgeSnapshot used by that debate. New Persona/Embedding
contracts apply only to new versions/snapshots; legacy rows remain readable and
reproducible.

## RAG and evidence

Draft and snapshot vectors are isolated by their owner IDs. Retrieval creates typed
receipts. The model may select only server-issued evidence IDs; the validator persists
only used receipts as `TurnSource` rows. A future EvidenceTrace links claims to those
immutable rows and server-derived source/speech locations. It does not certify truth.

## Prompt and context

The rules engine owns order, phase, retry budget and terminal behavior. Student persona
content is untrusted and cannot override platform rules. Each turn continues to receive
the full text of every predecessor turn. Wave 4 may serialize one persona and one rule
block per request and reuse stable receipts on structure-only retry, but it cannot
replace the predecessor transcript with summaries.

## Persistent state machines

- Debate: draft, running, debate-finished/completed, failed or stopped.
- Playback: preparing, ready, playing, paused, waiting-next, completed or stopped;
  mode is live or replay.
- Interaction: closed, open or finalized.
- Insight/report: independent durable attempts and immutable successful
  revisions.

The browser never advances these state machines by local timers. Database commit occurs
before event broadcast. WebSockets use short Sessions for handshake, snapshot, command
and disconnect rather than holding a Session for the socket lifetime.

## Database and file consistency

SQLite stores identities, permissions, immutable relations, text, hashes, chunk/vector
metadata, Jobs, operation journals and audit facts. Markdown/audio bytes live under a
controlled data root. Cross-database/file operations use staging or trash, fsync/hash
validation, short writer transactions, claim tokens and startup recovery.

## Provider ports

LLM, Embedding, VectorStore, TTS, VoiceClone and Translation are backend ports. Real
implementations are introduced one Gate at a time. Each Gate freezes model/endpoint,
input data, immutable version metadata, call count, timeout, retry, safe error, privacy,
cost ceiling and stop condition before a real request.

## Security boundaries

- Sessions are opaque HttpOnly cookies with CSRF and same-origin enforcement.
- Students are group-scoped; teachers are course-scoped; anonymous users receive only
  the minimal active classroom form.
- `.env`, account credentials, private audio and runtime data are never tracked.
- Raw barrage nicknames remain in teacher history but never enter Maya insight/report.
- Demo quick login is private-demo-only and must be disabled before formal classroom or
  public deployment.

## Classroom rendering

The default classroom serves committed scholar GLBs and a static courtyard through the
Next.js frontend. Audio remains authoritative for active-speaker motion and progressive
speech display; saved text remains readable when media fails. Optional Gaussian scene
packs are local experiments outside version control and are not a runtime dependency of
the default classroom.

## Private Chat and student Live

Workspace routes reuse session/course authorization. Conversations bind one owner
to an immutable published Agent version and its knowledge snapshot; no teacher
override reads another user's private history. A revision fence serializes messages,
and a stable request ID prevents duplicate paid work. LLM and retrieval use the
existing disclosure, policy and operation ledger; unknown acceptance is terminal.

Teacher Immerse renews a short Live lease. Students receive an allowlisted snapshot
and retained audio through separate read-only routes. Controller epochs, private
notes and unpublished turns are excluded; joining never triggers generation.
Installation-wide Provider preferences are teacher-only in the single-course Demo,
encrypted at rest, revisioned and applied only while generation is idle. See
[ADR-008](adr/ADR-008-agent-chat-live-provider-controls.md) for deferred speech work.
