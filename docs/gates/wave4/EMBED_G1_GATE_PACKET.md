# W4-EMBED G1.5 Gate Packet

Status: `G1.5 REPAIR CANDIDATE / G2 REAUDIT PENDING / FORMAL MAYA RUNTIME CALLS 0`

Issues: `#19 W4-EMBED-RUNTIME`, `#20 W4-PROVIDER-PREFLIGHT`

## Authorized scope

This candidate implements and tests the real-Embedding control seams without making a
formal Maya runtime request. It does not authorize a real Provider call or claim a
complete real RAG path. An independent account-only preflight made one 256-dimension
Embedding request and one LLM request with non-student fixtures; those are availability
evidence only. Formal real Embedding is now frozen at 1024 and has not run.

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

- backend full suite: `796 passed`;
- frontend: `33 files / 209 tests`, lint, TypeScript and production build passed;
- Ruff and mypy passed;
- frozen OpenAPI and generated client passed; the route semantic fixture contains `75`
  platform operations with zero placeholders, the live FastAPI comparator reports `55`
  implemented strict operations with zero placeholders, and the response checker covers
  `75` operations;
- repository/secret boundary and generated-source red-team probe passed;
- fresh/repeat migrations 0001–0013 plus populated Wave 1/2/3/4, Evidence Trace and
  Embedding identity downgrade/re-upgrade probes passed;
- fake-transport product evidence proves confirmation-before-call, exact 1024 request,
  durable query-stage reuse, publication/retrieval/Evidence receipt continuity,
  non-terminal provider gating and explicit retry;
- formal Maya runtime Provider calls: `0`; independent preflight calls: `2`.

## Remaining Gate boundary

No formal real 1024 request may run until a new exact clean SHA receives independent
Sol High `PASS / P0=0 / P1=0`. That audit must challenge the five repaired findings,
the pre-confirmation `prepared` operation (zero reservation/call), course authorization,
partial continuation, acceptance-unknown behavior, ordinary DTO secrecy and the
non-terminal Playback retry fence.

After PASS, exactly one safe 3-text 1024 preflight is allowed. It can prove only
`REAL EMBEDDING 1024 PREFLIGHT PASS`; W4-EMBED itself still requires empty-runtime
browser G3 publication → teacher confirmation → query → retrieval → Evidence receipt
and restart evidence. Current private-account plan/logging/retention controls must remain
fail closed unless the persisted reviewed policy proves them.

## G2 audit question

Sol High audited exact clean SHA `8be48334db4d564a7c13287973771d3cd28d727a`
and returned `CHANGES_REQUIRED / P0=0 / P1=5 / P2=0`:

1. the candidate used dimension 256 and omitted provider-visible dimension plus exact
   endpoint/policy binding;
2. accepted vectors were process-local and not restart-recoverable;
3. student publication did not prepare/confirm/run the real SnapshotBuild path;
4. query embedding and retrieval remained Mock 256;
5. teacher disclosure was not page-reachable or course/build-authorized.

The current repair candidate claims closure of these five findings but does not sign
itself. A new exact clean SHA now goes to independent read-only Sol High re-audit.
