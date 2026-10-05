# Knowledge generation durability and Provider stage contract (K2a/K2b)

Latest product override (2026-10-05, implementation in progress): Teacher save or explicit generate/regenerate expresses the exact Knowledge-generation intent. No separate “provider confirmation required / Open provider disclosure” step is permitted. Record the current actor-authorized exact payload under the registered reviewed policy; preserve course/source ACL, privacy, idempotency, accounting, current usable content and unknown no-resend. This replaces the historical separate-confirmation and separate Create AI Knowledge UI descriptions below. Agent creation and AI Knowledge creation use one Agent flow with Brainform RAG/Knowledge selection; canonical references use current Knowledge for future work without rewriting historical attempts.

K2a persists an explicitly supplied Teacher Knowledge intent. K2b1 adds a
confirmed, owner-authorized one-shot Provider operation and immutable sanitized
stage. K2b2-A materializes accepted candidates into the same K1 Set, one
permission-fenced Asset transaction at a time. The explicit Create/Update AI
Knowledge UI passed focused independent review; overall K2b2/backend acceptance
is pending. Ordinary Agent Done remains independent.

## Done intent and authorization

Generation intent is an optional publish-request field. Ordinary Teacher Done,
including an Agent with selected courseware, creates no generation Job/run.
Student Done also keeps the existing request shape. K2b2 will send the existing
intent only from an explicit AI Knowledge creation/update flow. Agent.md guides
that authorized operation; no Planner, semantic classifier, fixed Markdown
heading, Teacher capability switch, Toolkit binding or per-Asset approval is
required. When a caller explicitly supplies `generation.source_document_ids`,
the ordered IDs must exactly match the immutable draft's enabled documents.

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

`GET /knowledge-generation-jobs/{job_id}` is owner-only and returns safe state,
Set ID, timestamps, error code and accepted/materialized/failed item counts. It
never returns Markdown, source content, Provider request/response data or other
owners' rows. Owner Set summaries expose `generated_by_agent_id` only for a
generation-owned Set; manual Sets and non-owner projections return null.

Brainform summaries expose nullable `generation_job_id` only to the current
Teacher owner who can edit the canonical Set and still access the actual
generation Agent/version in the same course. An alias opens that same Set; it
does not become the generator. Student/shared rows and rows whose generator,
owner or course access is revoked return null. A still-authorized Teacher owner
can read a blocked job after source revocation. Reloading Brainform hydrates the
existing owner-only job status;
reading status never creates or retries a run. Missing exact disclosure consent
uses the existing disclosure link. Confirmation resumes that same blocked job
only; sending or unknown acceptance never authorizes a resend. Late list/status
responses cannot replace a newer job or another actor/course's state.

## K2a worker and K2b1 Provider boundary

Jobs are durable; the process-local task manager is only a wake mechanism.
Claims use a persisted token and lease. Current Agent, Set, Source, group,
course, file hash and authorization epochs are rechecked at claim, immediately
before dispatch, and in the accepted-stage transaction. With a non-Provider
selector, the intent blocks as `provider_not_configured`, with no Provider
operation, request or Assets.

With the configured DashScope LLM, K2b1 prepares the `llm_knowledge_generate`
manifest against the exact run and agent version. Its field classes are Teacher
Agent instructions, authorized courseware text, platform rules and an opaque
local identifier. The exact manifest and policy require the existing teacher
disclosure confirmation. Missing consent creates no ProviderOperation,
reservation or request. Ordinary source text is not screened by keyword.

Agno 3.0.11 receives a fresh Agent and may invoke exactly once. The callback
uses the final SDK system/user messages to build canonical UTF-8 JSON bytes;
their SHA-256 is the durable request hash and those bytes are passed unchanged
to `post_bytes`. Retry, history, memory, tools, cache and telemetry are off.
The credential is sent only in the Authorization header. No raw HTTP envelope,
header or request body is persisted. Knowledge generation reuses the existing
LLM accounting bucket without an added quota or retry allowance.

A valid response stores only canonical typed candidate JSON and validated
usage (or null when usage is absent/invalid); usage is never an Asset-content
gate. Acceptance, stage, reservation and run/job transitions commit together.
K2b1 alone does not materialize Assets. K2b2-A keeps the accepted claim for its
local worker, which can resume the immutable stage without another Provider
request. If ACL changes while the call is in flight, the response content is
suppressed and only a safe receipt hash/error is retained.

Startup never automatically repeats an uncertain request: reserved becomes
not-sent with zero charged count, sending becomes `acceptance_unknown`, and an
accepted stage remains accepted for local zero-network recovery. A failed local
stage commit becomes acceptance-unknown. No provider diagnostics enter the
owner status DTO.

## K2b2-A accepted-stage materialization

Each selected source gets a random, run-scoped `source_receipt_id`. The provider
sees that opaque ID beside authorized courseware text, never a client-chosen
binding or location. A candidate's optional receipt IDs become K1 source
relations only after the worker rechecks run, Set, binding, document, file,
hashes, epoch, index revision and current ACL. Invalid optional receipts are
dropped and counted as unverified; they do not reject otherwise valid content.

The worker hashes the canonical accepted stage and derives a deterministic
item key from run/stage/index. Each Concept, Question (including its teacher-only
Rubric/reference answer), or Note is validated with K1 rules and saved in its
own short transaction. A malformed item records a safe failure without undoing
earlier successes or suppressing later valid items. Items retain stage/candidate
hashes, receipt IDs, lineage and immutable AssetVersion IDs. Status counts mean
accepted candidates, committed versions, and failed plus skipped items.

The stable owner/course/Agent Set identity is reused on explicit later Done.
Generated items use stable kind/ordinal lineage. Each run freezes expected
Asset IDs, head sequence and origin at enqueue; materialization appends only
when the current head still matches. An older concurrent run skips a stale
item as `target_head_changed` while it may save independent items. Manual heads
stay intact (`manual_head_preserved`). Current Teacher, Agent, Set, source and
claim fences are checked for every item; revocation preserves committed items
and blocks remaining work. Startup reclaims an accepted stage for local
materialization with zero Provider calls; stale claims cannot write. Per-item
commits are immediately readable through K1 APIs. There is no review,
confirmation or content-quality gate.

Migration `0037_knowledge_generation_runs` adds the run table;
`0038_knowledge_generation_provider_stage` adds manifest and accepted-stage
data; `0039_knowledge_generation_materialization` adds source receipts,
target-head snapshots, item journal and generated lineage. Existing 0038 runs
receive an empty lineage baseline because that schema could not store generated
Assets. Migrations are atomic with Alembic head updates;
downgrade refuses to discard generation or materialization history. Debate
cleanup preserves K2 rows. Tests cover good/bad/good, citations, manual head,
source/Teacher/Set revocation, late claims, zero-network recovery, provider
accounting states and migration rollback. The explicit Teacher UI passed focused
independent review; overall K2b2 and real Provider acceptance remain pending.
No real Provider was called.
