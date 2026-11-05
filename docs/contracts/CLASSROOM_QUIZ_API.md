# Classroom Quiz API (M1–M3 freeze for 编码B)

Ticket: MAYA-QUIZ-20261105-01  
Module: `backend/app/modules/quiz`  
JSON Schema: `contracts/quiz-document.v1.schema.json`  
ADR: `docs/adr/ADR-011-classroom-quiz-parallel-domain.md`

All paths are under `/api/v1`. Mutations require session + `X-CSRF-Token`.

## Teacher

| Method | Path | Op | Notes |
|---|---|---|---|
| GET | `/courses/{course_id}/quizzes` | `listCourseQuizzes` | Draft + published |
| POST | `/courses/{course_id}/quizzes` | `createCourseQuiz` | Body: `CreateQuizRequest` |
| GET | `/courses/{course_id}/quizzes/{quiz_id}` | `getCourseQuiz` | Teacher DTO **includes** `items[].answer` |
| PATCH | `/courses/{course_id}/quizzes/{quiz_id}` | `patchCourseQuiz` | Draft only; published → **409** `quiz_published_immutable` |
| POST | `.../publish` | `publishCourseQuiz` | Done; bumps `content_revision` |
| POST | `.../unpublish` | `unpublishCourseQuiz` | Required before edit |
| GET | `/courses/{course_id}/record-attempts` | `listCourseRecordAttempts` | Teacher aggregate; `source` |

## Student

| Method | Path | Op | Notes |
|---|---|---|---|
| GET | `/courses/{course_id}/quizzes` | `listCourseQuizzes` | **Published only** |
| GET | `/courses/{course_id}/quizzes/{quiz_id}` | `getCourseQuiz` | `StudentQuizDTO`: **no** `answer` / `rubric` keys |
| POST | `.../attempts` | `submitCourseQuizAttempt` | One shot; zero LLM |
| GET | `/courses/{course_id}/my-record-attempts` | `listMyRecordAttempts` | `source: quiz\|chat` |

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
