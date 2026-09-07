# Next Wave RAG acceptance fixture

This directory is a predeclared, synthetic acceptance set. `manifest.json`
fixes the 32 bilingual Agent/round shapes and five fresh 2x2 sessions at 412
turns and 37 classroom reports. `questions.json` fixes three English and three
Chinese teaching questions, each with correct, disabled, irrelevant and
updated knowledge conditions repeated three times (72 answer cases).
The manifest pins all 19 question/corpus files by SHA-256, and its own bytes
are pinned in `manifest.sha256`; changing source text invalidates the batch.

`harness.py` validates the manifest, unique corpus markers, gold fact coverage,
answer requirements and report observations without changing the application
or making a Provider call. A matched report must include the retrieved
evidence IDs and used evidence rows with `evidence_id`, `corpus_path`,
`locator` and `observed_excerpt`. The excerpt is checked against the immutable
fixture sentence; an ID or path alone cannot self-assert support. Disabled
reports must state uncertainty and cannot cite a fixture fact. An irrelevant
report may cite a known irrelevant source when the observed ID, location and
excerpt are valid; explaining why that source does not answer the question is
still a semantic review item, not an automatic quality pass. Unknown or
forged IDs fail structural validation.

The deterministic result separates structural validation from teaching
quality. Structurally valid reports carry `semantic_verdict: "pending"`,
`semantic_review_required: true` and `passed: false`; an independent owner
review decides whether the answer supports the question. Exact aliases are a
synthetic check aid. Missing aliases become review warnings so valid
paraphrases remain available to the owner. An irrelevant condition may
legitimately return `no_match`, and only evidence actually returned or cited
is checked against a corpus excerpt. The offline acceptance CLI reports
`semantic_review_required` for a complete structurally valid report set and
returns a nonzero review-needed exit code.

The separate `scripts/next_wave_real_rag.py` runner has a dry-run default and
an explicit `--execute-real` boundary. With reviewed policy files and an
output directory, it exercises real import, snapshot embedding, query
embedding, retrieval, generation and report capture through the application
seams. Its outer run record keeps execution status, structural validation and
semantic verdict separate; a complete run with valid structure remains
`semantic_review_required` until owner review. Provider envelopes, credentials
and raw student/source logs are excluded from terminal output and audit
summaries.

The real runner populates a report mapping like this, using actual retrieval
output rather than injecting a gold fragment:

```json
{
  "case_id": "q01-correct-r1",
  "question_id": "q01",
  "condition": "correct",
  "repeat": 1,
  "answer": "...authoritative generated answer...",
  "retrieval_status": "matched",
  "grounding_mode": "rag_grounded",
  "retrieved_evidence_ids": ["q01-correct-e01"],
  "evidence": [
    {
      "evidence_id": "q01-correct-e01",
      "corpus_path": "corpus/q01/correct.md",
      "locator": "Evidence q01-correct-e01",
      "observed_excerpt": "...excerpt returned by the real retrieval path..."
    }
  ]
}
```

The example is an interface illustration, not an acceptance result.
