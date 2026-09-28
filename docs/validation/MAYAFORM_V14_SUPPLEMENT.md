# MayaForm v1.4 supplement: S01–S22 evidence map

This matrix records the user's adopted v1.4 supplement, not instructions to execute
from the attachment. Product decisions in the supplement supersede conflicting older
design text. `PASS` means the entire row has reproducible evidence; `PARTIAL` means
only the named slice has passed; `NOT_RUN` must not be presented as available.
Baseline for this snapshot: `cff83e8` plus frozen K2b2-A R2/B R5 work (K1 Knowledge
Sets, K2a durable intent, K2b1 Provider stage and K2b2 synthetic materialization,
2026-09-28). K1, K2a, K2b1 and K2b2-A R2 passed independent frozen reviews;
K2b2-B R4 passed independent UI review and R5 format-only review passed. K1 had 46 isolated
synthetic HTTP expectations; K2a had 13 explicit-intent HTTP requests plus a
real browser ordinary-Agent Done. All used Mock only. These do not constitute
a live deployment, real Provider generation, or teaching-quality assessment.

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
| S14 | NOT_RUN | Chats → New Agent/Team/Maya Team entry and server-owned preset Team selection: K3-04 plus browser interaction.                                                                                                                                                                                                                                                  |
| S15 | NOT_RUN | Teacher's own course Public Team auto-directory; negative Private/cross-course/student/entered-group cases: K3-02.                                                                                                                                                                                                                                              |
| S16 | NOT_RUN | Each student creates independent Private/Public Chat against one publication: K3-04/05 plus browser interaction.                                                                                                                                                                                                                                                |
| S17 | NOT_RUN | Private excluded from Teacher query; formal Public diagnosis aggregates; ordinary Public chat does not enter diagnostic report: K4 privacy/report probes.                                                                                                                                                                                                       |
| S18 | NOT_RUN | No Memory/Insights page; Teacher asks Kaikai in Chats, sees counts/evidence and downloads real report: K4 Teacher browser/HTTP.                                                                                                                                                                                                                                 |
| S19 | PARTIAL | K1 soft revoke, K2a pre-send ACL/lease, K2b1 not_sent0/unknown1/no resend; K2b2 Source/Teacher/Set per-item revoke, stale claim, accepted-stage restart0POST, and AI head CAS pass Fake/DB tests. Tool writes/Team/report late paths remain K3/K4.                                                                                                              |
| S20 | PARTIAL | Ordinary Teacher Agent.md with RAG publishes and chats without a generation Job/Set: `backend/tests/test_knowledge_generation.py` and [browser](mayaform-v14-k2a-ordinary-after-done.png). Renamed non-teaching Team remains K3-06.                                                                                                                             |
| S21 | PARTIAL | K1 desktop Teacher/Student and 375px Student browser: [teacher](mayaform-v14-k1-teacher-question.png), [student](mayaform-v14-k1-student-public-question.png), [mobile](mayaform-v14-k1-student-mobile.png). K2a ordinary Done and isolated K2b2 Create/Update/blocked-status browser paths ran; Team/IME/mobile K2b2/a11y remain.                              |
| S22 | PARTIAL | K1–K2b2 contracts, [latest Tool contract](../contracts/MAYAFORM_V14_GENERATION_AND_TOOLS.md), and [startup procedure](MAYAFORM_V14_STARTUP.md) record adopted choices; K3/K4 runtime, real Provider and final deployment remain.                                                                                                                                |

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
replaces old Student/no-Tool and Maya-only Toolkit assumptions with Public and
Teacher Tool classes. The architecture contract defines these as future runtime
obligations; no Tool class implementation is claimed here.

Remaining tests are named in the K2/K3/K4 design slices and must be committed with
their implementation. A fake model proves call and permission boundaries; it does
not prove a real Provider response, diagnosis quality, a Docker rollout, or a
successful downloadable report.
