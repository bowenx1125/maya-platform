# Same-evidence Persona comparison

This content-only pair is a deterministic teaching fixture, not a model-quality
claim. Both inputs must be tested against the exact same relevant file:
`fixtures/relevant/tiktok-recommendation-governance.md`. Neither persona is evidence,
and neither persona is uploaded as RAG.

| Persona input | Primary lens | Questions it should foreground |
| --- | --- | --- |
| `personas/safety-first/AGENT.md` | Youth protection and accountability | What concrete harm is present? How are age, privacy, audit coverage, and appeal tested? |
| `personas/creator-culture/AGENT.md` | Expression, innovation, and cultural diversity | What expression and discovery costs follow a restriction? Can separation, transparency, and controls address the risk? |

The expected comparison is a difference in framing and proposed safeguards while the
retrieved claim/evidence IDs remain identical. A real LLM is out of scope for W4-CONTENT;
the local acceptance script checks the shared evidence identity and the deliberate
persona contrast, then prints two deterministic, receipt-grounded teaching previews.
