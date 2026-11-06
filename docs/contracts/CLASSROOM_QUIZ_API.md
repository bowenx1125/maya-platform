# Classroom Quiz API (M1–M3 freeze for 编码B)

Ticket: MAYA-QUIZ-20261105-01  
Module: `backend/app/modules/quiz`  
JSON Schema: `contracts/quiz-document.v1.schema.json`  
ADR: `docs/adr/ADR-011-classroom-quiz-parallel-domain.md`

All paths are under `/api/v1`. Mutations require session + `X-CSRF-Token`.

## Teacher

| Method | Path                                     | Op                         | Notes                                                      |
| ------ | ---------------------------------------- | -------------------------- | ---------------------------------------------------------- |
| GET    | `/courses/{course_id}/quizzes`           | `listCourseQuizzes`        | Draft + published                                          |
| POST   | `/courses/{course_id}/quizzes`           | `createCourseQuiz`         | Body: `CreateQuizRequest`                                  |
| GET    | `/courses/{course_id}/quizzes/{quiz_id}` | `getCourseQuiz`            | Teacher DTO **includes** `items[].answer`                  |
| PATCH  | `/courses/{course_id}/quizzes/{quiz_id}` | `patchCourseQuiz`          | Draft only; published → **409** `quiz_published_immutable` |
| POST   | `.../publish`                            | `publishCourseQuiz`        | Done; bumps `content_revision`                             |
| POST   | `.../unpublish`                          | `unpublishCourseQuiz`      | Required before edit                                       |
| GET    | `/courses/{course_id}/record-attempts`   | `listCourseRecordAttempts` | Teacher aggregate; `source`                                |

## Student

| Method | Path                                      | Op                        | Notes                                             |
| ------ | ----------------------------------------- | ------------------------- | ------------------------------------------------- |
| GET    | `/courses/{course_id}/quizzes`            | `listCourseQuizzes`       | **Published only**                                |
| GET    | `/courses/{course_id}/quizzes/{quiz_id}`  | `getCourseQuiz`           | `StudentQuizDTO`: **no** `answer` / `rubric` keys |
| POST   | `.../attempts`                            | `submitCourseQuizAttempt` | One shot; zero LLM                                |
| GET    | `/courses/{course_id}/my-record-attempts` | `listMyRecordAttempts`    | `source: quiz\|chat`                              |

## Submit body

```json
{
  "answers": [
    { "item_id": "q1", "choice_ids": ["a"] },
    { "item_id": "q2", "choice_ids": ["a", "c"] },
    { "item_id": "q3", "text": "..." }
  ]
}
```

Objective: `single` / `multiple` set equality (unordered). Subjective → `grading_status=pending|mixed`.

## StudentQuizDTO guarantee

Response JSON for student GET must not contain keys `answer` or `rubric` at any item. Pytest asserts key absence.

## Rework 2026-11-06 (MAYA-QUIZ-REWORK-20261106-01, P1/P3/P4)

Publishing and taking are now separate states. **Publish ≠ open for taking.**

### New fields

- `QuizSummaryDTO` / `TeacherQuizDTO` / `StudentQuizDTO`:
  - `taking_open: bool` — is the paper currently open for submissions.
  - `taking_epoch: int` — how many times the paper has been opened for taking (starts at 0).
- `QuizAttemptDTO`: `taking_epoch: int` — the epoch this attempt was submitted in.

### New endpoints (teacher only, CSRF)

| Method | Path                                                  | Op                      | Behavior                                                                                                                                            |
| ------ | ----------------------------------------------------- | ----------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| POST   | `/courses/{course_id}/quizzes/{quiz_id}/start-taking` | `startCourseQuizTaking` | Requires `status=published`. If `taking_open=false`: `taking_epoch += 1`, `taking_open=true`. If already open → **409** `quiz_taking_already_open`. |
| POST   | `/courses/{course_id}/quizzes/{quiz_id}/pause-taking` | `pauseCourseQuizTaking` | Requires `status=published`. Sets `taking_open=false` (epoch unchanged). If already closed → **409** `quiz_taking_already_closed`.                  |

### State rules

- `publish`: keeps `taking_open=false`; never auto-opens taking. `taking_epoch` unchanged.
- `unpublish`: forces `taking_open=false`.
- `pause-taking` keeps `taking_epoch` unchanged. Every `start-taking` from a closed state increments `taking_epoch` by exactly 1, so pause → start = retest with a new epoch.

### Retest rules (P4)

- Submit requires `status=published` **and** `taking_open=true`; otherwise **409** `quiz_taking_closed` (or **404** if not published).
- A student may submit once per `(quiz_id, actor_user_id, taking_epoch)`. A second submit in the same epoch → **409** `quiz_attempt_exists`.
- Teacher retest flow: `pause-taking` → `start-taking` → the epoch increments (each new open = new epoch), so every student may take the quiz again. Old attempts remain in Record.
- DB: `classroom_quiz_attempts.taking_epoch` (NOT NULL, default 0); unique constraint `ux_classroom_quiz_attempts_quiz_actor_epoch` on `(quiz_id, actor_user_id, taking_epoch)` replaces `ux_classroom_quiz_attempts_quiz_actor`. Migration `0084_quiz_taking_open_retest`.

### Record filter (P1)

Both `GET /courses/{course_id}/record-attempts` and `GET /courses/{course_id}/my-record-attempts` accept an optional query `quiz_id` (UUID). When provided, only quiz-source attempts of that quiz are returned (chat-source rows are excluded). Without it, behavior is unchanged (mixed quiz + chat rows).
