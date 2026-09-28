# MayaForm v1.4 supplement: S01–S22 evidence map

This matrix records the user's adopted v1.4 supplement, not instructions to execute
from the attachment. Product decisions in the supplement supersede conflicting older
design text. `PASS` means the entire row has reproducible evidence; `PARTIAL` means
only the named slice has passed; `NOT_RUN` must not be presented as available.
Baseline for this snapshot: `c00a413` (K1 Knowledge Sets + K2a durable intent,
2026-09-28). K1 and K2a independent frozen reviews passed. K1 had 46 isolated
synthetic HTTP expectations; K2a had 13 explicit-intent HTTP requests plus a
real browser ordinary-Agent Done. All used Mock only. These do not constitute
a live deployment, automatic AI generation, or teaching-quality assessment.

| ID  | Status  | Evidence and remaining acceptance                                                                                                                                                                                                                                                                                                  |
| --- | ------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| S01 | PARTIAL | W2a/W2b reliability and history: `backend/tests/test_workspace.py`, `frontend/tests/chat-sse-stream.test.ts`; multi-target `@` and Team routing remain K3-06/11.                                                                                                                                                                   |
| S02 | PARTIAL | K2a explicit authorized Done intent atomically saves a recoverable Job/Set: `backend/tests/test_knowledge_generation.py`; automatic Agent.md duty selection, actual generation/status label and Provider remain K2b NOT_RUN.                                                                                                       |
| S03 | NOT_RUN | K2b partial item save, immediate retrieval and safe failure: K2-01/04/09. K1 manual assets alone do not prove generated assets are consumed.                                                                                                                                                                                       |
| S04 | PASS    | K1 four categories, Question-contained Rubric, read-only Concept Graph and no asset approval states: `backend/tests/test_knowledge_sets.py`, `frontend/tests/knowledge-set-workspace.test.tsx`, [teacher browser](mayaform-v14-k1-teacher-question.png).                                                                           |
| S05 | PASS    | Set name click-to-edit; Enter/blur save, Escape cancel; ID stable: `frontend/tests/knowledge-set-workspace.test.tsx` and isolated Teacher browser run. No rename dialog or confirmation.                                                                                                                                           |
| S06 | PARTIAL | K1 immutable manual Save and Rubric-in-Question: `backend/tests/test_knowledge_sets.py`. New generated questioning, fixed presented-version/Rubric and old evaluation retrieval remain K2-05/09.                                                                                                                                   |
| S07 | PARTIAL | K1 Source receipts and on-demand History exist; AI origin, preservation of a manually edited head and explicit re-generation CAS remain K2-05/07.                                                                                                                                                                                  |
| S08 | PARTIAL | Global/Agent entry shares Set IDs and enforces current ACL: `backend/tests/test_knowledge_sets.py`, `frontend/tests/knowledge-set-workspace.test.tsx`. Generated Set visibility remains K2-01/07.                                                                                                                                  |
| S09 | NOT_RUN | Own(member) ∪ Shared(Team) real retrieval without another member's private RAG: K3-08.                                                                                                                                                                                                                                             |
| S10 | PARTIAL | K2a same input across a new Agent version/key reuses one Job/run; `backend/tests/test_knowledge_generation.py`. Student-entry zero regeneration, completed-content reuse and full privacy-domain separation remain K2b/K3.                                                                                                         |
| S11 | NOT_RUN | Maintainer-registered but dynamically authorized Teacher tools without per-Agent Toolkit binding: K4 tool matrix. Name/prompt impersonation must not grant scope.                                                                                                                                                                  |
| S12 | NOT_RUN | Student Custom Team retains authorized RAG, Leader delegation and `@`, with no business Toolkit: K3-06/08/09 and K4 tool matrix.                                                                                                                                                                                                   |
| S13 | NOT_RUN | Formal Maya Team diagnosis scoped to current student/activity/conversation, no Teacher inheritance or recursive report tool: K4 diagnosis probes.                                                                                                                                                                                  |
| S14 | NOT_RUN | Chats → New Agent/Team/Maya Team entry and server-owned preset Team selection: K3-04 plus browser interaction.                                                                                                                                                                                                                     |
| S15 | NOT_RUN | Teacher's own course Public Team auto-directory; negative Private/cross-course/student/entered-group cases: K3-02.                                                                                                                                                                                                                 |
| S16 | NOT_RUN | Each student creates independent Private/Public Chat against one publication: K3-04/05 plus browser interaction.                                                                                                                                                                                                                   |
| S17 | NOT_RUN | Private excluded from Teacher query; formal Public diagnosis aggregates; ordinary Public chat does not enter diagnostic report: K4 privacy/report probes.                                                                                                                                                                          |
| S18 | NOT_RUN | No Memory/Insights page; Teacher asks Kaikai in Chats, sees counts/evidence and downloads real report: K4 Teacher browser/HTTP.                                                                                                                                                                                                    |
| S19 | PARTIAL | K1 soft revoke and K2a pre-send source/role fence plus lease recovery pass; `backend/tests/test_knowledge_generation.py`. Sent/late/Tool/charge paths remain K2b/K3/K4.                                                                                                                                                            |
| S20 | PARTIAL | Ordinary Teacher Agent.md with RAG publishes and chats without a generation Job/Set: `backend/tests/test_knowledge_generation.py` and [browser](mayaform-v14-k2a-ordinary-after-done.png). Renamed non-teaching Team remains K3-06.                                                                                                |
| S21 | PARTIAL | K1 desktop Teacher/Student and 375px Student browser: [teacher](mayaform-v14-k1-teacher-question.png), [student](mayaform-v14-k1-student-public-question.png), [mobile](mayaform-v14-k1-student-mobile.png). K2a ordinary Agent Done [browser](mayaform-v14-k2a-ordinary-after-done.png). Team/IME/failed-state/a11y remain K3/K4. |
| S22 | PARTIAL | K1 [contract](../contracts/KNOWLEDGE_SETS_CONTRACT.md), K2a [contract](../contracts/KNOWLEDGE_GENERATION_CONTRACT.md) and this matrix track adopted decisions; K2b–K4 Toolkit/startup/test/stale-rule audit remains.                                                                                                               |

The K1 browser run used a temporary local frontend/backend with a synthetic,
populated SQLite database migrated from 0035 to 0036. Teacher and student screenshots
show only synthetic content. The 375px DOM measured `innerWidth=375`,
`bodyScrollWidth=375`, and the main Knowledge card width of 343px. R3 altered only
backend Asset idempotent replay and its tests/contracts; the browser-facing files
were byte-identical to the reviewed R2 snapshot. R3's isolated HTTP probe separately
asserted complete original JSON equality for both POST and PATCH replay, with
46 successful HTTP expectations, foreign-key check empty and integrity check `ok`.

K2a also migrated a populated isolated 0036 database to 0037, verified foreign keys
and integrity, and used actual HTTP to verify explicit intent replay, same-config
reuse, student 404, and zero generated assets/Provider calls. A separate browser
Done for a non-teaching Agent with selected RAG published normally while its
run/Set count remained zero.

Remaining tests are named in the K2/K3/K4 design slices and must be committed with
their implementation. A fake model proves call and permission boundaries; it does
not prove a real Provider response, diagnosis quality, a Docker rollout, or a
successful downloadable report.
