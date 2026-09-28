# Maya Contract Map

## Current machine authority

- [`../../contracts/openapi-v0.1.yaml`](../../contracts/openapi-v0.1.yaml)
- [`../../contracts/ws-events.v1.schema.json`](../../contracts/ws-events.v1.schema.json)
- generated frontend client and route/response/schema checks in `scripts/`

These files and `docs/PROJECT.md` override historical
pre-code snapshots.

## Debate generation contracts

[`KNOWLEDGE_SETS_CONTRACT.md`](KNOWLEDGE_SETS_CONTRACT.md) describes K1's shared
Set/Asset store, immutable versions, source authority and student Question
projection.

[`DEBATE_GENERATION_CONTRACTS.md`](DEBATE_GENERATION_CONTRACTS.md) is the frozen
behaviour of the real Debate path — Persona, formal content, embedding identity,
evidence trace, the mutual-learning RuleSet, the prompt budget, the provider
control ledger and the LLM turn runtime. It was ten files in a `wave4/`
directory; splitting one subject across a directory only made it harder to read.

[`FOUR_ROUND_PROMPTS.md`](FOUR_ROUND_PROMPTS.md) records the current four-round
prompt examples. Completed Wave plans are deliberately not retained here; current
scope and verification live in `docs/PROJECT.md`.

The machine-readable schemas it describes live in `contracts/` beside the frozen
OpenAPI, because they are runtime assets rather than prose.
