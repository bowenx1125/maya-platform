# Maya Contract Map

## Current machine authority

- [`../../contracts/openapi-v0.1.yaml`](../../contracts/openapi-v0.1.yaml)
- [`../../contracts/ws-events.v1.schema.json`](../../contracts/ws-events.v1.schema.json)
- generated frontend client and route/response/schema checks in `scripts/`

These files and `docs/PROJECT.md` override historical
pre-code snapshots.

## Historical baseline

outside the product repository. They explain the baseline but contain dated statuses
and paths. They are not the current machine contract and must not override later Wave
Gate packets.

## Debate generation contracts

[`DEBATE_GENERATION_CONTRACTS.md`](DEBATE_GENERATION_CONTRACTS.md) is the frozen
behaviour of the real Debate path — Persona, formal content, embedding identity,
evidence trace, the mutual-learning RuleSet, the prompt budget, the provider
control ledger and the LLM turn runtime. It was ten files in a `wave4/`
directory; splitting one subject across a directory only made it harder to read.

The machine-readable schemas it describes live in `contracts/` beside the frozen
OpenAPI, because they are runtime assets rather than prose.
