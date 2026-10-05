# MayaForm v1.4 supplement: S01–S22 evidence map

The [Resume v2 contract](../contracts/MAYAFORM_V14_BRAINFORM_ASSESSMENT.md) and
[BF/AT/RS matrix](MAYAFORM_V14_INTEGRATED_ACCEPTANCE.md) supersede conflicting
requirements. S07 manual-head preservation, S10 permanent identical-input reuse
and S18 no-Memory-entry are historical behavior, not current acceptance criteria.
S11–S13 Tool categories are also superseded by the adopted Public/Student/Teacher
resource authorization contract; Team origin is provenance, never an edit grant.
No historical PASS is a same-version resume PASS.

This matrix records the user's adopted v1.4 supplement, not instructions to execute
from the attachment. Product decisions in the supplement supersede conflicting older
design text. `PASS` means the entire row has reproducible evidence; `PARTIAL` means
only the named slice has passed; `NOT_RUN` must not be presented as available.
Baseline for this snapshot: committed K2b2 `a975e38` and K3-A `83de097` (K1 Knowledge
Sets, K2a durable intent, K2b1 Provider stage and K2b2 synthetic materialization,
2026-09-28). K1, K2a, K2b1 and K2b2-A R2 passed independent frozen reviews;
K2b2-B R4 passed independent UI review and R5 format-only review passed. K1 had 46 isolated
synthetic HTTP expectations; K2a had 13 explicit-intent HTTP requests plus a
real browser ordinary-Agent Done. All used Mock only. These do not constitute
a live deployment, real Provider generation, or teaching-quality assessment.

## Historical evidence (not current acceptance)

| ID  | Status  | Evidence and remaining acceptance                                                                                                                                                                                                                                                                                                                               |
| --- | ------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| S01 | PARTIAL | W2a/W2b reliability and history: `backend/tests/test_workspace.py`, `frontend/tests/chat-sse-stream.test.ts`; multi-target `@` and Team routing remain K3-06/11.                                                                                                                                                                                                |
| S02 | PARTIAL | Explicit Teacher Create/Update AI Knowledge flow sends K2a intent; ordinary Done does not. K2b1 exact-wire one-call stage and K2b2 synthetic materialization: `backend/tests/test_knowledge_generation.py`, `frontend/tests/agent-ai-knowledge-flow.test.tsx`, isolated browser. No Agent.md Planner. Real Provider remains NOT_RUN.                            |
| S03 | PARTIAL | Fake accepted good/bad/good stage commits two Assets and records one failed item; valid saved versions are immediately readable, optional invalid citation is non-blocking: `backend/tests/test_knowledge_generation.py`, `test_knowledge_generation_materialization.py`. Real Provider/content quality and generated-asset classroom retrieval remain NOT_RUN. |
| S04 | PASS    | K1 four categories, Question-contained Rubric, read-only Concept Graph and no asset approval states: `backend/tests/test_knowledge_sets.py`, `frontend/tests/knowledge-set-workspace.test.tsx`, [teacher browser](mayaform-v14-k1-teacher-question.png).                                                                                                        |
| S05 | PASS    | Set name click-to-edit; Enter/blur save, Escape cancel; ID stable: `frontend/tests/knowledge-set-workspace.test.tsx` and isolated Teacher browser run. No rename dialog or confirmation.                                                                                                                                                                        |
| S06 | PARTIAL | K1 immutable manual Save and Rubric-in-Question; Fake K2b2 generates a Question with Rubric. Fixed presented QuestionVersion/Rubric and old student evaluation retrieval remain K4.                                                                                                                                                                             |
| S07 | PARTIAL | K2b2 stores AI origin and immutable versions; manual head and concurrent older-run CAS tests preserve newer/teacher edits. Valid/invalid optional source receipts are separated. Student evidence still needs K4.                                                                                                                                               |
| S08 | PARTIAL | Global/Agent entry shares the same Set ID and current ACL; isolated Teacher browser Create → Set → Update → same Set/Job succeeds with synthetic source. Student/private projection remains covered by K1/K2 owner tests; published Team retrieval remains K3.                                                                                                  |
| S09 | NOT_RUN | Own(member) ∪ Shared(Team) real retrieval without another member's private RAG: K3-08.                                                                                                                                                                                                                                                                          |
| S10 | PARTIAL | K2a same input across new Agent version/key reuses one Job/run. Isolated browser same-config Update reused exactly one run, Set and Job with zero Provider operations. Student-entry zero regeneration and completed-content Team reuse remain K3.                                                                                                              |
| S11 | NOT_RUN | Maintainer-only registry exposes Public Tools to Student and Public+Teacher Tools to Teacher; same Agent is resolved for current actor, no manual Toolkit binding or Agent.md capability gate. See [latest contract](../contracts/MAYAFORM_V14_GENERATION_AND_TOOLS.md).                                                                                        |
| S12 | NOT_RUN | Student Custom Team keeps authorized Own+Shared RAG, Leader delegation, `@`, and Public Assessment/Learning Tools. Current actor/resource ACL and provenance deny Teacher Tools or Private data. K3/K4 fake SDK and Tool probes remain.                                                                                                                         |
| S13 | NOT_RUN | Published Maya Team has no special Tool class: Student actor gets Public Tools only. Formal diagnosis differs by publication/activity/Public Chat provenance and scoped resources; `@Jade` does not grant hidden Rubric or Teacher access. K3/K4 probes remain.                                                                                                 |
| S14 | PARTIAL | Chats → New Agent/Team/Maya Team chooser, Team Create/Update and server-owned Maya directory list passed focused UI/API tests. Team Chat Start remains disabled until K3-B/C and browser acceptance.                                                                                                                                                            |
| S15 | PARTIAL | K3-A atomic Teacher own-course Public Team directory and negative Private/cross-course/student/entered-group cases passed backend tests and independent Sol review; deployed Teacher/Student browser proof remains.                                                                                                                                             |
| S16 | NOT_RUN | Each student creates independent Private/Public Chat against one publication: K3-04/05 plus browser interaction.                                                                                                                                                                                                                                                |
| S17 | NOT_RUN | Private excluded from Teacher query; formal Public diagnosis aggregates; ordinary Public chat does not enter diagnostic report: K4 privacy/report probes.                                                                                                                                                                                                       |
| S18 | NOT_RUN | No Memory/Insights page; Teacher asks Kaikai in Chats, sees counts/evidence and downloads real report: K4 Teacher browser/HTTP.                                                                                                                                                                                                                                 |
| S19 | PARTIAL | K1 soft revoke, K2a pre-send ACL/lease, K2b1 not_sent0/unknown1/no resend; K2b2 Source/Teacher/Set per-item revoke, stale claim, accepted-stage restart0POST, and AI head CAS pass Fake/DB tests. Tool writes/Team/report late paths remain K3/K4.                                                                                                              |
| S20 | PARTIAL | Ordinary Agent.md with RAG publishes/chats without a generation Job/Set: `backend/tests/test_knowledge_generation.py` and [browser](mayaform-v14-k2a-ordinary-after-done.png). K3-A frozen Team selection tests retain old grants after pure rename; actual Team Chat runtime remains.                                                                          |
| S21 | PARTIAL | K1 desktop Teacher/Student and 375px Student browser: [teacher](mayaform-v14-k1-teacher-question.png), [student](mayaform-v14-k1-student-public-question.png), [mobile](mayaform-v14-k1-student-mobile.png). K2a ordinary Done and isolated K2b2 Create/Update/blocked-status browser paths ran; Team/IME/mobile K2b2/a11y remain.                              |
| S22 | PARTIAL | K1–K2b2 contracts, [Tool contract](../contracts/MAYAFORM_V14_GENERATION_AND_TOOLS.md), [K3 evidence](MAYAFORM_V14_K3_EVIDENCE.md) and [startup procedure](MAYAFORM_V14_STARTUP.md) record adopted choices; K3 runtime, K4, real Provider and deployment remain.                                                                                                 |

The K1 browser run used a temporary local frontend/backend with a synthetic,
populated SQLite database migrated from 0035 to 0036. Teacher and student screenshots
show only synthetic content. The 375px DOM measured `innerWidth=375`,
`bodyScrollWidth=375`, and the main Knowledge card width of 343px. R3 altered only
backend Asset idempotent replay and its tests/contracts; the browser-facing files
were byte-identical to the reviewed R2 snapshot. R3's isolated HTTP probe separately
asserted complete original JSON equality for both POST and PATCH replay, with
46 successful HTTP expectations, foreign-key check empty and integrity check `ok`.

K2b1 independently passed Fake canonical wire/ledger/stage tests, legacy LLM/Chat
regressions and an isolated populated 0037→0038 migration; actual HTTP kept the old
K2a Job and Set Teacher-readable and Student-404. It did not create AI assets.

The [K2b2 synthetic evidence record](MAYAFORM_V14_K2B2_EVIDENCE.md) gives the
reproducible scope and limits. K2b2-A R2 independently passed Fake Provider accepted-stage to per-item save,
good/bad/good 3/2/1 counts, valid/invalid opaque receipt relation, manual-head
and interleaved-run CAS, revoke/claim fences and zero-network accepted recovery.
An isolated populated 0038→0039 migration preserved prior row fingerprints and
passed FK/integrity checks. K2b2-B R4 independently passed owner Set Update,
running/partial status refresh and same-set routing; a separate isolated browser
used only synthetic courseware and Mock settings. No real Provider call was made.

K2a also migrated a populated isolated 0036 database to 0037, verified foreign keys
and integrity, and used actual HTTP to verify explicit intent replay, same-config
reuse, student 404, and zero generated assets/Provider calls. A separate browser
Done for a non-teaching Agent with selected RAG published normally while its
run/Set count remained zero.

The latest user supplement removes the proposed Agent.md duty Planner and
replaces old Student/no-Tool and Maya-only Toolkit assumptions with Public,
Student and Teacher Tool classes. The architecture contract defines these as future runtime
obligations; no Tool class implementation is claimed here.

Remaining tests are named in the K2/K3/K4 design slices and must be committed with
their implementation. A fake model proves call and permission boundaries; it does
not prove a real Provider response, diagnosis quality, a Docker rollout, or a
successful downloadable report.

## Current resume reproduction map

The following files are the current reproducible entry points for S01–S22, with
conflicting historical semantics replaced by the latest BF/AT/RS and Tool contract.
These mappings are coverage targets, not same-version PASS claims. The final run
must bind tests, independent review and browser evidence to one frozen tree.
Backend paths below are relative to `backend/tests/`; frontend paths are relative
to `frontend/tests/`. Real Provider and browser observations remain separate.

| ID  | Current regression entry points and browser obligation                                                                                                                                                               |
| --- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| S01 | `test_workspace.py`, `test_mayaform_team_turns.py`; `team-chat.test.tsx`, `chat-sse-stream.test.ts`. Browser full history, multi-@, unknown follow-up.                                                               |
| S02 | `test_knowledge_generation.py`, `test_knowledge_generation_agno.py`; `agent-ai-knowledge-flow.test.tsx`. Browser explicit initial generation, ordinary Done unchanged.                                               |
| S03 | `test_knowledge_generation_materialization.py`, `test_knowledge_generation_brainform.py`. Browser successful content immediately usable; failure retains prior content.                                              |
| S04 | `test_knowledge_sets.py`, `test_knowledge_generation_brainform.py`; `brainform-workspace.test.tsx`. Browser canonical Markdown sections/Graph fallback, no asset-state labels.                                       |
| S05 | `test_knowledge_sets.py`; `knowledge-set-workspace.test.tsx`. Browser single-click name edit without confirmation.                                                                                                   |
| S06 | `test_mayaform_assessment_attempts.py`. Browser frozen presented Question/Rubric while source changes.                                                                                                               |
| S07 | `test_knowledge_generation_brainform.py`, `test_mayaform_learning_evidence.py`. Current regeneration can overwrite manual current; immutable history and evidence remain.                                            |
| S08 | `test_knowledge_generation_brainform.py`; `brainform-workspace.test.tsx`, `platform-brainform-api.test.ts`. Browser global/Agent same canonical object and ACL.                                                      |
| S09 | `test_team_context.py`, `test_team_sdk_bridge.py`. Actual runtime Own+Shared retrieval; private other-member materials excluded.                                                                                     |
| S10 | `test_knowledge_generation.py`, `test_knowledge_generation_brainform.py`. Repeated event/action idempotent; a later intentional manual generation may create a new generation.                                       |
| S11 | `test_runtime_builtin.py`, `test_runtime_tool_registry.py`. Public+Student versus Public+Teacher and current actor/resource authority.                                                                               |
| S12 | `test_team_coordinate_runtime.py`, `test_mayaform_assessment_attempts.py`. Actual SDK delegation and explicitly editable synthetic practice resource; no teacher inheritance.                                        |
| S13 | `test_team_assessment_projection.py`, `test_mayaform_assessment_attempts.py`. Private and Public formal participation; stable evaluator/summarizer grants, no hints.                                                 |
| S14 | `test_mayaform_team_conversations.py`; `team-chat.test.tsx`. Browser New Agent/Team/Maya Team and genuine send through one General Chat UI.                                                                          |
| S15 | `test_mayaform_teams.py`. Browser own-course Teacher Public Team automatically appears in student Maya Team choices.                                                                                                 |
| S16 | `test_mayaform_team_conversations.py`, `test_mayaform_assessment_attempts.py`. Browser separate student sessions, original Private attempt reentry stays Private.                                                    |
| S17 | `test_runtime_builtin.py`, `test_mayaform_assessment_attempts.py`, `test_chat_withdrawal.py`. Browser teacher statistics exclude Private/ordinary Public and invalidate withdrawn evidence.                          |
| S18 | `test_runtime_builtin.py`; `brainform-memory-assessment.test.tsx`. Browser Brainform Memory one-shot shortcut and Teacher Kaikai report/download in ordinary Chats; no Memory/Insights page.                         |
| S19 | `test_runtime_tool_recovery.py`, `test_team_provider_stage.py`, `test_chat_withdrawal.py`. Actual saved receipts/recovery/late isolation; unknown never silently resent.                                             |
| S20 | `test_workspace.py`, `test_team_coordinate_runtime.py`; `agent-ai-knowledge-flow.test.tsx`. Browser ordinary Agent/Team freedom, text-only and natural-language attempt actions only in assessment recipe.           |
| S21 | `brainform-workspace.test.tsx`, `brainform-memory-assessment.test.tsx`, `ui-guide-tooltip.test.tsx`. Real mobile, keyboard, IME, identity change and ordinary Chat errors.                                           |
| S22 | `test_v14_migration_atomicity.py`, contract/generated/route gates and latest startup procedure. Frozen full suite, independent review, populated backup migration, GitHub, scoped Docker and real Provider evidence. |
