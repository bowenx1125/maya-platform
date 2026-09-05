# Maya Platform

Maya is a local-first teaching platform. Student groups build culture-focused
Agents from an authored persona and an immutable Markdown knowledge snapshot. A
teacher picks 2–5 published Agents in click order, runs a versioned 2–5-round
English mutual-learning session, opens anonymous classroom interaction, and
generates a civilization mutual-learning report.

This file is the authority for what the product is and where it stands.
[AGENTS.md](../AGENTS.md) is the authority for how to work on it. When two sources
disagree, use the user's latest explicit decision, then this file, then the
contracts under [contracts/](contracts/) and [docs/contracts/](contracts/),
then the ADRs under [docs/adr/](adr/), then
[ARCHITECTURE.md](ARCHITECTURE.md).

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
- **Playback.** The teacher surface is Start / Next / Replay. Replay reuses
  retained immutable content and never calls a provider.
- **Interaction.** Public vote and named raw barrage are independent. Maya
  receives no nickname and no raw barrage list; counts are computed from frozen
  rows.
- **Language.** Authoritative speech and reports are English. Chinese is an
  on-demand derived representation and never re-enters generation.
- **Runtime.** Next.js, FastAPI, SQLite and local files behind one Caddy
  origin. No Redis, Celery, PostgreSQL or cloud storage.

## Demo composition

| Component                           | Mode                                                |
| ----------------------------------- | --------------------------------------------------- |
| Snapshot embedding, retrieval query | Real DashScope `text-embedding-v4`, 1024 dimensions |
| Debate LLM                          | Real fixed Qwen structured output                   |
| Maya Report                         | Real fixed Qwen structured output                   |
| TTS, Voice, Translation             | Mock                                                |

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

- **Round two, on `debates-beta-stage`.** Landed and pushed so far:
  - Every debate state has one word of its own. `stopped` used to read
    "Finished", so an interrupted lesson and a complete one looked identical;
    `waiting_next` used to read "Thinking" while nothing was generating at all.
    Now Stopped / Completed / Running / Waiting.
  - A draft that stops warming says so. Background warming halts at the first
    turn that will not generate, logging one line and changing no status, so
    the list kept reporting a frozen "Thinking 25%" for a draft that had given
    up. The turn row already carried `generation_status` and
    `safe_error_code`, so the listing reports the earliest failed turn as a
    stall — no new column — the badge reads Stalled with the round and the
    code, and Resume regenerates that one turn.
  - Claim-in-speech is enforced by meaning, not by bytes. A curly apostrophe,
    a line break inside a sentence or a repeated sentence used to cost the
    whole turn, and the repeat rule was never stated in the prompt at all. One
    matcher now serves both layers, forgives presentation and nothing else,
    and the prompt says exactly that. Per-turn length widened to 60-320 words.

  - **Why real turns were getting stuck, found by reading the runtime.** A
    real-provider turn is produced in two passes on purpose: the first accepts
    and stages the reply the supplier was paid for, the second publishes it, so
    a crash between them cannot lose a charged answer. Nothing was making the
    second pass. Whether a turn ever became ready depended on whether something
    else happened to prepare it again, and warming explicitly does not — a turn
    that "did not advance" is how it recognises a dead one. So a turn could
    stop one step short of ready with nothing to show for it: money spent,
    answer staged, `generation_status` still `pending`, no safe error code, and
    the debate parked at Running with nothing a teacher could act on. Thirteen
    turns in the runtime were in exactly that state against sixty-seven that
    published because something happened to touch them twice.
    `prepare_turn` now makes that pass itself, gated on an accepted unpublished
    operation so it can only ever publish, never generate. The stall marker and
    Resume now cover running debates too, not only drafts.

  Next, in order: a real-provider run to see whether generation is now
  reliable, since the publication gap — not the validator — was the blocker;
  `rule_id` in the repair feedback is deferred until that run says it is
  needed, because the repair policy hash is written into a database CHECK
  constraint and changing it costs a migration. Then audio retention with Delete | Voice / All; then the
  two surfaces split (Debates as the preview bench, beta as the classroom);
  then the face swap and the interface pass. The full work order, including the
  decisions behind each item, is the round-two artifact.

- **Debates (beta).** A sibling teacher surface at `/teacher/debates-beta`,
  beside the classic Debates entry and sharing its debates. It replaces the
  head-only avatar column with one WebGL scene holding every Agent as a full
  skeletal figure, hangs the speaking Agent's opening line over its head, and
  flies classroom messages right-to-left across the top third of the stage
  while the debate is still running. The classic Debates surface is untouched:
  the beta stage is a fork, the beta copy lives beside it, and the one shared
  backend change is off by default. Checks pass; **not yet rendered in a
  browser**, so nothing here is verified by running it.

- **Real-Core acceptance run.** The 8-call chain reaches the debate LLM and
  publishes a turn, but the model's first reply does not yet satisfy the
  mutual-learning validator reliably. The repair attempt fixes it sometimes and
  not always, because repair feedback carries the safe code without the
  validator's failure position.
- **Browser end-to-end** against the real composition.
- **Demo package**: fixed assets, one startup entry, reset and recovery
  instructions, Real/Mock disclosure.

### Not started

Production hardening: multi-process recovery, classroom-scale load, public
deployment, monitoring, backup and restore, production TTS and Voice, real
translation, data-governance and licensing review. None of these may block the
Demo.

## Real provider call ledger

Every charged request, including failed ones, is counted here.

- Snapshot embedding: several, across repeated acceptance attempts.
- Retrieval query embedding: 1 historical.
- Debate LLM: several, across repeated acceptance attempts, including
  structure-repair attempts.
- TTS: 3 historical failures. Voice: 1 historical enrolment.
- Automatic retries: 0. Every repeat was a deliberate fresh run.

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
