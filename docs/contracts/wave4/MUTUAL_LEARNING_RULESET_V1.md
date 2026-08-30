# Ordered Multi-Expert Mutual Learning V1

Status: `FROZEN / P1 REPAIRED / LOCAL G1.5 PASS / SOL G2 PENDING`

RuleSet ID: `ordered_multi_expert_mutual_learning_v1`

This is a new Mock-first protocol. It does not alter
`ordered_multi_agent_rounds_demo_v1` or `ordered_multi_agent_rounds_demo_v2`, and it
does not authorize a real Provider.

## Round phase

The pure resolver accepts `(round_no, is_final_round)` and returns the closed
`RoundPhase = opening | exchange | final_integration`:

- `round_no == 1` -> `opening`;
- `round_no > 1` and `is_final_round == false` -> `exchange`;
- `is_final_round == true` -> `final_integration`.

Inputs with `round_no < 1`, or `round_no == 1 && is_final_round` in a session whose
round count is at least two, are invalid. A configured plan computes
`is_final_round = round_no == round_count`, but the resolver itself does not own a
maximum. Mutual-learning sessions require at least two rounds. The current Demo product
may offer 2–5 rounds to bound runtime/cost; protocol semantics never branch on 2 or 5.

Two rounds map to `opening -> final_integration`; three map to
`opening -> exchange -> final_integration`; N maps to opening, N-2 exchanges and final
integration.

## Round barrier

For a turn in round `r`, Provider/generation context includes the original question,
shared public Case, current confirmed Persona, current KnowledgeSnapshot, assigned
pending question and public/final-ready turns whose `round_no < r`. It excludes every
same-round turn even if already final-ready, all future turns, every other Persona,
private snapshot/chunk and teacher note.

A–E order remains the deterministic generation/playback order, but does not change the
barrier. For this RuleSet, the persisted context IDs and transcript hash cover exactly
the prior-round visible set, not the full lower turn-index prefix used by legacy
RuleSets. Legacy fence semantics remain byte/behavior compatible behind their IDs.
The earlier general decision to retain complete previous speech means every speech in
this RuleSet-visible prior-round set, not a same-round leak; this versioned barrier is
the controlling contract.

## Phase requirements

### Opening

Each expert independently gives its understanding, professional priorities, 2–4 key
claims, own-snapshot evidence or honest general reasoning/no-match, missing
information, uncertainty and initial `position_summary`. Engagements,
answered-question IDs, other-Agent evaluation, claimed consensus and targeted questions
are forbidden.

### Exchange

Each turn answers its one required pending question when present; faithfully engages
at least one real prior-round public/final-ready claim; uses one of `agree | extend |
qualify | challenge | reconcile`; rechecks through its own snapshot; updates its
position using `unchanged | clarified | extended | qualified | partially_revised |
substantially_revised`; explains the reason and remaining uncertainty/unresolved issue;
and may ask at most one other expert one next-round question. Disagreement is never
required.

### Final integration

Each expert answers remaining assigned questions, engages at least one important
prior-round claim, records `learned_from_others`, compares opening/final position,
states a final professional judgment, preserves consensus and disagreement, classifies
each disagreement as `different_persona_or_framework | different_evidence |
evidence_conflict | insufficient_information | value_tradeoff`, records remaining
uncertainty and produces `final_recommendation`. Question must be `none`. Material new
topics not grounded in prior discussion are rejected.

## Versioned structured result

`EngagementV1` contains `target_turn_id`, optional `target_claim_id`, one closed
relation, `faithful_summary` and `response_summary`.

`KeyClaimV1` contains server-validated `claim_id`, exact `claim_text`, `claim_type =
factual | interpretation | value_judgement | proposal`, and `used_evidence_ids` drawn
only from current-request receipts.

`MutualLearningTurnResultV1` contains speech, key claims, engagements,
`answered_question_ids`, `learned_from_others`, position summary/update/reason,
`remaining_uncertainty`, optional unresolved issue, question, and final-only
`change_from_opening`, consensus, classified disagreements and recommendation. Phase
validators close required/forbidden fields. Legacy `StructuredTurnResult` is parsed
only for legacy RuleSet rows; historical JSON is not rewritten.

## Evidence and engagements

An expert may discuss another expert's public claim, but only current-participant
receipts can appear in its `used_evidence_ids`. Concrete quantities and explicit
research/expert/report attributions require a receipt. Value judgements may use honest
general reasoning with no public source. Engagement targets must exist in the visible
prior-round set; same-round, future and missing targets fail.

## Question queue

Each non-final turn asks at most one expert question; final turns ask none. Questions
carry question/source/target IDs and become eligible only in the next round. A
deterministic assignment gives each expert at most one required question per turn,
preferring the oldest unanswered question then source turn order/ID. Answered IDs are
never reassigned. Still-unanswered questions at final integration enter unresolved
questions rather than disappearing. The queue is derived from immutable structured
turns and RuleSet plan; no Provider selects assignments.

## Deterministic Mock synthesis

After all final-integration turns are public/final-ready, a pure synthesis module
derives `MutualLearningSynthesisV1`: direct answer, consensus, complementary views,
remaining classified disagreements, position changes, evidence conflicts, remaining
uncertainty and recommended next steps. It uses only public structured fields and used
evidence lineage. It does not vote facts, force consensus, invent facts or read private
Persona/RAG. The first implementation is deterministic Mock and makes no external
call.

## Public compatibility

New Debate creation explicitly selects the new RuleSet and `round_count` 2–5. Existing
creation defaults and all persisted legacy IDs retain two-round semantics. Public DTOs
add the new RuleSet ID, dynamic positive round numbers and optional versioned
mutual-learning fields/synthesis; old payloads remain valid. WebSocket round/turn
payloads accept the dynamic round number and optional phase/round-count without
changing event names. Replay reads frozen text/audio and never regenerates.

## Acceptance

The required matrix is 2×2, 3×3 and 5×5; no new-rule business branch may compare
`round_no == 2` or use an `else` meaning round two. Tests cover barrier isolation,
engagement targets/relations, required/final fields, own-snapshot evidence,
general-reasoning no-source, one-time question assignment, old RuleSet playback/Replay,
dynamic plans, DTO/WS/generated client and complete local backend/frontend checks.
