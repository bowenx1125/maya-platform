# Maya Platform Current Status

Last updated: 2026-08-31 (Asia/Shanghai)

## Current state

`WAVE_3_G3_PASS / W4_R0_PASS / W4_G0_SOL_PASS / PERSONA_MOCK_GATE_PASS / W4_MOCK_G2_SOL_PASS / W4_EMBED_G2_SOL_PASS / REAL_EMBED_1024_PREFLIGHT_FAILED / W4_LLM_A_G0_SOL_PASS / W4_LLM_A_G1_IN_PROGRESS`

The integrated local Wave 4 Mock candidate implements the versioned mutual-learning
protocol, confirmed Persona, claim-level Evidence Trace, strict PromptRequestV1,
formal content, Embedding/provider ports and durable provider-control foundations.
Mock G2 and subsequent Persona boundary audits closed every P0/P1. The user froze the
Persona Mock Gate at seven concrete criteria: stable PersonaSpec, six visible teaching
dimensions, required confirmation, correct freeze/hash/version, no unconfirmed
Debate/Provider, visibly different behavior for clearly different projections, and no
Evidence fabrication/raw private leakage. Exact SHA `48ff91f` received final Sol High
`PASS / P0=0 / P1=0 / P2=0`; arbitrary-string uniqueness optimization stopped. That
PASS unlocked W4-EMBED code and fake-transport acceptance, not a real request.

The W4-EMBED repair candidate now implements the frozen real 1024 identity end to end
through injected fake transport: durable multi-batch publication and continuation,
student publication orchestration, identity-matched query retrieval, exact per-turn
teacher disclosure/confirmation and non-terminal explicit retry. Current deterministic
evidence is backend `822`, frontend `34 files / 210 tests`, Ruff/mypy/lint/typecheck/build,
OpenAPI/generated/route/WS/repository boundaries and all populated Wave 1–4/0013
migration probes.

Sol High audited the prior exact candidate `9fabfb1` and returned
`CHANGES_REQUIRED / P0=0 / P1=2 / P2=1`: actual outbound document/query text needed an
explicit forbidden-data scan, the ordinary student publication error leaked a manifest
hash, and the pre-confirmation zero-reservation invariant needed a direct assertion. The
current clean repair candidate scans actual real-Embedding text before any export or
call, keeps unsafe input at zero manifest/operation/call, removes the hash from the
student error, adds a dedicated course-authorized teacher discovery page/DTO, and proves
`prepared / 0 requests / 0 charged / no reservation / no budget` before confirmation.
Sol High re-audited exact clean SHA `0c7c6e3` and returned
`PASS / P0=0 / P1=0 / P2=0`, unlocking only the one contracted safe 1024 preflight.
That single request returned HTTP 200 but the local adapter rejected the documented
native DashScope `output.embeddings` envelope because it incorrectly required a
response `model`; the preflight therefore ended
`REAL EMBEDDING 1024 PREFLIGHT FAILED` with safe code `embedding_model_mismatch`.
The request was not repeated. Official documentation confirms the native response uses
`text_index` and does not return `model`; commit `dbef20e` now isolates that exception
to the fixed DashScope-native dialect while generic/OpenAI-compatible responses still
require exact model. Incremental Sol then found one P1 conflict case where a correct
top-level model could mask a wrong `output.model`; commit `48da2a7` now validates both
locations independently and rejects every conflicting explicit declaration. Fake tests
cover the repair; Sol High returned `EMBED_DELTA PASS / P0=0 / P1=0 / P2=0` on exact
SHA `af0bd19`. The real preflight remains FAILED and cannot be retried. No CI run has
occurred.

W4-LLM-A G0-S began `CHANGES_REQUIRED / P1=6`; wire/schema, atomic publication, budget,
ownership, privacy and tokenizer contracts closed those findings. Re-audits closed
finish/usage, sentinel, retry and 1,510-Token reservation semantics, then found one P1:
repair feedback lacked a confirmed outbound class. The final candidate binds a finite
server-authored code/JSON-Pointer grammar and policy hash to the confirmed manifest.
Sol High returned `LLM_A_G0 PASS / P0=0 / P1=0 / P2=0` on exact SHA `4182d1a`.
Issues #22–#24 now own ledger/migration, adapter/output and turn runtime/disclosure fake
implementation. The PASS does not authorize a real LLM call.

## Source and remote

- Full development baseline: `a235c296239ab621bac615b2c9c5089528507850`
  (`feat: complete wave 3 pre-wave4 ux state gate`).
- Local protection tag: `pre-wave4-a235c29`.
- Verified complete bundle: `backups/pre-wave4-a235c29/maya-platform-a235c29.bundle`
  outside the repository; SHA-256 starts `553b852a1f51`.
- Canonical private repository: `bowenx1125/maya-platform`.
- Canonical remote `main` is at signed R0 closure SHA
  `48f6d7fda3aba988f705027669ba2db4c6358805`; deterministic CI run `33312476209`
  passed on that exact SHA.
- R0 Issue `#5` and PR `#6` record the Issue/worktree/owner/PR/audit trail.

## Signed Wave 3 evidence

- Backend: `433/433` tests at the signed candidate.
- Frontend: `28 files / 193 tests` at the signed candidate.
- Ruff, mypy, ESLint, TypeScript, Prettier and Next production build passed.
- OpenAPI generated client/response/route checks, WebSocket schemas, 0001–0007
  migrations, repository/secret boundary and Docker builds passed.
- Main-window browser G3 passed locale-only controls, waiting restoration, early/full
  Finish boundaries, manual-only Reconnect, localhost/LAN teacher control, two
  retained Replay cycles, anonymous interaction, Mock Maya report and Mock translation.

## Implemented product scope

- Demo authentication, quick login and one-course/two-group seed.
- Student Agent/version workflow, Markdown knowledge, immutable RAG snapshots,
  publishing, safe delete and teacher published-history inspection.
- Local 3D avatar rendering and Mock/real-safe voice boundaries.
- Versioned 2–5 Agent, 2–5 round mutual learning with opening/exchange/final phases,
  same-round isolation, pending questions, preserved disagreement and synthesis.
- Confirmed structured Persona with raw authorship retention, comparison UI and strict
  new-mutual-Debate eligibility while legacy Debate history remains compatible.
- Claim-level Evidence Trace with server IDs, exact UTF-16 speech spans, honest
  no-match/general-reasoning teaching UI and immutable Replay/history projection.
- Canonical two-message PromptRequestV1 with the complete RuleSet-visible speech set
  (all earlier-round public/final-ready speech for mutual learning), one Persona
  provider view, deduplicated evidence, bounded retry and hard pre-send budgets.
- Immutable SnapshotBuild/embedding adapter ports plus server-only policy, export,
  atomic budget and acceptance-unknown ledgers. Real selectors remain fail-closed.
- Independent anonymous vote/barrage, anonymous insight, Mock Maya report,
  history/download and on-demand Mock Chinese representation.

## Runtime and private state

- Docker containers are stopped.
- `data/` and `backend/data/` are absent.
- The next end-to-end acceptance must rebuild Agents, documents, snapshots and debates
  from an empty runtime root; historical browser data is not reusable evidence.
- Ignored `.env` and `backend/config/demo-accounts/accounts.private.md` are the only
  retained private runtime inputs and are mode `0600`.

## Provider state

- Real voice enrollment historically succeeded once.
- Real TTS attempts 1–3 failed; attempt 3 ended `tts_audio_invalid` and remains
  `FAILED-DEFERRED` until the Wave 4 TTS Gate fixes endpoint/language/diagnostic
  contracts before another request.
- Real LLM and Translation remain unavailable. The Embedding candidate now has a fixed
  runtime selector, no-redirect single-attempt transport, exact teacher disclosure and
  confirmation CAS, durable policy/export/budget/stage ledgers, atomic SQL Snapshot
  publication, restart-safe missing-batch continuation and identity-matched query
  retrieval exercised through injected fake transport. Independent audit of exact clean
  SHA `8be4833` returned
  `CHANGES_REQUIRED / P0=0 / P1=5 / P2=0`: the candidate still used dimension 256,
  accepted vectors were process-local, student publication did not enter the runtime,
  query retrieval remained Mock 256, and the teacher confirmation UI/authorization was
  not bound to the build's course. The current repair candidate claims closure of all
  five findings; exact SHA `0c7c6e3` later received Sol High PASS after all incremental
  repairs.
- An independent account-only preflight used non-student fixtures for one 256-dimension
  Embedding request and one structured LLM request. Both succeeded as basic API
  availability evidence while Maya's formal selectors stayed Mock. They are not Gate
  PASS evidence and must not be repeated. The formal real Embedding identity is now
  frozen at `dashscope / text-embedding-v4 / cn-beijing / 1024 / w4-embed-v1`.
- The one permitted 1024 preflight made exactly one three-text batch request. HTTP was
  200, but local response parsing failed closed as `embedding_model_mismatch`, so the
  only truthful status is `REAL EMBEDDING 1024 PREFLIGHT FAILED`. The call was not
  repeated; no vectors, cosine or PASS claim were retained. The official response-shape
  repair is fake-tested and awaiting incremental Sol review.
- Later real calls are authorized in principle by the user but still require the exact
  policy/export/budget Gate and must fail closed if the account plan or controls cannot
  be verified.

## Confirmed Wave 4 decisions

- Repository-root `PROJECT.md` becomes the only portable authority entry.
- Workers use `PROJECT_STATUS.md + Issue/Task Packet + named ADR/contracts + assigned
code`, not the full historical monolith.
- Every Wave 4 coding task uses an Issue, branch, independent worktree and owner;
  intermediate validation is local plus Sol High, with one final integrated PR/CI.
- New Agent versions keep raw `AGENT.md` and add an extraction-only Persona confirmed
  by a current group member before publication. The compiler cannot improve or invent.
- Context visibility is RuleSet-versioned. Mutual learning receives every
  public/final-ready earlier-round speech in full and exactly once while preserving a
  strict same-round barrier; legacy RuleSets retain their historical predecessor set.
- Evidence Trace records claim provenance; it is not a truth-verification claim.
- There is no numeric Token-reduction KPI and no teacher/operator cost-display task.
- Local, private GitHub, implementation, real Provider and potentially billed work are
  authorized, but implementation and calls still follow their Gate stop conditions.
- Engineering uses a debug/test loop until the frozen criteria pass; tests and product
  boundaries are not weakened.

## Active risks

1. The old continuity monolith contains superseded current-looking statements; it is
   archived and must not be a default task input.
2. Claim-level evidence proves lineage, not factual correctness.
3. Real Provider policy/account/logging controls have not been verified against the
   current private account. The single 1024 preflight allowance is exhausted, so no
   further real Embedding call is permitted by the current Gate.
4. TTS is still a hard blocker for complete real-service G5.

## Next Gate

Do not repeat the exhausted 1024 preflight. Complete Issues #22–#24 through Luna local
fake-transport implementation, main-window integration and exact-SHA Sol G2 audit.
W4-EMBED remains unsigned because the real preflight and empty-runtime browser
publication/query/retrieval/Evidence/restart chain have not passed. GitHub CI remains
deferred to the final integrated Wave 4 PR.
