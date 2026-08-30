# EvidenceTraceV1

Status: `FROZEN / P1 REPAIRED / SOL G2 PASS / REAL CALLS 0`

## Meaning

Evidence Trace proves generation lineage: which query returned which immutable chunk
and which validated speech claim selected it. It does not prove that a source or model
claim is factually correct. The UI must use “supports/used as context”, never
“fact-checked/verified true”.

## Closed records

Every retrieval subquery has a server UUID, kind, exact text, exact hash, turn ID and
snapshot ID. Every receipt adds the immutable evidence ID, chunk ID, source filename,
source locator, excerpt, score, rank and threshold key. The Provider receives query
and evidence IDs plus the necessary excerpt; it cannot assign IDs.

`source_locator` is server-derived as
`md:<source-document-uuid>:chars:<start>-<end>`, where offsets are half-open Unicode
code-point offsets into the normalized immutable Markdown source. The browser resolves
the authorized document UUID to its display filename; the locator sent to or returned
by a Provider never contains a local path.

Every key claim produces one or more trace rows:

```json
{
  "trace_version": "evidence_trace_v1",
  "turn_id": "uuid",
  "claim_id": "uuid",
  "claim_text": "exact speech slice",
  "claim_type": "factual | background | value_judgement | proposal",
  "query_id": "uuid | null",
  "query_kind": "viewpoint | pending_question | rebuttal | updated_position | context | null",
  "query_text": "string | null",
  "evidence_id": "uuid | null",
  "chunk_id": "uuid | null",
  "source_filename": "string | null",
  "source_locator": "string | null",
  "support_mode": "direct | contextual | general_reasoning | no_match",
  "speech_span": { "start_utf16": 0, "end_utf16": 0 }
}
```

Offsets are half-open UTF-16 code-unit offsets so browser slicing is exact. The server
derives the final span by matching the Provider-returned exact `claim_text` to speech;
ambiguous or non-exact matches fail validation. `claim_id` is server-derived after
validation. Multiple rows may share one claim ID when multiple actually used evidence
items support it.

## Coverage and support rules

- the Provider returns 1–12 teaching claims that cover the turn's central position,
  each new argument and each factual/background assertion containing a concrete
  quantity or explicit source attribution;
- the current server factual-pattern validator remains a lower bound. Every sentence
  it flags must be contained by a factual/background trace with `direct` evidence;
- `direct` means the excerpt directly addresses the claim; `contextual` means it only
  supplies background. Neither label asserts independent truth;
- factual quantities and claims attributed to experts, studies, surveys or reports
  require `direct` evidence;
- value judgements and proposals may use `general_reasoning` with all evidence/source
  fields null;
- `no_match` is used only when the frozen retrieval result contains no qualifying
  receipt. It has no evidence/source and is displayed as “No relevant evidence found;
  this claim is general reasoning”;
- when receipts exist but a claim does not use them, the claim uses
  `general_reasoning`, not `no_match`;
- a claim cannot cite a receipt from another AgentVersion/KnowledgeSnapshot;
- every public source must be referenced by at least one validated claim, and every
  evidence-bearing claim must resolve to a persisted used receipt;
- unused receipts are private audit data and never enter the public source list;
- one whole speech cannot be bound wholesale to one source unless its single exact
  claim span truly covers the whole speech and passes the same rules.

## Persistence and teaching UI

Turn, query, receipt, claim and span rows commit atomically with final-ready text before
TTS/publication. Replay, report input and history read the same immutable trace; they do
not regenerate it. A claim inspector shows the highlighted speech, retrieval reason,
query, source locator/excerpt and support mode. General reasoning and no-match displays
an empty source list.

For the strict Wave 4 path, an empty/malformed claim trace or a non-exact/ambiguous
speech slice fails generation closed; it is never coerced to `[]`. Corrupt persisted
trace makes Replay unavailable with a stable safe error before any normal replay event.
Legacy turns whose persisted trace is the valid empty list remain readable.

Reports may consume only evidence IDs actually used by source turns. They cannot
upgrade contextual evidence to direct or convert general reasoning into a citation.
