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
| RAG Opening | 160 characters         | 100 words              |
| Discussion  | 140 characters         | 90 words               |
| Response    | 160 characters         | 100 words              |
| Conclusion  | 180 characters         | 115 words              |

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

## Prior verification boundary

Earlier real four-round case `a2e6b748-91d7-40ce-b1db-70525224bde1`
completed eight speeches and Report revision 3. Eight LLM and four query calls
succeeded first attempt under the earlier retrieval policy. Other cases failed on
routing or acceptance_unknown. Full replay, RAG relevance and classroom quality
were not accepted. No partial test pass establishes universal success.

The owner authorizes main delivery and Docker updates, with final manual classroom
audit. A requested browser-click attempt was blocked by the Mac lock screen.
No usage reset is authorized. The external `/Users/xubosmell/Desktop/Maya/HANDOFF.md`
is owner-requested and can contain operational continuation instructions.

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
  Remake is always reachable in the list, including when no error classifier
  has detected a stall. It follows the first incomplete eligible turn or the
  retained playback checkpoint and uses current server versions. No generic
  failure prose is inserted into the list.

The new POST `/rebirth` and `/remake` endpoints use teacher authentication,
CSRF, idempotency and current-revision/control checks. Only Destroy intentionally
ignores old version values. Frozen OpenAPI, generated client and route fixtures
were updated together. Audit records distinguish fresh generation authorization
from media-only recovery; scope budgets preserve earlier allocated costs.

## Previous consolidated verification

Before the subsequent manual-browser fixes: 131 focused backend and 276 frontend
checks passed, alongside typing/lint/build checks. An earlier full backend suite
had 1,271 passes and 43 failures; it was not rerun in full. These results do not
accept the latest code or real classroom behavior. The Chinese Report call above
succeeded; no universal classroom-success claim is made.

## Latest manual-browser corrections — September 8 continuation

The owner reported stale Preview detail, silent Next, and duplicate-looking
Agent text under rapid Next after the preceding delivery. This invalidates any
assumption that its unit-test pass accepted classroom playback. The owner now
requests source/static audit only, with actual browser acceptance performed by
the owner. No tests or paid/provider/browser trials were run for this continuation.
Only deployment compilation is required to install the updated application.

Confirmed source causes and corrections:

- The text Preview detail loaded only once and did not mount a classroom WS
  subscription. It now silently polls while visible and refreshes on focus,
  preserving cards and rejecting stale responses across requests/routes.
- The WS loop overwrote a completed event task when a command published an event
  during its handler. The event was persisted but never delivered. Both receive
  and event tasks now survive until their results have actually been consumed.
- The frontend inferred turn indices from fixed Agent order even though rounds
  rotate speakers. It now uses existing identity or ordered public-event indices.
  Full snapshot application updates visible speech and speaker together; old
  callback/private replies cannot change a newer turn. The latest inspected
  four-Agent case had 12 distinct stored speech hashes; that read is evidence
  against exact database duplication, not an evaluation of semantic repetition.
- Next explicitly interrupts playing/paused audio and advances one adjacent
  ready turn under the same expected-turn/version CAS. Rapid duplicate requests
  cannot skip an extra turn. A natural-ended version conflict is retried once
  only after a fresh snapshot proves the original source turn is still current.
  Unready successors leave playback waiting. On the final speech, Next completes
  its existing playback; Final can stop the last Preview speech and freeze the
  barrage cutoff in one transaction before the normal final-generation queue.
- A delayed pre-play failure is validated before revoking a media ticket, so
  an invalid old failure cannot invalidate current playback.

The requested pre-delivery static audit also found two classroom blockers:
Rebirth deleted the completed Preview jobs that SQL Next requires; it now
preserves/rebinds their completion receipts to the new classroom fence, without
regeneration. Remake now inspects both LLM turn IDs and `turn:<id>` query IDs:
settled failed queries can restart on a fresh turn identity, successful query
stages stay reusable, and sending/unknown requests remain protected.

Every new four-round turn now retrieves from its own KB. Relative priorities in
the actual stage Prompts are high / low / medium / high, not numeric neural
attention weights. Opening/response anchors and stable question targets shape
queries; final queries use discussion memory, specific disagreement and frozen
barrages. At most three queries share one Embedding batch per turn. This changes
normal query batches from 2N to 4N (3N Preview, N final) within the existing first-run
4N ceiling, without extra LLM calls. Explicit Rebirth/Remake add only their new
turn-query allowance; existing token/money limits and provider consent remain.
No backend duplicate-text, S-ID or word-count rejection was added. Saved outputs
are not rewritten; the RAG/Prompt changes govern newly generated turns.

Deployment result and manual acceptance remain separate: the code is prepared
for the owner's browser audit, not certified as universally successful.

## Remake stalled Preview correction — September 8

A sanitized live inspection of `a675c540-611f-46fd-bd0b-f4da552f5c99`
found six ready speeches, followed by a pending seventh turn and a pending job
without progress after Remake. Both paid LLM attempts for that turn had failed
with `question_route_invalid`; their retained stage rows were incorrectly treated
as recoverable success. The old transcript fence then prevented a fresh claim.
The route also called scheduler release, permanently excluding this draft from
Preview scheduling, and only attempted to enqueue one turn.

Remake now checks the Provider operation state before reusing a staged response.
Settled failed responses use the existing explicit fresh-turn allowance; their
operation/charge records survive. The replacement keeps its input prefix and
cutoff, and subsequent ungenerated dependencies reference the replacement ID.
Local accepted-result recovery clears an unpublished claim fence while keeping
cached valid speech unchanged. Draft Remake explicitly reopens the Preview
scheduler and resumes the remaining sequence, rather than marking it ended.
Repeated identical requests do not schedule a second recovery.

Report now exposes only Regenerate (Conclude creates the first report); Refresh
and Generate labels are removed, and View revision is renamed Review.

The inspected failure debate was deleted during diagnosis and was not recreated.
Current validation results are recorded below; they are not a guarantee of model
quality or universal recovery from external failures.

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
new IDs, keeping exact Preview/audio. Report has only Regenerate and Review.
Generate Audio is removed from debate details. The list uses
Unvoice → Revoice → Revoice... (disabled) → Unvoice; failures retain the respective
retry action without an error message. List audio state is loaded from actual
saved-turn audio, not an optimistic label on a failed deletion. Agent version
pills are left of the divider, with Group on the right and aligned columns.
Remake supports draft/failed/stopped/completed and replay checkpoints, repairs
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

## Runtime and established UI

Next.js, FastAPI, SQLite/local files and Caddy share port 8080. Inspect active
SQLite only inside its container. Preserve private configuration, knowledge and
runtime data. TTS/Voice remain Mock; Debate LLM, Embedding and Report are configured
real DashScope adapters with independent authorization. Current Embedding is
text-embedding-v4, 1024 dimensions.

Teacher lists/creation use yellow rows on white paper. Unvoice/Destroy sit beside
Remake/Rebirth; Open Stage uses their action styling. Failed actions preserve the row.
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
