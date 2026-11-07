# Maya Contract Map

## Current machine authority

- [`../../contracts/openapi-v0.1.yaml`](../../contracts/openapi-v0.1.yaml)
- [`../../contracts/ws-events.v1.schema.json`](../../contracts/ws-events.v1.schema.json)
- generated frontend client and route/response/schema checks in `scripts/`

These files and `docs/PROJECT.md` override historical
pre-code snapshots.

## Classroom Quiz

[`CLASSROOM_QUIZ_API.md`](CLASSROOM_QUIZ_API.md) is the single Quiz contract:
routes, permissions, publish/taking states, retest epochs, grading, student
answer isolation, Record aggregation, the attempt ZIP export, the teacher and
student controls, and known gaps with evidence. Quiz routes sit outside the
frozen OpenAPI; they are classified in
[`../../contracts/route-surface-placeholders.json`](../../contracts/route-surface-placeholders.json).
[`../../contracts/quiz-document.v1.schema.json`](../../contracts/quiz-document.v1.schema.json)
describes the stored paper, and
[ADR-011](../adr/ADR-011-classroom-quiz-parallel-domain.md) records why Quiz is a
separate domain. [`CLASSROOM_QUIZ_REWORK_FE.md`](CLASSROOM_QUIZ_REWORK_FE.md) is
the merged 2026-11-06 frontend brief, kept only as a pointer and a dated scope
record.

## Knowledge and generation contracts

[`KNOWLEDGE_SETS_CONTRACT.md`](KNOWLEDGE_SETS_CONTRACT.md) describes K1's shared
Set/Asset store, immutable versions, source authority and student Question
projection.

[`KNOWLEDGE_GENERATION_CONTRACT.md`](KNOWLEDGE_GENERATION_CONTRACT.md) records
the current generation Tool/intent, exact authorization, durable jobs and canonical-version boundary.
[`MAYAFORM_V14_GENERATION_AND_TOOLS.md`](MAYAFORM_V14_GENERATION_AND_TOOLS.md)
records the latest user-approved K2b2/K3/K4 trigger, Tool and provenance
decisions; its unimplemented obligations are not release claims.

[`DEBATE_GENERATION_CONTRACTS.md`](DEBATE_GENERATION_CONTRACTS.md) retains Debate
Persona, embedding, evidence, ledger and wire-schema details. Historical budget
estimates and preflight gates in it do not override the current unbounded accounting
rules, authorization or four-round contract.

[`FOUR_ROUND_PROMPTS.md`](FOUR_ROUND_PROMPTS.md) records the current four-round
prompt examples. Completed Wave plans are deliberately not retained here; current
scope and verification live in `docs/PROJECT.md`.

The machine-readable schemas it describes live in `contracts/` beside the frozen
OpenAPI, because they are runtime assets rather than prose.

## Historical validation records

`docs/validation/` holds dated MayaForm v1.4 evidence. None of it is a current
release gate or acceptance status; current progress is in
[`../PROJECT.md`](../PROJECT.md).

- [`MAYAFORM_V14_INTEGRATED_ACCEPTANCE.md`](../validation/MAYAFORM_V14_INTEGRATED_ACCEPTANCE.md):
  the BF/AT/RS requirements adopted on 2026-10-03, all NOT_RUN as recorded.
- [`MAYAFORM_V14_SUPPLEMENT.md`](../validation/MAYAFORM_V14_SUPPLEMENT.md): the
  S01–S22 coverage map of test entry points, not PASS claims.
- [`mayaform-v14-resume-inputs.json`](../validation/mayaform-v14-resume-inputs.json):
  a fingerprint of the `feat/mayaform-v14` resume inputs (base
  `1b1bfcae73feeb2765a0b838bf967e8874a333fb`, committed in `f59df827`). Its
  sha256 values are not current hashes, and no script checks them.
