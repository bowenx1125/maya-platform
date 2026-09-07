# Maya Platform

Maya is a local-first teaching platform. Student groups build culture-focused
Agents from an authored persona and an immutable Markdown knowledge snapshot. A
teacher picks 2–5 published Agents in click order, runs a versioned 2–5-round
mutual-learning session, opens anonymous classroom interaction, and
generates a civilization mutual-learning report.

This file is the authority for what the product is and where it stands.
[AGENTS.md](../AGENTS.md) is the authority for how to work on it. When two sources
disagree, use the user's latest explicit decision, then this file, then the
contracts under [contracts/](contracts/) and [docs/contracts/](contracts/),
then the ADRs under [docs/adr/](adr/), then
[ARCHITECTURE.md](ARCHITECTURE.md).

## Next Wave proposal updated 2026-09-07

Status: **PLAN AND ACCEPTANCE APPROVED / IMPLEMENTATION IN PROGRESS**.
The complete proposal is [NEXT_WAVE_PLAN.md](contracts/NEXT_WAVE_PLAN.md).
The owner's latest clarification supersedes both the earlier first-round-only
preview and the earlier all-classroom-provider-free proposal:

- Preview prepares and retains every turn in rounds 1 through N-1, including
  speech and audio. The first round is independent; middle rounds use earlier
  rounds. The final round is generated live in the 3D Bench.
- Every non-final turn accepts classroom barrages. One final-round action freezes
  all eligible prior-turn messages. Every Agent chooses and substantively answers
  at least one available barrage in its final speech; an empty eligible pool
  requires no reply. No Agent reads same-round final speeches.
- Report generation is explicitly initiated from the 3D Bench after Conclude,
  through a separate Provider interface. Its failure does not fail the debate.
- New Agent Markdown drops Debate strategy and Boundaries. Five remaining Persona
  sections feed generation; legacy published versions remain immutable/readable.
- The owner has approved segments with text, source_ids, reply_to and optional
  support_mode (September 8: restore direct +5/contextual +2/no_match 0 grades).
  Seven compact input groups replace verbose metadata and duplicated
  output analysis. The candidate segment prompt/schema is deployed for debugging; model configuration is unchanged.
- Delete existing debate-owned run records while preserving authored Agents,
  knowledge/snapshots, accounts and Provider configuration. Authorized offline cleanup completed on September 7.
- Unify UI with Teacher Debates and remove explanatory chrome. 古月 owns 3D
  faces and voice/TTS; Kaikai owns account management and student-workspace UI;
  徐伯闻 owns the remaining modules and accepts every delivery.
  The colleague workbook uses the exact Chinese owner name 徐伯闻.
- Target DDL is 2026-09-10. Main-agent diagnosis/audit/integration and bounded Luna
  Max coding may run alongside independent UI work after plan confirmation.
  Contracts, migrations, cleanup and deployment remain serial.

The owner now requires RAG teaching quality and a 100% real acceptance result.
Approved on September 7, with real debugging under way: 32 bilingual shape cases plus five fresh
consecutive 2x2 sessions (37 complete sessions, 412 turns, 37 reports), and
72 controlled RAG answers across relevant, disabled, irrelevant and updated
knowledge conditions. Predeclared factual targets and source support, not citation
counts, determine RAG quality. Normal cases require no manual rescue; one disclosed
structure repair is allowed and first-attempt success is reported separately.
Fault injection tests require correct recovery. On September 8 the owner kept
TTS/Voice Mock and took over real classroom/browser acceptance personally.
Section 14 of the proposal defines the
approved criteria and debug loop. The owner explicitly authorized implementation,
runtime cleanup and the agreed real acceptance work. Luna Max workers handle bounded
coding tasks; the main agent owns shared contracts, integration and real testing.

The new flow requires replacing terminal-status-only Bench eligibility with
complete non-final preview readiness, a final-input freeze and live final-turn
preparation. It also deliberately changes the meaning of the old claim-level
EvidenceTrace/scoring contract and adds an anonymous classroom-message outbound
class; these changes need explicit versioned implementation and acceptance.

### Evidence and limits

Previous release baseline is 1cea562 on debates-beta-stage, with matching backend sources
and an exact-head successful CI on PR #27. The earlier same-session audit passed
1,067 backend and 216 frontend tests, lint/types/format, contracts and routes;
that is not new-protocol or real-browser acceptance. The runtime audit found 14
accepted unpublished operations, one acceptance-unknown, and seven incomplete
public plans admitted by the beta status filter. These are pre-cleanup historical findings.

Delivery artifacts: a 13-page Chinese Word proposal and a 53-row Excel table
(43 徐伯闻, 4 古月, 6 Kaikai), all accepted by 徐伯闻 with DDL 9.10. They include
the approved 37-session/72-answer criteria. Manual ownership/blank-plan edits were
preserved. Updated pages and worksheet regions were visually checked.

### UI follow-up (September 7)

The Bench title is left-aligned. Delete Voice/All sit beside Resume in the warm
Debate list card. Stage list, Dashboard, creation and Preview use warm yellow;
Stage rows have only Open Stage. Preview navigation is inline, Audio Ready
replaces Saved, and its progress card is removed; list preparation shows x / y
turns. Open Message/Hide toggles the same QR without closing interaction.
Conclude opens the report; grades appear only there. Duplicate insight/report
status cards are removed. The owner delegates final classroom testing to himself.

### Implementation checkpoint (September 7, not release acceptance)

The owner resumed after the September 7 pause and requested GitHub delivery plus
a final Docker restart. Backend grading/replay checks are complete; classroom
acceptance remains the owner's manual task. No new real-provider test run was
started during this resume. Removing a usage stop never authorizes reset credits.

- Five-section Persona, paragraphs and accepted-result recovery are integrated.
  Five synthetic Agents have real Embedding snapshots; three baseline Agents use Mock.
- Preview retains non-final text/audio; final freezes barrages and generates live.
  Competing queues were removed. TTS staging/claim fences preserve saved text.
- Authorized offline cleanup removed 45 old debates, 227 turns and 67 runtime
  files, preserving authored Agents/knowledge, accounts and configuration.
  New scoped Delete Voice/All endpoints include durable file journals. Actual
  HTTP deletion of four audio files, identical repeated deletion and regeneration
  of all four passed, preserving speech, RAG and Report hashes with unchanged
  LLM/Embedding counters. Partial-delete and cancellation replay counts were fixed.
- One fresh normal 2x2 session completed creation, Preview, HTTP/WS playback,
  barrage/final round, Conclude and Report download without manual rescue.
  Its nine successful operations were four query, four LLM and one Report,
  all attempt one, zero repairs. Preview took 21.4s; Report 10.2s. TTS was Mock.
- RAG formal01 stopped after 31/72 answers on query acceptance-unknown (77 ledger
  charged reservations); formal02 stopped after 21/72 on snapshot unknown (52).
  Neither operation was resent. Independent review passes the 21 completed
  formal02 answers, including current/updated facts and appropriate uncertainty.
  Full RAG acceptance remains incomplete; execution and semantic review are separate.
- Diagnostic07 stopped at its first selected case: snapshot/query succeeded,
  LLM connect failed as not_sent. Its ledger counts three charged reservations,
  which does not prove three supplier-accepted requests. No answer was produced.
  DNS/TCP/TLS/HEAD probes later passed; historical cause remains unproven.
  Safe transport diagnostics were added without retry.
- The Report UUID-only citation bug was fixed. New v2 reports no longer append
  repeated filler to reach 600 words; the 900-word ceiling, six sections, exact
  sources and interaction totals remain. Migration 0023 preserves legacy rules.
  The actual database migration had zero FK violations and a private backup.
  A new real Report completed in 13.5s with 397 words and no padding.
- Headless Chrome verified fixes for missing/obscured figures, lost RAG fields,
  oversized headings and failed drafts labeled Thinking. Report dialog/Escape
  works. Inspected desktop pages had no horizontal overflow or page errors.
- Replay readiness now supports completed debates and shares StoredFile/WAV
  path, hash, size and duration validation with media access. Six focused SQL/HTTP
  checks cover ordered Replay, missing/corrupt audio and actual DeleteVoice.
  Whole classroom replay remains for the owner's manual acceptance.
- Paragraph support_mode restores direct +5/contextual +2/no_match 0; missing
  legacy grades remain ungraded. The same saved grades feed Check RAG and Report.
  Per-turn evidence IDs are validated before report source deduplication, fixing
  a false rejection when one chunk is reused across rounds. Focused checks pass.
- Typed public UUIDs no longer trigger phone detection; actual identity tokens
  and phone prose still fail. This privacy fix is included in the rebuilt backend.
- Backend regression: 1,244 passed; the sole sandbox-blocked localhost wire test
  passed separately with port access. New grading/report checks (43), Replay (6)
  and runner checks passed. Frontend: 253 passed before the final progress-copy
  edit; subsequent classroom tests waived by owner. Ruff/mypy/format and contracts
  passed: 82 declared routes, 61 implemented, no placeholders. Schema head: 0023.

Delivered to main (code merge f2e8b1b); other local/remote branches are deleted.
Docker backend/frontend/gateway were recreated and became healthy. TTS/Voice stay
Mock. Next: owner-led manual classroom/RAG acceptance. Preserve failed ledgers;
private artifacts and backups remain outside Git in Maya outputs.

## Product boundaries

These are settled decisions, not open questions.

- **Organization.** One seeded course, one teacher (Maya) and one group of
  three students (Bowen, Kaikai, Jade). Course and group membership are
  read-only.
- **Authorization.** Students are scoped to their group. Teachers see published
  immutable history, never drafts. Cross-group objects return not found.
- **Agent versions.** Published and superseded versions and their knowledge
  snapshots are immutable. New persona or knowledge needs a new version.
- **Knowledge.** Markdown only. A draft enables group documents explicitly;
  publishing freezes source bytes, chunks, vector metadata and lineage.
- **Debate.** A new Debate is always `ordered_multi_expert_mutual_learning_v1`
  with 2–5 Agents in slots A–E and 2–5 rounds. The two legacy demo RuleSets
  stay readable so existing Debates keep working, but no surface creates them.
  The rules engine, not the model, chooses the order.
- **Context.** A mutual-learning turn receives the complete text of every
  public turn from earlier rounds, exactly once, and never a same-round turn.
  Visible speech is never summarized.
- **Evidence.** Only server-selected receipts actually used by a validated turn
  become public sources. `no_match` uses general reasoning with no source.
- **Playback.** Replay reuses retained immutable content and never calls a
  provider. The next Wave prepares all non-final rounds in Preview and creates
  the final round live in Bench; the candidate flow is under real acceptance.
- **Interaction.** Public votes and named local barrages remain independent.
  The next Wave exports only reviewed anonymous barrage text for final-round
  replies and Bench reports. Nicknames and account identities stay local; this
  new outbound class is versioned in new manifests; legacy manifests remain unchanged.
- **Language.** Current debate generation supports English and Chinese, selected
  at creation before prewarming in the new protocol. The former
  derived-translation feature has been removed. The report language path must be
  checked with the new language-lock acceptance cases.
- **Runtime.** Next.js, FastAPI, SQLite and local files behind one Caddy
  origin. No Redis, Celery, PostgreSQL or cloud storage.

## Demo composition

| Component                           | Mode                                                |
| ----------------------------------- | --------------------------------------------------- |
| Snapshot embedding, retrieval query | Real DashScope `text-embedding-v4`, 1024 dimensions |
| Debate LLM                          | Real fixed Qwen structured output                   |
| Maya Report                         | Real fixed Qwen structured output                   |
| TTS, Voice                          | Mock                                                |

Every delivery surface must label this Real/Mock split honestly.

The provider call count is derived from the Debate's own shape, not fixed:

```
calls = 1 snapshot
      + (Agents with a real Snapshot) × rounds   retrieval queries
      + Agents × rounds                          debate LLM turns
      + 1 report
```

A 2-Agent, 2-round Demo is 8 calls; 3 Agents over 2 rounds is 10. Each turn may
additionally spend one structure-repair attempt. `demo_acceptance_expected_calls`
in `app/providers/control.py` is the single definition.

## Where the product stands

### Working, verified by running it

- Student agent, version, knowledge, voice and publish surfaces; teacher
  debate setup, playback control, interaction, provider approvals and
  disclosures; classroom page; Real/Mock composition strip.
- Three seeded demo Agents — Socrates, Plato and Laozi, one confirmed by each
  student — so a teacher can open a multi-Agent Debate from an empty runtime
  with no setup.
- The complete all-Mock chain end to end: multi-Agent, two-round mutual
  learning with an evidence trace per public turn, transcript, interaction open
  and close, insight, and a 600–900 word English report that names no winner.
- Real Snapshot embedding and real Debate LLM turns against DashScope,
  including a structure-repair attempt that recovers a turn whose first reply
  missed a rule.

### In progress

Round two is on `debates-beta-stage`. Its landed changes are:

- Distinct Stopped / Completed / Running / Waiting labels, with Stalled and
  single-turn Resume for failures projected by the list. The draft reset path
  still needs the diagnostic correction recorded in the September 7 plan.
- One presentation-tolerant claim/speech matcher; English per-turn length is
  60-320 words. The latest commit makes prompt, generation and playback share
  the same bound and logs safe exception source positions.
- `prepare_turn` performs a second local preparation pass only when an accepted
  stage exists and the turn is not ready. Fresh real end-to-end acceptance is
  pending; old-stage rejection does not establish new-run reliability.
- The beta bench uses `female_1.glb`, with mouth/expression morphs and no animation
  clips, replacing the old bodies. Stage assets are about 3.8 MB. Browser visual
  acceptance remains pending; public asset licensing is a separate boundary.
- Beta has a combined Start/Next button and filters terminal status names. The
  filter still admits incomplete historical plans and the primary button is
  not yet a replay Start for finished debates. Full classroom separation,
  audio retention, deletion, interaction/summary assembly and UI cleanup follow
  the revised next-Wave plan above.

Real-Core acceptance, real browser end-to-end and the final startup/reset/recovery
package remain incomplete. Repair feedback already carries JSON pointers; adding
an explicit rule identifier is conditional on observed fresh-run failures and
requires a policy/schema migration.

### Not started

Production hardening: multi-process recovery, classroom-scale load, public
deployment, monitoring, backup and restore, production TTS and Voice, real
translation, data-governance and licensing review. None of these may block the
Demo.

## Provider accounting

The supplier console is the billing authority. New runs retain their runtime
ProviderOperation and acceptance ledgers for reservation, duplicate-call prevention
and recovery. This document does not maintain a second approximate call list.
Old-run deletion remains planned.

## Recorded deviations from the frozen Wave 4 contracts

Each is a deliberate decision, reversible, and scoped to the Demo.

1. **Supplier-tokenizer gate removed.** `LLM_A_RUNTIME_V1` and
   `PROMPT_BUDGET_V1` required a reviewed supplier tokenizer before a real LLM
   request, but none was ever pinned into the runtime, which made the real
   Debate LLM and real Report unreachable. The conservative UTF-8 counter
   over-counts, so it can only reject an over-large request; its exact id and
   asset hash are still recorded with every request. Pinning a real supplier
   tokenizer is deferred.
2. **Derived call budget.** The fixed seven/eight-call plan is replaced by the
   shape-derived plan above, which is what allows a structure repair.
3. **Structure repair enabled for the real composition.** A repair inherits its
   first attempt's acceptance run and takes the next ordinal, so a charged
   repair can never escape the ledger.
4. **Provider dialect projection.** The supplier rejects a `response_format`
   schema that constrains an array with `uniqueItems`, so the wire copy drops
   those keywords. The frozen schema stays the hash-checked authority for
   validating the response, and local validation still enforces them.
5. **`position_update_reason` may be empty.** The frozen schema required it
   non-empty in every phase while the domain validator only requires it for
   exchange and final integration. The schema now matches the domain rule.
6. **Configuration faults stay terminal.** `llm_tokenizer_unauthorized` and
   `provider_preflight_blocked` remain outside the safe generation codes, so a
   misconfiguration fails a Debate closed rather than parking it.

7. **The beta stage is a fork, not a refactor.** `components/debate-beta/stage`
   copies the classic stage rather than parameterising it, so Debates (beta)
   cannot regress Debates while both are changing. The duplication is the cost
   of that guarantee and is meant to end when beta either graduates or is
   dropped; the pure protocol, label and speech-stream modules are imported
   from the classic stage rather than copied.
8. **`DEBATES_BETA_LIVE_INTERACTION` splits one gate into two.** Opening
   classroom interaction required a finished debate and a complete round
   matrix. Finalising still does. With the switch on, opening also accepts a
   running debate with at least two Agents, which is what puts the join code on
   the beta stage. The switch is off by default, so the classic surface keeps
   the after-the-debate rule. **While it is on the vote is a running tally, not
   a verdict taken once every Agent has spoken — report it that way.**

## Document map

- [AGENTS.md](../AGENTS.md) — how to work on this repository.
- [ARCHITECTURE.md](ARCHITECTURE.md) — stable system and data boundaries.
- [contracts/](../contracts/) — machine-readable OpenAPI and WebSocket contracts.
- [docs/contracts/](contracts/) — human contracts and provenance.
- [docs/adr/](adr/) — one durable decision per file.
- [docs/requirements/original.md](requirements/original.md) — historical
  source requirements, not the current contract.
- [docs/investigations/](investigations/) — open questions with the
  evidence gathered so far.
