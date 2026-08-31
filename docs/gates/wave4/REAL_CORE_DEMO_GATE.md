# Real-Core Demo Gate

Status: `REAL-EMBED-R0 CHANGES_REQUIRED / P0=0 / P1=2 / REAL-CORE CALLS 0`

Every task in this Gate is classified before execution. Only `DEMO-BLOCKER` work may
delay Demo V1. Everything else belongs to the Wave 4.1 Post-Demo Hardening backlog.

## Demo composition

| Component | Demo V1 mode |
| --- | --- |
| Embedding | Real DashScope `text-embedding-v4` at 1024 |
| Debate LLM | Real fixed Qwen structured output |
| TTS | Mock |
| Voice | Mock |
| Translation | Mock |
| Maya Report | Mock |

The browser and delivery report must expose this Real/Mock composition without exposing
model IDs, endpoints, workspace IDs, credentials or raw Provider responses.

## REAL-EMBED-R0 design audit

Sol High reviewed clean integration candidate
`debbf8ef3d0df2f20013e9bd44e48d3eb1c2ceb0` and returned
`CHANGES_REQUIRED / P0=0 / P1=2`:

1. `DEMO-BLOCKER`: an empty runtime has no reviewed persisted ProviderPolicySnapshot
   and no safe policy-import entry. The importer must persist only non-secret reviewed
   policy/control data, reject incomplete or unreviewed input, be idempotent and never
   print credentials.
2. `DEMO-BLOCKER`: there is no frozen identity-free Chinese one-chunk fixture, SHA
   manifest and product E2E driver. The fixture must stay below 600 whitespace tokens,
   produce exactly one chunk and freeze the topic plus expected Chinese matching terms.

No product Provider request may occur until both findings receive Sol P0/P1 closure.

## Minimal Real Embedding E2E

1. Start from an empty runtime with every Provider set to Mock.
2. Create/publish one Mock control Agent and create one target Agent through product APIs.
3. Upload the frozen Chinese Markdown, compile and confirm its Persona.
4. Review account controls and import the non-secret exact policy. Switch only Embedding
   to DashScope; LLM/TTS/Voice/Translation remain Mock.
5. First target publish creates the exact Snapshot manifest and returns
   `provider_confirmation_required`; real call count remains `0`.
6. Teacher reads and confirms that exact AgentVersion disclosure.
7. Student repeats the same idempotent publish operation. Send exactly one Snapshot
   batch with `parameters.dimension=1024`; publish one immutable real Snapshot.
8. Teacher creates a two-Agent, two-round Debate with the real Agent first. Start creates
   the opening query manifest and parks before transport; cumulative real calls remain `1`.
9. Teacher confirms the exact query disclosure and explicitly retries preparation.
10. Send exactly one opening-query batch. Mock LLM/TTS completes the turn. Verify
    `matched`, the real Snapshot/chunk TurnSource and a non-empty Evidence Receipt/Trace;
    then stop without advancing to another turn.

## Call cap and stop conditions

Real product call cap for REAL-EMBED-E2E: exactly `2` maximum.

- Snapshot embedding: at most `1` request.
- Opening query embedding: at most `1` request.
- No automatic retry is authorized for this acceptance run.

Stop with no further call if policy/account controls, fixture hash, Persona, manifest,
confirmation, endpoint, budget, response shape/order/dimension or publication identity
does not match. A Snapshot transport/acceptance failure stops before query. A query
failure, `no_match`, wrong Snapshot/chunk or missing Evidence Trace is an E2E failure;
the fixture must not be changed to manufacture a pass.

The historical failed 1024 preflight is not repeated and is not part of this two-call
product budget.

## Remaining Real-Core work packages

- `DEMO-BLOCKER — REAL-LLM-E2E`: 2–3 confirmed Agents, own RAG, two complete rounds.
- `DEMO-BLOCKER — BROWSER-E2E`: empty-runtime create-to-Replay product chain.
- `DEMO-BLOCKER — DEMO-PACKAGE`: fixed assets, startup/reset/recovery and Real/Mock
  disclosure.
- one final exact-SHA GitHub PR/CI.

Distributed recovery, repeated restarts, broad recall evaluation, multiple real
Snapshots/queries, corruption repair and generic Provider frameworks are explicitly
`POST-DEMO-HARDENING`.
