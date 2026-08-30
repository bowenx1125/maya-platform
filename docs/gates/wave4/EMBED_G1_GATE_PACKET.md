# W4-EMBED G1.5 Gate Packet

Status: `CANDIDATE / INDEPENDENT SOL AUDIT REQUIRED / REAL CALLS 0`

Issues: `#19 W4-EMBED-RUNTIME`, `#20 W4-PROVIDER-PREFLIGHT`

## Authorized scope

This candidate implements and tests the real-Embedding control seams without making an
external request. It does not authorize a real Provider call or claim a complete real
RAG path.

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

## Frozen invariants

- No request occurs before exact policy, manifest, confirmation and budget preflight.
- Unknown account plan, stale confirmation, export drift, budget failure or unknown
  acceptance fails closed.
- Raw `AGENT.md`, student identity, teacher notes, private snapshot data and credentials
  are never emitted through public DTOs or logs.
- Old snapshots remain immutable; a real build creates a new snapshot only.
- The Provider operation and product snapshot cannot report contradictory success.
- A worker, fake transport or local test cannot sign its own real-service Gate.

## Deterministic evidence

- backend full suite: `711 passed`;
- frontend: `32 files / 206 tests`, lint, TypeScript and production build passed;
- Ruff and mypy passed;
- frozen OpenAPI, generated client and strict live route comparison passed with `73`
  platform operations and zero placeholders;
- repository/secret boundary and generated-source red-team probe passed;
- migrations 0001–0012 and formal-content acceptance passed;
- real Provider calls: `0`.

## Known incomplete seams for Sol classification

1. Accepted vector staging is currently process-local; restart recovery is not yet a
   durable SQL product path.
2. The student publication API does not yet prepare the exact SnapshotBuild/export
   manifest and invoke this runtime end to end.
3. Retrieval does not yet use a real query embedding compatible with the published
   real document-vector snapshot.
4. No current private-account plan, region, logging, retention or no-training control
   has been verified; therefore no real request is authorized.

## G2 audit question

Sol High must return `PASS | CHANGES_REQUIRED` with P0/P1/P2 counts for this exact clean
SHA. A PASS on the foundation only permits the next local repair slice. W4-EMBED real
G3 requires all P0/P1 findings closed, a newly confirmed exact export manifest and a
separately recorded bounded call authorization.
