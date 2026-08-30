# Wave 4 G0 Teaching and Provider Contract Gate

Gate: `w4-g0-2026-08-30`

Status: `G0-S PASS / MOCK-FIRST PRODUCT CODE AUTHORIZED / REAL CALLS 0`

Issue: `#8 W4-G0: freeze teaching, Persona, Evidence, Prompt and Provider contracts`

## Goal

Freeze the teaching causality, complete-history Prompt, evidence provenance, formal
content, external data, model, call/cost and failure contracts before implementation.

## Owned files

- `docs/contracts/wave4/**`;
- this Gate Packet;
- links/status in `docs/contracts/README.md`, `PROJECT_STATUS.md` and named ADRs.

No product code, database migration, OpenAPI, WebSocket schema, public DTO, generated
client, Provider selector or secret/configuration value is in scope.

## Acceptance

- the six Wave 4 contract files answer all 17 required questions;
- strict Persona grammar cannot invent or silently omit content;
- every predecessor speech remains complete and appears exactly once per LLM request;
- raw Persona and platform rule duplication are forbidden;
- Evidence Trace distinguishes lineage from truth and hides unused receipts;
- fixed resources, allowed external fields, caps, retries and uncertain outcomes are
  explicit;
- all new Mock/real W4 debates reject unconfirmed legacy Persona through one stable
  path; existing output remains read/replay-only;
- real embedding uses a teacher-confirmed immutable pre-provider SnapshotBuild and
  publishes a new Snapshot only after validated success;
- every real request atomically reserves count/max-cost before I/O and has
  crash-recoverable accepted-unknown semantics;
- supplier storage/no-training terms, account product, Beijing endpoint and optional
  logging/backflow controls are verified and bound to teacher export confirmation;
- no numeric Token-reduction KPI and no cost-display product task returns;
- formal content is honestly not yet frozen and blocks real embedding;
- document authority, links, format and repository/secret boundaries pass;
- existing deterministic product suite remains green;
- independent Sol High G0-S returns `PASS / P0=0 / P1=0` on the exact candidate;
- real calls remain zero.

## Sol High G0-S challenge

Sol is read-only and must challenge, at minimum:

1. teaching causality and Persona omission/invention behavior;
2. full-history preservation versus duplicate removal;
3. claim/source provenance without overstated truth;
4. external student/teacher/RAG data and regional Provider boundary;
5. model/version availability, count/cost caps and pre-send enforcement;
6. retry, timeout, accepted-unknown and immutable-snapshot recovery;
7. legacy AgentVersion behavior and Gate ordering.

Any P0/P1 returns the packet to the main window for repair and exact re-audit. A PASS
authorizes only the next Mock-first implementation Issues. Real calls begin no earlier
than the W4-EMBED G3 boundary in `G0_DECISIONS.md`.

## G0-S evidence

- exact audited contract candidate: `c5604fd9aff8533962d653f869b326b8a0a94825`;
- independent Sol High: `PASS / P0=0 / P1=0 / P2=0`;
- five P1 findings were repaired before PASS: legacy Persona path, pre-provider
  SnapshotBuild lifecycle, embedding item/batch limits, atomic request reservations and
  supplier storage/account-plan policy preflight;
- local document authority, Prettier, repository/secret boundary and diff checks: PASS;
- user changed the Wave 4 process after G0-S: intermediate loops use local tests plus
  Sol audit, and GitHub CI runs once on the complete final integration PR;
- real Provider calls through G0-S: `0`.
