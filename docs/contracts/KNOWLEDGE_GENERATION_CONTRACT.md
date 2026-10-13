# Knowledge generation: authorization, durability and current versions

This is the current v1.4 contract. It replaces the historical K2 separate
confirmation screen, separate asset-management UI and manual-head preservation
rules. Implementation and deployment evidence belong in [PROJECT](../PROJECT.md).
The [Brainform contract](MAYAFORM_V14_BRAINFORM_ASSESSMENT.md) and
[UI contract](MAYAFORM_FINAL_UI_POLISH_SPEC_V2.md) define the product interface.

## Intent and current authorization

Agent creation and AI Knowledge creation share the Agent workbench. A Teacher
selects authorized Brainform RAG or Knowledge and saves Agent.md; the explicit
generation flow records the selected RAG generation intent with Done. Ordinary
Agent Done need not generate. Bound RAG content changes also update Knowledge
with an established generation relationship. Manual `↻` remains available.

A Teacher Agent Chat may use the maintainer-registered
`generate_agent_knowledge` Tool for its current published Agent and enabled RAG.
The Tool derives actor, course, Agent/version, source IDs and target from the
authenticated invocation; the model cannot supply another identity or arbitrary
target. Each enabled RAG must still be `workspace_state=active` with a readable
file; a published binding that outlived a Brainform hide fails closed as
`knowledge_generation_sources_unavailable` (not a bare `not_found`), and the
Tool description tells the model to ask the teacher to re-select active RAG and
publish again. It reuses the same generation service, stable Set and durable
worker. It is not a separate Agent compiler, content reviewer or Toolkit binding
flow.

Teacher save, explicit regeneration or an authorized generation Tool action
expresses the exact intent. No separate “provider confirmation required / Open
provider disclosure” step is required for this generation. The worker records
the exact authorized manifest under the current reviewed Provider policy and
rechecks actor/course, Agent/Set ownership and read/edit, source visibility,
hashes, epochs and index revisions. Missing policy or revoked access stops that
task accurately; it does not grant access or permanently lock Chats.

Agent.md, names and creator identity do not confer permissions. Student runtime
does not expose this Teacher Tool. Team data-use consent remains separately
bound to the actual published Team version and resources; removing the Knowledge
generation confirmation screen does not invent Team or Private-data consent.

## Atomic enqueue and replay

The initiating transaction creates or reuses the owner/course/Agent's stable
canonical Set, source bindings, Agent relation, job and generation run. These
commit with the product action or its accepted Tool receipt, or roll back together.
Only after commit does the process-local task manager wake the durable job.
Startup recovery uses the same persisted claims and leases.

One product action has one stable action ID, exact payload hash and replay result.
Retries, double-clicks and differently keyed repeats of the same saved input do
not create duplicate Sets, versions, runs or charges. A later explicit manual
regenerate action may generate again even if source content is unchanged.
The Teacher Tool reuses the current matching pending/running/completed generation
when present and reports its real state; it does not turn an unknown request into
an automatic retry. A changed payload cannot reuse an action ID.

The input binds owner/course, Agent and Set identity/epochs, Agent.md hash,
policy and ordered source identity/hash/epoch/index manifest. Mutable display
names and random version IDs do not alone create new work. Every reuse still
checks current authorization.

Job status is owner-only: safe state, Set/job identity, timestamps, error code and
item counts, without source text, Provider bodies, credentials or foreign rows.
Brainform exposes the generation job only to the current Teacher owner who can
edit the Set and access its actual generator. Reading status never enqueues,
retries or dispatches a Provider request. Late responses cannot replace another
identity, course, selected object or newer job.

## Public SDK and actual send

Use pinned Agno 3.0.11 through public interfaces and the thin MayaForm adapter.
The Knowledge worker's fresh Agent invokes one authorized generation request;
its retry, history, memory, tools, cache and telemetry do not create additional
calls. This generation Agent is distinct from the Teacher Chat Agent that
requested the job.

The final SDK messages produce canonical UTF-8 request bytes; the durable hash
and actual `post_bytes` bytes must match. Credentials remain in the transport
header. Raw HTTP bodies, headers and credentials are not persisted in diagnostics.
The transition to `sending` rechecks current authorization in the writer
transaction. Accounting is retained without product call, token or cost quotas.

Usable completed response content is required. Missing/invalid usage is recorded
as absent metadata and never rejects otherwise usable content. Acceptance,
sanitized immutable stage, accounting and job transitions commit consistently.
Revocation during a call suppresses unauthorized content while retaining the
necessary safe receipt and actual billing state.

Startup converts unsent reservations to not-sent and uncertain sending to
`acceptance_unknown`. It never automatically resends an unknown request. An
accepted stage can resume local materialization without another Provider call.
Failure to persist an accepted response cannot be falsely reported as not-sent.

## Materialization and canonical promotion

The server issues opaque source receipts. Optional invalid citations create no
verified relation; they need not reject otherwise legal content. Verified
relations are saved only after rechecking the exact source/version/ACL.

Each candidate uses a deterministic run/stage/item key and stable lineage.
Concepts, Questions with teacher-only Rubric/reference, and Notes retain immutable
versions and provenance. Partial successful items remain traceable, but a failed
or incomplete generation does not replace a complete usable canonical document.
The canonical Markdown and its executable question projection agree on the
selected version and actual included assets; omitted/edited questions cannot
silently use older live heads.

A valid newest generation appends a new canonical version and makes it current,
including when it replaces manually edited content. The manual version stays in
history. An old generation cannot overwrite a newer source/intent generation;
duplicate materialization cannot create another version. Generation failure
preserves the previous usable content. Rename/no-op changes do not generate.

After a successful relevant canonical change, active/paused formal Team attempts
using that object receive the ordinary Chat message “老师已更改当前回合的
Knowledge，请重新答题。” The same attempt gets a new question-selection
generation; old answers remain historical and cannot enter the new evaluation.
Paused attempts stay paused, completed attempts stay unchanged, and old accepted
evaluator/Boundary results cannot write to the new selection. Promotion, selection,
notice and write fences are transactional. Failed/partial/no-op/rename changes
do not reset a round. This affects neither ordinary Chat nor learning Memory.

## Presentation, migrations and acceptance

During real work show only `Generating AI Knowledge`; no Ready/Reviewed/Published
badge or Teacher content approval. Saved complete content is usable immediately.
Brainform renders one canonical Markdown object with section headings and a
visual-only Graph, independent view/edit routes and shared RAG operations.
Errors retain content and a valid recovery path, without a new workflow panel.

Migrations retain old Set/Asset/Question IDs, source receipts, versions, history,
Chat, evidence and provider ledger. Downgrades that would discard history refuse
rather than rebuilding a parent table unsafely. Generation tables began in
0037–0039; canonical and attempt-selection migrations extend them. Current head
and actual backup/upgrade results are recorded in PROJECT, not inferred here.

Acceptance covers current ACL before send and write, action replay/concurrency,
exact transport bytes, billing/unknown isolation, accepted-stage recovery,
manual replacement with history, partial failure, newest-generation fencing,
active/paused attempt reanswer and completed-history stability. Final product
acceptance additionally requires an actual Teacher Agent Tool call, real
generation, shared canonical references, student Team answers saved to the DB
and a correctly scoped Teacher report; focused Fake tests do not substitute.
