# Wave 4 Contract Set

Status: `G0-S PASS / MOCK G1.5 PASS / SOL G2 FOURTH P1 REPAIR / REAL CALLS 0`

These files freeze the pre-code contract for Issue #8. They distinguish three layers:

1. product semantics that every Provider must obey;
2. server-only external-data, usage and failure controls;
3. Gate-specific authorization for Mock, implementation and real-service evidence.

No browser DTO exposes supplier identity, model ID, external resource ID, raw usage
ledger, price table, key, endpoint or private path. No Wave 4 product implementation or
real Provider request started before Sol High G0-S returned
`PASS / P0=0 / P1=0 / P2=0` on contract candidate `c5604fd`. Mock-first implementation
is now authorized; each real Provider remains separately gated.

Official supplier facts recorded in this contract were checked on 2026-08-30. They are
inputs to a frozen Gate, not a promise that a supplier will keep a model or price
available. Any unavailable model, changed price basis or changed regional behavior
fails preflight and requires an explicit contract revision; there is no silent
`latest` fallback.
