# Maya Platform Current Status

Last updated: 2026-08-31 (Asia/Shanghai)

## Current state

`WAVE_3_G3_PASS / W4_R0_PASS / W4_G0_SOL_PASS / PERSONA_MOCK_GATE_PASS / W4_MOCK_G2_SOL_PASS / W4_EMBED_G2_SOL_PASS / LLM_RECOVERY_DEMO_GATE_PASS / REAL_CORE_DEMO_IN_PROGRESS`

The current target is the smallest repeatable Real-Core Demo, not production-wide
Provider recovery. Every new task is classified before work starts:

- `DEMO-BLOCKER`: directly required by the Real-Core acceptance chain;
- `POST-DEMO-HARDENING`: recorded for Wave 4.1 and forbidden from blocking Demo V1.

The Demo may combine Real Embedding and Real LLM with Mock TTS, Voice, Translation and
Report. Product UI and delivery evidence must identify each component as Real or Mock.

## Last signed module evidence

### Persona and Mock teaching chain

- Persona Mock Gate is frozen PASS at exact SHA `48ff91f`.
- `AGENT.md -> PersonaSpecV1` is deterministic; all six teaching dimensions are visible.
- Student confirmation freezes canonical JSON/hash/version. Unconfirmed Persona cannot
  enter a new Debate or Provider request.
- Distinct Persona projections produce explainable Mock behavior changes without raw
  private-text leakage or fabricated Evidence.
- Mutual learning supports 2–5 Agents and 2–5 rounds with opening/exchange/final phases,
  same-round isolation, full earlier-round speech and claim-level Evidence Trace.

### Embedding implementation

- Fake-transport W4-EMBED G2 received Sol High PASS at exact SHA `0c7c6e3`.
- The response-dialect delta received incremental Sol PASS at `af0bd19`.
- Frozen real identity is `dashscope / text-embedding-v4 / cn-beijing / 1024 /
  w4-embed-v1`.
- Product code has exact teacher manifest/confirmation, 1024 request validation,
  immutable Snapshot publication, restart-safe batch continuation and identity-matched
  real query retrieval.
- Real product E2E has not passed. The historical one-call 1024 preflight returned HTTP
  200 but failed the then-current local response contract; it was not repeated.

### LLM Recovery Demo Gate

- Implementation audit source: clean SHA
  `63b1e865e16e45912863e307be398abe285ec2eb`.
- Equivalent main-window integration before this status update:
  `debbf8ef3d0df2f20013e9bd44e48d3eb1c2ceb0`.
- Sol High incremental result: `PASS / P0=0 / P1=0 / P2=0`.
- Backend: `925 passed`; focused P1 product/recovery: `50 passed` in Sol audit.
- Frontend: `35 files / 214 tests`; typecheck, lint and production build passed.
- Ruff passed; mypy passed for `159` application files.
- Provider policy fixture, real SQL/Playback rollback, restart continuation with LLM
  call delta `0`, and non-zero cancellation generation `7` all passed.
- Accepted stage + canonical recovery input persist before TTS. Final Turn, receipts,
  Evidence, job, audio metadata and operation/reservation success share one SQL Session.
  Publication failure rolls back SQL and removes audio.
- No real LLM request and no GitHub CI were used for this Gate.

This is `LLM Recovery Demo Gate = PASS`, not a claim of distributed or corruption-proof
production recovery. Excluded work is in
[Wave 4.1 Post-Demo Hardening](docs/requirements/WAVE_4_1_POST_DEMO_HARDENING.md).

## Real-Core Demo completion state

| Acceptance slice | Current result |
| --- | --- |
| New environment starts | Not yet re-accepted from an empty runtime root |
| Real Embedding 1024 product E2E | Offline Gate PASS; formal two-call product run not complete |
| Real LLM two-round product E2E | Not complete |
| 2–3 confirmed Agents complete two rounds | Not complete with real core Providers |
| Chinese real RAG hit and Evidence Receipt | Not complete |
| Teacher export confirmation and budget enforcement | Fake-tested; not yet accepted in real E2E |
| Accepted-after-restart avoids a second LLM charge | Fake product path PASS; real Demo scenario pending |
| Browser create-to-Replay chain | Not complete for Real-Core candidate |
| Demo package and Real/Mock disclosure | Not complete |

## Real call ledger

Calls made after the Real-Core Demo scope reset in this status: `0`.

Known historical bounded evidence, which is not the Real-Core product E2E:

- Embedding: one 256-dimension availability request passed; one formal 1024 request
  returned HTTP 200 and failed the old local response contract.
- LLM: one account-only structured availability request passed.
- TTS: three failed attempts; no new TTS call is authorized by the Real-Core Demo.
- Voice: one historical enrollment succeeded.

The earlier preflight allowances remain exhausted and will not be repeated. The user's
new authorization is for the exact confirmed, budgeted product E2E path, using a fixed
Demo fixture and the minimum necessary calls. Any identity, policy, budget, confirmation,
response or publication mismatch fails closed before another call.

## Minimum remaining Demo blockers

1. `DEMO-BLOCKER — REAL-EMBED-E2E`: the offline implementation Gate is PASS at exact
   SHA `e6d6c2780723dfeae33db953ea8c49edd37c8901`, with Sol High
   `P0=0 / P1=0 / P2=0`, backend `925 passed`, reviewed-policy importer, fixed Chinese
   one-chunk fixture, product driver and confirmed-Persona Chinese query path. Before the
   formal two-call run, verify the account-side policy controls and import the exact
   reviewed non-secret policy into a new runtime. Then execute one 1024 Snapshot request,
   one Chinese query request and stopped-database Evidence verification.
2. `DEMO-BLOCKER — REAL-LLM-E2E`: 2–3 confirmed Agents, their own RAG, PromptRequestV1,
   fixed Qwen structured output and complete two-round Evidence Trace.
3. `DEMO-BLOCKER — BROWSER-E2E`: empty-runtime student Agent/Persona/knowledge/publish,
   teacher Debate/playback/finish, interaction/history/Replay.
4. `DEMO-BLOCKER — DEMO-PACKAGE`: fixed Agent/RAG/topic assets, one startup entry,
   reset and failure-recovery instructions, plus visible Real/Mock disclosure.
5. One final integrated GitHub PR/CI on the exact locally accepted SHA.

## Post-Demo Hardening

The following cannot block Demo V1 and must not be started while Demo blockers remain:

- recovery of every legacy schema and arbitrary corrupt ledger;
- repeated/multi-process/distributed restart matrices;
- administrator recovery consoles and a generic multi-Provider recovery framework;
- public deployment, production classroom identity/security, 30–60-user load,
  monitoring, backup/restore, DeepL, production TTS, licensing and data-governance work.

See [Wave 4.1 Post-Demo Hardening](docs/requirements/WAVE_4_1_POST_DEMO_HARDENING.md).

## Source, runtime and safety

- Canonical private repository: `bowenx1125/maya-platform`.
- The last remote CI evidence remains the R0 run on `48f6d7f`; no intermediate Wave 4
  branch has been pushed and GitHub CI remains deferred to the final integrated PR.
- The integration worktree has no runtime data. A separate pre-existing local stack owns
  port 8080 and must not be stopped or reused. Real-Core acceptance must use an isolated
  port and empty runtime root, then build new Agents, documents, snapshots and Debates.
- Ignored `.env` and the private Demo account file remain mode `0600`; their contents,
  credentials, raw Provider responses and student-private data must never be reported.
- Real TTS, Voice, Translation and Report remain Mock for Demo V1.

## Next Gate

Verify the reviewed account policy, then execute `REAL-EMBED-E2E` only through the
product path. It is a newly authorized formal Demo publication, not a repeat of the
exhausted preflight. Use the fixed Chinese fixture, exact teacher manifest/confirmation,
the two-call cap and fail-closed call ledger.
After it passes, proceed immediately to `REAL-LLM-E2E`, then browser E2E and Demo package.
The active packet is
[Real-Core Demo Gate](docs/gates/wave4/REAL_CORE_DEMO_GATE.md).
