# ADR-005: Claim-level evidence provenance

Status: `ACCEPTED / NOT IMPLEMENTED`

Key generated claims will bind to immutable `TurnSource` rows or explicitly use general
reasoning/no-match. The server validates exact claim text, derives speech spans and
source locations, and rejects cross-snapshot or unused evidence. This is provenance and
teaching explanation, not automatic factual verification.
