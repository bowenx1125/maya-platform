# Knowledge generation durability contract (K2a)

K2a persists an explicitly supplied Teacher Knowledge preparation intent with
Agent Done. It does not call a Provider or create AI-authored Assets. Automatic
generation is not available until K2b.

## Done intent and authorization

Generation intent is an optional publish-request field. Ordinary Teacher Done
keeps the existing request even when the Agent has selected courseware; it does
not infer teaching intent from the Teacher role or source presence and creates no
generation Job/run. Student Done also keeps the existing request shape. K2a has
no Teacher generation switch or confirmation. K2b must later derive a controlled
intent from Agent.md and the current task without requiring a new Teacher choice.
When a caller explicitly supplies `generation.source_document_ids`, the ordered
IDs must exactly match the immutable draft's enabled documents.

The server requires the current actor to be the Agent owner and a Teacher in its
course. It rechecks active Agent/version state, course and Group access, source
ownership/visibility, current document/file hashes, authorization epochs and
index revisions before persisting. Agent names and Markdown never grant role or
resource access.

## Atomic durable run

On the existing publish final commit, the server may create one Private personal
Knowledge Set for the stable owner/course/Agent identity, add currently authorized
selected Sources, link the Set to that Agent, and insert its `jobs` row and
`knowledge_generation_runs` row. These rows commit with Done and the completed
publish idempotency response, or roll back together. A response replay preserves
the original run/job/Set identifiers. The new input key is a canonical SHA-256
over owner, course, Agent identity/privacy epoch, target Set identity/privacy
epoch, Agent.md hash, policy version and ordered source binding/hash/epoch/index
manifest; it excludes the random AgentVersion ID and mutable display names.
The database unique key reuses the same run across concurrent or differently
keyed identical Done requests. Every reuse rechecks current authorization.

`GET /knowledge-generation-jobs/{job_id}` returns only the safe status, Set ID,
timestamps and safe error code to the current Teacher owner. It never returns
Markdown, source content, Provider request/response data or other owners' rows.

## K2a worker boundary

Jobs are durable; the process-local task manager is only a wake mechanism.
Claims use a persisted token and lease, source/Agent/Set fences are checked again
at claim, and startup requeues only abandoned K2a in-process claims. Since no
Knowledge Provider operation exists in K2a, the worker immediately stores
`blocked/provider_not_configured`, with zero outbound calls and no Assets. A
revoked source or scope stores `blocked/authorization_revoked`. Neither status
means generation completed; no fake output is written. Nullable
`provider_operation_id` and `request_hash` reserve the later K2b ledger link;
accepted stages and item materialization are not part of this migration.

Migration `0037_knowledge_generation_runs` adds the run table and indexes
atomically with the Alembic head. Its downgrade refuses if a generation run or
generation Job exists. Debate cleanup preserves generation runs. Focused tests
cover Done/job atomicity, same-input reuse, owner-only status, source revocation,
claim/startup recovery, fresh and populated migration, and rollback on DDL and
head-write failure. These checks establish the K2a persistence boundary only.
