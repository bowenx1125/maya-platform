# Classroom Quiz contract

This is the single prose contract for Classroom Quiz: the HTTP surface, state
rules, student isolation, Record aggregation, the attempt export and the
teacher/student controls that drive them. It replaces the separate
2026-11-06 frontend rework note, which now only points here.

Verified on 2026-11-08 (JST) against `main` at
`8dec1dbeee2caedc25e039970895025dfc70efcb`. When this file and the code
disagree, the code and its tests win; record the deviation here, do not
silently rewrite either side. Progress and deployment facts live in
[PROJECT](../PROJECT.md).

| Concern               | Source of truth                                                                            |
| --------------------- | ------------------------------------------------------------------------------------------ |
| Routes and gates      | `backend/app/modules/quiz/router.py`, `service.py`                                         |
| DTOs                  | `backend/app/modules/quiz/schemas.py`                                                      |
| Item validation       | `backend/app/modules/quiz/document.py`                                                     |
| Objective grading     | `backend/app/modules/quiz/grading.py`                                                      |
| ZIP export            | `backend/app/modules/quiz/export.py`                                                       |
| Tables                | `backend/migrations/versions/0083_classroom_quizzes.py`, `0084_quiz_taking_open_retest.py` |
| Backend tests         | `backend/tests/test_classroom_quiz_api.py`, `test_classroom_quiz_export.py`                |
| Frontend client/gates | `frontend/lib/api/quiz.ts`, `frontend/lib/quiz-gate.ts`, `frontend/lib/quiz-urls.ts`       |
| Frontend tests        | `frontend/tests/quiz-*.test.ts`                                                            |
| Decision record       | [ADR-011](../adr/ADR-011-classroom-quiz-parallel-domain.md)                                |
| Document shape        | `contracts/quiz-document.v1.schema.json` (descriptive; no runtime code loads it)           |

Quiz is a parallel domain: it never writes `assessment_attempts` or
conversations, and submission makes no model or Agent WebSocket call.

## Operations

All paths are under `/api/v1`. Every mutation needs a signed-in session and an
`X-CSRF-Token` header. None of these operations is in the frozen
`contracts/openapi-v0.1.yaml`; see [Route-surface classification](#route-surface-classification).

| Method | Path                                                     | operationId                | Who                        |
| ------ | -------------------------------------------------------- | -------------------------- | -------------------------- |
| GET    | `/courses/{course_id}/quizzes`                           | `listCourseQuizzes`        | course member              |
| POST   | `/courses/{course_id}/quizzes`                           | `createCourseQuiz`         | course teacher             |
| GET    | `/courses/{course_id}/quizzes/{quiz_id}`                 | `getCourseQuiz`            | course member              |
| PATCH  | `/courses/{course_id}/quizzes/{quiz_id}`                 | `patchCourseQuiz`          | course teacher, draft only |
| POST   | `/courses/{course_id}/quizzes/{quiz_id}/publish`         | `publishCourseQuiz`        | course teacher             |
| POST   | `/courses/{course_id}/quizzes/{quiz_id}/unpublish`       | `unpublishCourseQuiz`      | course teacher             |
| POST   | `/courses/{course_id}/quizzes/{quiz_id}/start-taking`    | `startCourseQuizTaking`    | course teacher             |
| POST   | `/courses/{course_id}/quizzes/{quiz_id}/pause-taking`    | `pauseCourseQuizTaking`    | course teacher             |
| POST   | `/courses/{course_id}/quizzes/{quiz_id}/attempts`        | `submitCourseQuizAttempt`  | course student             |
| GET    | `/courses/{course_id}/quizzes/{quiz_id}/attempts/export` | `exportCourseQuizAttempts` | course teacher             |
| GET    | `/courses/{course_id}/my-record-attempts`                | `listMyRecordAttempts`     | course member (own rows)   |
| GET    | `/courses/{course_id}/record-attempts`                   | `listCourseRecordAttempts` | course teacher             |

There is no delete-quiz route (`DELETE …/quizzes/{quiz_id}` returns 405) and
no route that reads, hides or grades a single quiz attempt.

## Permissions

- Not an active member of the course: **404** on every operation.
- Teacher-only operations reached by a student (create, patch, publish,
  unpublish, start/pause, export, `record-attempts`): **404**
  (`workspace.access.course_member(teacher=True)` raises `not_found`). Tests
  accept 403 or 404; the observed status is 404.
- A course teacher submitting an attempt: **403**.
- A student never sees a draft: the list filters to `published` and
  `getCourseQuiz` on a draft returns **404**. Submitting to a draft is also
  **404**.
- `group_id` is stored and validated against the course, but neither the list
  nor the get filters by it: every course student sees every published quiz.
  The teacher editor does not send `group_id`.

## States and transitions

A quiz has `status` (`draft` | `published`) and, independently,
`taking_open` (bool) and `taking_epoch` (int, starts at 0). **Publish freezes
the paper; it does not open it for taking.**

| Action       | Requires                         | Effect                                                                                 | Refusal                                                                               |
| ------------ | -------------------------------- | -------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| create       | teacher                          | `draft`, `content_revision=0`, `taking_open=false`, `taking_epoch=0`                   | item validation **422** (below)                                                       |
| patch        | `draft`                          | replaces the given fields; items re-validated                                          | `published` → **409** `quiz_published_immutable`                                      |
| publish      | `draft`, ≥1 item                 | `published`, `content_revision += 1`, `content_hash`, `published_at`; taking unchanged | already published → **409** `quiz_already_published`; no items → **422** `quiz_empty` |
| unpublish    | `published`                      | `draft`, `published_at=null`, `taking_open=false`; epoch kept                          | draft → **409** `quiz_not_published`                                                  |
| start-taking | `published`, `taking_open=false` | `taking_epoch += 1`, `taking_open=true`                                                | draft → **409** `quiz_not_published`; open → **409** `quiz_taking_already_open`       |
| pause-taking | `published`, `taking_open=true`  | `taking_open=false`; epoch kept                                                        | draft → **409** `quiz_not_published`; closed → **409** `quiz_taking_already_closed`   |

Consequences that tests or a probe confirm:

- Every closed→open transition starts a new epoch, so pause → start is a
  retest round. Unpublish → edit → publish → start also starts a new epoch
  (observed: epoch 1 → 2, `content_revision` 1 → 2).
- Publish is not idempotent on the server; the editor's Done lock only stops a
  double click from creating or publishing twice.
- Item validation on create, patch and publish (`document.py`): duplicate item
  id → `quiz_item_duplicate`; choice items need ≥2 unique choices
  (`quiz_item_choices_invalid`) and `answer.choice_ids`
  (`quiz_answer_required`); `single` needs exactly one, all ids must exist
  (`quiz_answer_invalid`); text items must not carry choices. All are **422**.

## Submission and grading

Body: `{"answers": [{"item_id": "q1", "choice_ids": ["a"]}, {"item_id": "q3", "text": "…"}]}`
with at least one answer.

- Requires `published` (else **404**) and `taking_open=true` (else **409**
  `quiz_taking_closed`).
- One attempt per `(quiz_id, actor_user_id, taking_epoch)`; a second submit in
  the same epoch is **409** `quiz_attempt_exists`. The unique constraint
  `ux_classroom_quiz_attempts_quiz_actor_epoch` (0084, replacing the 0083
  per-actor constraint) is the final guard. A local probe of 5 rounds × 4
  concurrent submits for one student returned one 201 and three 409 per
  round, with no 500; the service has no explicit mapping for a constraint
  violation that slips past its pre-check.
- `single`/`multiple`: unordered set equality with the key scores the item's
  `points`, otherwise 0. Text items are stored with `points_awarded=null`.
  `grading_status` is `complete` (objective only), `pending` (text only) or
  `mixed`. No route grades text items later, so `pending`/`mixed` is final in
  this version.
- Answers for unknown item ids are kept with `type: "unknown"` and not scored.
  Missing answers to `required` items are not rejected, and the `settings`
  flags (`shuffle_*`, `allow_skip`, `time_limit_sec`) are stored but not
  enforced by the server.
- The attempt stores `content_revision`, `taking_epoch`, the full
  `document_snapshot_json` (including the key) and the normalized answers.
- The 201 `QuizAttemptDTO` returns the submitter's normalized answers,
  including per-item `correct` and `points_awarded`.

## Student answer isolation

- `StudentQuizDTO` is rebuilt from an allow-list of item fields, and the
  server asserts that no `answer` or `rubric` key survives. The test checks the
  raw JSON for both keys.
- `my-record-attempts` returns only the caller's own quiz attempts (plus, for
  students, their own legacy chat attempts). Rows carry scores and status, not
  answers.
- `listCourseQuizzes` uses the same `QuizSummaryDTO` for both roles, so a
  student also receives `attempt_count`: the course-wide number of non-hidden
  attempts on that quiz, across all epochs.

## Record aggregation

`record-attempts` (teacher) and `my-record-attempts` (own) return
`RecordAttemptDTO` rows, newest first, with `source: "quiz" | "chat"`. Without
`quiz_id` they merge quiz attempts with legacy chat assessment attempts
(teacher: course-wide; student: own). With `quiz_id` they return only that
quiz's quiz-source rows.

`RecordAttemptDTO` carries `attempt_id`, `user_id`, `student_name`, `title`,
`status`, `submitted_at`, `score_objective`/`score_max_objective`,
`grading_status`, `quiz_id`, `conversation_id`, `points_awarded`/`points_total`,
`phase` and `team_name`. It does **not** carry `taking_epoch`,
`content_revision` or answers. Quiz rows report `phase="completed"` when
grading is complete and `"scoring_not_saved"` otherwise.

Attempts with `teacher_hidden_at` set are excluded from counts, Record and
export. No route sets that column for quiz attempts yet.

## Export

`GET …/quizzes/{quiz_id}/attempts/export[?taking_epoch=N]` returns
`application/zip` as an attachment named
`quiz-<slug>-<first 8 hex of id>-attempts.zip`, with `Cache-Control: no-store`.
A non-integer `taking_epoch` is **400**.

- Includes only `status="submitted"` attempts with no `teacher_hidden_at`,
  optionally narrowed to one epoch.
- Files: `manifest.json` (counts, filter, `taking_epoch_filter`),
  `quiz.json` (the quiz's **current** document, including the key),
  `attempts.json` (per attempt: id, user id, display name, revision, epoch,
  time, grading, scores, answers) and `summary.md`. With zero submissions it
  still returns 200, `attempts.json` is `[]`, and `README.md`/`summary.md` say
  `No submissions yet.`
- Rows contain no email, password or token fields (asserted). Each attempt's
  own `document_snapshot_json` is not exported, so an attempt from an earlier
  `content_revision` is shown beside the current paper.
- The Records page calls export without `taking_epoch` (all epochs).

## Teacher and student controls

| Page                                           | Control (English copy)                                            | Calls / rule                                                                                  |
| ---------------------------------------------- | ----------------------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| Editor `/teacher/quizzes/new`, `/{id}`         | Done                                                              | create or patch, then publish; in-flight lock (`beginDoneLock`); then back to the list        |
| Editor (published) and list row                | Start evaluation / Pause evaluation                               | `start-taking` / `pause-taking`; shown only for published quizzes                             |
| Editor (published) and list row                | Unpublish                                                         | `unpublish`; until then the editor hides Done and the edit controls (`isPublishedLocked`)     |
| List row                                       | Published/Draft, Accepting submissions/Paused, `{count} attempts` | from `QuizSummaryDTO`                                                                         |
| List row → `/teacher/quizzes/records?quiz_id=` | Records, Download                                                 | `record-attempts?quiz_id=` (also filtered client-side); Download only when scoped to one quiz |
| Student `/student/quiz`                        | Available: Start / Not open yet                                   | Start only when `taking_open === true` (`canStudentStartQuiz`)                                |
| Student `/student/quiz?tab=records`            | Records                                                           | `my-record-attempts` without `quiz_id`                                                        |

Empty states appear only when the request succeeded with no rows. Student
pages call through `PlatformApi`; teacher pages call through `QuizApi`
(`frontend/lib/api/quiz.ts`). English copy for Quiz codes lives in
`frontend/lib/i18n.ts` (`quiz_taking_already_open`,
`quiz_taking_already_closed`, `quiz_taking_closed`, `quiz_attempt_exists`) and
`frontend/lib/error-copy.json` (the other Quiz codes, #376). See gap 6 for
the teacher path.

## Known gaps and deviations (evidence, not changed here)

1. **Route-surface gate.** `contracts/route-surface-placeholders.json` lists
   nine Quiz operations but not `startCourseQuizTaking`,
   `pauseCourseQuizTaking` or `exportCourseQuizAttempts`. On 8dec1db,
   `node scripts/compare_route_surface.mjs --server-openapi …` fails with
   "unexpected server operation" for exactly those three. CI has not reported
   it because the `deterministic` job fails at an earlier backend-test step.
2. The old frontend note promised that publish was idempotent and that Record
   rows carried `taking_epoch`. Neither is true (see above).
3. [ADR-011](../adr/ADR-011-classroom-quiz-parallel-domain.md) still says "one
   submitted attempt per student per quiz". 0084 made it one per epoch.
4. A student who already submitted in the open epoch still sees Start. No DTO
   tells them, so they learn it from the 409 after answering.
5. Teachers cannot see a quiz attempt's answers in the UI, hide or delete a
   quiz attempt, grade text items or delete a quiz. Answers are reachable
   only through the ZIP.
6. **Teacher error copy.** The backend sends errors as top-level
   `{code, message, details, request_id}`. `QuizApi`'s `toPlatformApiError`
   only reads a FastAPI-style `detail` wrapper, so on the teacher pages the
   code is dropped and the raw JSON body becomes the message. A local probe
   (409 `quiz_taking_already_open` through `QuizApi.startTaking`) gave
   `code=null` and rendered the JSON text instead of "Taking is already
   open.". Student calls use `PlatformApi.readErrorPayload` and are not
   affected.

## Route-surface classification

The Quiz operations are server extras outside the frozen OpenAPI and are
classified in `contracts/route-surface-placeholders.json` (owner
`T2-QUIZ-M1M3`). Gap 1 lists the three that still need a classification.

## Verification behind this file

On 2026-11-08 (JST), tree 8dec1db, local PostgreSQL 16:

- `cd backend && uv run pytest -p no:warnings tests/test_classroom_quiz_api.py tests/test_classroom_quiz_export.py tests/test_database.py`:
  18 passed.
- `pnpm -C frontend exec vitest run tests/quiz-export.test.ts tests/quiz-m4.test.ts tests/quiz-rework-b-r2.test.ts tests/quiz-validation.test.ts`:
  31 passed.
- Throwaway probes (not committed) confirmed the publish/unpublish/start
  refusals, teacher-submit 403, student-export 404, the epoch after republish,
  the concurrent-submit result and the teacher error parsing (gap 6) quoted
  above.
- The route-surface comparison failed as described in gap 1.

These runs cover Quiz only. They are not a full-suite, browser or production
acceptance.

## History

- 2026-11-05, MAYA-QUIZ-20261105-01 (M1–M3): domain, publish gate, student
  stripping, objective grading, Record aggregate; migration 0083.
- 2026-11-06, MAYA-QUIZ-REWORK-20261106-01 (P1/P3/P4): publish separated from
  taking, retest epochs, `quiz_id` Record filter; migration 0084.
- 2026-11-07, #375/#374: teacher ZIP export (backend/frontend).
- 2026-11-08: the frontend rework note merged into this file.
