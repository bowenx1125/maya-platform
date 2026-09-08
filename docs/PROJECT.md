# Maya Platform

Maya is a local teaching platform: groups publish culture-focused Agents with
Persona and immutable Markdown knowledge; teachers run multi-Agent lessons,
collect classroom messages and conclude with an independent Report.
This file is the progress authority. [AGENTS.md](../AGENTS.md) defines repository
work; the user's latest explicit instruction overrides older plans.

## Approved four-round teaching flow — September 8, 2026

New debates have exactly four rounds and two to five Agents. The complete round
selector is removed. New snapshots record `teaching_protocol=four_round_v1`;
paragraph storage remains `segments_v2`. The owner waived historical playback
and recovery compatibility. Existing records are not silently regenerated/deleted.

1. RAG Opening: high-priority own-KB evidence; independent claim and its relevance. Culture is
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

| Round       | Chinese upper guidance | English upper guidance |
| ----------- | ---------------------- | ---------------------- |
| RAG Opening | 500 characters         | 320 words              |
| Discussion  | 450 characters         | 280 words               |
| Response    | 550 characters         | 350 words              |
| Conclusion  | 650 characters         | 420 words              |

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

Report inputs preserve bibliographic URLs after the owner removed the blanket
`https://` rejection; a real call succeeded. Unexpected failures now fail both
revision and aggregate. Startup reconciles orphan generating aggregates without
calling the Provider, preserving active jobs. Frontend status reads ignore stale
responses and failed revision-history reads cannot hide a ready report. Logs
contain safe codes and exception types, never response bodies.

## Verification boundary

Previous partial real runs do not establish complete RAG/classroom acceptance.
The owner authorizes main delivery and Docker updates; final classroom audit is
manual. No usage reset is authorized. The external owner-requested HANDOFF.md
contains continuation instructions.

## Current requested fixes — September 8 classroom audit

Implemented: Next media failures recover in place using saved audio, with no
Regenerate or generic playback-failure card. Duplicate prepared-media messages
do not restart the same audio element. A committed recovery event is now published
even when audio fails before started_ack. Lists refresh progress every two seconds
while visible and on focus.

Content requirements (language, length, wording, source aliases) are prompt-only.
Speech prompts reserve S IDs for metadata and ask for natural references to RAG.
No backend S-token detection/replacement is added; saved speeches stay unchanged.
Report language follows the frozen debate language: Chinese for zh, English for en.
Report prose is no longer rejected for language, length, Markdown or rhetorical
rules; schema 0025 also removes the old database word-count publication limits.
Only readable output, authorization, verified source bindings, cost and state integrity remain.

The report is rendered as Markdown, including headings/lists/tables, with raw HTML
execution disabled. Stage uses larger Agent names without A/B/C. Retained replay
uses saved text/audio and hides Open Message; no new barrages are collected.
A lone second-row action spans the controls. Conclude becomes available after
replay completes. One newly authorized real Report for Chinese debate
`c0e48278-c094-4c1f-8b6f-080b48b13767` completed in about 14 seconds;
revision 3 is ready with a Chinese title and 1,007 Chinese characters. No Debate
LLM or TTS regeneration was requested for this playback audit.

## Classroom actions — final owner decisions

- **Unvoice** removes saved audio; speech and sources survive.
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
  One global Remake sits beside New Debate; no per-row Remake remains. It
  refreshes every record and recovers failed/stalled work, following the first
  incomplete eligible turn or the
  retained playback checkpoint and uses current server versions. No generic
  failure prose is inserted into the list.

The new POST `/rebirth` and `/remake` endpoints use teacher authentication,
CSRF, idempotency and current-revision/control checks. Only Destroy intentionally
ignores old version values. Frozen OpenAPI, generated client and route fixtures
were updated together. Audit records distinguish fresh generation authorization
from media-only recovery; scope budgets preserve earlier allocated costs.

## Earlier browser-state corrections

The owner reproduced stale Preview, silent Next and duplicate-looking Agent text.
Corrections include visible-page Preview polling; preserving completed WS event
and receive tasks until consumed; sequential public-event indices under rotated
speaker order; atomic speech/speaker snapshot application; and rejecting stale
media callbacks. Next can interrupt playing/paused audio and advance the adjacent
ready turn under version/identity checks. A natural-ended race retries only after
confirming the original source turn is still current. Final freezes the barrage
cutoff transactionally. Rebirth preserves completed Preview job receipts.

Every new turn retrieves from its own KB with Prompt priorities high/low/medium/
high. Up to three queries share one Embedding batch per turn: 3N Preview plus N
final, within the initial 4N ceiling. Explicit Rebirth/Remake add only their new
query allowance under existing token/money/consent limits. Saved outputs are not
rewritten. These changes were not universal browser or teaching-quality acceptance.

## Remake recovery

Settled failed Provider responses are not cached successes. Explicit Remake uses
its fresh-turn allowance, preserves charge records and valid cached results,
rebinds pending dependencies and rejoins Preview scheduling. Unknown acceptance
is not resent. Report offers Regenerate and Review; Conclude creates its first
revision. Deleted diagnostic records are not recreated.

## Latest owner refinements

All model auxiliary-output requirements are prompt guidance, not speech rejection
or repair triggers. Wrong/missing question routing, optional discussion memory,
source aliases, support modes and barrage replies preserve exact paragraph text.
Only usable metadata is projected. Unknown source IDs never become evidence;
inconsistent support is ungraded (zero points), while valid direct/contextual/
no_match retain +5/+2/+0. No text is truncated, rewritten or padded. Missing
optional response memory cannot block Conclude/Report; history remains available.
Structural nonempty text/JSON parsing, consent, costs and database ownership/state
fences remain. Prompt instructions still describe the expected output.

Rebirth now accepts completed replay and binds new final-turn dependencies to the
new IDs, keeping exact Preview/audio. A later live-schema reproduction found migration
0020's final_input_immutable trigger still blocked Rebirth. Explicit reset writes
now temporarily suspend and restore that one trigger inside BEGIN IMMEDIATE;
ordinary updates stay protected and rollback restores data plus trigger. The
current real case reproduced successfully in an in-memory clone, with Preview
text/audio IDs unchanged and the trigger restored. No live records were reset.
Lifecycle fixtures now include this actual trigger and the multi-draft recovery
queue; 14 checks cover these paths, including
rollback protection. Report has only Regenerate and Review.
Generate Audio is removed from debate details. The list uses
Unvoice → Revoice → Revoice... (disabled) → Unvoice; failures retain the respective
retry action without an error message. List audio state is loaded from actual
saved-turn audio, not an optimistic label on a failed deletion. Agent version
pills are left of the divider. Group is right-aligned with the same 18px text
inset and typography as Destroy, sharing its action CSS without a hover effect; both
align vertically with the version pill.
The recovery service supports draft/failed/stopped/completed and replay checkpoints, repairs
orphan job claims and rebinds retained completion receipts. Completed healthy
history stays completed; failed Reports can be regenerated through the same
explicit click. In-flight/unknown paid requests are not duplicated, and another
active classroom's ownership is not silently taken away. These remain recovery
boundaries, so universal one-click recovery from every external outage is not claimed.

The list's additive audio_restore_needed field avoids fetching every detail
(which would change the Preview scheduler owner). Frozen OpenAPI, generated
client and fixtures are updated together; no database migration is needed.
Revoice also restores saved audio in Stopped/Failed debates without restarting
the lesson or calling the Debate LLM.

Latest verification: 81 focused backend checks plus 9 cached-audio checks passed;
17 frontend checks, typing, targeted lint/format and semantic contract comparison
passed. Both production images built and were restarted. Browser navigation
confirmed Agent pill/divider alignment, list actions and no detail Generate Audio.
Two retained-replay Next clicks switched Elena → Mira → Rowan with matching text;
this is a spot check, not full classroom or teaching-quality acceptance. No paid
Provider-generation test or destructive browser action was performed.

## Prompt-only repetition correction

Actual Prompts anchor each speaker in its own Persona, opening, RAG and questions.
Later turns contribute evidence, answers or judgment rather than paraphrasing the
previous speaker. Agreement is allowed; no similarity rejection or text rewriting
was added. New model output still requires manual teaching-quality review.

## Latest delivery additions

Destroy rejected four real records because committed debate_turn_tts journals
use staging/debate-turn-tts/course/debate/turn/operation.wav, absent from its
ownership allowlist. Exact same-course/debate UUID WAV paths are now recognized;
other scopes, traversal and symlinks remain protected. All four deletes succeeded
in independent in-memory clones with foreign keys intact. Actual user records
were not deleted during diagnosis. Owned empty staging directories are removed.

Global Remake refreshes the list, resumes abnormal drafts and failed Reports,
and continues past a blocked record. Preview resumptions queue serially rather
than overwriting scheduler ownership. Stage and Debate lists share DebateStatus,
so Ready/Completed label and badge treatment come from the same state mapping.

Both Conclude paths now request report/generate?initial=true after finalization.
The writer transaction reuses any started/ready/failed report instead of making
a second initial revision; Regenerate still explicitly creates a new revision.
Report history omits Ready and its separator, keeping the word count and Review.
The separate How to date with girls? connection failure is deferred at the owner's
request: the recorded failure was an Embedding ConnectError, not rejected speech;
a no-auth HEAD probe subsequently connected. No new paid generation test was run.

Latest batch verification: 47 focused backend checks and 61 frontend checks
passed, including scoped TTS-file deletion, trigger-aware Rebirth, queued global
recovery, initial-report reuse and Conclude's first-generation request. Type,
targeted lint/format and OpenAPI semantic checks passed. The full suites and a
new paid teaching-quality run were not performed.

## Runtime and established UI

Next.js, FastAPI, SQLite/local files and Caddy share port 8080. Inspect active
SQLite only inside its container. Preserve private configuration, knowledge and
runtime data. TTS/Voice remain Mock; Debate LLM, Embedding and Report are configured
real DashScope adapters with independent authorization. Current Embedding is
text-embedding-v4, 1024 dimensions.

Teacher lists/creation use yellow rows on white paper. Unvoice/Destroy sit beside
Rebirth; global Remake sits beside New Debate; Open Stage uses their action styling. Failed actions preserve the row.
Stage titles are removed; speech scrolls above compact gold controls and bubbles
persist until Next. Open Message/Hide preserves its QR session. Conclude contains
Report and scores; Audio Ready indicates retained audio. This change adds only
fixed-four-round and phase-label UI work.

## Remaining scope

Earlier two-round and partial RAG experiments do not validate this four-round
protocol. Full RAG quality acceptance remains incomplete. Module DDL is 9.10; acceptance owner is 徐伯闻.
古月 owns 3D/voice/TTS, Kaikai accounts/student UI, 徐伯闻 remaining modules.

Classroom-scale load, public deployment, monitoring, backup/restore, real speech
and data/licensing governance remain outside this local Demo scope.
[ARCHITECTURE.md](ARCHITECTURE.md), [contracts](../contracts/) and [ADRs](adr/)
retain stable design references.

Latest Prompt guidance treats speeches as substantive essay answers: relevant
explanation, evidence and direct answers earn credit; repetition, digression and
padding do not. Persona shapes priorities, criteria and recommendations, never
invented facts. RAG material is selected for complementary relevance and explained,
not merely named. Expanded language-specific upper guidance appears above; no
minimum or runtime length rejection was restored. Provider request/token ceilings
remain unchanged. An additional 21 four-round backend checks and 11 Preview/Stage
frontend checks passed after this change; frontend types passed. These checks
do not validate model answer depth or teaching quality. Preview and Stage Check RAG now count unique evidence source IDs,
not paragraphs, using the same badge treatment. Saved speeches remain unchanged.

Stage presentation now uses “unconnected” for network disconnection. Controller
waiting and Finish-blocked prose, generic 3D error text, redundant confirmation
labels and the Stage audio replacement browser dialog are removed. Connection,
control, Provider authorization and mutation guards remain enforced.
Targeted UI/connection checks: 26 passed; types passed and lint had no errors
(four existing warnings). Broader playback checks also exposed unresolved native
ended-ack and hidden-turn-index assertions; no claim of full playback acceptance.
