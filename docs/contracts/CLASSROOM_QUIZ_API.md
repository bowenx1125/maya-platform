# Classroom Quiz contract

This is the single prose contract for Classroom Quiz: the HTTP surface, state
rules, student isolation, attempt detail, hand and opt-in AI grading, hiding, Record
aggregation, the attempt export and the teacher/student controls that drive
them. It replaces the separate
2026-11-06 frontend rework note, which now only points here.

First verified on 2026-11-08 (JST) against `main` at
`8dec1dbeee2caedc25e039970895025dfc70efcb`; updated the same day for
migration `0085_quiz_manual_grading` (attempt detail, hand grading, hide,
Record epochs, Record moved under Quiz). When this file and the code
disagree, the code and its tests win; record the deviation here, do not
silently rewrite either side. Progress and deployment facts live in
[PROJECT](../PROJECT.md).

| Concern               | Source of truth                                                                                                                                        |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Routes and gates      | `backend/app/modules/quiz/router.py`, `service.py`                                                                                                     |
| DTOs                  | `backend/app/modules/quiz/schemas.py`                                                                                                                  |
| Item validation       | `backend/app/modules/quiz/document.py`                                                                                                                 |
| Objective grading     | `backend/app/modules/quiz/grading.py`                                                                                                                  |
| ZIP export            | `backend/app/modules/quiz/export.py`                                                                                                                   |
| Tables                | `backend/migrations/versions/0083_classroom_quizzes.py`, `0084_quiz_taking_open_retest.py`, `0085_quiz_manual_grading.py`, `0091_quiz_show_results.py` |
| Backend tests         | `backend/tests/test_classroom_quiz_api.py`, `test_classroom_quiz_export.py`, `test_classroom_quiz_attempt_review.py`, `test_classroom_quiz_results.py` |
| Frontend client/gates | `frontend/lib/api/quiz.ts`, `frontend/lib/quiz-gate.ts`, `frontend/lib/quiz-urls.ts`                                                                   |
| Frontend tests        | `frontend/tests/quiz-*.test.ts(x)`                                                                                                                     |
| Decision record       | [ADR-011](../adr/ADR-011-classroom-quiz-parallel-domain.md)                                                                                            |
| Document shape        | `contracts/quiz-document.v1.schema.json` (descriptive; no runtime code loads it)                                                                       |

Quiz is a parallel domain: it never writes `assessment_attempts` or
conversations, and submission makes no model or Agent WebSocket call.

## Operations

All paths are under `/api/v1`. Every mutation needs a signed-in session and an
`X-CSRF-Token` header. The frozen `contracts/openapi-v0.1.yaml` includes
list/detail, exemptions, scheduling and results visibility; see
[Route-surface classification](#route-surface-classification).

| Method | Path                                                                  | operationId                | Who                               |
| ------ | --------------------------------------------------------------------- | -------------------------- | --------------------------------- |
| GET    | `/courses/{course_id}/quizzes`                                        | `listCourseQuizzes`        | course member                     |
| POST   | `/courses/{course_id}/quizzes`                                        | `createCourseQuiz`         | course teacher                    |
| GET    | `/courses/{course_id}/quizzes/{quiz_id}`                              | `getCourseQuiz`            | course member                     |
| PATCH  | `/courses/{course_id}/quizzes/{quiz_id}`                              | `patchCourseQuiz`          | course teacher, draft only        |
| DELETE | `/courses/{course_id}/quizzes/{quiz_id}`                              | `deleteCourseQuiz`         | course teacher                    |
| POST   | `/courses/{course_id}/quizzes/{quiz_id}/publish`                      | `publishCourseQuiz`        | course teacher                    |
| POST   | `/courses/{course_id}/quizzes/{quiz_id}/unpublish`                    | `unpublishCourseQuiz`      | course teacher                    |
| POST   | `/courses/{course_id}/quizzes/{quiz_id}/start-taking`                 | `startCourseQuizTaking`    | course teacher                    |
| POST   | `/courses/{course_id}/quizzes/{quiz_id}/pause-taking`                 | `pauseCourseQuizTaking`    | course teacher                    |
| PUT    | `/courses/{course_id}/quizzes/{quiz_id}/results`                      | `putCourseQuizResults`     | course teacher                    |
| POST   | `/courses/{course_id}/quizzes/{quiz_id}/attempts`                     | `submitCourseQuizAttempt`  | course student                    |
| GET    | `/courses/{course_id}/quizzes/{quiz_id}/attempts/export`              | `exportCourseQuizAttempts` | course teacher                    |
| GET    | `/courses/{course_id}/quizzes/{quiz_id}/attempts/{attempt_id}`        | `getCourseQuizAttempt`     | teacher, or the attempt's student |
| DELETE | `/courses/{course_id}/quizzes/{quiz_id}/attempts/{attempt_id}`        | `hideCourseQuizAttempt`    | course teacher                    |
| PUT    | `/courses/{course_id}/quizzes/{quiz_id}/attempts/{attempt_id}/grades` | `gradeCourseQuizAttempt`   | course teacher                    |
| GET    | `/courses/{course_id}/my-record-attempts`                             | `listMyRecordAttempts`     | course member (own rows)          |
| GET    | `/courses/{course_id}/record-attempts`                                | `listCourseRecordAttempts` | course teacher                    |

`DELETE …/quizzes/{quiz_id}` removes that quiz. It is a different route from
hiding one attempt.
`/attempts/export` is declared before `/attempts/{attempt_id}` so "export" is
never parsed as an attempt id.

## Permissions

- Not an active member of the course: **404** on every operation.
- Teacher-only operations reached by a student (create, patch, publish,
  unpublish, delete, start/pause, export, hide, grade, `record-attempts`): **404**
  (`workspace.access.course_member(teacher=True)` raises `not_found`). Tests
  accept 403 or 404; the observed status is 404.
- A course teacher submitting an attempt: **403**.
- Results visibility: a student receives **403**; a non-member receives **404**.
- Attempt detail: a course teacher reads any non-hidden attempt of the quiz;
  a student reads only their own; anything else, and any hidden attempt, is
  **404**.
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
  (`quiz_item_choices_invalid`); `single` allows zero or one key id after
  dropping blanks, and all nonblank key ids must exist (`quiz_answer_invalid`);
  text items must not carry choices. All validation errors are **422**.

### No standard answer

For `single`/`multiple`, missing or null `answer`, or missing, null, empty,
or non-array `answer.choice_ids` means no standard answer. Whitespace-only strings
(including empty strings) are ignored, never treated as ids; a key containing only
such strings also means no standard answer. The teacher UI saves
`answer: {"choice_ids": []}` for this case. The backend normalizes non-array keys
to null instead of Pydantic's former schema-layer 422; array entries must still be
strings, and unknown nonblank ids still produce `quiz_answer_invalid`.

Without a standard answer, a non-empty student selection containing only existing
choice ids yields `correct: true` and full `points`. No submission, an empty
selection, or only blank/whitespace strings yields `correct: null` and
`points_awarded: 0`, including required items. Invalid nonblank selections yield
`correct: false` and 0 points. No new field is added. Items with a non-empty key
retain unordered set equality grading and boolean `correct` (true/false).

Existing attempts derive these choice results from their frozen paper on read
(detail, Record and ZIP export), without changing stored answers or score columns.
Manual teacher text grades take precedence over AI grades and remain unchanged.
Student projections continue to omit `answer`, `rubric` and `grading`.

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
  `points`, otherwise 0 (see [No standard answer](#no-standard-answer)). Text items
  are stored with `points_awarded=null`.
  `grading_status` is `complete` (no text items), `pending` (text only) or
  `mixed` until a teacher grades every text item by hand (see
  [Hand grading](#hand-grading-no-model-call)).
- Answers for unknown item ids are kept with `type: "unknown"` and not scored.
  Missing answers to `required` items are not rejected, and the `settings`
  flags (`shuffle_*`, `allow_skip`, `time_limit_sec`) are stored but not
  enforced by the server.
- The attempt stores `content_revision`, `taking_epoch`, the full
  `document_snapshot_json` (including the key) and the normalized answers.
- The 201 `QuizAttemptDTO` returns the submitter's normalized answers.
  Per-item `correct` and `points_awarded` appear only when results are visible.

## Results visibility

`PUT …/quizzes/{quiz_id}/results` accepts `{"show_results": true | false}`
(strict boolean) and returns `QuizSummaryDTO`. It is available to course
teachers in draft and published states and requires the normal session,
Origin and CSRF checks. The flag lives in `classroom_quizzes.show_results`,
outside the frozen document/settings, and applies immediately to every
attempt, including earlier rounds. Turning it off hides results again.

Migration `0091_quiz_show_results` follows `0090_bowen_identity_choice`, backfills
existing quizzes to true, then sets the database default to false and the
column to NOT NULL. New quizzes default to false in both SQL and ORM inserts.
Quiz summaries, student papers, submission receipts, Record rows and attempt
details carry `show_results` (legacy chat Record rows retain true).

When false, student submission receipts return null aggregate scores and
grading status; their answers contain only item IDs/types and chosen IDs/text.
Submission reads visibility again after committing the attempt, so a teacher
changing it during grading also controls that receipt.
Student Record rows return null objective/AI scores, points, grading status
and phase. Student attempt detail returns null scores, points, grading status
and graded time; item correctness, awarded points, AI scores and feedback are
null and `graded` is false. Question text, choices, maximum item points and
the student's own answers remain available. Answer keys/rubrics remain private
regardless of visibility. With true, the previous grading projections apply.

Teacher papers, submissions, grading and ZIP exports retain their complete
results in either state. Quiz has no notification/event or websocket score
payload; live and chat reports do not read classroom Quiz attempts.

The teacher's published quiz banner has one optimistic switch capsule after
Extend time and before Download: `Results hidden` (off, default) or
`Results shown` (on), with rollback on failure. There is no duplicate banner
sticker. Teacher list rows have only a cyan `Results shown` sticker with an eye
icon while shown, including drafts; hidden rows have no visibility sticker.
There are no question-mark icons or tooltips for this feature.

Hidden student rows show a lime `Submitted` sticker and remain expandable.
Their paper shows questions and the student's answers without correctness
marks, row tints, Points/Feedback columns or a score header. Submission shows
the existing `Submitted` sticker and `Your answers are in.`. The receipt's
current visibility controls the submit screen; only explicit true enables
student results, including when a visibility field is missing or malformed.
Shown student behavior and teacher grading remain unchanged.

## Student answer isolation

- `StudentQuizDTO` is rebuilt from an allow-list of item fields, and the
  server asserts that no `answer` or `rubric` key survives. The test checks the
  raw JSON for both keys.
- `my-record-attempts` returns only the caller's own quiz attempts (plus, for
  students, their own legacy chat attempts). Rows carry scores and status, not
  answers.
- A student's attempt detail is `StudentQuizAttemptDetailDTO` (`view:
"student"`): their responses, per-item `correct`, points and the teacher's
  feedback, with no `answer` key or rubric. The server asserts the key is
  absent, and the test checks the raw JSON. The distinct `view` literal stops
  FastAPI from serializing a student payload through the teacher model.
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
`phase`, `team_name`, and for quiz rows `taking_epoch` and `content_revision`.
It carries no answers. For quiz rows `points_awarded` is
`score_objective + score_manual` and `points_total` covers every item,
text questions included, so an ungraded paper never reads as full marks.
`phase` is `"completed"` once grading is complete and `"grading_pending"`
before.

The Quiz pages show only `source: "quiz"` rows: a quiz's Submissions tab
(teacher) and the student's Quiz list. Chat rows are no longer shown in the
UI; the endpoints still return them. See [Record placement](#record-placement).

Attempts with `teacher_hidden_at` set are excluded from counts, Record,
detail and export.

## Attempt detail

`GET …/attempts/{attempt_id}` returns the paper as it was frozen in the
attempt's `document_snapshot_json`, item by item, with
`response_choice_ids`/`response_text`, `correct` (choice items),
`points_awarded`, `graded`, `feedback`, plus `taking_epoch`,
`content_revision`, `score_objective`/`score_max_objective`,
`score_manual`/`score_max_manual`, `points_awarded`/`points_total`,
`grading_status` and `graded_at`. The teacher view (`view: "teacher"`) adds
each item's `answer` (choice ids or rubric).

## Hand grading (no model call)

`PUT …/attempts/{attempt_id}/grades` with
`{"grades": [{"item_id": "q3", "points_awarded": 2.5, "feedback": "…"}]}`
(1–500 grades; feedback ≤ 4000 characters). No AI or model call is involved.

- Only text items (`short_text`/`long_text`) of the attempt's frozen paper can
  be graded; an unknown or choice item, or the same item twice in one
  request, is **422** `quiz_grade_item_invalid`. Points must be finite, ≥ 0
  and ≤ that item's points on the frozen paper (a later edit does not move
  the cap): **422** `quiz_grade_points_invalid` with `details.max_points`.
- A grade upserts per item and records the grader and time in
  `manual_grades_json`. `score_manual` is the sum, `score_objective` never
  changes, and `grading_status` becomes `complete` once every text item has
  a grade. The row is locked (`SELECT … FOR UPDATE`) while grading.
- Hidden attempts cannot be graded (**404**).

## AI grading (opt-in per text item)

A text item may carry `grading: {mode: "ai", score_min, score_max, rules}`
(absent or `mode: "manual"` = hand grading only). `rules` must be at least
20 characters and `0 ≤ score_min ≤ score_max ≤ points`, else **422**
`quiz_grading_invalid`; students never receive `grading`. The editor shows
one "AI grading" switch beside Required: AI grades by the item's rubric
within 0..points, so the editor sends `rules` = rubric, `score_min` = 0 and
`score_max` = points.

- Submit makes no model call. When the frozen paper has AI items and an LLM
  is configured, a background task hands the attempt to a two-thread grading
  pool and returns (queued in memory; a restart drops the queue and those
  items stay pending for hand grading). With no LLM configured nothing is
  queued.
- The worker reads what needs scoring, calls the model with no transaction
  open, then locks the row only to write `ai_score` for items that have
  neither an AI score nor a teacher grade. Scores are clamped to the range.
- A teacher grade always wins over `ai_score`. `grading_status` is
  `complete` once every text item has a teacher grade or an AI score.
- Teacher attempt items carry `ai_grading` and `ai_score`; the Submissions
  paper shows "AI n / points" or "AI score pending" under the editable
  points of AI items only. Rows keep Graded / Needs grading.

## Deleting a quiz

`DELETE /courses/{course_id}/quizzes/{quiz_id}` (**204**, course teacher,
operation `deleteCourseQuiz`) deletes the quiz for good in any state, with
every attempt taken on it (answers, grades, AI scores) in the same
transaction. It leaves the teacher list, both Records, counts and the
export; a later submit or a second delete is **404**. There is no undo. The
teacher list shows "Delete quiz" on each quiz row, after a confirm that
names the quiz. The quiz page does not. Cancelling the confirm leaves the
row. A failed delete leaves the row and shows the error.

## Hiding an attempt

`DELETE …/attempts/{attempt_id}` (**204**) sets `teacher_hidden_at`. The
attempt leaves teacher and student Record, `attempt_count`, detail and the
export, for the student too. The row is kept, so the student still cannot
submit again in that epoch (`quiz_attempt_exists`). There is no unhide
route. A second hide, or a hide by a student, is **404**.

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
  time, grading, objective and manual scores, `points_awarded`/`points_total`,
  `graded_at`, `manual_grades`, answers) and `summary.md` (its Score column
  is `points_awarded/points_total`). With zero submissions it
  still returns 200, `attempts.json` is `[]`, and `README.md`/`summary.md` say
  `No submissions yet.`
- Rows contain no email, password or token fields (asserted). Each attempt's
  own `document_snapshot_json` is not exported, so an attempt from an earlier
  `content_revision` is shown beside the current paper.
- The quiz page's Download calls export without `taking_epoch` (all epochs).

## Teacher and student controls

| Page                                      | Control (English copy)                                                             | Calls / rule                                                                                                                           |
| ----------------------------------------- | ---------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| List `/teacher/quizzes`                   | New; one row per quiz: LIVE / Paused / Draft chip, `{count} attempts`; Delete quiz | `QuizSummaryDTO`; the row opens `/teacher/quizzes/{id}`; Delete quiz confirms, then `DELETE …/quizzes/{id}`, and does not open the row |
| Quiz page `/teacher/quizzes/new`, `/{id}` | Tabs Paper \| Submissions (`?tab=paper\|submissions`)                              | Submissions is locked until the quiz is published or has attempts                                                                      |
| Paper tab (draft)                         | title typed in the banner, Done                                                    | create or patch, then publish; in-flight lock (`beginDoneLock`); then back to the list                                                 |
| Paper tab (published)                     | read-only paper, lock notice with Unpublish                                        | `unpublish`; until then Done and the edit controls are hidden (`isPublishedLocked`)                                                    |
| Quiz page banner (published)              | Start evaluation / Pause evaluation, Download                                      | `start-taking` / `pause-taking`; `attempts/export` (Download also when a draft has rows)                                               |
| Submissions tab                           | All rounds / Round N / Needs grading · N filters; rows by student                  | `record-attempts?quiz_id=` (also filtered client-side); a published quiz opens here                                                    |
| Submissions row                           | opens the attempt: Key column, points/feedback inputs, Save grades, Hide           | attempt detail, `grades`, hide (after a confirm)                                                                                       |
| Student `/student/quiz`                   | one list: Start rows, own results (Round N, Graded / Not graded yet), Not open     | Start only when `taking_open === true` and no result for the open round                                                                |
| Student result row                        | opens own marked paper (no Key)                                                    | `my-record-attempts` quiz rows, attempt detail                                                                                         |

Empty states appear only when the request succeeded with no rows. Student
pages call through `PlatformApi`; teacher pages and the attempt detail call
through `QuizApi` (`frontend/lib/api/quiz.ts`), which reads the same
top-level `{code, message, details, request_id}` error body as `PlatformApi`.
English copy for Quiz codes lives in `frontend/lib/i18n.ts`
(`quiz_taking_already_open`, `quiz_taking_already_closed`,
`quiz_taking_closed`, `quiz_attempt_exists`) and `frontend/lib/error-copy.json`
(the other Quiz codes, grading codes included). Submissions and result rows
carry no press-motion hit layer: its hover overlay covered the grading controls in a
real browser.

## Page layout (owner pick, 2026-11-08, second round)

Option A, "one page per quiz", replaced the first-round look after the owner
found it redundant:

- **Lists are rows, not cards with keys.** A teacher row shows one state chip
  (B's blinking LIVE lamp while accepting, still under reduced motion;
  otherwise Paused or Draft), the title and the attempt count. The whole row
  opens the quiz. New is the shared banner action.
- **One quiz page, two tabs.** Paper is the question sheet; Submissions is the
  quiz's record. That is how editing and the record are told apart: a draft
  opens on Paper with its Submissions tab locked; a published quiz opens on
  Submissions and its Paper is read-only. Rare actions (Start/Pause, Download)
  sit in the banner; Unpublish sits on the lock notice it lifts.
- **Paper:** worksheet question cards (`#01`, type pill, ruled paper), a
  − n + points stepper, a lime correct-answer key that keeps the real radio or
  checkbox ("Mark as correct answer"), and B's dashed "Add question" slot.
- **Submissions:** round and Needs grading filters, rows by student with
  round, a Graded / Needs grading chip and a mono score. A row opens the
  marked paper (red margin, red total, lime/red rows).
- **Student:** one list with no tabs. Quizzes open now (Start) come first,
  then the student's results (opening their marked paper), then quizzes not
  open yet.
- **Empty states:** sticker cards with the existing one-line copy.
- **Keys:** a symbol and a word (`QuizKey` in
  `frontend/components/quizzes/quiz-chrome.tsx`), shared press and busy
  motion, stacked symbol-over-word under 600px.

## Record placement

Owner decisions (2026-11-08): the formal chat-assessment Record left
Brainform, and in the second round its board ("Chat tests") was removed from
the Quiz pages because teachers no longer use it. `/teacher/record` redirects
to `/teacher/quizzes`, `/student/record` to `/student/quiz`, and the old
`/teacher/quizzes/records?quiz_id=` link to that quiz's Submissions tab (no
`quiz_id`: the list). The chat-assessment endpoints, their data and their
permission checks are unchanged; only the frontend board
(`AssessmentRecordPanel`) was deleted. No attempt was copied, rewritten or
removed.

## Known gaps (evidence, not changed here)

1. A student who already submitted in the open epoch still sees Start. No DTO
   tells them, so they learn it from the 409 after answering.
2. `listCourseQuizzes` gives students the course-wide `attempt_count`.
3. `group_id` does not filter which students see a quiz; the server does not
   enforce `required` or the `settings` flags.
4. The export's `quiz.json` is the current paper, not each attempt's frozen
   snapshot (the attempt detail does use the snapshot).
5. No unhide route.

Closed on 2026-11-08: the three unclassified route-surface operations, the
teacher error copy (raw JSON), the missing attempt detail/hide/grading, the
missing `taking_epoch` on Record rows, the frontend note's two wrong claims
and ADR-011's per-quiz wording (amended there).

## Route-surface classification

List/detail, exemptions, scheduling and results visibility are frozen OpenAPI
operations. The remaining Quiz operations are classified server extras in
`contracts/route-surface-placeholders.json` (owner `T2-QUIZ-M1M3`). The frozen
DTO schemas also describe nullable student grading projections and complete
teacher projections.

## Verification behind this file

2026-11-08 (JST), branch `claude/exciting-lamport-ualph4` on `main` 19e9ba19,
local PostgreSQL 16, Node 24.14.0:

- Backend full `uv run pytest`: 3172 tests, 131 failed. 129 of those fail
  identically on `main` (Wave4 persona/prompt/mutual-learning, embedding
  presend). The other 2 (`test_debate_voice_params`, one
  `test_preview_recovery_regressions` case) passed 3/3 when rerun alone and
  are load flakes. No Quiz, Record or migration test failed. `ruff check`,
  `ruff format --check` and `mypy app` passed.
- Frontend `pnpm -C frontend test --run`: 1155 passed, 13 skipped. Typecheck
  passed, lint has 0 errors (4 pre-existing warnings), and the production
  build passed.
- Contract scripts from AGENTS.md (frozen OpenAPI, generated contracts/WS,
  responses, document authority, Latin tables, repo boundary, route surface
  incl. `compare_route_surface.mjs`, redocly, prettier) passed.
- Migration: a database filled by `main` (0084) with a quiz and two submitted
  attempts was backed up (`pg_dump -Fc` with `pg_restore --list` OK), then
  upgraded by this branch to 0085. Rows were kept with `score_manual=0` and
  `manual_grades_json={}`, and a pre-migration attempt then graded to
  `complete`. An empty database upgraded twice and was ready.
- Browser E2E (Playwright, `next dev` and a local mock-provider backend):
  the teacher creates a quiz in the editor and publishes it with Done
  (taking stays closed), then Start evaluation; two students submit; the
  teacher sees Round 1, the key and rubric, hand-grades the text question
  (4.5 / 5, Grades saved), hides one attempt after a confirm and downloads
  the ZIP (1 attempt, hand grade included). Unscoped Records shows the chat
  Record board, which opens. `/teacher/record` and `/student/record`
  redirect, and neither sidebar has a Brainform Record row. The student sees
  their own answers, (Correct), 2.5 / 3 and the feedback, with no Key and no
  rubric, plus their chat Record board; the hidden attempt is gone for that
  student. A pause → start retest shows Round 2. A stale Pause shows "Taking
  is already paused.", not JSON. At 390px there is no horizontal scroll.

This is not a production acceptance; nothing was deployed.

## History

- 2026-11-05, MAYA-QUIZ-20261105-01 (M1–M3): domain, publish gate, student
  stripping, objective grading, Record aggregate; migration 0083.
- 2026-11-06, MAYA-QUIZ-REWORK-20261106-01 (P1/P3/P4): publish separated from
  taking, retest epochs, `quiz_id` Record filter; migration 0084.
- 2026-11-07, #375/#374: teacher ZIP export (backend/frontend).
- 2026-11-08: the frontend rework note merged into this file; migration 0085
  adds attempt detail, hand grading (no AI), hide and Record epochs; the chat
  Record moved from Brainform to Quiz Records.
- 2026-11-08 (#383/#384 with review fixes): opt-in AI grading of text items;
  no row lock or request thread held during the model call.
- 2026-11-08: real quiz delete, which takes its attempts with it. The
  Delete quiz key then moved from the Paper tab onto each list row.
- 2026-11-08 (second round): owner picked layout A, one page per quiz with
  Paper | Submissions and a single student list; the Chat tests board was
  removed from the UI (endpoints and data kept). Browser E2E on the new pages:
  list rows open their quiz; a new quiz has Submissions locked; a live quiz
  opens on Submissions, a text answer is hand-graded and saved; Paper is
  read-only with Unpublish; a two-round quiz filters by Round 2; old Records
  links redirect; the student opens a result without the key; no horizontal
  scroll at 390px.
