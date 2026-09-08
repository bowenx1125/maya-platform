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
of its length, and never truncates or pads it. Nonempty text, structure, source
references, question routing and state integrity remain enforced. Structure and
reference errors share at most one authorized repair with frozen input and
explicit feedback. One-call authorization cannot gain another call; unknown
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

The owner removed the blanket `https://` rejection from Report input checks.
Original bibliographic URLs and source prose now pass unchanged; there is no URL
omission projection. A real Report with these URLs completed successfully.
Unexpected task logs now record exception type rather than validation input bodies.

An unexpected task failure previously failed the revision/job but left its
aggregate generating. A sanitized live read found two generating aggregates
with zero generating revisions, alongside three ready reports. The fix updates
aggregate failure and reconciles orphan states at startup without another
Provider call, preserving valid in-progress jobs. The frontend independently
reads Report status, ignores stale responses and prevents a failed/hung revision
history read from masking success. Report remains a separate Conclude operation.

## Verification and delivery boundary — September 8 continuation

The four-round real case `a2e6b748-91d7-40ce-b1db-70525224bde1` completed
all eight speeches, retained audio, frozen classroom messages, final-round replies
and the HTTP/WebSocket playback sequence. Its six Preview turns took about 38s.
Eight Debate LLM operations and four query-Embedding operations succeeded on
attempt one. No completed speech was regenerated. Independent Report revision 3
is ready with original source URLs preserved. Two Report calls succeeded in total:
one tested an intermediate URL-omission projection, the second tested the final
owner-approved removal of the blanket URL check. The first failed revision never
reached the Report Provider. Supplier billing and the operation ledger are authoritative.

The browser showed all eight public speeches, two 3D figures, the speech bubble,
separate scrolling speech/control areas and Conclude. A retained-audio replay began
successfully; restarting Docker during replay exposed an existing recovery issue:
controls can remain disabled until an explicit release/reload. A complete eight-turn
browser audio replay has NOT been accepted. Report can now read the original frozen
final input after a completed lesson's replay is released; live generation still
requires the cancellation fence. Never treat replay's control generation as a reason
to regenerate the already frozen classroom messages.

Previous delivery checks (before this classroom audit):

- 63 focused backend generation/routing/recovery tests passed, including one real
  SQL accepted-stage recovery with a fake supplier proving one LLM call only.
- 26 focused Report tests passed, including source URL preservation, memory,
  orphan status reconciliation and completed-history/live-fence separation.
- Full frontend: 264 tests passed; typecheck passed; lint has zero errors and
  four existing warnings. Backend Ruff/mypy passed (187 modules); formatter
  checked 319 files. Backend/frontend Docker builds and health checks passed.
- Full backend suite still has 47 failing cases. Many depend on obsolete two-round
  creation or old protocol fixtures; others need investigation. Current-contract
  tests passing does not make that suite green. Only the shared recovery fixture
  needed by the current SQL test was migrated to explicit four-round Preview.
- Formatting, document-authority and repository secret/runtime boundaries passed.
  No database backups or runtime/provider payloads are added to Git.

Other observed cases are failures, not successful lessons:
`731791c9-7f85-46a3-b529-8c22a369a23e` has five of six Preview speeches saved;
its last response exhausted its two attempts on question/barrage routing errors.
The repaired Prompt now states only the current phase's metadata requirements,
with explicit null values and actionable repair feedback. Its ledger has four
succeeded query operations, five succeeded LLM operations and four failed LLM
operations. `34d0a285-c148-4a9e-8098-2b9891d963ae` reached seven speeches; its
last request has acceptance_unknown and was not resent. That incomplete test was
ended through the normal API. A Chinese case failed at 96/77 characters under the
old 100-character floor; no speech-length rejection remains in the paragraph path.

Remaining: migrate/remove obsolete tests while preserving current authorization,
cost, source and concurrency coverage; repair interrupted browser replay recovery;
review RAG teaching quality with topic-matched Persona/knowledge fixtures. The real
case above intentionally exposed mismatched relationship-psychology material for a
classroom-history topic: some answers correctly acknowledged the gap, one opening
followed the Persona's unrelated scenario, and later conclusions were repetitive.
This is functional run evidence, NOT evidence that RAG relevance, natural debate
quality, all requirements or a universal 100% success rate have been accepted.

The owner resumed work for the playback, live-list, bilingual Report and Stage
changes below. Preserve the other window's existing test/replay edits.
The owner prefers consolidated validation and proportionate failure follow-ups.
A paid Chinese Report check was authorized and completed. The latest owner decision
leaves actual browser/classroom acceptance to the owner; do not run further browser
tests for this delivery. The quota stop boundary is removed; future
Chat GPT-6 continuation uses Bridge MCP and can continue until usage is exhausted.
No quota reset is authorized. The owner explicitly requested the external
`/Users/xubosmell/Desktop/Maya/HANDOFF.md` be overwritten with operational state
and parallel Luna Max ownership/integration instructions; no Codex access setup.

## Current requested fixes — September 8 classroom audit

Implemented: Next media failures recover in place using saved audio, with no
Regenerate or generic playback-failure card. Duplicate prepared-media messages
do not restart the same audio element. A committed recovery event is now published
even when audio fails before started_ack. Lists refresh progress every two seconds
while visible and on focus.

The owner reproduced a further silent Next failure in their own browser. A
read-only runtime check found the server already on successor turn index 6 in
ready state with no pending media command. The frontend now drives media preparation
from committed ready state, including detail updates that beat the REST response.
Stale successful Next callbacks reconcile state without repeating Next, creating
a second pending ticket or regenerating speech. A classic/Beta race regression
covers this order. This final fix still needs the owner's actual-browser acceptance.

Content requirements (language, length, wording, source aliases) are prompt-only.
Speech prompts reserve S IDs for metadata and ask for natural references to RAG.
No backend S-token detection/replacement is added; saved speeches stay unchanged.
Report language follows the frozen debate language: Chinese for zh, English for en.
Report prose is no longer rejected for language, length, Markdown or rhetorical
rules; schema 0025 also removes the old database word-count publication limits.
Only parsing/shape, authorization, source bindings, cost and state integrity remain.

The report is rendered as Markdown, including headings/lists/tables, with raw HTML
execution disabled. Stage uses larger Agent names without A/B/C. Retained replay
uses saved text/audio and hides Open Message; no new barrages are collected.
A lone second-row action spans the controls. Conclude becomes available after
replay completes. One newly authorized real Report for Chinese debate
`c0e48278-c094-4c1f-8b6f-080b48b13767` completed in about 14 seconds;
revision 3 is ready with a Chinese title and 1,007 Chinese characters. No Debate
LLM or TTS regeneration was requested for this playback audit. The earlier partial
browser replay is not a complete replay acceptance result.

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
- **Rebirth** is available on completed lessons in live mode. It preserves the
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
  Remake appears for a failed generation or stale media state (ready/paused after
  15 seconds, playing beyond its expected duration plus a margin). No generic
  failure prose is inserted into the list.

The new POST `/rebirth` and `/remake` endpoints use teacher authentication,
CSRF, idempotency and current-revision/control checks. Only Destroy intentionally
ignores old version values. Frozen OpenAPI, generated client and route fixtures
were updated together. Audit records distinguish fresh generation authorization
from media-only recovery; scope budgets preserve earlier allocated costs.

## Latest consolidated verification

- 131 focused backend checks passed: current lifecycle/cleanup, four-round
  generation, prompt-only prose, bilingual Reports, migration, recovery and
  related API behavior. This includes Rebirth preserving six saved Preview turns
  and successfully starting again, Destroy removing a running debate despite
  stale versions, and Remake preserving the paid operation while replacing only
  the failed turn. Exact repeated reset requests do not generate twice.
- All 276 frontend tests passed. Typecheck passed. Backend Ruff and mypy passed
  (188 modules), and 320 Python files passed format checks. Contract generation,
  route comparison and production image builds are part of this delivery.
- An earlier full backend run in this audit had 1,271 passes and 43 failures.
  The subsequent focused pass corrects the report-length/schema-head expectations
  and verifies the new lifecycle work; the entire backend suite was not rerun
  after those changes. Remaining old protocol/recovery fixtures are not declared
  green. No full-suite or universal classroom-success claim is made.
- The one real Chinese Report run above succeeded. The owner specifically reserved
  final browser/audio/3D/classroom acceptance for manual audit. No further paid
  classroom or browser test was performed after that instruction.

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

## Prior evidence and remaining work

The previous protocol baseline recorded 1,244 backend and 253 frontend checks
before later UI patches. One real two-Agent/two-round lesson completed with four
query, four LLM and one Report operations, all first attempt; a later real Report
also completed. That evidence does not validate this new four-round protocol.
Formal RAG experiments stopped at 31/72 and 21/72 on acceptance-unknown and were
not resent. Full RAG quality acceptance remains incomplete. Ledgers and private
artifacts/backups stay outside Git.

[NEXT_WAVE_PLAN.md](contracts/NEXT_WAVE_PLAN.md) remains history; this plan
supersedes conflicting old barriers, retrieval/round and length rules. The module
workbook uses DDL 9.10 and acceptance owner 徐伯闻. 古月 owns 3D/voice/TTS, Kaikai
owns accounts/student UI, 徐伯闻 owns remaining modules.

Production concurrency, classroom-scale load, public deployment, monitoring,
backup/restore, real speech and data/licensing governance remain outside this
local Demo scope. [ARCHITECTURE.md](ARCHITECTURE.md), [contracts](../contracts/)
and [ADRs](adr/) retain stable design references.
