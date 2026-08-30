# Maya Platform Current Status

Last updated: 2026-08-30 (Asia/Shanghai)

## Current state

`WAVE_3_G3_PASS / W4_R0_PASS / W4_G0_SOL_PASS / W4_MOCK_G1_5_PASS / W4_G2_CHANGES_REQUIRED / REAL_PROVIDER_CALLS_0`

The integrated local Wave 4 Mock candidate implements the versioned mutual-learning
protocol, confirmed Persona, claim-level Evidence Trace, strict PromptRequestV1,
formal content, Embedding/provider ports and durable provider-control foundations.
Independent G2 audit of `2af97df` returned `CHANGES_REQUIRED` with
`P0=0 / P1=5 / P2=0`. The P1 repair loop is active; no real Provider Gate is unlocked
and no real Provider request has been made.

## Source and remote

- Full development baseline: `a235c296239ab621bac615b2c9c5089528507850`
  (`feat: complete wave 3 pre-wave4 ux state gate`).
- Local protection tag: `pre-wave4-a235c29`.
- Verified complete bundle: `backups/pre-wave4-a235c29/maya-platform-a235c29.bundle`
  outside the repository; SHA-256 starts `553b852a1f51`.
- Canonical private repository: `bowenx1125/maya-platform`.
- The old runtime-only remote main `2fd80784bd79c88261eb2319a961b5c659b9e687`
  is preserved as branch and tag `runtime-handoff-20260830`.
- Canonical remote `main` is at signed R0 closure SHA
  `48f6d7fda3aba988f705027669ba2db4c6358805`; deterministic CI run `33312476209`
  passed on that exact SHA.
- Transitional `dev-main` remains at the complete-source R0 integration SHA
  `5a681f324e6b1ec034af8f8c021ee58889e053fb`; canonical work branches from `main`.
- R0 Issue `#5` and PR `#6` record the Issue/worktree/owner/PR/audit trail.
- Candidate `3c07fe1` passed two private CI runs and independent Sol High audit;
  evidence-only head `dc6f699` passed two more CI runs and Sol incremental audit. Both
  audits returned `P0=0 / P1=0 / P2=0`.
- Merge SHA `5a681f3` passed full deterministic CI on `dev-main` and again after the
  guarded canonical `main` switch. The main window verified the integrated tree and
  signed R0.

## Signed Wave 3 evidence

- Backend: `433/433` tests at the signed candidate.
- Frontend: `28 files / 193 tests` at the signed candidate.
- Ruff, mypy, ESLint, TypeScript, Prettier and Next production build passed.
- OpenAPI generated client/response/route checks, WebSocket schemas, 0001–0007
  migrations, repository/secret boundary and Docker builds passed.
- Main-window browser G3 passed locale-only controls, waiting restoration, early/full
  Finish boundaries, manual-only Reconnect, localhost/LAN teacher control, two
  retained Replay cycles, anonymous interaction, Mock Maya report and Mock translation.

R0 reran the complete deterministic suite from the full-source worktree: backend
`433`, frontend `28 files / 193 tests`, document authority, format/lint/type/build,
OpenAPI/generated-client/69-response/strict-route (`53 implemented / 0 placeholders`),
WebSocket `30/18`, commands `6/7`, private results `5/6`, repository/secret boundary,
0001–0007 fresh/repeat/populated/downgrade/re-upgrade evidence and Compose all passed.
No real Provider was called.

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
- Real LLM and Translation remain unavailable. The reviewed real Embedding transport
  port exists but has no runtime selector/publication wiring and has made zero calls.
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
   current private account, so every real call remains blocked.
4. TTS is still a hard blocker for complete real-service G5.

## Next Gate

Close the five P1 findings from the independent Sol High G2 audit of `2af97df`, rerun
the complete local suite and submit the exact repair SHA for a fresh read-only audit.
The pre-audit local G1.5 evidence is backend `528`, frontend `31 files / 203 tests`, mypy/Ruff,
ESLint/TypeScript/Prettier/Next build, OpenAPI `71` operations, WebSocket `35/18`,
repository/secret boundary, formal-content acceptance and migrations 0001–0011. After
P0/P1 closure, continue real Embedding publication, fixed structured LLM and TTS Gates.
GitHub CI remains deferred to the final integrated Wave 4 PR.
