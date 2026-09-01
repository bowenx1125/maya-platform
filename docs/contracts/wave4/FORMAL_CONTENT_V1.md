# FormalContentV1

Status: `CONTENT V1 FROZEN / MOCK ACCEPTANCE PASS / REAL EMBEDDING NOT STARTED`

W4-CONTENT is Mock-only and precedes real embedding. It creates the actual TikTok
teaching corpus; W4-G0 does not pretend that placeholder or historical fixture text is
formal content.

The content packet must contain:

- one bounded English Markdown teaching document about TikTok recommendation-system
  governance, youth protection, expression, innovation and cross-cultural trade-offs;
- a source manifest with title, publisher/author, publication date, direct URL,
  access date, license/usage basis and the exact claims each source informs;
- primary/authoritative sources for law, policy, platform disclosures and quantitative
  claims; secondary commentary is labeled as interpretation;
- explicit fact/value separation and date scope;
- at least one relevant retrieval fixture, one adjacent-but-insufficient fixture and
  one clearly unrelated no-match fixture;
- content and manifest SHA-256 values plus the exact chunking version;
- no student identity, nickname, credential, private account data, audio or copyrighted
  full-text copying beyond permissible short excerpts and original synthesis.

Acceptance requires source-link review, claim/source spot checks, relevant/no-match
Mock retrieval, two contrasting Persona Mock turns over the same evidence and a
main-window teaching review. Content remains editable until that Gate signs its hashes;
real embedding cannot run earlier.

## Frozen content evidence

The seeded Demo Agents under `backend/app/modules/demo_baseline/agents/` are the current authored corpus; the earlier standalone review packet was removed once they replaced it.

- corpus SHA-256: `7fab29d2bddc241ea2021284f2766e6e6cecb705b9a56ff041838c1fe606c24a`;
- source-manifest SHA-256: `9193e384a0c29bf51274055b4cd3a6273fc6276ad14113db4b8398a335648ce5`;
- 14 claim markers map to 7 primary/authoritative sources;
- relevant fixture: matched; adjacent and unrelated fixtures: no-match with no source;
- two contrasting Persona fixtures use the same receipt while changing only their
  declared teaching priorities;
- checksum, JSON, secret/PII pattern, actual Mock lexical/vector and pytest acceptance:
  PASS;
- main-window teaching review: PASS, with first-party TikTok pages retained as labeled
  platform statements rather than independent audits;
- Provider/model calls: `0`.

Any content or manifest edit invalidates this status and requires new hashes and the
same acceptance sequence before a new real SnapshotBuild.
