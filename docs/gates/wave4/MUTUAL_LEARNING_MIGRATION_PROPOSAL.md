# W4 Mutual Learning Migration Proposal

Status: `USER AUTHORIZATION REQUIRED / IMPLEMENTATION NOT STARTED / REAL CALLS 0`

Task: `W4-MUTUAL-LEARNING-RULESET`

## Blocking fact

The current SQLite/SQLAlchemy schema enforces named constraint
`ck_debate_turns_round: round_no >= 1 AND round_no <= 2` in both the model and migration 0004. API, playback DTOs and generators also cap the value at two, but those are code
changes; the database constraint makes a 3- or 5-round persisted Debate impossible.

Reusing round 1/2, hiding a second counter in JSON or disabling SQLite checks would
corrupt semantics and violate the requested compatibility boundary. Implementation is
therefore stopped before Luna/code work.

## Proposed migration 0008

Add `0008_wave4_mutual_learning_rounds.py`, down-revision
`0007_wave3_interaction_report`.

Upgrade uses SQLite-safe Alembic `batch_alter_table(..., recreate="always")` to replace
only `ck_debate_turns_round` with `round_no >= 1`. The RuleSet's immutable
`rule_snapshot_json` owns each Debate's configured `round_count`; the database stores a
positive protocol round and does not encode today's product maximum of five.

No column, legacy row, RuleSet ID, turn index, structured JSON, source, audio, timestamp,
foreign key, unique constraint or index changes. No old turn is backfilled or rewritten.
New synthesis is deterministically derived from existing versioned `structured_json`,
so it needs no new table.

Downgrade first checks for `round_no > 2`. If any exists, it aborts with an explicit
lossless-downgrade error before table recreation. If all rows are legacy-compatible, it
restores the original named `1..2` constraint. It never deletes or renumbers turns.

## Migration verification

- empty 0001→0008 upgrade and repeated head upgrade;
- populated 0001→0007→0008 fingerprints for all existing Debate/turn/source/playback
  rows, foreign keys, indexes and named constraints;
- insert round 3/5 succeeds after 0008; round 0 still fails;
- legacy-only downgrade to 0007 and re-upgrade is lossless;
- downgrade with a round >2 fails before data/schema mutation;
- old v1/v2 two-round Debate read, playback and Replay tests remain unchanged;
- product max-round validation lives in the new RuleSet/API, not the database check.

## Implementation ownership after authorization

Main window owns migration/model, shared OpenAPI/WS/generated client, root status and
final integration. Luna Max owns the new pure round/policy/validator/synthesis modules,
versioned Mock generation, setup/playback adapters, frontend rule/round controls and
assigned tests. Sol High remains read-only for code audit.

Intermediate iterations use local tests and Sol audit only. No intermediate GitHub CI
is required. Before the one final Wave 4 PR, the workflow trigger will be narrowed to
`pull_request` plus manual dispatch so the final PR head runs one CI; after PASS the
exact audited head will fast-forward canonical main, avoiding a second merge-SHA run.

## Requested authorization

Authorize exactly the 0008 constraint replacement and its lossless tests above. This
does not authorize any other schema change or real Provider call.
