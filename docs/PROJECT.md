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

## Report loading correction

Bibliographic URLs stay allowed; failed jobs settle aggregate and revision;
startup reconciles orphan generating jobs without paid calls; UI ignores stale
status responses and failed history reads cannot hide a ready report; logs
hold safe codes/types, never response bodies.

## Verification boundary

Previous partial real runs do not establish complete RAG/classroom acceptance;
the owner authorizes main delivery and Docker updates, final classroom audit is
manual, and no usage reset is authorized. The external owner-requested
HANDOFF.md holds continuation instructions.

## Established classroom behavior

Next can interrupt audio and recover using saved media; lists refresh while
visible and on focus. Language, length and source alias wording are
Prompt-only; S IDs remain metadata; report language follows the debate,
renders Markdown without executing raw HTML, and does not reject prose for
rhetorical/length rules; schema 0025 removed old report word-count publication
limits. Larger Stage names omit A/B/C. Replay uses saved text/audio, hides
Open Message and collects no new barrages; 3D controls stay in two columns:
Next/Back then End/Interact during live playback, and disabled Next/Back then
Replay/Conclude at completion.

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
- **Remake** supersedes Resume/Release in the list. The owner's later
  correction explicitly supersedes the earlier stop-to-Stopped proposal: Remake
  recovers a current/adjacent failed turn and leaves the classroom resumable;
  End remains stop. Saved speech/audio are reused; missing saved audio uses the
  dedicated TTS path. A settled failed paid turn can get a new identity and a
  bounded new attempt on the teacher's explicit click, while old charges stay.
  Accepted results are recovered locally; sending/acceptance-unknown requests
  are not duplicated. One global Refresh (Remake recovery) sits beside New; no
  per-row Remake remains. It refreshes every record and recovers failed/stalled
  work, following the first incomplete eligible turn or the retained playback
  checkpoint and using current server versions. No generic failure prose enters
  the list. Recovery endpoints keep authentication, CSRF, idempotency and
  control checks; only Destroy ignores old versions; audits separate fresh
  generation authorization from media-only recovery and prior costs remain.

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

## Prompt-only repetition correction

Prompts anchor each speaker in its own Persona, RAG and prior position, asking
later turns to add evidence, answers or judgment; agreement is allowed, with no
similarity rejection or rewriting; teaching quality still needs manual review;
an Embedding connection issue stays deferred at the owner's request.

## Runtime and established UI

Next.js, FastAPI, SQLite/local files and Caddy share port 8080. Inspect active
SQLite only inside its container; preserve private configuration, knowledge
and runtime data. TTS/Voice remain Mock; Debate LLM, Embedding and Report use
configured real DashScope adapters with independent authorization; Embedding
is 1024-dimensional. Teacher lists/creation use yellow rows on white paper;
Devocalize/Destroy sit beside Rebirth; Immerse uses
their action styling; failed actions preserve the row. Stage titles are
removed; the bottom operation panel always shows the speech beside two-column
light controls, with no separate transcript toggle; bubbles persist until
Next; Interact/Hide preserves its QR session; Conclude shows Evaluation sorted
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
Topic/Background cards, Done beside Back, and Ruleset language selection.

## Frozen Markdown Ruleset and current Report repair

Default teaching content lives only in
backend/app/modules/debates/default_rules/zh.md and en.md, loaded through a
teacher-scoped read-only endpoint. Agents Order is followed by one Debate
Ruleset row: compact language switch and Edit. Selected-language Markdown is
rendered full-width; Edit shows raw text; Save updates that language and
returns to rendered mode. Done is disabled while editing; the old Multi-round
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
states assumptions without inventing facts. 3D Stage removes the transcript
header count and visible connection wording; a single current/total bubble
sits at the transcript top right, outside controls, following the displayed
turn (e.g. 4/12): green when connected, red otherwise, with accessible
nonvisual connection text; existing 3D network recovery uses Back/re-entry and
sign-in/reload actions remain. Report preserves complete evidence within total
request budgets and drops obsolete translated_markdown failure fields;
diagnostics keep safe validation paths; the owner reset the affected lesson,
preventing replay of its original failed Report. Creation defaults to Chinese;
language changes outside Edit preserve independent CN/EN drafts and only the
selected language drives generation; draft updates that omit language preserve
it. Creation uses linked-height
Topic/Background inputs and newest-first Agents Order with version/group,
stable selection and per-Agent stance/notes; mobile stacks. Navigation:
Home/Classroom; list: Debates/New; the separate Beta list is removed (old URL
redirects), nested 3D controls remain. Immerse opens the same control route
from ready Preview or each eligible list row; action order is Rebirth when
completed, Immerse, Devocalize/Revocalize, Destroy; audio restoration shows
disabled Revocalize...; stage ready label is Ready. Mayaform brands Home/login/
navigation; teacher surfaces share yellow/white cards, gold dividers, 24/18px
panel insets and 20px section gaps. Agent Profile shows the full body;
immutable RAG documents keep Check and Download; Evaluation and Report use
yellow content in white shells with version actions at the top right. 3D
Replay is hidden before completion;
conclude waits for playback completion. Stage shows Waiting when Next is
enabled, otherwise Generating; replay recovery uses saved media and existing
controller acquisition; readiness reads do not enable retries or auto-advance;
already-ready notifications skip refresh; live starts and controller handoff
clear legacy replay cursors; report bibliographic prose no longer triggers
private-input keyword rejection; relationship/schema checks remain; retained
report input validates; Agent.md has a 12,000-character total budget, no
field/list caps.

## Obsolete protocol removal — September 10, 2026

The two old demo RuleSets, their Prompt module and generation/retrieval/Mock
branches are removed. The API and WebSocket contracts accept only
`ordered_multi_expert_mutual_learning_v1`; new Debates use four-round
`segments_v2`; migration files and stored-result readers remain because the
database depends on them; obsolete length and prior-round-only test baselines
no longer block every-round RAG and same-round context.

## Preview Background module

Preview starts with a yellow Background card when Background is non-blank.

## Stalled-debate correction

The local 8,000-token per-item Embedding cap was removed for long Backgrounds;
request-level limits remain. LLM validation checks JSON/approved fields, not
keywords or identity patterns in prose; credentials and endpoints stay absent
from outbound DTOs; failed turns need one explicit Retry/Refresh after deploy.

## Account integration — September 12, 2026

The owner approves PR 28's single-course Demo, open student registration
without invitations, five-character passwords, and distinct
unknown-username/wrong-password messages; multi-course registration stays
deferred. Catalog accounts remain source-managed; teacher edits apply to
registered accounts; migration 0029 backfills NFKC/casefold username keys and
NFKC/whitespace/casefold course-group keys with database uniqueness;
registration claims run in one writer transaction; duplicate claims return a
form alert without changing an existing login; registration and teacher moves
share group normalization/upsert; canonical collisions stop migration.

Teacher access persists in teacher_group_access across catalog sync. Enter
grants full workspace CRUD under the teacher identity; Groups has Enter only
and Homeward returns to Accounts. No course subtitle; publication/history,
CSRF, course and provider consent/cost rules remain; this supersedes the
previous teacher deletion prohibition; existing real LLM four-round
generation, Embedding and Report configuration is preserved; TTS/Voice stay as
configured; real Provider acceptance is manual; account integration had
partial backend 1339/24 results; contracts, lint and types passed. Classroom
behavior remains a manual acceptance boundary.

## Accounts and student workspace design

Accounts, student routes and QR interaction share teacher typography, white/
pale-yellow surfaces, gold dividers and responsive spacing. Home/group lists
show Agent names and status; Description lives in Agent Info; Homeward returns
to Accounts; duplicate panels, counters and title prose are removed; content,
validation, consent and Provider configuration are unchanged; type/lint/build
passed and desktop/390px UI was inspected; classroom audit stays open.

## Classroom display — September 18, 2026

PR 29 merged at `ed22231`. Two to five licensed scholar figures stand around
the courtyard table; jaw motion, bubble and Transcript follow audio, while
saved text remains readable on media failure. `/local-roundtable` accepts a
local generated WAV directory. Cloned voices are uploader-owned. Optional
Gaussian scene packs remain local experiments described by ADR-007, not a
default runtime dependency.

The frontend suite passes 364 tests with one explicitly skipped historical
native-audio case. Two fully skipped obsolete backend test files and completed
planning/blocker documents were removed; current assertions and the four-round
manual checklist remain. A fresh Docker build started healthy backend,
frontend and gateway containers; `/`, frontend `/health` and backend
`/health/ready` returned HTTP 200. The owner is performing the classroom audit.
No paid Provider request was sent; Mac performance, cloud TTS and formal
classroom acceptance remain open.
