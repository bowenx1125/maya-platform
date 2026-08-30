# Maya Platform Current Status

Last updated: 2026-08-30 (Asia/Shanghai)

## Current state

`WAVE_3_G3_PASS / READY_FOR_WAVE_4 / W4_R0_G1.5_PASS / SOL_R0_AUDIT_PENDING / WAVE_4_PRODUCT_CODE_NOT_STARTED`

Wave 4 R0 is a documentation, repository and workflow Gate. It does not implement
Persona, Evidence Trace, Prompt changes or a real Provider.

## Source and remote

- Full development baseline: `a235c296239ab621bac615b2c9c5089528507850`
  (`feat: complete wave 3 pre-wave4 ux state gate`).
- Local protection tag: `pre-wave4-a235c29`.
- Verified complete bundle: `backups/pre-wave4-a235c29/maya-platform-a235c29.bundle`
  outside the repository; SHA-256 starts `553b852a1f51`.
- Canonical private repository candidate: `bowenx1125/maya-platform`.
- The old runtime-only remote main `2fd80784bd79c88261eb2319a961b5c659b9e687`
  is preserved as branch and tag `runtime-handoff-20260830`.
- The full baseline is available on remote branch `dev-main`; remote main has not yet
  been replaced.
- Active R0 Issue: `#5 W4-R0: canonical docs and reproducible development workflow`.
- Active branch/worktree: `w4/r0/05-doc-workflow` in `maya-wt-r0-05`.
- Active PR: `#6 W4-R0: establish portable project authority`, targeting `dev-main`.
- The exact R0 candidate identity is the PR head SHA reported by Git/GitHub/CI. It is
  intentionally not duplicated inside the candidate commit because a commit cannot
  contain its own final SHA. `a235c29` remains the last signed product baseline until
  R0 passes CI, Sol High and main-window integration.

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
- Two-round 2–5 Agent debate setup, honest Mock RAG hit/no-hit, closed structured turn
  output and teacher-paced playback/recovery/Replay.
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
- Real LLM, Embedding and Translation implementations remain fail-closed/Mock-only.
- No R0 action may call a real Provider. Later real calls are authorized in principle
  by the user but still require the corresponding frozen Gate before the first request.

## Confirmed Wave 4 decisions

- Repository-root `PROJECT.md` becomes the only portable authority entry.
- Workers use `PROJECT_STATUS.md + Issue/Task Packet + named ADR/contracts + assigned
code`, not the full historical monolith.
- Every Wave 4 coding task uses an Issue, branch, independent worktree, owner, PR, CI,
  independent Sol High audit and main-window integration.
- New Agent versions keep raw `AGENT.md` and add an extraction-only Persona confirmed
  by a current group member before publication. The compiler cannot improve or invent.
- Every debate turn continues to receive the complete text of all previous turns.
- Evidence Trace records claim provenance; it is not a truth-verification claim.
- There is no numeric Token-reduction KPI and no teacher/operator cost-display task.
- Local, private GitHub, implementation, real Provider and potentially billed work are
  authorized, but implementation and calls still follow their Gate stop conditions.
- Engineering uses a debug/test loop until the frozen criteria pass; tests and product
  boundaries are not weakened.

## Active risks

1. The runtime-only remote tree is not a reproducible development branch until R0 is
   merged and CI runs on the full source SHA.
2. The old continuity monolith contains superseded current-looking statements; it is
   archived and must not be a default task input.
3. Persona extraction from arbitrary Markdown needs an explicit closed contract; it
   cannot silently infer or improve student intent.
4. Claim-level evidence can prove lineage, not factual correctness.
5. TTS is still a hard blocker for complete real-service G5.

## Next Gate

Keep PR #6 open while its exact head passes private CI and independent Sol High review.
Fix findings on the same branch and rerun the affected/full checks. Merge into
`dev-main` only after `P0=0 / P1=0`, verify CI on the resulting merge SHA, and then move
the canonical remote development main. After R0 is signed, draft Wave 4 G0 contracts
for PersonaSpecV1, EvidenceTraceV1, complete-history Prompt request assembly, formal
content, Provider data/call limits and failure semantics.
