# Maya Platform

Maya teaches through published Agent Markdown, RAG knowledge, classroom
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
4. Conclusion: high-priority fresh own-KB retrieval plus public earlier speeches
   and session memory; name another Agent's point and explain
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
Each Agent reads only its own knowledge and Persona. Other Agents' public
speeches stay visible; their knowledge receipts and Persona do not. Migration
0024 removes only the obsolete speaker/snapshot FK, retaining turn ownership,
chunk/snapshot and unique constraints; direct +5,
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
- **Delete** deletes the target debate regardless of draft/running/stalled/
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
is 1024-dimensional. Devocalize/Delete sit beside Rebirth; failed actions
preserve the row. The Immerse topic stays fixed at the bottom left. The old bottom operation panel is removed.
Small fixed-size buttons stand alone on the far right, without a backing board.
Transcript toggles a separate sidebar with Public Debate, status, progress and
Check RAG; Escape closes it and restores focus. Bubbles persist until Next;
Interact/Hide preserves its QR session; Conclude shows Evaluation sorted
by score without name prefixes, plus Report Version/History; Audio Ready
indicates retained audio.

## Remaining scope

徐伯闻 owns content acceptance, 古月 3D/voice/TTS, Kaikai accounts/student UI.
Full RAG quality, classroom load, public deployment, monitoring, backup/restore
and real speech remain unverified. [ARCHITECTURE.md](ARCHITECTURE.md),
[contracts](../contracts/) and [ADRs](adr/) hold stable design references.

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
Ruleset row: compact language switch with pencil Edit and checkmark Save.
Selected-language Markdown is rendered full-width; Edit shows raw text; the
checkmark beside 中文/English saves that language and returns to rendered mode.
Sidebar Back discards an unsaved edit. Sidebar Done creates the debate and does
not save an unsaved ruleset edit (Done stays away while the ruleset is in Edit).
The old Multi-round Civilization/phase block is removed and Topic/Background use
warm paper textareas.
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
“RAG证实”/“RAG提示”/“我感觉”, editable Prompt guidance only. A speech answers
the Topic from retrieved evidence first. No-match general reasoning infers that
answer from Agent.md, keeps a narrower source claim at its own scope, and does
not invent facts absent from Agent.md and the sources. Transcript has one current/total
indicator with nonvisual connection status. Network recovery uses Back/reentry;
Report keeps complete evidence within request budgets and safe error paths.
Creation defaults to Chinese, preserves independent CN/EN drafts and omitted
language, uses linked-height Topic/Background and newest-first Agents Order;
mobile stacks. The separate Beta list redirects to Debates. Row actions remain
Rebirth, Immerse, Devocalize/Revocalize and Delete. Full Agent Profile and
immutable RAG Check/Download remain. Replay and Conclude require completion;
saved media/controller recovery never automatically retries generation or advances.
Live starts/handoff clear replay cursors. Report bibliographic prose is not a
private-input keyword failure; relationship/schema guards remain. Agent.md has
a 12,000-character total budget without field/list caps.

## Obsolete protocol removal — September 10, 2026

Old RuleSets and their branches are removed. Only
`ordered_multi_expert_mutual_learning_v1` is accepted; new Debates use four-round
`segments_v2`. Migration files and stored-result readers remain for retained data.

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

## Working — workspace, private Chats and Live

Migration 0030 adds owner-bound history, encrypted local Provider preferences and
20-second Live leases. Chats freezes a published version/snapshot and uses request
identity, revision fences and a cost ledger. Unknown provider acceptance stops a
conversation. Five components remain visible: LLM/Embedding/Report can switch;
TTS/Voice stay Mock/Deferred. Student Live shares public content and retained audio,
never controller messages or a new generation request per spectator.

Non-login UI follows ui-ux-pro-max Minimalism and the login mood: display-serif
section headings, warm paper cards (`#fdfaf3`), quiet type scale, original mark in
the Mayaform navigation item. No separate brand wordmark, visible page titles or
Refresh. Accounts keeps username/group/status; group Enter is an arrow with an
accessible name. Logout matches sidebar link size. Components has one Check,
skips Ready/deferred items, confirms the maximum paid calls and stops on failure.
Mode/key changes invalidate the relevant checks. Live keeps speech history.

Sidebar New stays registered on screens that own it and fades when disabled;
Back and Done still appear only when that screen needs them. Chats has New,
conversation delete (hover/focus X on a history row), and Send; switching the
Agent model always opens a new chat. Agent entry shows the current version; New
opens/creates its next draft. Done saves then publishes the returned revision
when checks pass; Back warns about unsaved edits. Libraries use quiet icon
actions (pencil Edit, download glyph, X Delete) and one Back/Done editor.
Failed creation retains text and retry identity.

Earlier deployed browser acceptance covered both identities, owner-only history,
Components/Accounts, 375px/desktop, Replay and Live. Immerse buttons retained
104x44px desktop dimensions; Docker and retained classroom/assets were healthy.
That release made 11 assistant-paid calls: 4 Chat Embedding + 4 Chat LLM,
1 LLM Check and 2 Report Checks. Repeated requests/history added none. Decimal
budget multiplication fixed a second-message failure before dispatch. Concurrent
user work brought that dated ledger to 17 successes (7 Embedding, 10 LLM/checks);
these counts do not describe the new checkpoint or later user requests.

## Working — free Markdown, deletion and composer checkpoint

Agent.md now passes directly to Chats and Debate generation as authored Chinese/
English Markdown, maximum 12,000 characters. Its optional default template covers
identity, characteristics and four thinking questions; no chapter parser, per-field
caps, semantic rules or executed ToT/ReAct. Persona/Compile/Confirm and Test Chat UI
are removed. Legacy columns, frozen API routes and historical codecs remain for
saved data; they no longer gate publishing. RAG content is unrestricted, capped at
100,000 characters per file, not across all files; file access and non-execution
boundaries remain. Old classroom rules/results are not rewritten.

Migration 0031 adds a shared Agent tombstone. Workspace Delete removes teacher/
student access, retains immutable assets and private chats read-only, and preserves
shared knowledge/voice files. Any Debate reference or active publication blocks
deletion under the same writer lock as concurrent creation/publication.

Chats is the visible label; Message and redundant knowledge revision/status copy
are removed. Switching Agent restores nonempty history; New alone starts fresh.
Sending clears the draft immediately and shows the user message while waiting;
the accessible arrow sits inside the composer. A network failure restores text
and preserves request identity. Same-conversation saved history is sent on reentry;
no cross-chat personal memory is promised.

Acceptance: backend 1391 passed/21 skipped; frontend 373 passed/1 skipped, plus
23 focused UI checks. Types, Ruff, format, API/WS/boundary/reset and migration probes
passed; old migration seeds now use historical columns, not today's ORM. Docker
rebuilt/restarted, migration 0031/readiness/integrity passed after SQLite backup.
Teacher Chats checked at 1440px/375px without overflow; arrow is 44x44px inside the
composer. No new real calls, live Agent deletion or classroom generation. Obsolete
Persona UI/tests and duplicate full Prompts removed; provider quality remains unverified.

## Working — Chats without product I/O caps (observed 2026-09-23)

Removed Chats product input/output stop rules that blocked SiyaH. Observed in
the local Docker stack (`POST /api/v1/conversations/{id}/messages`):

- Historical failures stored as `chat_context_full` (32,000-byte outbound JSON
  gate and related turn/daily ceilings).
- After those gates were lifted, SiyaH still failed with
  `export_data_forbidden` because Agent.md contains the lesson word
  `Authorization` and chat preflight scanned educational payload prose as if it
  were a credential leak.

Code change (same commit): drop the 20-turn stop, 100/day limit, 4,000-character
message max, outbound JSON byte reject, and `max_tokens: 1500` request field;
keep full conversation history in the prompt without summary/crop instructions;
skip chat payload content scanning while leaving auth, CSRF, ownership,
acceptance-unknown stop, and header credential handling intact; use finite
per-call ledger reservations with sentinel-unbounded scope ceilings so multi-turn
chats still share one budget. OpenAPI `SendChat` no longer declares
`maxLength: 4000` or a `429` response. Focused backend chat tests passed,
including a regression that sends educational `Authorization` text.

Not observed in this change: a new charged SiyaH real-provider acceptance run
after Docker rebuild; RAG teaching-quality acceptance. Supplier capacity,
authentication, ownership and deduplication remain.

## Working — quiet workspace UI (observed in code 2026-09-24)

Mayaform home shows Welcome then Members; the old Workspace Members card is gone.
Student Knowledge lists `Files · N` in a two-column tile grid; library Delete is the
quiet X and soft-hides or removes the library row without rewriting published
knowledge snapshots. Workspace and teacher Agents use a six-column tile grid with
name, group, and version bubble vertically centered on warm paper; green/brown
bubbles show the version label; hover/focus swaps the label for X to delete.
Teacher Debates list no longer opens Preview from the row — Immerse remains the
entry. AGENT.md, Evidence, and Knowledge snapshot cards use a top-right download
icon; Evidence downloads every RAG file in the block; snapshot file rows keep
filename and character count without `order N`. Snapshot SNAPSHOT/CONTENT/FILES
are three vertical stacks (label above value) at the existing number size. Chats
composer is a single-line bar at the bottom of the pane. Ruleset save is the
checkmark beside language; sidebar Done does not save an unsaved Edit. Symbol
actions and faded New / contextual Back/Done remain as before.

## Snapshot publish quota — September 23, 2026

The owner removed the real-snapshot request, token and CNY ceilings. Planning still
packs at most 10 items and 30,000 counted tokens per batch. `embedding_snapshot`
scope rows use unbounded ceilings so reservation cannot reimpose the old cap. Query
embedding and LLM budgets are unchanged.

A later publish of the same 罗燕玲 draft reached DashScope. One batch was accepted
and staged; the next batch returned HTTP 500. Continuation keeps a staged accept,
restores it when the stage still matches, and resends an explicit
`provider_http_rejected` batch once.

The publish after that accepted five batches, then one batch hit a DashScope read
timeout at 30 seconds (`acceptance_unknown`) and the two batches after it stayed
`not_sent`. The next click stopped before any send because a timeout with no staged
response was terminal, and that batch was already on attempt 2 of 2. Continuation
now sends an `acceptance_unknown` batch that has no staged response again, up to
three attempts for the build. The embedding read timeout is 120 seconds. Accepted
batches are still reused. Retrying the timed-out batch is another charged request.

The draft was saved again before the next publish, so that click started a new
build instead of continuing the timed-out one. At 07:28 UTC all nine batches of
that build succeeded. 罗燕玲 version `eaa37c26-c30a-4332-826c-2533820dcc13` is
published with a DashScope `text-embedding-v4` snapshot, dimension 1024, and 12
stored chunks. The earlier timed-out build remains on the ledger and was not
resent.

SiyaH's later draft had both embedding batches staged, then the local snapshot
commit failed and those rows stayed `failed`. Later clicks stopped before any
send. A failed batch that still has a matching stage is restored to `accepted`
and published locally; the supplier request is not repeated. At 07:39 UTC draft
`cc072330-3885-4a39-ba28-adb0136fd976` published that way, with a DashScope
`text-embedding-v4` snapshot, dimension 1024, 7 stored chunks, and no new
embedding request.

Debate query identity uses the published AGENT.md hash. A missing compiled
Persona hash no longer stops the turn, and the segment prompt sends that
AGENT.md.

Debate turns no longer stop on a prompt token, byte or output count, and a
Debate's query and LLM scope ceilings are unbounded. Embedding and query
batches are not rejected for input size. A draft whose current turn already
failed does not take the warmer away from another Debate. A query that was
proven not sent can be attempted once more. The stored LLM recovery input no
longer stops at 256 KiB, so a turn whose prompt includes AGENT.md can be saved
after the supplier accepts it.

## Next atomic task

`LLM_MODEL` selects the chat, debate and report model. When it is unset, the
server uses `qwen3.8-max-2026-09-02`. Supplier price cards are not consulted.
Embedding and speech models stay pinned. A charged acceptance run on that
snapshot has not been recorded.

Then implement model/effort UI independent of teacher defaults, with provider
capabilities and server-side keys. Prefer audited assistant-ui/AI Elements/Agno
reuse (ADR-008), no cloud history.

Later real-time face-to-face voice uses Bailian Beijing, after text/UI manual audit.
The teacher Components switch still leaves TTS and Voice deferred. Full RAG
teaching quality, real speech, classroom-scale load and public deployment remain
unverified.

Chat streaming is `POST /api/v1/conversations/{conversation_id}/messages:stream`.
The JSON `POST .../messages` route remains. A turn's full assistant text is
committed once, immediately before `text_done`; a later TTS failure does not
remove it. TTS runs once after that and the `tts_ready` event carries an
`audio_url`, not audio bytes. `lang` is `zh-CN` or `en`. Student enrollment
still stores the external voice id encrypted and a draft can bind
`voice_profile_id`. TTS and voice clone may be `dashscope` beside the existing
real slices only through `DASHSCOPE_API_KEY`. Defaults stay mock. This change
made no charged provider call.
