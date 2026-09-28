# MayaForm v1.4 supplement: S01–S22 evidence map

This matrix records the user's adopted v1.4 supplement, not instructions to execute
from the attachment. Product decisions in the supplement supersede conflicting older
design text. `PASS` means the entire row has reproducible evidence; `PARTIAL` means
only the named slice has passed; `NOT_RUN` must not be presented as available.
Baseline for this snapshot: `513af18` (K1 Knowledge Sets, K2a durable intent and
K2b1 Provider stage, 2026-09-28). K1, K2a and K2b1 independent frozen reviews passed. K1 had 46 isolated
synthetic HTTP expectations; K2a had 13 explicit-intent HTTP requests plus a
real browser ordinary-Agent Done. All used Mock only. These do not constitute
a live deployment, automatic AI generation, or teaching-quality assessment.

| ID  | Status  | Evidence and remaining acceptance                                                                                                                                                                                                                                                                                                  |
| --- | ------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| S01 | PARTIAL | W2a/W2b reliability and history: `backend/tests/test_workspace.py`, `frontend/tests/chat-sse-stream.test.ts`; multi-target `@` and Team routing remain K3-06/11.                                                                                                                                                                   |
| S02 | PARTIAL | K2a explicit Done intent and K2b1 confirmed single Provider call/stage are durable: `backend/tests/test_knowledge_generation.py`. The visible AI Knowledge flow, actual materialization/status label and real Provider remain K2b2 NOT_RUN; no Agent.md Planner.                                                                   |
| S03 | NOT_RUN | K2b partial item save, immediate retrieval and safe failure: K2-01/04/09. K1 manual assets alone do not prove generated assets are consumed.                                                                                                                                                                                       |
| S04 | PASS    | K1 four categories, Question-contained Rubric, read-only Concept Graph and no asset approval states: `backend/tests/test_knowledge_sets.py`, `frontend/tests/knowledge-set-workspace.test.tsx`, [teacher browser](mayaform-v14-k1-teacher-question.png).                                                                           |
| S05 | PASS    | Set name click-to-edit; Enter/blur save, Escape cancel; ID stable: `frontend/tests/knowledge-set-workspace.test.tsx` and isolated Teacher browser run. No rename dialog or confirmation.                                                                                                                                           |
| S06 | PARTIAL | K1 immutable manual Save and Rubric-in-Question: `backend/tests/test_knowledge_sets.py`. New generated questioning, fixed presented-version/Rubric and old evaluation retrieval remain K2-05/09.                                                                                                                                   |
| S07 | PARTIAL | K1 Source receipts and on-demand History exist; AI origin, preservation of a manually edited head and explicit re-generation CAS remain K2-05/07.                                                                                                                                                                                  |
| S08 | PARTIAL | Global/Agent entry shares Set IDs and enforces current ACL: `backend/tests/test_knowledge_sets.py`, `frontend/tests/knowledge-set-workspace.test.tsx`. Generated Set visibility remains K2-01/07.                                                                                                                                  |
| S09 | NOT_RUN | Own(member) ∪ Shared(Team) real retrieval without another member's private RAG: K3-08.                                                                                                                                                                                                                                             |
| S10 | PARTIAL | K2a same input across a new Agent version/key reuses one Job/run; `backend/tests/test_knowledge_generation.py`. Student-entry zero regeneration, completed-content reuse and full privacy-domain separation remain K2b/K3.                                                                                                         |
| S11 | NOT_RUN | Maintainer-only registry exposes Public Tools to Student and Public+Teacher Tools to Teacher; same Agent is resolved for current actor, no manual Toolkit binding or Agent.md capability gate. See [latest contract](../contracts/MAYAFORM_V14_GENERATION_AND_TOOLS.md).                                                           |
| S12 | NOT_RUN | Student Custom Team keeps authorized Own+Shared RAG, Leader delegation, `@`, and Public Assessment/Learning Tools. Current actor/resource ACL and provenance deny Teacher Tools or Private data. K3/K4 fake SDK and Tool probes remain.                                                                                            |
| S13 | NOT_RUN | Published Maya Team has no special Tool class: Student actor gets Public Tools only. Formal diagnosis differs by publication/activity/Public Chat provenance and scoped resources; `@Jade` does not grant hidden Rubric or Teacher access. K3/K4 probes remain.                                                                    |
| S14 | NOT_RUN | Chats → New Agent/Team/Maya Team entry and server-owned preset Team selection: K3-04 plus browser interaction.                                                                                                                                                                                                                     |
| S15 | NOT_RUN | Teacher's own course Public Team auto-directory; negative Private/cross-course/student/entered-group cases: K3-02.                                                                                                                                                                                                                 |
| S16 | NOT_RUN | Each student creates independent Private/Public Chat against one publication: K3-04/05 plus browser interaction.                                                                                                                                                                                                                   |
| S17 | NOT_RUN | Private excluded from Teacher query; formal Public diagnosis aggregates; ordinary Public chat does not enter diagnostic report: K4 privacy/report probes.                                                                                                                                                                          |
| S18 | NOT_RUN | No Memory/Insights page; Teacher asks Kaikai in Chats, sees counts/evidence and downloads real report: K4 Teacher browser/HTTP.                                                                                                                                                                                                    |
| S19 | PARTIAL | K1 soft revoke; K2a pre-send ACL/lease; K2b1 accepted-stage suppression, not_sent0 charge, unknown1/no resend and restart0HTTP pass. Tool writes/Team/report late paths remain K3/K4.                                                                                                                                              |
| S20 | PARTIAL | Ordinary Teacher Agent.md with RAG publishes and chats without a generation Job/Set: `backend/tests/test_knowledge_generation.py` and [browser](mayaform-v14-k2a-ordinary-after-done.png). Renamed non-teaching Team remains K3-06.                                                                                                |
| S21 | PARTIAL | K1 desktop Teacher/Student and 375px Student browser: [teacher](mayaform-v14-k1-teacher-question.png), [student](mayaform-v14-k1-student-public-question.png), [mobile](mayaform-v14-k1-student-mobile.png). K2a ordinary Agent Done [browser](mayaform-v14-k2a-ordinary-after-done.png). Team/IME/failed-state/a11y remain K3/K4. |
| S22 | PARTIAL | K1/K2a/K2b1 contracts, [latest Tool contract](../contracts/MAYAFORM_V14_GENERATION_AND_TOOLS.md), and [startup procedure](MAYAFORM_V14_STARTUP.md) record adopted choices; K2b2–K4 runtime and final deployment remain.                                                                                                            |

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
