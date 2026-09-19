# Maya Platform

Maya teaches through published Agents, Persona/RAG knowledge, classroom debates,
student messages and independent reports.
Progress authority; [AGENTS.md](../AGENTS.md) defines work. Latest user decisions prevail.

## Approved four-round teaching flow — September 8, 2026

New debates have exactly four rounds and two to five Agents. The complete round
selector is removed. Snapshots use `four_round_v1` and `segments_v2`. The owner waived historical playback
and recovery compatibility. Existing records are not silently regenerated/deleted.

1. Opening: high-priority own-KB evidence; independent claim and its relevance. Culture is
   a perspective, not proof; acknowledge missing evidence.
2. Discussion: low-priority new own-KB retrieval. Start from the speaker's own
   first-round position/evidence, then respond to specific other claims with
   agreement, challenge or a question. Ask the cyclically assigned stable Agent
   ID a clear question. No moderator or question-planning model is added.
3. Response: medium-priority RAG; prioritize round-two questions. Query the speaker's own knowledge
   with the actual question or challenged point. State retained, qualified or
   revised position and why. Save concise session memory in the same LLM output.
4. Conclusion: high-priority fresh own-KB retrieval, alongside history, shared
   evidence and session memory. Name another Agent's point, explain agreement,
   criticism and learning. Freeze
   earlier barrages once; each Agent substantively answers one eligible message
   when available. No messages means no invented reply; disagreement may remain.

Preview saves exact text and Mock audio for rounds one through three; round four
is generated live. Opening is independent. Later turns see all successful prior
turns, including the same round, with complete previous-round barriers. Speaking
order rotates but identities/question targets stay stable. Scheduling, SQL Next,
input hashes and recovery use the same prefix. Completed results/accepted stages
are reused rather than charged again.

| Round      | Chinese upper guidance | English upper guidance |
| ---------- | ---------------------- | ---------------------- |
| Opening    | 500 characters         | 320 words              |
| Discussion | 450 characters         | 280 words              |
| Response   | 550 characters         | 350 words              |
| Conclusion | 650 characters         | 420 words              |

The owner's latest decision removes all backend speech-length validation and
all minimum lengths. These upper bounds appear in the actual System Prompt only.
Chinese guidance counts non-whitespace characters including punctuation; English
counts alphanumeric runs with internal apostrophes/hyphens as one word. Only
segment text counts. The backend neither rejects nor repairs a response because
of its length, and never truncates or pads it. Only readable nonempty paragraph text is required from model output. Auxiliary
question/memory/source/barrage/support metadata cannot reject a speech. Unusable
metadata is omitted or left ungraded; valid source bindings and original text
remain exact. Unreadable JSON/text shares at most one authorized repair with
frozen input and feedback. One-call authorization cannot gain another call; unknown
acceptance is never silently resent.

Question routing is separate from barrage reply_to. Third-round memory contains
position/change/reason/influence/unresolved_question, never classroom speech/TTS,
Agent.md, published versions or knowledge. Round four and Report read it under a
separate session_discussion_memory outbound manifest class.

Cross-Agent source reuse requires an originating validated own-KB receipt in a
successful preceding turn of the same debate. Aliases deduplicate snapshot/chunk.
Migration 0024 removes only the obsolete speaker/snapshot FK, retaining turn
ownership, chunk/snapshot and unique constraints. direct +5, contextual +2 and
no_match +0 are evidence-support categories, not factual correctness scores.

Actual outbound prompts and synthetic I/O:
[FOUR_ROUND_PROMPTS.md](contracts/FOUR_ROUND_PROMPTS.md),
[four-round-example.json](contracts/four-round-example.json).
Content acceptance reviews actual answers, new points, evidence and reasoned
disagreement; string similarity and keyword counts are not hard failure gates.

## Report loading correction

Bibliographic URLs remain allowed. Failed jobs settle aggregate and revision;
startup reconciles orphan generating jobs without paid calls. UI ignores stale
status responses; failed history reads cannot hide a ready report. Diagnostic
logs contain safe codes/types, never response bodies.

## Verification boundary

Previous partial real runs do not establish complete RAG/classroom acceptance.
The owner authorizes main delivery and Docker updates; final classroom audit is
manual. No usage reset is authorized. The external owner-requested HANDOFF.md
contains continuation instructions.

## Established classroom behavior

Next can interrupt audio and recover using saved media. Lists refresh while
visible and on focus. Language, length and source alias wording are Prompt-only;
S IDs remain metadata. Report language follows the debate, renders Markdown
without executing raw HTML, and does not reject prose for rhetorical/length
rules. Schema 0025 removed old report word-count publication limits. Larger Stage
names omit A/B/C. Replay uses saved text/audio, hides Open Message and collects
no new barrages. 3D controls stay in two columns: Next/Back then End/Interact
during live playback, and disabled Next/Back then Replay/Conclude at completion.

## Classroom actions

- **Devocalize** removes saved audio; speech and sources survive.
- **Destroy** deletes the target debate regardless of draft/running/stalled/terminal
  state. Its writer transaction uses current revisions, so a stale list cannot
  block the destructive intent. The list sends the ID without depending on a
  successful detail projection and removes the row after the delete commits,
  even if file cleanup is pending. Other active classrooms no longer block a
  scoped deletion. An absent legacy playback row is materialized transactionally.
  Workers receive cancellation after the durable deletion fence; the HTTP response
  does not wait for an external supplier to return. Teacher/course authorization,
  shared-file ownership and path safety remain enforced. This cannot retract a
  request already sent to a supplier, and late work cannot recreate the deleted graph.
- **Rebirth** is available on completed lessons, including retained replay. It preserves the
  first three rounds' exact text, evidence, discussion memory and audio, unpublishes
  them for classroom replay, removes final-round turns/audio and classroom/report
  data, creates a fresh closed message window, and returns to a Preview-ready draft.
  New final turns have new identities. Cost operations survive. Each explicit
  Rebirth funds only one additional final round (within the existing per-turn
  attempt cap); it does not call a Provider itself or regenerate Preview.
- **Remake** supersedes Resume/Release in the list. The owner's later correction
  explicitly supersedes the earlier stop-to-Stopped proposal: Remake recovers a
  current/adjacent failed turn and leaves the classroom resumable; End remains stop.
  Saved speech/audio are reused; missing saved audio uses the dedicated TTS path.
  A settled failed paid turn can get a new identity and a bounded new attempt on
  the teacher's explicit click, while old charge records remain. Accepted results
  are recovered locally. Sending/acceptance-unknown requests are not duplicated.
  One global Refresh (Remake recovery) sits beside New; no per-row Remake remains. It
  refreshes every record and recovers failed/stalled work, following the first
  incomplete eligible turn or the
  retained playback checkpoint and uses current server versions. No generic
  failure prose is inserted into the list.

Recovery endpoints retain authentication, CSRF, idempotency and control checks.
Only Destroy ignores old versions. Audit records distinguish fresh generation
authorization from media-only recovery; prior cost allocations remain.

## Playback and retrieval

Preview polls while visible. Stage consumes ordered WebSocket events, applies
speech/speaker atomically, ignores stale media callbacks and lets Next interrupt
audio. Final freezes barrages transactionally. Each round retrieves from its own
KB with high/low/medium/high Prompt priority; up to three queries share one
Embedding batch, within the existing 4N initial allowance.

## Recovery and output boundaries

Settled failed Provider responses are not cached successes. Explicit Remake uses
its fresh-turn allowance, preserves charge records and valid cached results,
rebinds pending dependencies and rejoins Preview scheduling; unknown acceptance is
never resent and deleted diagnostic records are not recreated. Report offers
Regenerate and Review; Conclude creates its first revision. Readable speech
survives unusable auxiliary metadata; invalid bindings remain ungraded. No text
truncation, padding or rewriting. Rebirth resets final dependencies in one writer
transaction, restoring immutability triggers on success or rollback.
Devocalize/Revocalize preserve their action after failures. Consent/cost/identity/
state guards remain, and these checks do not establish real-service acceptance.

## Prompt-only repetition correction

Prompts anchor each speaker in its own Persona, RAG and prior position, asking
later turns to add evidence, answers or judgment. Agreement is allowed; no
similarity rejection or rewriting. Teaching quality still needs manual review.

A separate Embedding connection issue remains deferred at the owner’s request.

## Runtime and established UI

Next.js, FastAPI, SQLite/local files and Caddy share port 8080. Inspect active
SQLite only inside its container. Preserve private configuration, knowledge and
runtime data. TTS/Voice remain Mock; Debate LLM, Embedding and Report are configured
real DashScope adapters with independent authorization. Current Embedding is 1024-dimensional.

Teacher lists/creation use yellow rows on white paper. Devocalize/Destroy sit beside
Rebirth; global Refresh sits beside New; Immerse uses their action styling. Failed actions preserve the row.
Stage titles are removed; speech scrolls above compact gold controls and bubbles
persist until Next. Interact/Hide preserves its QR session. Conclude shows Evaluation sorted by score without name prefixes, and Report Version/History. Audio Ready indicates retained audio.

## Remaining scope

Full RAG quality acceptance remains incomplete. 徐伯闻 owns acceptance; 古月 owns
3D/voice/TTS and Kaikai accounts/student UI.

Classroom-scale load, public deployment, monitoring, backup/restore, real speech
and data/licensing governance remain outside this local Demo scope.
[ARCHITECTURE.md](ARCHITECTURE.md), [contracts](../contracts/) and [ADRs](adr/)
retain stable design references.

Preview and Stage Check RAG count unique evidence sources. Waiting/Finish-blocked
prose, generic 3D error text and audio replacement dialogs are removed; control
and cost guards remain. Older broad Wave2 playback tests retain two unresolved
native-ended/hidden-index assertions; targeted Beta checks are not a full-suite pass.

## Topic and Background

Topics accept arbitrary visible scripts/symbols. Topic/optional Background are
stored separately (migration0026); titles display Topic only. Outbound text uses
NFC/control cleanup and whitespace folding without removing meaningful punctuation.
Background is unverified scenario data. Total Provider budgets remain; draft edits
invalidate old Preview plans. Creation has separate white Topic/Background cards, Done beside Back,
and language selection in Ruleset.

## Frozen Markdown Ruleset and current Report repair

Default teaching content now lives only in backend/app/modules/debates/default_rules/
zh.md and en.md. The creation form loads both through a teacher-scoped read-only
endpoint. Agents Order is followed by one Debate Ruleset row: compact language
switch and Edit. Selected-language Markdown is always rendered full-width;
Edit shows raw text; Save updates that language in this form and returns to rendered mode. Done is disabled while
editing. The old Multi-round Civilization/phase block is removed; Topic and
Background inputs use white textareas.

Create freezes both authored Markdown files and eight complete System messages
(four for each language) in rule_snapshot_json. Markdown is sent intact, with no
heading parser or old pedagogical Prompt appended. Only the language/current-round,
JSON/source/routing execution contract is added. Changes to default files or other
debates cannot alter this snapshot. Draft updates preserve frozen rules and reject
attempts to replace them; default-file reads make no Provider calls. Migration
0027_frozen_teaching_markdown freezes defaults for existing four-round rows while
preserving their saved speeches, custom snapshots and non-four-round records.

Turn input hashes and recovery envelopes retain frozen System messages; repair
appends feedback to the same message. UI rejects executable HTML/unsafe links.
Provider budgets and authorization are unchanged; model compliance remains manual.
Chinese direct/contextual/no_match wording is “RAG证实”/“RAG提示”/“我感觉”, editable
Prompt guidance only. No-match reasoning states assumptions without inventing facts.

3D Stage removes the transcript header count and visible connection wording.
A single current/total bubble sits at the transcript top right, outside controls,
following the displayed turn (e.g. 4/12): green when
connected, red otherwise, with accessible nonvisual connection text. Existing
3D network recovery uses Back/re-entry; authentication sign-in/reload actions remain.

Report preserves complete evidence within total request budgets and omits obsolete
translated_markdown failure fields. Diagnostics retain safe validation paths. The
owner reset the affected lesson, preventing replay of its original failed Report.

Creation defaults to Chinese; language changes outside Edit preserve independent
CN/EN drafts and only the selected language drives generation. Draft updates that
omit language preserve it. Create section title dividers share one style.

Creation uses linked-height Topic/Background inputs and newest-first Agents Order
with version/group, stable selection and per-Agent stance/notes; mobile stacks.

Navigation: Home/Classroom; list: Debates/New.
The separate Beta list is removed (old URL redirects); nested 3D controls remain.
Immerse opens the same control route from ready Preview or each eligible list row.
Action order is Rebirth when completed, Immerse, Devocalize/Revocalize, Destroy.
Audio restoration displays disabled Revocalize...; stage ready label is Ready.

Mayaform brands Home/login/navigation. Teacher surfaces share yellow/white cards,
gold dividers, 24/18px panel insets and 20px section gaps. Agent Profile shows the
full body; immutable RAG documents retain Check and Download. Evaluation and Report
use yellow content in white shells with version actions at the top right.

3D Replay is hidden before completion; Interact/Hide preserves the QR session.
Conclude waits for playback completion. Stage shows Waiting when Next is enabled,
otherwise Generating. Replay recovery uses saved media and existing controller
acquisition. Readiness reads do not enable generation/media retries or auto-advance;
already-ready notifications skip refresh. Live starts and controller handoff clear
legacy replay cursors. Report bibliographic prose no longer triggers private-input
keyword rejection; relationship/schema checks remain. Retained report input validates.

Agent.md has a 12,000-character total budget; no field/list caps.

## Obsolete protocol removal — September 10, 2026

The two old demo RuleSets, their Prompt module and their generation/retrieval/Mock
branches are removed. The API and WebSocket contracts accept only
`ordered_multi_expert_mutual_learning_v1`; new Debates use four-round
`segments_v2`. Migration files and stored-result readers remain because the
database still depends on them. Obsolete length and prior-round-only test
baselines no longer block the current every-round RAG and same-round context.

## Preview Background module

Preview starts with a yellow Background card when Background is non-blank.

## Stalled-debate correction

The local 8,000-token per-item Embedding cap was removed for long Backgrounds;
request-level limits remain. LLM validation now checks JSON/approved fields,
not keywords or identity patterns in teacher/RAG/classroom prose. Credentials
and endpoints remain absent from outbound DTOs. Existing failed turns need an
explicit Retry/Refresh after the backend update.

## Account integration — September 12, 2026

The owner approves PR 28's single-course Demo, open student registration without
invitations, five-character passwords, and distinct unknown-username/wrong-password
messages. Multi-course registration remains deferred. Catalog accounts remain source-managed; teacher edits apply to registered accounts.

Migration 0029 backfills NFKC/casefold username keys and NFKC/whitespace/casefold
course-group keys with database uniqueness. Registration claims run in one writer
transaction; duplicate claims return a form alert without changing an existing
login. Registration and teacher moves use the same group normalization/upsert.
Canonical collisions stop migration.

Teacher access persists in teacher_group_access across catalog sync. Enter grants
full workspace CRUD under the teacher identity. Groups has Enter only; Homeward
returns to Accounts. No course subtitle. Publication/history, CSRF, course and provider consent/cost rules remain.
This supersedes the previous teacher deletion prohibition.

Existing real LLM four-round generation, Embedding and Report configuration is
preserved; TTS/Voice remain as configured. Real Provider acceptance remains manual.

Account integration had partial frontend 334/1 and backend 1339/24 results;
contracts, lint, types and Docker health passed. Classroom audit remained open.

## Accounts and student workspace design

Accounts, student routes and QR interaction share teacher typography, white/
pale-yellow surfaces, gold dividers and responsive spacing. Home/group lists show
Agent names and status; Description lives in Agent Info; Homeward returns to
Accounts. Duplicate panels, counters and title prose are removed. Content,
validation, consent and Provider configuration are unchanged. Type/lint/build
passed and desktop/390px UI was inspected; classroom audit remains open.

## Classroom display — September 18, 2026

Bubble follows audio; text survives errors. Two licensed FBXs became textured
GLBs; 2-5 figures stand with lowered hands and moving jaws in Chrome/Edge.
The supplied courtyard replaced chairs/seating; a stray elder accessory is
hidden in stage clones. ZIPs untracked, no push.
Student clone IDs remain owner-only. Two speakers stand opposite; 3-5 form a
ring. Beta transcript follows audio and falls back to full text on failure.
Full-stage `/local-roundtable` imports a generated WAV directory;
Chromium played two Qwen3-TTS turns in sequence with 3D speaker motion and
audio-paced text. Desktop/mobile rendered; Mac untested. Local Qwen3.6 and
Qwen3-TTS samples are not Maya Provider integration. Full suites retain known
failures.
Cloud TTS, classroom acceptance and voice cloning remain open; no paid Provider
request was sent.
Sep 19: controls, grounding and lighting polished; 390/320px checked.
Immerse keeps the teacher dock; local transcript translucent. Teacher/Mac audit
open. Courtyard trials: soft SOG (`?splat=1`), sharp mesh (`?depth=1`); see
[ADR-007](adr/ADR-007-courtyard-splat.md).
