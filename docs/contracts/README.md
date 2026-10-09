# Maya Contract Map

## Current machine authority

- [`../../contracts/openapi-v0.1.yaml`](../../contracts/openapi-v0.1.yaml)
- [`../../contracts/ws-events.v1.schema.json`](../../contracts/ws-events.v1.schema.json)
- generated frontend client and route/response/schema checks in `scripts/`

These files and `docs/PROJECT.md` override historical
pre-code snapshots.

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
