# W4-EMBED G1.5 Gate Packet

Status: `G2 SOL PASS / REAL 1024 PREFLIGHT FAILED RESPONSE CONTRACT / W4-EMBED NOT SIGNED`

Issues: `#19 W4-EMBED-RUNTIME`, `#20 W4-PROVIDER-PREFLIGHT`

## Authorized scope

This candidate implements and tests the real-Embedding control seams. It does not claim
a complete real RAG path. An independent account-only preflight made one 256-dimension
Embedding request and one LLM request with non-student fixtures; those remain
availability evidence only. The separately gated 1024 preflight has now used its single
request allowance and failed local response validation after HTTP 200.

Implemented boundaries:

- fixed `text-embedding-v4` model selection and Beijing workspace endpoint shape;
- explicit Mock versus real Embedding selector with every companion Provider kept Mock;
- exact teacher-only `ProviderDataCallV1` disclosure and confirmation CAS;
- policy, export-manifest, budget-reservation and acceptance-state ledgers;
- deterministic SnapshotBuild batching and frozen payload hashes;
- injected no-redirect, one-attempt HTTP transport with `not_sent` versus
  `acceptance_unknown` classification;
- staged vector validation and atomic SQL publication of immutable snapshots together
  with operation success;
- fake-transport integration tests only.

The current repair candidate additionally closes the five prior G2 findings:

- all document and query requests are fixed to
  `dashscope / text-embedding-v4 / cn-beijing / 1024 / w4-embed-v1`, including
  the provider-visible dimension and exact endpoint/policy equality check;
- sanitized accepted vectors and stages are durable SQL rows; restart reconciliation
  preserves accepted work, never retries acceptance-unknown work and continues only a
  proven `not_sent` missing batch;
- confirmed student publication prepares the exact owner-bound build/export manifest,
  invokes the controlled runtime and atomically publishes the immutable Snapshot;
- generation retrieval embeds the exact 1–3 frozen turn subqueries with the published
  Snapshot identity and emits normal server-assigned Evidence receipts;
- the course teacher can discover each exact per-turn manifest through a dedicated safe
  DTO, review/confirm it, and explicitly retry the non-terminal pending turn. Ordinary
  classroom WebSocket/DTOs receive only a safe recoverable code, never a manifest,
  provider, model or endpoint.

Independent Sol High then audited exact clean SHA
`9fabfb1f9f3a718005f55cfa7f34ed17afd7919f` and returned
`CHANGES_REQUIRED / P0=0 / P1=2 / P2=1`. The current candidate closes those three
findings without making a Provider call:

- the actual real-Embedding document text and canonical turn queries are scanned before
  export hashing, manifest persistence, confirmation or Provider selection; credential-
  and private-identity-shaped inputs fail closed with no manifest, operation, reservation
  or Provider call;
- ordinary student publication errors no longer contain a manifest hash. A dedicated,
  course-authorized teacher route discovers exact publication manifests from the
  AgentVersion owner chain, including an unconfirmed manifest that has no operation row;
- direct regression assertions prove a pre-confirmation query operation remains
  `prepared` with zero requests, zero charged requests, no reservation and no scope
  budget.

Sol High re-audited exact clean SHA
`0c7c6e3c85ad8dced45e1588e99a19921f1a1a8a` and returned
`PASS / P0=0 / P1=0 / P2=0` on all eight repaired findings.

The single permitted three-text 1024 preflight then made one request. It returned HTTP
200, but the local adapter rejected it as `embedding_model_mismatch`. The official
DashScope synchronous response contract documents `output.embeddings[].text_index` and
does not return `model` in that native envelope. The generic validator had incorrectly
applied the OpenAI-compatible response-model requirement to both dialects.

Commit `dbef20e` introduces an explicit response dialect: generic/OpenAI-compatible
responses still require exact model, while only the fixed DashScope adapter accepts the
documented native `output.embeddings` envelope without model; any explicit model must
still match. Fake tests reject wrong model, wrong envelope, count/order/dimension and
non-finite vectors. No second real request was made.

## Frozen invariants

- No request occurs before exact policy, manifest, confirmation and budget preflight.
- Unknown account plan, stale confirmation, export drift, budget failure or unknown
  acceptance fails closed.
- Raw `AGENT.md`, student identity, teacher notes, private snapshot data and credentials
  are never emitted through public DTOs or logs.
- Old snapshots remain immutable; a real build creates a new snapshot only.
- The Provider operation and product snapshot cannot report contradictory success.
- A worker, fake transport or local test cannot sign its own real-service Gate.

## Current deterministic evidence

- backend full suite: `817 passed`;
- frontend: `34 files / 210 tests`, lint, TypeScript and production build passed;
- Ruff and mypy passed;
- frozen OpenAPI and generated client passed; the route semantic fixture contains `76`
  platform operations with zero placeholders, the live FastAPI comparator reports `55`
  implemented strict operations with zero placeholders, and the response checker covers
  `76` operations;
- repository/secret boundary and generated-source red-team probe passed;
- fresh/repeat migrations 0001–0013 plus populated Wave 1/2/3/4, Evidence Trace and
  Embedding identity downgrade/re-upgrade probes passed;
- fake-transport product evidence proves confirmation-before-call, exact 1024 request,
  durable query-stage reuse, publication/retrieval/Evidence receipt continuity,
  non-terminal provider gating and explicit retry;
- formal real 1024 preflight calls: `1` (HTTP 200, local validation failed);
  earlier independent availability calls: `2`.

## Remaining Gate boundary

The response-dialect correction requires an incremental exact-SHA Sol review, but the
single 1024 preflight allowance is exhausted and must not be repeated. The only truthful
service status remains `REAL EMBEDDING 1024 PREFLIGHT FAILED`; HTTP 200 alone is not a
Gate PASS. W4-EMBED also still lacks empty-runtime browser G3 publication → teacher
confirmation → query → retrieval → Evidence receipt and restart evidence. Current
private-account plan/logging/retention controls remain fail closed unless the persisted
reviewed policy proves them.

## G2 audit question

Sol High audited exact clean SHA `8be48334db4d564a7c13287973771d3cd28d727a`
and returned `CHANGES_REQUIRED / P0=0 / P1=5 / P2=0`:

1. the candidate used dimension 256 and omitted provider-visible dimension plus exact
   endpoint/policy binding;
2. accepted vectors were process-local and not restart-recoverable;
3. student publication did not prepare/confirm/run the real SnapshotBuild path;
4. query embedding and retrieval remained Mock 256;
5. teacher disclosure was not page-reachable or course/build-authorized.

Those five findings and the later two P1/one P2 findings were closed and signed by Sol
High on `0c7c6e3`; the only subsequent code delta is the isolated documented
response-dialect correction described above.
