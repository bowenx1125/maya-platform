# ADR-011: Classroom Quiz as a parallel assessment domain

Status: ACCEPTED  
Date: 2026-11-05  
Ticket: MAYA-QUIZ-20261105-01

## Context

Formal chat assessments persist attempts in `assessment_attempts` with
`source_conversation_id` **NOT NULL** and a foreign key to
`agent_conversations`. Classroom questionnaire quizzes must:

- accept one POST of answers with **zero LLM / zero Agent WebSocket** calls;
- avoid fabricating a conversation just to satisfy the chat attempt ledger;
- keep historical chat Record rows readable.

Hard-wiring quiz submits into `assessment_attempts` would reintroduce per-turn
conversation traffic and couple questionnaire grading to Team recipe / chat
finalizers.

## Decision

Introduce a **parallel Quiz domain**:

- `classroom_quizzes` — course-scoped draft/published papers with
  `document_json`, `content_revision`, and publish timestamps.
- `classroom_quiz_attempts` — one submitted attempt per student per quiz,
  storing `document_snapshot_json`, objective scores, and answers. **No**
  conversation FK.

Student-facing DTOs **strip** `answer` / `rubric` keys. Published papers are
immutable until Unpublish → edit → Done (publish). Subjective AI grading is
out of v1 (`grading_status=pending|mixed`).

Record aggregation exposes `source: "quiz" | "chat"` so UI can merge both
ledgers without migrating chat rows.

## Consequences

- New Alembic revision `0083_classroom_quizzes`; `ALEMBIC_HEAD` advances.
- Learning/chat attempt APIs remain unchanged; Quiz routes live under
  `/api/v1/courses/{course_id}/quizzes` and `/record-attempts`.
- Frontend (编码B/C) consumes frozen Quiz DTOs; must not call Agent WS on the
  student answer path.

## Amendments

- 2026-11-06 (`0084_quiz_taking_open_retest`): an attempt is unique per
  student per quiz **per taking epoch**, not per quiz; each start-taking from
  a closed state opens a new epoch (retest).
- 2026-11-08 (`0085_quiz_manual_grading`): teachers grade text items by hand,
  with no model call, against each attempt's frozen paper. `score_objective`
  stays automatic and `score_manual` holds the hand grades. Teachers can hide
  an attempt, and the formal chat-assessment Record moved from Brainform to
  the Quiz Records pages, its data unchanged. Current behavior:
  [Classroom Quiz contract](../contracts/CLASSROOM_QUIZ_API.md).
