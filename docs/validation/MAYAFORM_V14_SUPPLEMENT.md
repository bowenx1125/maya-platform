# MayaForm v1.4 supplement: S01–S22 evidence map

This matrix records the user's adopted v1.4 supplement, not instructions to execute
from the attachment. Product decisions in the supplement supersede conflicting older
design text. `PASS` means the entire row has reproducible evidence; `PARTIAL` means
only the named slice has passed; `NOT_RUN` must not be presented as available.
Baseline for this snapshot: `bbf04d0` (K1 Knowledge Sets, 2026-09-28). The K1
independent frozen review passed, the deterministic suite passed, and an isolated
synthetic HTTP run passed 46 requests with zero real Provider calls. These do not
constitute a live deployment or teaching-quality assessment.

| ID | Status | Evidence and remaining acceptance |
| --- | --- | --- |
| S01 | PARTIAL | W2a/W2b reliability and history: `backend/tests/test_workspace.py`, `frontend/tests/chat-sse-stream.test.ts`; multi-target `@` and Team routing remain K3-06/11. |
| S02 | NOT_RUN | K2a Done-to-Job atomicity, then K2b live generation/status; K2-01/08. Exact generating label appears only during generation, never as a permanent blocked state. |
| S03 | NOT_RUN | K2b partial item save, immediate retrieval and safe failure: K2-01/04/09. K1 manual assets alone do not prove generated assets are consumed. |
| S04 | PASS | K1 four categories, Question-contained Rubric, read-only Concept Graph and no asset approval states: `backend/tests/test_knowledge_sets.py`, `frontend/tests/knowledge-set-workspace.test.tsx`, [teacher browser](mayaform-v14-k1-teacher-question.png). |
| S05 | PASS | Set name click-to-edit; Enter/blur save, Escape cancel; ID stable: `frontend/tests/knowledge-set-workspace.test.tsx` and isolated Teacher browser run. No rename dialog or confirmation. |
| S06 | PARTIAL | K1 immutable manual Save and Rubric-in-Question: `backend/tests/test_knowledge_sets.py`. New generated questioning, fixed presented-version/Rubric and old evaluation retrieval remain K2-05/09. |
| S07 | PARTIAL | K1 Source receipts and on-demand History exist; AI origin, preservation of a manually edited head and explicit re-generation CAS remain K2-05/07. |
| S08 | PARTIAL | Global/Agent entry shares Set IDs and enforces current ACL: `backend/tests/test_knowledge_sets.py`, `frontend/tests/knowledge-set-workspace.test.tsx`. Generated Set visibility remains K2-01/07. |
| S09 | NOT_RUN | Own(member) ∪ Shared(Team) real retrieval without another member's private RAG: K3-08. |
| S10 | NOT_RUN | Persisted generation input key, same-config reuse and domain separation: K2-03, including a new student's Chat causing zero re-generation. |
| S11 | NOT_RUN | Maintainer-registered but dynamically authorized Teacher tools without per-Agent Toolkit binding: K4 tool matrix. Name/prompt impersonation must not grant scope. |
| S12 | NOT_RUN | Student Custom Team retains authorized RAG, Leader delegation and `@`, with no business Toolkit: K3-06/08/09 and K4 tool matrix. |
| S13 | NOT_RUN | Formal Maya Team diagnosis scoped to current student/activity/conversation, no Teacher inheritance or recursive report tool: K4 diagnosis probes. |
| S14 | NOT_RUN | Chats → New Agent/Team/Maya Team entry and server-owned preset Team selection: K3-04 plus browser interaction. |
| S15 | NOT_RUN | Teacher's own course Public Team auto-directory; negative Private/cross-course/student/entered-group cases: K3-02. |
| S16 | NOT_RUN | Each student creates independent Private/Public Chat against one publication: K3-04/05 plus browser interaction. |
| S17 | NOT_RUN | Private excluded from Teacher query; formal Public diagnosis aggregates; ordinary Public chat does not enter diagnostic report: K4 privacy/report probes. |
| S18 | NOT_RUN | No Memory/Insights page; Teacher asks Kaikai in Chats, sees counts/evidence and downloads real report: K4 Teacher browser/HTTP. |
| S19 | NOT_RUN | Revocation/deletion/late work and repeated tool side effects/charges: K2-06/07, K3-11, K4 idempotency probes. K1 soft revoke alone is insufficient. |
| S20 | NOT_RUN | A non-teaching Team with renamed members runs normally and ordinary Agent Done does not force knowledge generation: K2-02 and K3-06. |
| S21 | PARTIAL | K1 desktop Teacher/Student and 375px Student browser: [teacher](mayaform-v14-k1-teacher-question.png), [student](mayaform-v14-k1-student-public-question.png), [mobile](mayaform-v14-k1-student-mobile.png). Full three-entry/Team/IME/failed-state/a11y browser paths remain K3/K4. |
| S22 | PARTIAL | K1 [contract](../contracts/KNOWLEDGE_SETS_CONTRACT.md) and this matrix capture adopted decisions; remaining K2–K4 Toolkit contract, startup instructions, tests and stale-rule scan must be completed before full PASS. |

The K1 browser run used a temporary local frontend/backend with a synthetic,
populated SQLite database migrated from 0035 to 0036. Teacher and student screenshots
show only synthetic content. The 375px DOM measured `innerWidth=375`,
`bodyScrollWidth=375`, and the main Knowledge card width of 343px. R3 altered only
backend Asset idempotent replay and its tests/contracts; the browser-facing files
were byte-identical to the reviewed R2 snapshot. R3's isolated HTTP probe separately
asserted complete original JSON equality for both POST and PATCH replay, with
46 successful HTTP expectations, foreign-key check empty and integrity check `ok`.

Remaining tests are named in the K2/K3/K4 design slices and must be committed with
their implementation. A fake model proves call and permission boundaries; it does
not prove a real Provider response, diagnosis quality, a Docker rollout, or a
successful downloadable report.
