# Maya Platform Current Status

Last updated: 2026-08-31 (Asia/Shanghai)

## Current state

`WAVE_3_G3_PASS / W4_R0_PASS / W4_G0_SOL_PASS / PERSONA_MOCK_GATE_PASS / W4_MOCK_G2_SOL_PASS / W4_EMBED_G1_5_REPAIR_CANDIDATE / G2_REAUDIT_PENDING / REAL_EMBED_1024_NOT_RUN`

The integrated local Wave 4 Mock candidate implements the versioned mutual-learning
protocol, confirmed Persona, claim-level Evidence Trace, strict PromptRequestV1,
formal content, Embedding/provider ports and durable provider-control foundations.
Independent Mock G2 audit of `2af97df` returned `CHANGES_REQUIRED` with
`P0=0 / P1=5 / P2=0`. All five Mock repairs passed local checks. The exact-SHA re-audit of
`1aa7170` verified those repairs but found two additional P1 boundary cases: bounded
Persona fields could overrun the 200-word Mock turn limit, and incomplete running
legacy Debates could still reach generation without confirmed Persona. Both incremental
P1 repairs passed the full local matrix. The exact-SHA audit of `cd2c5b5` verified the
legacy-generation fix but found two further Persona projection P1s: mid-field
differences could collide, and legal source-shaped Persona wording could enter speech
as an unsupported attribution. The audit of `8e83c01` verified source safety but showed
that bounded free-text sampling cannot honestly promise a unique speech for every
possible raw difference. The user then froze the Persona Mock Gate at seven concrete
criteria: stable PersonaSpec, visible six dimensions, required confirmation, correct
freeze/hash/version, no unconfirmed Debate/Provider, visibly different behavior for
clearly different projections, and no Evidence fabrication/raw private leakage. The
current implementation satisfies all seven, so Persona Mock is PASS and further
arbitrary-string uniqueness optimization has stopped. Final Sol High audit of exact
clean SHA `48ff91f` returned `PASS / P0=0 / P1=0 / P2=0`. This unlocks W4-EMBED code
and fake-transport acceptance, not an automatic real request. No formal Maya runtime
Provider request has been made.

The W4-EMBED repair candidate now implements the frozen real 1024 identity end to end
through injected fake transport: durable multi-batch publication and continuation,
student publication orchestration, identity-matched query retrieval, exact per-turn
teacher disclosure/confirmation and non-terminal explicit retry. Current deterministic
evidence is backend `812`, frontend `34 files / 210 tests`, Ruff/mypy/lint/typecheck/build,
OpenAPI/generated/route/WS/repository boundaries and all populated Wave 1–4/0013
migration probes. It has not called a real Provider and cannot run the one permitted
1024 preflight until a new exact clean SHA receives Sol High `P0=0 / P1=0`.

Sol High audited the prior exact candidate `9fabfb1` and returned
`CHANGES_REQUIRED / P0=0 / P1=2 / P2=1`: actual outbound document/query text needed an
explicit forbidden-data scan, the ordinary student publication error leaked a manifest
hash, and the pre-confirmation zero-reservation invariant needed a direct assertion. The
current clean repair candidate scans actual real-Embedding text before any export or
call, keeps unsafe input at zero manifest/operation/call, removes the hash from the
student error, adds a dedicated course-authorized teacher discovery page/DTO, and proves
`prepared / 0 requests / 0 charged / no reservation / no budget` before confirmation.
This repair is awaiting exact-SHA Sol re-audit; no formal runtime request or CI run has
occurred.

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
- Real LLM and Translation remain unavailable. The Embedding candidate now has a fixed
  runtime selector, no-redirect single-attempt transport, exact teacher disclosure and
  confirmation CAS, durable policy/export/budget/stage ledgers, atomic SQL Snapshot
  publication, restart-safe missing-batch continuation and identity-matched query
  retrieval exercised only through injected fake transport. It has made zero formal
  Maya runtime calls. Independent audit of exact clean SHA `8be4833` returned
  `CHANGES_REQUIRED / P0=0 / P1=5 / P2=0`: the candidate still used dimension 256,
  accepted vectors were process-local, student publication did not enter the runtime,
  query retrieval remained Mock 256, and the teacher confirmation UI/authorization was
  not bound to the build's course. The current repair candidate claims closure of all
  five findings, but Real Embedding remains unsigned pending exact-SHA re-audit.
- An independent account-only preflight used non-student fixtures for one 256-dimension
  Embedding request and one structured LLM request. Both succeeded as basic API
  availability evidence while Maya's formal selectors stayed Mock. They are not Gate
  PASS evidence and must not be repeated. The formal real Embedding identity is now
  frozen at `dashscope / text-embedding-v4 / cn-beijing / 1024 / w4-embed-v1`; its
  preflight has not run.
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

Submit the exact clean W4-EMBED repair SHA to independent Sol High. Any P0/P1 returns to
the local debug/test loop. Only `PASS / P0=0 / P1=0` unlocks the one safe 3-text 1024
preflight. A successful preflight still does not sign W4-EMBED; empty-runtime browser G3
publication, exact teacher confirmation, query retrieval, Evidence receipt and restart
must also pass. GitHub CI remains deferred to the final integrated Wave 4 PR.
