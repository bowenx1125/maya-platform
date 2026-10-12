# Knowledge Sets and Assets (K1)

K1 adds a shared, manually authored store for course and Agent knowledge. The
teacher workspace at `/teacher/knowledge`, teacher Agent detail at
`/teacher/knowledge?agent_id=…`, and student Agent entry at
`/student/knowledge?agent_id=…` read and write the same stable Set and Asset
IDs. This is a teaching-content library; it does not create a second raw-file/RAG
store.

The teacher top-level Knowledge route has separate Original Sources and Knowledge
Sets views. Original Sources reuses the existing raw Knowledge library. Agent
entry points select the same Set IDs; they do not copy files or assets. Students
open Sets only through current Group and owner access rules.

## Content and version rules

A Set contains source links and versioned Assets in four categories: Sources,
Concepts, Questions and Notes. A Question owns its optional reference answer
and Rubric. Graph is a read-only List/Graph view inside Concepts, not a fifth
category; its nodes open Concept details, and edits use the Asset editor.

Creating or editing an Asset saves a new immutable content version and makes it
current immediately. Each Set content write uses a content-revision CAS; name
and visibility use a separate metadata-revision CAS. Renaming changes metadata
only. Mutation requests also use the platform idempotency ledger, so replaying a
completed request returns its original result without adding another version.
Asset create/update replay rechecks current owner and source authorization, then
returns the accepted DTO fields and timestamp spellings even after a later Asset
version exists. If authorization has been revoked, replay fails closed with 404.

Question DTOs for ordinary students omit both `reference_answer` and `rubric`,
including version history. The student content hash is calculated from the
student-visible projection, so hidden answer or Rubric edits do not create a
fingerprint signal. Teacher and owner projections retain the full immutable
Question.

Asset history is fetched on demand from the selected Asset detail. It contains
only versions currently readable by that actor, with visible save times and
currently authorized source names where available. Lists show content names and
short previews; version numbers and Rubric badges are not shown there.

## Scope and source authority

Every Set belongs to one course and either a personal owner (`group_id = null`)
or a current Group membership. SQLite/PostgreSQL schema has a composite
Group/course foreign key. Personal Sets stay owner-only. Group Sets can be
shared with their Group; a Public Set can contain only current Public sources
from that Group. A private source may be linked to its owner’s private Set and
never becomes readable to a peer through an Agent link.

Set sources reference the existing `KnowledgeDocument`, `StoredFile`, and
`FileReference` rows. Binding and later saving a citation both re-check current
course/Group access, source visibility, active version, hashes and authorization
epoch. Each immutable Asset version stores source binding IDs, document/file
hashes, authorization epoch, and exact citation locations. If source access is
revoked, Set detail redacts its identifying metadata; the owner may remove the
unavailable binding, but cannot save new derived content against it.
Non-owners can list or open a Set only while every active source remains readable.
When a source is withdrawn, the Set is hidden from them rather than returned with
a misleading zero `source_count`; the owner retains an opaque unavailable binding
ID to remove it, without filename or hash.

Citation offsets are zero-based Unicode codepoint positions with an inclusive
start and exclusive end in the normalized, frozen Markdown. When `excerpt_hash`
is supplied, the server verifies its SHA-256 against that exact source slice and
the stored file/content hashes. `section_path` and `paragraph_index` are rejected
until they can be derived from the source; they are not accepted as verified facts.

Making a Private Group Set Public advances its authorization epoch. Old Private
Asset versions remain owner-only; a Public Set's `asset_count` includes only
currently readable Asset heads. The owner can edit an old Asset and save a new
version after sharing; that current version becomes readable to the Group without
another Publish or Review step, while earlier versions stay private. Read-only
Set and Graph DTOs omit internal CAS/authorization counters and private timestamps.
Non-owner source/asset counts include only currently readable items; source
authorization epochs and Asset sequence numbers are omitted. Non-owner Asset DTOs
omit the original creation timestamp; the visible current version's update time
and authorized history remain available. History lists only authorized versions.

The owner-only `DELETE /knowledge-sets/{set_id}` operation is a soft revoke. It
CAS-checks metadata and content revisions, advances the authorization epoch,
and records `deleted_at`; it does not cascade-delete historical Assets, versions,
source references or file references. Late reads and writes fail closed. Debate
cleanup preserves all six K1 tables and their FileReferences, and checks real
table/trigger gates on known 0035 or 0036 heads. A 0036 downgrade refuses before
DDL if any of its six tables contains data.

## API and implementation boundary

`GET/POST /courses/{course_id}/knowledge-sets` lists and creates Sets.
`GET/PATCH/DELETE /knowledge-sets/{set_id}` reads, renames/shares and revokes.
`PUT/DELETE /knowledge-sets/{set_id}/sources` replaces or removes source links.
`GET/POST /knowledge-sets/{set_id}/assets`, `GET/PATCH /knowledge-assets/{id}`
and `GET /knowledge-assets/{id}/versions` manage typed immutable content.
`GET /knowledge-sets/{set_id}/graph` returns the read-only Graph.
`GET/PUT /agents/{agent_id}/knowledge-sets` links existing Set IDs to an Agent;
it stores only the relation and never copies Asset or source data.

Migration `0036_knowledge_sets_assets` is additive and atomic with the Alembic
head update on SQLite. It creates the Set, source binding, Asset, immutable
Asset version, version-source and Agent-binding tables. AI provenance columns
are reserved for K2; K1 does not run generation jobs or call a Provider. K3
owns the Agent SDK/runtime integration.
