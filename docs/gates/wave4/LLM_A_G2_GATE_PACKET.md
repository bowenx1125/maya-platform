# W4-LLM-A G2 Gate Packet

Status: `LLM RECOVERY DEMO GATE PASS / P0=0 / P1=0 / REAL LLM CALLS 0 / CI DEFERRED`

Issues: `#22 ledger/migration`, `#23 adapter/output/privacy`, `#24 runtime/disclosure`,
`#25 teacher turn approval page`.

## Candidate scope

This candidate implements the frozen W4-LLM-A contract with fake transports only:

- migrations `0014_llm_runtime_budget_buckets` and `0015_llm_recovery_input` preserve
  existing history, isolate
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
- authoritative course-member identity tokens are scanned before manifest persistence
  and immediately before send; fictional/cultural Agent names remain an intentional
  Persona field and are not misclassified as student identity;
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

## Signed incremental evidence

- implementation audit source:
  `63b1e865e16e45912863e307be398abe285ec2eb` (clean);
- equivalent main-window integration before the status-signing commit:
  `debbf8ef3d0df2f20013e9bd44e48d3eb1c2ceb0`;
- Sol High: `PASS / P0=0 / P1=0 / P2=0`;
- real SQL/Playback publication failure rolls back Turn/source/file writes while the
  operation and reservation remain accepted;
- restart continuation completes with LLM call delta `0`;
- non-zero cancellation generation `7` is bound through accepted recovery and final
  publication;
- legacy accepted output without a recovery input remains nonterminal and blocked;
  wider legacy/corruption recovery is Post-Demo Hardening.

## Mechanical evidence

- backend: `925` tests passed;
- frontend: `35 files / 214 tests` passed;
- Ruff and mypy (`159` application files) passed;
- ESLint, TypeScript and Next production build passed;
- migrations 0001–0015 and populated preservation probes passed;
- frozen OpenAPI/generated client/response/route checks passed with `77` operations;
- WebSocket schemas/fixtures, document authority, Docker Compose validation and
  repository/secret-boundary red-team probes passed;
- real LLM Provider calls: `0`; GitHub CI runs: `0`.

## Audit boundary

The frozen Real-Core audit boundary is satisfied. This PASS covers one accepted-stage
restart without a repeated LLM call and one atomic SQL publication/rollback path. It
does not certify distributed workers, arbitrary ledger repair, repeated restart matrices
or a generic recovery framework; those are Wave 4.1 Post-Demo Hardening. No real LLM
request or CI was used to sign this Gate.
