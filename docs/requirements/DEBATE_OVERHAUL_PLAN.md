# Debate overhaul — agreed plan

Owner: Bowen. Written 2026-09-04. This is the alignment document: when writing
any of this code later, read this file first rather than re-deriving intent
from the diff.

Every string change below applies to **both** locales. `frontend/lib/i18n.ts`
holds two parallel dictionaries (`enMessages`, `zhMessages`) and
`tests/wave1c-m02.test.tsx:91` fails the build when a key's English and Chinese
values are identical unless the value is in `ALLOWED_IDENTICAL_TERMS`. So an
English label shortened to one word gets a real Chinese word, never the same
token on both sides.

---

## Phase 1 — Copy, evidence panel, and the setup control

No contract change. Fully reversible.

### 1.1 Renames

| Now (en / zh)                                           | Becomes (en / zh)            | Where                                 |
| ------------------------------------------------------- | ---------------------------- | ------------------------------------- |
| Finish debate / 结束辩论                                | `End` / `结束`               | `control/page.tsx:128`                |
| Back to debate list / 返回辩论列表                      | `Back` / `返回`              | i18n `debateBack`, `debateBackToList` |
| Start debate / 开始辩论                                 | `Start` / `开始`             | i18n `debateStart`                    |
| `Next / 下一步` (slash-joined on both sides)            | `Next` / `下一步`            | i18n `debateNext`                     |
| Published transcript / 已公开发言                       | `Public Debate` / `公开发言` | i18n `debateTranscript`               |
| Debates / 辩论列表                                      | `Debate Title` / `辩论标题`  | i18n `debateList`                     |
| Inspect claim evidence lineage + count / 查看观点证据链 | `Check RAG` / `查看 RAG`     | `evidence-trace-inspector.tsx:190`    |
| Debate complete / 辩论已结束                            | `Finish` / `完成`            | i18n `debateComplete`                 |
| Debate needs attention / 辩论需要处理                   | `Failed` / `失败`            | i18n `debateFailed`                   |
| Finished / 已结束                                       | `Completed` / `已完成`       | `control/page.tsx:146`                |
| Waiting / 等待中 (while generating)                     | `Thinking` / `生成中`        | `control/page.tsx:145`                |

### 1.2 Deletions

- `debateListLede` — "统一查看课堂辩论草稿与已完成场次。"
- "本轮已完成，等待教师继续。"
- `demoSystemBaseline` — the whole System baseline block is hidden.

### 1.3 Check RAG panel

Three display categories, mapped from the backend `support_mode` enum. The enum
itself does not change.

| `support_mode`                | Shown as                     |
| ----------------------------- | ---------------------------- |
| `direct`                      | Direct evidence / 直接证明   |
| `contextual`                  | Indirect evidence / 间接证明 |
| `no_match`, general reasoning | No evidence / 没有证据       |

Folding `no_match` into "indirect" was rejected: it would claim indirect
evidence for a speech where retrieval found nothing.

**Current position becomes its own row.** It is not a label today — the backend
glues it into the query string at
`backend/app/modules/debates/generation/retrieval.py:353`:

```python
f"{topic}\nState this participant's independent viewpoint and core reasons.\n"
f"Current position: {position}"
```

so the panel prints topic + instruction + stance as one blob after 检索问题.

Fix with no contract change, using two fields the browser already has:

- **检索问题** — render `query_kind` (`viewpoint` / `pending_question` /
  `rebuttal` / `updated_position`) as a human label.
- **当前立场** — read `current_position_summary`, already in the participant DTO
  (`frontend/lib/api/generated/schema.d.ts:1608`).
- The exact sent text stays available in a collapsed "actual retrieval text".

Do **not** split `query_text` on the literal `"Current position:"`. The four
query kinds have different shapes, and `query_text` is the receipt of what was
actually embedded — rewriting it in the view falsifies an evidence record.

### 1.4 Round-count control

`components/debate/setup/debate-setup.tsx:604` is a `<select>` of 2–5. Replace
with a segmented row of large tap targets, and enlarge the 多轮专家互鉴 block's
type. Same 2–5 values, same state.

While here: line 618 computes `selectedIds.length * roundCount` inline. Route it
through `expectedTurnCount` in `frontend/lib/debate-rounds.ts` — the
single-resolver rule below.

### 1.5 Button economy

One word or one symbol wherever the meaning survives it (`+` for New debate).

### 1.6 Teacher-screen copy audit

Nine teacher routes (`app/teacher/**/page.tsx`) and the components they reach.
Twenty-one strings of 55 characters or more. The cut is not by length — it is by
whether the sentence tells the teacher something the control does not.

**Delete.** Narration that restates the control beside it:

| Key                        | Why                                                                                            |
| -------------------------- | ---------------------------------------------------------------------------------------------- |
| `debateListLede`           | restates the page title                                                                        |
| `wave3Description`         | lists what is on the page you are looking at — and names the translation feature being deleted |
| `interactionFinalizedNote` | "The input snapshot is immutable; insight/report generation may now continue."                 |
| `debateSelectedLede`       | "The letter follows click order and is not a separate editable field."                         |
| `debateCandidatesLede`     | restates the selector's own behaviour                                                          |
| `newDebateLede`            | restates the selector's own behaviour                                                          |
| `debateApprovalLede`       | restates the approval control                                                                  |

**Keep — these carry an action, and Phase 3 depends on them.** Deleting fault
copy would directly undercut the self-healing requirement: an error must still
say what to do. Tighten the wording, keep the substance.

`debateProviderSetupIncomplete` (says plainly that retrying cannot help),
`debateConnectionOriginMismatch`, `debateReplaceAudioConfirm` (a confirmation
before an irreversible action), `wave3DownstreamUnavailable` and
`interactionAvailability` (why the entry is missing — Phase 3 attaches the
action), `debateNoCandidates`, `debateNoPublishedSpeech`, `debatePartial`.

**Two of these are user-visible overfitting**, found by this audit and worth
fixing on their own merits:

- `debateFlow` — "Round 1 A→B→C→D→E · Round 2 A→B→C→D→E · …" hard-codes two
  rounds and five agents in the copy a teacher reads, while the product accepts
  2–5 × 2–5.
- `debateFixedRulesLede` — "Two rounds · 80–200 English words per turn" asserts
  two rounds for the same reason.

Both are derived from the chosen shape or removed. `debateMutualLearningRules`
says "English words per turn", which contradicts §4.2 and is rewritten there.

`debateRoundCountHint` keeps its `{turns}` count but loses the sentence around
it. `debateTopicPlaceholder` is an example, not narration — it stays.

### 1.7 Back, and the interaction entry

`components/debate/setup/debate-setup.tsx:380` keeps `debateBack` as `Back` /
`返回` for the list.

On the interaction page there are two links today
(`interaction/page.tsx:68` and `:74`): one to the debate stage, one to the
debate list. **The list link goes away.** `Back` on the interaction page means
back to the debate stage — the screen the teacher came from. The
`debateBackToList` key is deleted along with its other caller
(`control/page.tsx:304`), since the stage's own `Back` (§1.6 placement) already
covers that route.

The entry that opens the classroom interaction is renamed to **`Interaction`** /
`课堂互动` (from "Open classroom interaction" / `interactionOpen`), and
`wave3Title` / `wave3BackToPlayback` follow the same economy.

### 1.8 Control placement

`Back` and `End` move **below** `Next`, into the panel under the 3D face that
already holds the lesson controls. Their original positions are removed, not
duplicated. The stage keeps one control cluster, ordered Start / Next / Back /
End — with `Interaction` alongside once §1.7 lands.

---

## Phase 2 — Bugs

Reproduce in the browser first and capture the real error. No static guessing.

1. **No classroom-interaction entry after Finish.**
2. **No entry in the Completed state.**
3. **Report generation fails.**

The gate behind (1) and (2) is `has_complete_finished_playback`
(`backend/app/modules/debates/playback/eligibility.py:18`), which requires all
of: every turn `public` with non-empty speech, `playback.status == "completed"`,
`mode == "live"`, and `controller_epoch` / `pending_action` /
`pending_ticket_hash` / `pending_media_command_id` all null. A lingering
controller epoch after Finish is the leading suspect — to be confirmed by
running it, not by reading it.

### 2.1 Vote totals show raw UUIDs

`faa1ba05-…-c1` `0 · 0%` is `{participant_id}{count} · {percentage}%`.
`history-view.tsx:190` renders `vote.participant_name ?? vote.participant_id`,
but the frozen `VoteAggregate` schema
(`frontend/lib/api/generated/schema.d.ts:1780`) carries only `participant_id`,
`count`, `percentage` — there is no name to fall back from. Join client-side
against the participants the page already loads (id → slot + agent name). No
contract change.

---

## Phase 3 — Self-healing and Release

**Explicitly overturned design decision.** `backend/app/cli/playback_reset.py`
is a CLI and not a router on purpose: _"so a normal browser or an accidental
invocation cannot reset classroom state."_ Bowen has decided not to preserve
that intent. Recovery moves into the UI.

Guardrails that stay: teacher role, the debate must belong to a course the
actor teaches, and an explicit in-UI confirmation (the browser equivalent of
`--confirm RESET`).

| Broken state                                                                | Today                                    | Becomes                                                                                                                               |
| --------------------------------------------------------------------------- | ---------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| A debate stuck `running` blocks every new one                               | `python -m app.cli.playback_reset`       | **Release** button on the debate list                                                                                                 |
| Teacher opens a new debate that cannot start because another holds the slot | Silent failure, then the button vanishes | The blocking debate is named **in place, below**, with its own Release button — no navigating back                                    |
| A turn's generation died                                                    | Ambiguous status, decorative button      | **Failed → Regenerate**, wired to the existing `POST /debates/{id}/preparation/retry`                                                 |
| Connection dropped                                                          | Reconnect sometimes does nothing         | Attribute the drop (network / sequence gap / session expired / superseded) and offer the one action that actually resolves that cause |
| LAN IP changed → CSRF and QR break                                          | Edit `.env`, restart                     | Resolve the RFC1918 address at runtime instead of freezing it at bootstrap                                                            |

Principle: **no failure state may require a terminal.** If a fault injection
can only be cleared by editing files or running a CLI, Phase 3 is not done.

New endpoint for Release → OpenAPI re-freeze (four steps, `AGENTS.md` §4).

---

## Phase 4 — Draft pre-warm, language lock, translation removal, audio release

### 4.1 Draft pre-warm with progress

```
draft ──created──▶ Thinking   background pre-warm in turn_index order,
  │                           progress = ready turns / expected turns
  ├─ teacher opens another debate ──▶ yield: stop at a turn boundary,
  │                                   keep what is cached, return to draft,
  │                                   resumable later
  ├─ 100% ──────────────────────────▶ Ready (text and audio both cached)
  ├─ Start ─────────────────────────▶ running (cached turns play at once;
  │                                   uncached ones wait there)
  └─ End ───────────────────────────▶ terminal, never pre-warms again
```

**Yield and End are different stops.** Yield is reversible, lands on a turn
boundary, and never discards a provider call already paid for. End is final.
Opening any other debate — running or thinking — yields the previous one so it
cannot block the view.

Two invariants today stand in the way:

- `prepare_turn` returns unless `debate.status == "running"`.
- `turn_index not in {current_index, current_index + 1}` returns.

The second is the CAS fence and **is not touched** — it governs who may advance
playback, a different concern. Pre-warm takes an independent path writing the
same `debate_turns` rows; once a debate starts, `_turn_ready(turn)` already
skips ready turns, so the cache is reused with no change to playback logic.

Progress denominator is `expected_turn_count(debate, participants)` — general
over 2–5 agents × 2–5 rounds by construction.

Contract: list DTO gains `prepared_turns` / `expected_turns` → re-freeze.

Cost note, accepted: pre-warming drafts spends real provider calls on debates
that may never run.

### 4.2 Debate output language

Today the rule is hard-coded in the prompt:
`mutual_learning_prompts.py:63` — _"Authoritative speech is English only."_

Change: the language chosen in the UI **at the moment Start is pressed** decides
whether the debate is generated in Chinese or English, frozen into
`rule_snapshot_json` alongside `round_count`.

**Can it be switched mid-debate? Recommendation: no, and the UI should say so.**
It is technically possible, but a debate is a chain — each turn's prompt carries
the previous speeches, and turns are pre-warmed ahead of the teacher. Switching
at turn 5 of 12 leaves a bilingual transcript, an evidence chain whose queries
were embedded in the other language, and already-cached turns that would have to
be thrown away and re-paid for. So: locked at Start; changing the UI language
afterwards translates the chrome, not the debate.

### 4.3 Remove translation / DeepL entirely

Scope: frontend `components/translation/`, the panel's entry points, the backend
`app/modules/translations/` module (7 files), both
`/debates/{debate_id}/translations` routes in the frozen contract, the
`TRANSLATION_PROVIDER` selector in `.env.example` and `core/config.py:119,337`,
its mention in `_provider_allowed`, and the docs references. The three
`translation_*` tables get a migration; data loss here is intended and only
affects a feature being deleted.

Contract: routes removed → re-freeze.

### 4.4 Classroom interaction panel

Keep: **votes + barrages + agent scores + report**, in that order, with history
collapsed into one module and nothing below the report. Remove the
public-speech duplication and everything listed below.

Delete outright:

- "The input snapshot is immutable; insight/report generation may now continue."
- "M13 · ANONYMOUS AUDIENCE" and "Votes and barrages are independent."
- "The report reads only public turns, used evidence, final anonymous votes, and validated anonymous classroom insight."
- "MAYA · CIVILIZATION MUTUAL LEARNING"
- "Raw barrages remain named for the teacher display; vote records remain anonymous."
- "Successful revisions stay available when a later attempt fails."
- "Mock workflow representation; not a claim about real LLM quality"
- The duplicated Vote totals / Raw barrages / Maya report history blocks at the
  bottom of the page.

Rename and restyle:

- "Turn the debate into a shared learning record" → **Report**, with
  **Refresh** and **Regenerate** beside it.
- **Live vote → a pie chart**, labelled with agent names (see 2.1).
- Left column aligns flush to the edge — no dead margin, one clean rectangle.

The remaining status lines (Anonymous classroom insight / Current report /
revision history) are compressed to the same economy without being asked line by
line: one label, one state, no explanatory sentence.

### 4.5 Agent scoring

A quantified read of how much each Agent grounded its speeches in retrieved
evidence, scored from the same evidence chain Check RAG already displays.

| Claim's `support_mode`        | Points |
| ----------------------------- | ------ |
| `direct`                      | +5     |
| `contextual`                  | +2     |
| `no_match`, general reasoning | 0      |

An Agent's score is the sum over its public turns, over every claim in each
turn's evidence chain.

**Computed in the browser, no contract change and no backend work.**
`DebateTurn` already carries `evidence_trace` in the frozen contract
(`schema.d.ts:1663`) and the transcript endpoint returns `DebateTurn[]`, so the
page has everything it needs. The `support_mode` → category mapping is the
_same helper_ written for §1.3 — one function serves both the Check RAG labels
and the score, so the two can never disagree.

Placement in the classroom interaction page, top to bottom:

```
votes (pie) + barrages
agent scores (bar chart)
report
—— nothing below ——
```

Charting: there is no chart library in this project and none is added. One small
shared SVG module renders both the vote pie (§4.4) and the score bars, keeping
the dependency surface at zero and the two charts visually consistent.

Label it for what it measures. This counts how often a claim was tied to
retrieved evidence — it is not a judgement of argument quality, in the same
spirit as the panel's existing "records generation lineage, not fact checking".

### 4.6 Audio release on Finish

Only sessions that ran to completion — `has_complete_finished_playback` true.
Partial Finish, `failed` and `stopped` keep their audio. `audio_file_id` stays
as a tombstone; the UI shows the existing `audioNotRetained` copy.

---

## Standing rule: reuse, then delete

Every item above prefers an existing seam to a new one — the score reuses the
evidence chain the panel already renders and the `support_mode` mapping written
for Check RAG; Regenerate reuses `POST /debates/{id}/preparation/retry`; the
pre-warm reuses `debate_turns` rows and `_turn_ready`; both charts share one SVG
module. Three of the four phases therefore change no contract at all.

The other half of that rule: whatever a change makes unreachable gets deleted in
the same commit — the translation module and its routes, the removed interaction
copy, any component left with no caller. Dead code that still compiles is the
expensive kind, because the next person has to prove it is dead before touching
anything near it.

## Audit method

The failure this guards against is real and recent: five separate sites had
hard-coded `participants * 2`, so a 3-agent 4-round debate looked incomplete to
every one of them and classroom interaction answered 404.

1. **Shape matrix.** 2/3/4/5 agents × 2/3/4/5 rounds — all 16, not just the demo
   shape. Each checks planned turn count, pre-warm progress denominator,
   evidence-chain count, and the post-Finish interaction entry.
2. **Single-resolver grep gate.** Anything needing a round count calls
   `debate_round_count` / `expected_turn_count` (backend) or
   `debateRoundCount` / `expectedTurnCount` (frontend). Audit by grepping for
   literal arithmetic near participants/rounds; every hit is a violation.
3. **Locale parity.** The existing key-set and zh≠en tests catch half-finished
   renames automatically.
4. **Fault injection** — the proof that Phase 3 is not decorative. Deliberately
   create each broken state (stuck `running`, dead turn, severed SSE, changed
   LAN IP) and recover **using only the UI**. Any state needing a terminal means
   Phase 3 is unfinished.
5. **Browser end-to-end in both locales**: create → pre-warm → start → step
   through → End → review → classroom interaction → report.
6. **Full gate every step**: `pnpm check` (backend lint/format/types/pytest,
   216 frontend tests, contract freeze check).

Known flake: `test_two_database_threads_concurrent_replace_have_one_winner`
races two SQLite writers and loses about one run in three. Re-run before
treating it as a regression.

---

## Sequence

| Phase                                                                                        | Contract                    | Ships                  |
| -------------------------------------------------------------------------------------------- | --------------------------- | ---------------------- |
| 1 — copy, Check RAG, round control, button economy                                           | unchanged                   | visible immediately    |
| 2 — interaction-entry bugs, report failure, vote names                                       | unchanged                   | reproduce first        |
| 3 — Release, Regenerate, reconnect attribution, runtime IP                                   | +1 endpoint, re-freeze      | fault injection passes |
| 4 — pre-warm, language lock, translation removal, panel cleanup, agent scores, audio release | +fields, −routes, re-freeze | 16-shape matrix passes |

Phases 1 and 2 touch no contract and land first. Phases 3 and 4 each re-freeze
the hash once.
