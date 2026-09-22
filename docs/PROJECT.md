# Maya Platform

Maya teaches through published Agents, Persona/RAG knowledge, classroom
debates, student messages and independent reports. Progress authority;
[AGENTS.md](../AGENTS.md) defines work. Latest user decisions prevail.

## Approved four-round teaching flow — September 8, 2026

New debates have exactly four rounds and two to five Agents; the complete
round selector is removed. Snapshots use `four_round_v1` and `segments_v2`;
the owner waived historical playback and recovery compatibility; existing
records are not silently regenerated/deleted.

1. Opening: high-priority own-KB evidence; independent claim and relevance;
   culture is a perspective, not proof; acknowledge missing evidence.
2. Discussion: low-priority new own-KB retrieval; start from the speaker's
   first-round position, respond to specific claims with agreement, challenge
   or a question, and ask the cyclically assigned stable Agent ID a clear
   question; no moderator or question-planning model is added.
3. Response: medium-priority RAG, round-two questions first; query own
   knowledge with the actual question or challenged point, state the retained,
   qualified or revised position and why, and save concise session memory in
   the same LLM output.
4. Conclusion: high-priority fresh own-KB retrieval plus history, shared
   evidence and session memory; name another Agent's point and explain
   agreement, criticism and learning; freeze earlier barrages once; each Agent
   answers one eligible message when available; no messages, no invented reply;
   disagreement may remain.

Preview saves exact text and Mock audio for rounds one through three; round
four is generated live. Opening is independent. Later turns see all successful
prior turns, including the same round, with complete previous-round barriers;
speaking order rotates but identities/question targets stay stable; scheduling,
SQL Next, input hashes and recovery use the same prefix; completed
results/accepted stages are reused, not charged again.

| Round      | Chinese upper guidance | English upper guidance |
| ---------- | ---------------------- | ---------------------- |
| Opening    | 500 characters         | 320 words              |
| Discussion | 450 characters         | 280 words              |
| Response   | 550 characters         | 350 words              |
| Conclusion | 650 characters         | 420 words              |

The owner's latest decision removes all backend speech-length validation and
minimums; the upper bounds live only in the System Prompt. Chinese guidance
counts non-whitespace characters including punctuation; English counts
alphanumeric runs with internal apostrophes/hyphens as one word; only segment
text counts. The backend never rejects, repairs, truncates or pads by length;
only readable nonempty paragraph text is required. Auxiliary
question/memory/source/barrage/support metadata cannot reject a speech;
unusable metadata is dropped or left ungraded, while valid bindings and source
text stay exact; unreadable JSON/text gets at most one authorized repair with
frozen input and feedback, one-call authorization cannot gain another, and
unknown acceptance is never silently resent. Question routing is separate from
barrage reply_to; third-round memory holds
position/change/reason/influence/unresolved_question, never classroom
speech/TTS, Agent.md, published versions or knowledge; round four and Report
read it under a separate session_discussion_memory outbound manifest class.
Cross-Agent source reuse needs an originating validated own-KB receipt in a
successful preceding turn of the same debate; aliases deduplicate
snapshot/chunk; migration 0024 removes only the obsolete speaker/snapshot FK,
retaining turn ownership, chunk/snapshot and unique constraints; direct +5,
contextual +2 and no_match +0 are evidence-support categories, not factual
correctness scores. Actual outbound prompts and synthetic I/O:
[FOUR_ROUND_PROMPTS.md](contracts/FOUR_ROUND_PROMPTS.md),
[four-round-example.json](contracts/four-round-example.json); content
acceptance reviews actual answers, new points, evidence and reasoned
disagreement; string similarity and keyword counts are not hard failure gates.

## Verification boundary

Operational browser acceptance is recorded below; complete RAG/content quality
still needs the owner's review. Main delivery and Docker updates are authorized;
no usage reset is authorized.

## Established classroom behavior

Next can interrupt audio and recover using saved media; lists refresh while
visible and on focus. Language, length and source alias wording are
Prompt-only; S IDs remain metadata; report language follows the debate,
renders Markdown without executing raw HTML, and does not reject prose for
rhetorical/length rules; schema 0025 removed old report word-count publication
limits. Larger Stage names omit A/B/C. Replay uses saved text/audio, hides
Open Message and collects no new barrages. Immerse controls are now a fixed-size
right-edge stack; a separate Transcript button toggles the speech sidebar.

## Classroom actions

- **Devocalize** removes saved audio; speech and sources survive.
- **Destroy** deletes the target debate regardless of draft/running/stalled/
  terminal state; its writer transaction uses current revisions, so a stale
  list cannot block the destructive intent. The list sends the ID without
  depending on a successful detail projection and removes the row after the
  delete commits, even if file cleanup is pending; other active classrooms no
  longer block a scoped deletion and an absent legacy playback row is
  materialized transactionally; workers get cancellation after the durable
  deletion fence and the HTTP response does not wait for an external supplier.
  Teacher/course authorization, shared-file ownership and path safety stay
  enforced; this cannot retract a request already sent to a supplier, and late
  work cannot recreate the deleted graph.
- **Rebirth** is available on completed lessons, including retained replay. It
  preserves the first three rounds' exact text, evidence, discussion memory and
  audio, unpublishes them for classroom replay, removes final-round turns/audio
  and classroom/report data, creates a fresh closed message window, and returns
  to a Preview-ready draft with new-identity final turns. Each Rebirth funds
  one additional final round (within the per-turn attempt cap); it calls no
  Provider and regenerates no Preview.
- **Remake** remains a guarded recovery API, not a visible Refresh action. The
  latest UI removes all Refresh buttons, bulk retry and blocked-lesson recovery
  buttons. List/focus reads never regenerate failures. Explicit recovery retains
  prior charges, reuses saved results, and cannot duplicate sending or unknown
  acceptance. End remains stop; auth, CSRF, identity and control guards remain.

## Playback and retrieval

Preview polls while visible. Stage consumes ordered WebSocket events, applies
speech/speaker atomically, ignores stale media callbacks and lets Next
interrupt audio; final freezes barrages transactionally. Each round retrieves
from its own KB with high/low/medium/high Prompt priority; up to three queries
share one Embedding batch within the 4N initial allowance. Settled failed
Provider responses are not cached successes; explicit Remake uses its
fresh-turn allowance, preserves charge records and valid cached results,
rebinds pending dependencies and rejoins Preview scheduling; deleted
diagnostics are not recreated. Report
offers Regenerate and Review; Conclude creates its first revision. Readable
speech survives unusable auxiliary metadata; invalid bindings stay ungraded.
Rebirth resets final dependencies in one
writer transaction, restoring immutability triggers on success or rollback;
Devocalize/Revocalize survive failures; consent, cost, identity and state
guards remain, none establishing real-service acceptance.

## Runtime and established UI

Next.js, FastAPI, SQLite/local files and Caddy share port 8080. Inspect active
SQLite only inside its container; preserve private configuration, knowledge
and runtime data. TTS/Voice remain Mock; Debate LLM, Embedding and Report use
configured real DashScope adapters with independent authorization; Embedding
is 1024-dimensional. Devocalize/Destroy sit beside Rebirth; failed actions
preserve the row. Stage titles and the bottom operation panel are removed.
Small fixed-size buttons stand alone on the far right, without a backing board.
Transcript toggles a separate sidebar with Public Debate, status, progress and
Check RAG; Escape closes it and restores focus. Bubbles persist until Next;
Interact/Hide preserves its QR session; Conclude shows Evaluation sorted
by score without name prefixes, plus Report Version/History; Audio Ready
indicates retained audio.

## Remaining scope

Full RAG quality acceptance remains incomplete: 徐伯闻 owns acceptance; 古月 owns
3D/voice/TTS and Kaikai accounts/student UI. Classroom-scale load, public
deployment, monitoring, backup/restore, real speech and data/licensing
governance stay outside this local Demo scope.
[ARCHITECTURE.md](ARCHITECTURE.md), [contracts](../contracts/) and [ADRs](adr/)
hold stable design references; preview and Stage Check RAG count unique
evidence sources; Waiting/Finish-blocked prose, generic 3D error text and
audio replacement dialogs are gone. Current automated checks do not replace
the owner's classroom content and visual audit.

## Topic and Background

Topics accept arbitrary visible scripts/symbols; Topic/optional Background are
stored separately (migration0026); titles display Topic only. Outbound text
gets NFC/control cleanup and whitespace folding without removing meaningful
punctuation; Background is unverified scenario data; provider budgets remain;
draft edits invalidate old Preview plans; creation has separate white
Topic/Background cards, sidebar Back/Done, and Ruleset language selection.

## Frozen Markdown Ruleset and current Report repair

Default teaching content lives only in
backend/app/modules/debates/default_rules/zh.md and en.md, loaded through a
teacher-scoped read-only endpoint. Agents Order is followed by one Debate
Ruleset row: compact language switch and Edit. Selected-language Markdown is
rendered full-width; Edit shows raw text; sidebar Done updates that language,
Back discards the edit. Both return to rendered mode and restore the debate
creation actions; saving rules never creates a debate. The old Multi-round
Civilization/phase block is removed and Topic/Background use white textareas.
Create freezes both authored Markdown files and eight complete System messages
(four per language) in rule_snapshot_json. Markdown is sent intact, with no
heading parser or old pedagogical Prompt appended; only the language/
current-round, JSON/source/routing execution contract is added. Changes to
default files or other debates cannot alter this snapshot; draft updates
preserve frozen rules and reject replacement attempts; default-file reads make
no Provider calls. Migration 0027_frozen_teaching_markdown freezes defaults
for existing four-round rows, preserving saved speeches, custom snapshots and
non-four-round records. Turn input hashes and recovery envelopes keep frozen
System messages; repair appends feedback to the same message. UI rejects
executable HTML/unsafe links; provider budgets and authorization are unchanged;
model compliance stays manual; Chinese direct/contextual/no_match wording is
“RAG证实”/“RAG提示”/“我感觉”, editable Prompt guidance only; no-match reasoning
states assumptions without inventing facts. Transcript has one current/total
indicator with nonvisual connection status. Network recovery uses Back/reentry;
Report keeps complete evidence within request budgets and safe error paths.
Creation defaults to Chinese, preserves independent CN/EN drafts and omitted
language, uses linked-height Topic/Background and newest-first Agents Order;
mobile stacks. The separate Beta list redirects to Debates. Row actions remain
Rebirth, Immerse, Devocalize/Revocalize and Destroy. Full Agent Profile and
immutable RAG Check/Download remain. Replay and Conclude require completion;
saved media/controller recovery never automatically retries generation or advances.
Live starts/handoff clear replay cursors. Report bibliographic prose is not a
private-input keyword failure; relationship/schema guards remain. Agent.md has
a 12,000-character total budget without field/list caps.

## Obsolete protocol removal — September 10, 2026

The two old demo RuleSets, their Prompt module and generation/retrieval/Mock
branches are removed. The API and WebSocket contracts accept only
`ordered_multi_expert_mutual_learning_v1`; new Debates use four-round
`segments_v2`; migration files and stored-result readers remain because the
database depends on them; obsolete length and prior-round-only test baselines
no longer block every-round RAG and same-round context.

## Account integration — September 12, 2026

Single-course Demo: open student registration, five-character passwords,
distinct unknown-user/wrong-password errors; multi-course registration deferred.
Catalog accounts stay source-managed. Migration 0029 enforces canonical username
and group uniqueness; collisions stop migration, duplicates never alter a login.
Teacher group access survives catalog sync: Enter grants workspace CRUD under
the teacher identity; Homeward returns to Accounts. CSRF, publication, course,
provider consent and cost boundaries remain; TTS/Voice configuration is preserved.

## Classroom display — September 18, 2026

PR 29 merged at `ed22231`. Two to five licensed scholar figures stand around
the courtyard table; jaw motion, bubble and Transcript follow audio, while
saved text remains readable on media failure. `/local-roundtable` accepts a
local generated WAV directory. Cloned voices are uploader-owned. Optional
Gaussian scene packs remain local experiments described by ADR-007, not a
default runtime dependency.

Two fully skipped obsolete backend tests and completed plans were removed;
current assertions and the four-round manual checklist remain.

## Operation panel and browser acceptance — September 22, 2026

The owner approved ending the previous lesson, retaining its content. One Ready
three-Agent debate completed Start, Next, Interact/Hide, Check RAG, four rounds/
12 turns, Conclude and Version 1 Report. Replay and reload preserved the result.
Nine Preview speeches were reused. Seven new charged calls succeeded with exact
confirmations: three Embedding queries, three final LLM turns and one Report;
replay/reopening Report added none. TTS/Voice remain Mock; no student messages/
votes were sent. Real speech and classroom-scale acceptance remain unverified.

Retained Preview turns 5/6 and 8/9 have identical speech ignoring whitespace;
list text says “2 Rounds” despite the four-round snapshot. Neither was rewritten.
Performance and full RAG teaching quality remain open.
[ADR-008](adr/ADR-008-agent-chat-live-provider-controls.md) records the accepted
integration/reuse boundaries. This earlier acceptance does not cover the new work below.

## Working — workspace, private Chat and Live, September 22, 2026

Private teacher/student Chat uses existing published Agents and 3D previews.
The approved scope includes Provider controls, read-only Live and non-login UI;
no effort selector, Chat uploads or new framework dependency. AGENTS.md sets
simplicity first; permissions, prompts and safety/cost confirmations remain.

Migration 0030 adds owner-bound conversation history, encrypted local Provider
preferences and 20-second Live leases. Chat freezes the published version/snapshot,
retains history and sources, uses request identity and revision fences, and stops
on unknown Provider acceptance. Five components remain visible: LLM/Embedding/Report
can switch; TTS/Voice remain deferred. Existing classroom audio configuration is not
changed. Live uses student-only snapshots/authorized retained audio, never controller
messages or new generation per spectator.

Non-login UI uses ui-ux-pro-max and Web Interface Guidelines: scoped system fonts,
gray/white surfaces, login warm yellow, original mark in the Mayaform nav item,
no separate brand/header, no visible page titles or Refresh. Accounts keeps
username/group/status. Chat shows one current Agent name. Components is compact
with one Check: skip Ready/deferred items, confirm the maximum paid calls, stop
on failure. Mode changes invalidate only that item; key changes invalidate all.
Live places full public speech history below the scene and reconnects by reentry.
Sidebar New/Back/Done replace duplicate page actions and hide when unavailable;
Chat has New/Send only, fullscreen Immerse keeps its controls. Agent entry directly
shows the current version; New creates or opens its next-version draft. Student
Done saves edits then publishes the returned revision only if server checks pass;
Compile also saves first. Back warns about unsaved Agent edits. Workspace drops
the duplicate knowledge summary; libraries keep one editor with Back/Done. Failed
creation retains text, unchanged retries retain identity and edits rotate it.
Chat New clears the composer without saving an empty conversation; the first
message saves it. Older empty records are hidden, not deleted.

Acceptance: frontend 377 passed, one skipped; typecheck passed, lint has four
existing warnings. Base-release backend run: 1384 passed, 21 skipped and the documented
two-writer knowledge-test flake failed; its immediate isolated rerun passed.
Base checks: nine workspace tests, Ruff, mypy, formatting and all contract,
boundary and reset-safety gates passed. Images built with unchanged dependencies;
containers were healthy after recreation.

Browser checks covered teacher/student Chat, history, source display, ownership
isolation (cross-user reads return 404), Components, Accounts and 375px/desktop
layout. Ready/Completed Immerse controls remain 104x44px desktop, with transparent
parent; Transcript preserves Public Debate and completion state. Two identities
verified saved replay, Live late entry/reentry and public history without student
controls; completion switches Live offline.
Existing classrooms, Agent assets, login and TTS configuration survive.

Sidebar follow-up: IAB at 1440px/375px verified create/cancel, direct Agent view,
existing-draft New and Ruleset Done. No overflow or duplicate page actions;
Chat and Ready Immerse keep their exceptions. Obsolete Info tests/styles were
replaced by flow tests. No backend changes or new provider calls; no Agent published.

Real acceptance in this change used 11 assistant-initiated paid calls: four Chat
messages (four Embedding plus four LLM), one LLM Check and two Report Checks.
Two-message retest returned 90/180 characters with one/two sources; repeated same
request and history reads made no extra calls. A manual second-message failure was
reproduced offline: multiplying an early float disagreed with the stored decimal
budget; multiplication now stays Decimal until conversion. The failed request made
no new provider call and remains in history; user-generated content was not edited.
Live replay and all-Ready Check made no generation calls. The workspace ledger
also includes concurrent user tests: 17 successful paid calls total (7 Embedding,
10 LLM including checks) at this acceptance snapshot, not all assistant requests.

User chose Bailian Beijing for later real-time face-to-face voice, explicitly after
this manual-audit delivery. No real-time service has been called or installed;
TTS/Voice remain Mock/Deferred. Full RAG teaching quality, real speech, classroom
load and public deployment remain unverified.
