# Knowledge generation durability and Provider stage contract (K2a/K2b1)

K2a persists an explicitly supplied Teacher Knowledge intent. K2b1 adds a
confirmed, owner-authorized one-shot Provider operation and an immutable,
sanitized accepted stage. K2b1 does not materialize Assets or claim completed
Knowledge. K2b2 must add the explicit AI Knowledge product path and transactional
per-Asset save. Ordinary Agent Done remains independent.

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

`GET /knowledge-generation-jobs/{job_id}` returns only the safe status, Set ID,
timestamps and safe error code to the current Teacher owner. It never returns
Markdown, source content, Provider request/response data or other owners' rows.

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
usage (or null when usage is absent/invalid). Acceptance, stage, reservation and
run/job transitions commit together. The run remains `blocked/accepted_stage_ready`
and the Job remains pending until K2b2 materializes per-Asset transactions; no
AI-authored Asset or successful completion is asserted by K2b1. If ACL changes
while the call is in flight, the response content is suppressed and only a
safe receipt hash/error is retained.

Startup never automatically repeats an uncertain request: reserved becomes
not-sent with zero charged count, sending becomes `acceptance_unknown`, and an
accepted stage remains accepted for local zero-network recovery. A failed local
stage commit becomes acceptance-unknown. No provider diagnostics enter the
owner status DTO.

Migration `0037_knowledge_generation_runs` adds the run table; `0038_knowledge_generation_provider_stage`
adds the run manifest hash and accepted-stage ledger. Both run transactionally
with the Alembic head; downgrades refuse generation or Provider history. Debate
cleanup preserves generation rows, provider stages and their FK-linked
operations. Tests cover Done/job atomicity, same-input reuse, owner status,
source revocation, exact-wire Fake dispatch, consent requeue, one-shot states,
stage suppression/recovery, fresh and populated migrations and fault rollback.
These tests use no real Provider. K2b2 Asset creation and Teacher UI remain
future work.
