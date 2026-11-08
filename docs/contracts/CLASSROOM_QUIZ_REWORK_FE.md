# Classroom Quiz frontend rework note (historical, merged)

Status: **merged on 2026-11-08 into
[CLASSROOM_QUIZ_API.md](CLASSROOM_QUIZ_API.md)**, which is the single Quiz
contract. That file holds the teacher-control table, the student gate,
Records, the error codes and the known deviations. Do not add behavior here.

This note was the 2026-11-06 frontend brief for ticket
`MAYA-QUIZ-REWORK-20261106-01` (coding A = backend, coding B = frontend),
based on backend branch `t2/quiz-rework-p1p3p4-20261106` and migration
`0084_quiz_taking_open_retest`. Its scope lock is kept as a dated record:

- REPORT-CLICK narrowed to the manual editor; no two-column Agent authoring or
  courseware-upload quiz generation.
- The legacy chat assessment endpoints stay unchanged.
- No deploy or merge to `main` from that brief; release needed a reviewer PASS
  and user approval.

Two statements in the original brief did not match the implementation and are
**not** current:

- "Publish is idempotent if already published": a second publish returns
  **409** `quiz_already_published`; only the editor's Done lock prevents a
  double send.
- "Record rows carry `taking_epoch`": `RecordAttemptDTO` has no
  `taking_epoch`. The epoch is in `QuizAttemptDTO`, quiz DTOs and the export.

The original text is in Git history (`git log -- docs/contracts/CLASSROOM_QUIZ_REWORK_FE.md`).
