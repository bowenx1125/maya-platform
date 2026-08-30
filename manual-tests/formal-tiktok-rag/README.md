# Formal TikTok mutual-learning content fixture

This is the W4-CONTENT Mock-only packet for Issue #12. It contains one original,
bounded English teaching corpus, a claim-level primary-source manifest, three
retrieval fixtures, and two contrasting Persona inputs for same-evidence teaching.
The source-link and claim spot-check record is in `SOURCE_REVIEW.md`.

## Separation and scope

- Upload `tiktok-recommendation-governance.md` as the formal knowledge Markdown.
- Upload only the files in `fixtures/` as retrieval controls when running a local
  Mock comparison. Do not upload a Persona as RAG evidence.
- Upload each `personas/*/AGENT.md` through the persona path, never through the
  knowledge-library path.
- All material is synthetic/original and contains no student identity, credentials,
  audio, or private account data. The source manifest links public primary or
  authoritative materials; it does not copy their full text.
- Platform statements are explicitly labelled and are not independent audits. The
  evidence freeze is 2026-08-30. A future content revision must receive a new
  manifest/content hash pair.

## Expected deterministic Mock comparison

For the fixed topic `Should the United States ban TikTok's recommendation algorithm?`
and the current `mock_lexical_anchor_v2` policy:

| Fixture | Expected result | Why |
| --- | --- | --- |
| `fixtures/relevant/tiktok-recommendation-governance.md` | `matched` | Contains multiple authoritative topic anchors and relevant claims. |
| `fixtures/adjacent/cultural-expression-and-youth-privacy.md` | `no_match` | Adjacent values are present, but there is no recommendation-system topic anchor. |
| `fixtures/unrelated/mineral-field-notes.md` | `no_match` | Unrelated subject and no topic anchor. |

The no-match outputs must have no evidence source. General reasoning must never be
described as a retrieved fact.

## Local checks

From the repository root:

```text
uv run --project backend python manual-tests/formal-tiktok-rag/scripts/acceptance.py
```

The script validates the manifest/content and fixture hashes, source metadata and
claim mapping, checks for accidental secrets/PII patterns, runs the actual local
Mock lexical gate plus vector receipt adapter, and compares both Persona inputs over
the same evidence. It never contacts a provider or calls a model.
