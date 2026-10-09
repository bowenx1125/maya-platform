# MayaForm v1.4 generation and Tool authorization contract

The adopted [Resume v2 contract](MAYAFORM_V14_BRAINFORM_ASSESSMENT.md) supersedes
conflicting clauses here. In particular, canonical Markdown is the Knowledge
source of truth, bound RAG changes enqueue durable generation intents, successful
new regeneration replaces manual current while preserving history, Brainform has
a lightweight Memory entry, and active assessment attempts expose no hints.
Existing same-config deduplication applies to one action/event, not all future
manual regenerate intents.

This contract records the latest user-authored v1.4 architecture supplement. It
supersedes conflicting K2b2/K3/K4 design notes. It does not claim these features
are implemented. K1 Knowledge Sets and the K2a optional, durable generation-intent
API remain as accepted.

## AI Knowledge trigger

An **explicit product flow** is the generation signal. In an AI Knowledge
creation/update flow, a Teacher creates or edits an Agent, writes Agent.md,
selects Sources, and presses Done. The client sends the already-defined K2a
generation intent with the exact selected Sources. The server validates current
actor, role, course, Agent, Set and Source relationships and atomically records
the task. Ordinary Agent Done does not send this intent. The Teacher is not
required to configure a Toolkit, use fixed Agent.md headings, pass a capability
classifier, approve AI content or confirm each generated asset.

There is **no extra Planner** that reads Agent.md to decide whether this Agent
deserves generation. Do not send Agent.md or Sources, create a Provider operation,
charge, or create a Job just to infer the Agent's type. Agent.md guides the
authorized generation task after the product action is known. Generation uses
Agno 3.0.11's public SDK boundary and MayaForm's exact Provider manifest,
permission, idempotency and charged-request ledger. SDK retry, cache, memory,
history and telemetry must not create an unregistered second call. Unknown
acceptance is not automatically resent.

During actual generation the UI says exactly `Generating AI Knowledge`. Saved
Sources, Concepts, Questions (including Rubric) and Notes become usable when
their valid transaction commits. A Teacher Save creates and activates one new
immutable version; it needs no content Review, Confirm, Approve or Publish step.
Failure or partial success is stated accurately and preserves successful items.

Source citations prefer a server-issued opaque receipt from authorized
Knowledge search/read. The server resolves the verified Source, span, offset and
hash; the model need not fabricate these fields. A citation that cannot be
verified creates **no verified source relation**. If the citation is optional
and the asset's own schema, required data and ACL are valid, save the asset
without that relation. This rule does not weaken K1's source-authenticity check
for a relation that is saved.

## Maintainer registry and current Tool classes

Only the maintenance layer develops, registers, updates or removes Tool code.
Teachers and students cannot upload handlers, install Toolkits, add arbitrary
MCP endpoints, or manually attach system Tools to an Agent. There is no Teacher
Tool configuration page and no Agent.md capability compiler or approval gate.

The [latest resource authorization correction](MAYAFORM_V14_TOOL_RESOURCE_AUTHORIZATION.md)
replaces the earlier two-class assumption. The registry has three classes:

| Current actor | Exposed Tool classes         |
| ------------- | ---------------------------- |
| Student       | Public Tools + Student Tools |
| Teacher       | Public Tools + Teacher Tools |

The same teacher-created Agent gets Public + Student when invoked by a Student
and the Teacher set when invoked by a Teacher. Agent owner, Team creator, member
name, prompt text and a Teacher-published Maya Team never confer Teacher Tools.
The Agent chooses an exposed Tool using Agent.md, the Leader instruction, the
current task and context; MayaForm does not call a Planner to choose or approve
its capability list.

**Tool exposure and resource authorization are separate decisions.** Public
means both actor types may see a Tool, not that its target data are public.
One service operation such as `read_knowledge` checks the current actor and
target resource rather than duplicating student/teacher handlers. Typical
resource actions are `read`/`edit`, append-only raw evidence uses `read`/`append`,
course statistics use `aggregate`, and course publication uses `publish`.
Handlers recheck the resource ACL and transaction preconditions on every call.

Public Tools cover authorized Knowledge read/search/list/create/edit/delete;
session and workflow state; answer and skip recording; assessment request,
read and versioned edit; question selection and session finish; and learning
evidence/boundary/snapshot operations. They are available to ordinary Agents,
Student Custom Teams, ordinary Teams and Maya Teams under the current actor's
ACL. Assessment read/edit/create rights are target-resource permissions, distinct from
Tool availability. A learner can read their own formal safe view without edit rights.
A server-authorized evaluator may append formal revisions only within its active
attempt and assigned answers; a summarizer may update only its assigned Boundary.
A synthetic editable practice resource can succeed from a Custom Team through the
same generic ACL mechanism. No new practice product is implied.
A Teacher's Public Assessment Tool does not grant access to another student's
Private Assessment.

Teacher Tools add only course-level, permitted cross-student aggregation and
publication: for example Public course evidence/assessments, learning counts
and boundaries, group learning, course learning reports, and course Team
publish/unpublish. They do not bypass Private Chat or Private Assessment.
No Tool named `read_other_student_private_chat` or equivalent exists in the
registry. Private Chat remains owner-only.

A routine Tool permission denial is a structured Tool failure. It does not
permanently fail the Conversation or prevent a later user message; the Agent may
explain the denied action and continue. Fatal run state is reserved for a true
system-level inability to continue. Tool writes use MayaForm's transaction,
idempotency and side-effect ledger; Agno completion alone is not business
success.

Chats uses its existing General Chat messages, errors and composer for Agent,
Team and Maya Team. Assessment states govern backend operations only; students
start, pause, continue, abandon, redo and query submitted records through natural
language. Tool denials do not create a Permission Panel, assessment state card or
lifecycle button group. Brainform remains the independent information interface.

## Reusable Provider consent and the actual sending boundary

Teacher course consent has separate `llm_agent_chat` and `embedding_query`
purposes. Each binds the current exact policy and declared outbound field
classes; an LLM grant does not authorize Embedding. A valid purpose-specific
grant is reused without per-message Teacher approval. For Single Chat query
Embedding, the outbound text is the current owner's query; the Teacher course
disclosure does not expose a student's Private conversation. Team consent binds
the published Team version and its declared resources. Ordinary non-Chat Teacher
query consent retains its original exact manifest/Agent/course relationship.

Preparation and consent are insufficient if access changes before transport.
Immediately before the operation enters `sending`, the same writer transaction
rechecks the current actor, course, resource access, publication, grant, claim
and exact request binding. Revocation before this point sends nothing and
releases the local reservation. A still-readable historical snapshot is valid;
newer content alone does not invalidate it. Sent or unknown requests retain their
accounting and are never silently resent.

If assessment sources have been revoked, a separately authorized, closed
owner-action request may still query the owner's submitted answers/progress or
abandon the existing attempt. Its wire contains only the current user message,
fixed public protocol and one constrained Tool schema allowing these three actions:
no Teacher Agent.md,
source text, Rubric or earlier history. It cannot resume, redo, answer, score or
provide hints. The server validates every action and discards unsupported prose;
the result uses the existing General Chat presentation.

## Evidence, Assessment and course provenance

Raw answers and raw learning evidence are append-only. A wrong first attempt,
hinted correction, retry and skip remain distinct records; there is no ordinary
Tool to overwrite an old answer or evidence row. `edit_assessment` advances a
current revision while retaining previous judgments and provenance for audit.

Student Custom Team and published Maya Team may both use Public Assessment and
Learning Tools. Every record retains true actor, Conversation, Team identity and
version, course/group where applicable, and origin such as `custom_team` or
`published_course_team`. The latter is not a special Tool class. Formal course
diagnosis/report aggregation filters explicitly eligible provenance, current
course and Public Chat; Custom Team evidence cannot impersonate a Teacher's
published course Team, and Private Chat contributes neither content nor count.

## Limits and verification

Backend rules may enforce authentication, current ACL, privacy, schema,
transactions, idempotency, concurrency, provenance, integrity and Provider
billing. They may not add hidden Chat rounds, authored-text limits, Tool-call
caps, silent Source/history truncation, automatic content review, fixed question
counts, named-member call order or keyword-based capability gates. A real
Provider capacity failure must be reported accurately, without trimming the
user's material or fabricating success.

The following are **acceptance obligations, not current PASS claims**:

1. Student runtime exposes Public + Student Tools; Teacher runtime exposes Public
   plus Teacher Tools, for the same teacher-created Agent under two actors.
2. A Public Tool's allowed resource succeeds and a guessed Private resource
   fails without revealing another student's data or locking the Chat.
3. Student Custom Team can use authorized Assessment/Learning Tools, but its
   evidence cannot enter formal Public course diagnosis as published-Team data.
4. Raw answer/evidence retries append distinct records; Assessment edit retains
   revisions and provenance; duplicate Tool requests produce one side effect.
5. Optional invalid citation does not save a verified relation and does not
   reject an otherwise valid asset; a verified receipt creates the exact
   server-checked relation.
6. Agno's public SDK path cannot make an unregistered retry, write, generation
   or charged request; `acceptance_unknown` stays isolated and Chat can continue.

The [supplement acceptance matrix](../validation/MAYAFORM_V14_SUPPLEMENT.md)
maps requirements to evidence. Actual current revision, focused/full/independent
checks, browser, deployment and real Provider results belong in
[PROJECT](../PROJECT.md); historical acceptance never substitutes for a changed tree.
