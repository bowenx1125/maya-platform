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
Catalog accounts start source-managed; a successful self-service password change
creates a database override without mutating the read-only catalog. Login checks
that override first, the current session survives the change, and every other
session is revoked. Migration 0029 enforces canonical username and group uniqueness;
collisions stop migration, duplicates never alter a login.
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

## Current workspace, profiles and provider behavior

Migration 0030 adds owner-bound Chat history, encrypted local Provider settings
and 20-second Live leases. Chats freeze the published Agent version and knowledge
snapshot, preserve same-conversation history and request identity, and stop on
unknown provider acceptance. Live spectators receive only public content and
retained audio. LLM, Embedding and Report are configurable; TTS/Voice stay
Mock/Deferred. Agent.md is passed as authored Markdown (12,000-character maximum),
and RAG files allow 100,000 characters each. Product-level Chat turn, daily,
message, prompt-byte and output-token caps are removed; authorization, CSRF,
ownership, deduplication, ledger and unknown-acceptance guards remain.

Migration 0031 adds shared Agent tombstones. Delete removes workspace access but
retains immutable assets and private Chats read-only; a Debate reference or active
publication blocks it. Quiet workspace actions use accessible icon controls;
Chats has New, delete and an inline Send arrow; libraries share Back/Done editors.
The product UI uses compact Inter typography and warm paper surfaces; display serif
is reserved for login. Teacher Debate rows enter through Immerse.

Student and teacher Home show a welcome, course context and live guide status.
Student progress derives from group Agent, Knowledge and Voice state; teacher
progress derives from course, group, published-Agent and Debate state. Home shows
group members and published-Agent authors with generated preset avatars, and the
teacher roster uses the same avatars. Every signed-in user can choose a preset and
change their own password; uploads are not accepted. Migration 0033 adds the
nullable avatar field. Password changes keep the current session and revoke all
others; catalog accounts gain a database credential override.

Snapshot publication has no request, token or CNY ceiling, but batches still pack
at most 10 items and 30,000 counted tokens. Matching staged accepts are restored
after local failure instead of resent; unknown acceptance may retry up to three
times per build, with a 120-second embedding read timeout. Debate query identity
uses the published Agent.md hash. Query and LLM scope ceilings are unbounded, and
stored recovery input has no 256 KiB stop. Authentication, ownership, immutable
snapshot and cost-ledger boundaries remain. Real-provider quality and classroom
scale remain unverified.

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
The JSON `POST .../messages` route remains and stores assistant text through the
same commit as the stream. A turn's full assistant text is committed once,
immediately before `text_done`; a later TTS failure does not remove it. The
conversation lock is released immediately after `text_done`, and the request
database session is not held across the LLM call or TTS. TTS runs once after
that and the `tts_ready` event carries an `audio_url`, not audio bytes. `lang`
is `zh-CN` or `en`. Student enrollment still stores the external voice id
encrypted and a draft can bind `voice_profile_id`. TTS and voice clone may be
`dashscope` beside the existing real slices only through `DASHSCOPE_API_KEY`.
Defaults stay mock. Qwen voice-clone WAVs may keep RIFF and data sizes near
2**31; only that placeholder shape is rewritten before the same technical audio
check. TTS sends `language_type` English or Chinese for en and zh. The debate
contract's "language English" line is the previously checked mode. Enrollment
sends supplier language `zh` or `en` from sample language `zh-CN` or `en`.
`DASHSCOPE_API_KEY` is rotated by editing the environment and restarting;
voice rows do not store the key. `BASELINE_DEFAULT_VOICES` selects a ready
profile for an immutable baseline character, and an omitted name uses
`FALLBACK_VOICE_PROFILE_ID`. This change made no charged provider call.
