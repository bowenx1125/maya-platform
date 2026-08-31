# Wave 4 Contract Set

Status: `G0-S PASS / PERSONA MOCK PASS / MOCK G2 SOL PASS / REAL EMBEDDING 1024 PREFLIGHT FAILED / LLM-A G0 DELTA CANDIDATE`

These files freeze the pre-code contract for Issue #8. They distinguish three layers:

1. product semantics that every Provider must obey;
2. server-only external-data, usage and failure controls;
3. Gate-specific authorization for Mock, implementation and real-service evidence.

Ordinary browser DTOs expose no supplier identity, model ID, external resource ID, raw
usage ledger, price table, key, endpoint or private path. The dedicated teacher-only
ProviderDataCallV1 disclosure may show the approved supplier display name, region,
purpose, outbound data classes and storage/no-training/retention facts plus exact
policy/manifest/revision CAS. It never shows model IDs, endpoints, workspace or
resource IDs, credentials, private paths, raw ledgers or raw supplier responses. No Wave 4 product implementation or
real Provider request started before Sol High G0-S returned
`PASS / P0=0 / P1=0 / P2=0` on contract candidate `c5604fd`. Mock-first implementation
is now authorized; each real Provider remains separately gated.

Official supplier facts recorded in this contract were checked on 2026-08-30. They are
inputs to a frozen Gate, not a promise that a supplier will keep a model or price
available. Any unavailable model, changed price basis or changed regional behavior
fails preflight and requires an explicit contract revision; there is no silent
`latest` fallback.

W4-LLM-A design is additionally specified by:

- `LLM_A_RUNTIME_V1.md` — exact Beijing wire, privacy, durable runner, budget,
  confirmation and atomic publication rules;
- `LLM_TURN_OUTPUT_SCHEMA_V1.json` — the complete strict Provider-output schema whose
  references are mapped to server-owned IDs after validation.
- `LLM_REPAIR_FEEDBACK_V1.json` — the only server-authored code/pointer grammar allowed
  to alter the canonical user message on a confirmed structure-repair attempt.
