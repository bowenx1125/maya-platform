# MayaForm v1.4 K2b2 synthetic acceptance evidence

The frozen K2b2-A R2 and K2b2-B R5 files form Git tree
`65a93cae9fb6f3788f8908c94e80405a98b3f366` when applied to base
`cff83e8`, without any other dirty worktree files. Independent backend R2
and frontend R4/R5 reviews passed their stated frozen scopes; their local
review reports are retained with the task rather than as release artifacts.

The Fake Provider path sent one canonical, consented request. A three-candidate
response saved a Question with Rubric and a Note, recorded the malformed middle
item as failed, retained one verified opaque Source relation, and saved the Note
without a relation for its invalid optional receipt. The owner Job reported
accepted/materialized/failed counts of 3/2/1. Tests also cover source, Teacher
and Set revocation between item commits; stale claim fencing; accepted-stage
restart with no second Provider POST; manual head preservation; and two distinct
AI runs whose interleaved results keep a newer head while saving a nonconflicting
item. See `backend/tests/test_knowledge_generation.py` and
`backend/tests/test_knowledge_generation_materialization.py`.

An isolated populated 0038 database upgraded to 0039 with all pre-existing table
rows and old columns unchanged by row fingerprint, no foreign-key violations,
and `PRAGMA integrity_check=ok`. The new target-head snapshot table backfilled
old runs. Independent fault probes exercised backfill, DDL and head-update
rollback. The browser and migration probes use separate synthetic databases.

In the isolated browser, a Teacher entered **Knowledge Sets → Create AI
Knowledge**, created a personal Agent with free-format Agent.md, uploaded one
synthetic Markdown Source, and pressed Done. The receipt opened the same Agent's
private Set and owner Job. With Mock LLM settings, the Job truthfully reported
`provider_not_configured`; it did not claim generated assets or make a Provider
operation. The Set exposed **Update AI Knowledge**; that action created V1.1,
kept the selected Source, and Done returned the same Set and Job. The synthetic
database contained one run, one Set, one source receipt, zero Provider operations,
and passed foreign-key/integrity checks. This browser flow proves UI wiring and
reuse, while the Fake Provider tests prove actual per-item asset persistence.

Real Provider response quality, production Docker rollout, Team retrieval,
classroom diagnosis, and learning outcomes are separate acceptance work.
