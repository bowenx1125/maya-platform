# W4-LLM-A G2 Gate Packet

Status: `G2 SOL AUDIT CANDIDATE / REAL LLM CALLS 0 / CI DEFERRED`

Issues: `#22 ledger/migration`, `#23 adapter/output/privacy`, `#24 runtime/disclosure`,
`#25 teacher turn approval page`.

## Candidate scope

This candidate implements the frozen W4-LLM-A contract with fake transports only:

- migration `0014_llm_runtime_budget_buckets` preserves 0001–0013 history, isolates
  non-transferable budget buckets, binds manifests to Debate/Turn owners and persists
  immutable accepted LLM output/usage stages;
- only `llm_debate_turn` can authorize a new call; legacy `llm_debate` remains readable
  for historical disclosure but fails every new preflight;
- the adapter requires the reviewed model, Beijing endpoint, tokenizer asset, price
  card, exact two-message prompt, output schema, field allowlist and repair policy;
- accepted bytes and safe diagnostics are staged before local schema/reference mapping;
- attempt 2 is bounded by the confirmed manifest and is only a frozen proven-not-sent
  retry or a minimal structure-repair request; acceptance-unknown is never retried;
- the runtime keeps pre-confirmation work at zero use, re-enters the exact prepared
  operation after confirmation, and atomically publishes Turn, Evidence Trace, usage and
  operation success;
- startup recovery has no transport and touches only the LLM budget bucket;
- authoritative course/member and Agent names are scanned before manifest persistence
  and immediately before send;
- the teacher page discovers exact turn manifests through Debate -> Course ownership
  using a compact DTO. Students, other-course users and missing Debates receive stable
  403/404 behavior without Provider details.

## Direct acceptance evidence

- 2 Agents x 2 rounds completes four fake turns and stages/publishes each one;
- stale or missing confirmation creates no reservation and makes zero adapter calls;
- a confirmed retry reuses the exact prepared zero-use operation;
- proven-not-sent gets at most one frozen second attempt; acceptance-unknown gets none;
- accepted restart resumes from the immutable local stage with zero Provider calls;
- publication failure rolls back Turn and operation success together;
- the ninth attempt in the 2x2 fixture is rejected before the adapter;
- identity tokens in every Provider-visible prompt field fail before manifest/operation;
- structure failure stages safe metadata and may repair once without repeating retrieval;
- old Debate, Replay, Mock Persona, Evidence Trace and Embedding behavior remain green.

## Mechanical evidence

- backend: `874` tests passed;
- frontend: `35 files / 214 tests` passed;
- Ruff and mypy (`157` application files) passed;
- ESLint, TypeScript and Next production build passed;
- migrations 0001–0014, populated preservation and downgrade/re-upgrade probes passed;
- frozen OpenAPI/generated client/response/route checks passed with `77` operations;
- WebSocket schemas/fixtures, document authority, Docker Compose validation and
  repository/secret-boundary red-team probes passed;
- real LLM Provider calls: `0`; GitHub CI runs: `0`.

## Audit boundary

Sol High must review the exact clean integration SHA, run adversarial zero-call,
ownership, retry, stage/recovery, atomicity, usage/cost and privacy probes, and return
`P0=0 / P1=0` before G2 can pass. This packet cannot approve its own implementation.
No real LLM request is authorized or required for G2/G3; the historical availability
preflight is non-repeatable.
