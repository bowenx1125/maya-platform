# Wave 4 Mock-First G1.5 Gate Packet

Status: `LOCAL G1.5 PASS / INDEPENDENT SOL G2 PENDING / REAL CALLS 0`

## Scope

This candidate integrates Issues #10–#16 without a real Provider request:

- `ordered_multi_expert_mutual_learning_v1`, dynamic 2–5 rounds and a strict
  same-round barrier;
- deterministic PersonaSpecV1 compilation, confirmation, versioning and teaching
  comparison;
- EvidenceTraceV1 claim/query/chunk/span lineage and public inspector;
- PromptRequestV1/PromptBudgetV1 with one rules message, one canonical user message,
  complete prior-round speech and frozen repair semantics;
- frozen formal TikTok content;
- immutable SnapshotBuild and real-ready/fake-transport Embedding ports;
- server-only policy/export/budget/operation ledgers with durable SQLite reservation.

Real Embedding publication, a real LLM adapter, real TTS recovery and every billed
request remain outside this Gate.

## Compatibility

- Legacy RuleSet v1/v2 semantics and historical Replay are not rewritten.
- Legacy AgentVersion rows remain nullable and are not backfilled with a Persona.
- New mutual-learning Debates require a confirmed Persona; legacy RuleSets remain
  usable with their historical published versions.
- Migrations 0008–0011 are append-only. Lossy downgrade is refused for round >2,
  populated Persona/provider-control rows and retained EvidenceTrace rows.

## Local evidence

- backend: `528 passed`;
- frontend: `31 files / 203 tests passed`;
- mypy `133` source files, Ruff, ESLint, TypeScript and Prettier: pass;
- Next production build: pass;
- OpenAPI: `71` operations, generated client and strict FastAPI comparison: pass;
- WebSocket: `35` positive / `18` negative; commands `6/7`; results `5/6`;
- document authority, repository/secret boundary and generated-source red-team probe:
  pass;
- migrations 0001–0011, including Wave 4 round and EvidenceTrace lossless probes:
  pass;
- formal content: corpus hash
  `7fab29d2bddc241ea2021284f2766e6e6cecb705b9a56ff041838c1fe606c24a`,
  relevant matched, adjacent/unrelated no-match: pass;
- real Provider/network calls: `0`.

## G2 audit questions

Sol High must return `PASS | CHANGES_REQUIRED` with P0/P1/P2 counts and inspect at
least:

1. no new-rule fixed-round-two assumption or same-round context leak;
2. Persona raw/structured hash, confirmation CAS, publish/reset and legacy boundaries;
3. server-derived claim IDs, exact UTF-16 spans, own-snapshot receipts, honest no-match
   and Replay/history identity;
4. actual provider-visible Prompt bytes: no raw AGENT.md, teacher note, filename,
   snapshot/private metadata, duplicate rule block or duplicate evidence excerpt;
5. retrieval reuse and accepted/not-sent/acceptance-unknown retry classification;
6. SQLite atomic provider reservation, unique attempt tuple and migration safety;
7. OpenAPI/WS/generated-client compatibility and provider-neutral browser DTOs.

Any P0/P1 blocks the corresponding later real Provider Gate. A worker cannot sign its
own implementation.
