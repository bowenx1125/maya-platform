# ADR-005: Claim-level evidence provenance

Status: `ACCEPTED / NOT IMPLEMENTED`

Key generated claims will bind to immutable `TurnSource` rows or explicitly use general
reasoning/no-match. The server validates exact claim text, derives speech spans and
source locations, and rejects cross-snapshot or unused evidence. This is provenance and
teaching explanation, not automatic factual verification. The closed record and
support rules are frozen in
[`../contracts/DEBATE_GENERATION_CONTRACTS.md`](../contracts/DEBATE_GENERATION_CONTRACTS.md#evidence-trace).
