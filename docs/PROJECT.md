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

## Established classroom behavior

Next can interrupt audio and recover using saved media. Lists refresh while
visible and on focus. Language, length and source alias wording are Prompt-only;
S IDs remain metadata. Report language follows the debate, renders Markdown
without executing raw HTML, and does not reject prose for rhetorical/length
rules. Schema 0025 removed old report word-count publication limits. Larger Stage
names omit A/B/C. Replay uses saved text/audio, hides Open Message and collects
no new barrages; a lone second-row action fills the row.

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

## Playback and retrieval

Preview polls while visible. Stage consumes ordered WebSocket events, applies
speech/speaker atomically, ignores stale media callbacks and lets Next interrupt
audio. Final freezes barrages transactionally. Each round retrieves from its own
KB with high/low/medium/high Prompt priority; up to three queries share one
Embedding batch, within the existing 4N initial allowance.

## Remake recovery

Settled failed Provider responses are not cached successes. Explicit Remake uses
its fresh-turn allowance, preserves charge records and valid cached results,
rebinds pending dependencies and rejoins Preview scheduling. Unknown acceptance
is not resent. Report offers Regenerate and Review; Conclude creates its first
revision. Deleted diagnostic records are not recreated.

## Recovery and output boundaries

Auxiliary model metadata cannot reject a readable speech. Invalid question,
memory, source, support or barrage bindings are omitted/ungraded, never invented.
Consent, cost, identity, state and readable JSON/text boundaries remain. No body
truncation, padding or automatic wording replacement is performed.

Rebirth preserves Preview/audio, resets final dependencies, and changes frozen
final input inside a writer transaction that restores its immutability trigger.
Rollback restores both data and trigger. Remake respects unknown/in-flight paid
requests and other active classrooms. Healthy completed speech is reused.
Unvoice/Revoice retain their respective action after failures. Agent version
pills sit left of the divider, Group right without hover. Recovery has targeted
checks and in-memory live-schema reproductions, not universal service guarantees.

## Prompt-only repetition correction

Actual Prompts anchor each speaker in its own Persona, opening, RAG and questions.
Later turns contribute evidence, answers or judgment rather than paraphrasing the
previous speaker. Agreement is allowed; no similarity rejection or text rewriting
was added. New model output still requires manual teaching-quality review.

## Other delivered repairs

Destroy recognizes only scoped UUID WAV paths under debate-turn-tts staging,
cleans owned empty directories, and retains traversal/symlink protections. Four
live-schema in-memory copies passed deletion/foreign-key checks; user records
were not deleted for testing. Global Remake queues recoveries without stealing
active Preview ownership. Stage and Debate lists share Ready/Completed badges.

Conclude requests initial=true; a writer transaction reuses an already-started
first report. Regenerate explicitly creates another revision. Report history
retains word count/Review and omits Ready. A separate Embedding ConnectError was
deferred at the owner's request after recreation worked. Earlier targeted
checks do not establish full classroom quality acceptance.

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

Preview and Stage Check RAG count unique evidence sources. Waiting/Finish-blocked
prose, generic 3D error text and audio replacement dialogs are removed; control
and cost guards remain. Older broad Wave2 playback tests retain two unresolved
native-ended/hidden-index assertions; targeted Beta checks are not a full-suite pass.

## Topic and Background — September 8

Creation accepts any script, numbers, punctuation and emoji independently of the
selected output language. Topic still needs visible content. Original Topic and
optional Background are saved separately; migration 0026_debate_background adds
an empty-default column, leaving existing records unchanged. Before model input,
NFC normalization removes invisible control/format/surrogate characters and
collapses whitespace while retaining meaningful symbols and word separators.
Generation, each round's RAG query and Report receive a labeled Topic/Background
context through the frozen topic field. Background is teacher scenario data, not
verified evidence or system instructions. Reports no longer reject this context
at the former 1200-character title limit; Provider token/call budgets remain.
Lists/public classroom titles show only the authored Topic. Draft edits discard
old Preview plans as before; their next frozen inputs include the new background.

Creation uses a yellow Topic textarea, an optional Background below it, English/
Chinese compact switch in Ruleset, and Create Debate Draft beside Back. No extra
Provider call or automatic regeneration of existing records was introduced.

Topic/Background persistence, retrieval, Report and setup checks passed offline.

## Frozen Markdown Ruleset and current Report repair

Default teaching content now lives only in backend/app/modules/debates/default_rules/
zh.md and en.md. The creation form loads both through a teacher-scoped read-only
endpoint. Selected Order is followed by one Debate Ruleset row: compact language
switch, Details, Edit. Details renders only the selected language in a full-width scrollable document;
Edit shows raw text; Save updates that language in this form and returns to Details. Create is disabled while
editing. The old Multi-round Civilization/phase block is removed; Topic and
Background inputs are yellow.

Create freezes both authored Markdown files and eight complete System messages
(four for each language) in rule_snapshot_json. Markdown is sent intact, with no
heading parser or old pedagogical Prompt appended. Only the language/current-round,
JSON/source/routing execution contract is added. Changes to default files or other
debates cannot alter this snapshot. Draft updates preserve frozen rules and reject
attempts to replace them; default-file reads make no Provider calls. Migration
0027_frozen_teaching_markdown freezes defaults for existing four-round rows while
preserving their saved speeches, custom snapshots and non-four-round records.

GenerationContext passes the frozen System text into each turn's server-only
snapshot. Input hashes include it; persisted recovery envelopes retain it, and
repair appends feedback to the same message. UI rendering suppresses executable
HTML and unsafe script links. Provider budgets and authorization remain unchanged;
these engineering checks cannot guarantee model compliance or teaching quality.
Chinese default wording is direct “RAG证实”, contextual “RAG提示”, no_match “我感觉”.
The last includes independent LLM reasoning with assumptions/grounds, not invented
facts. These are editable Prompt instructions only, not output rejection rules.

3D Stage removes the transcript header count and visible connection wording.
A single current/total bubble follows the displayed turn (e.g. 4/12): green when
connected, red otherwise, with accessible nonvisual connection text. Existing
reconnect actions remain available without explanatory notices.

Live Report diagnosis: retained evidence in debate 8d8c9171-723b-4189-84aa-a7ef4ad7548c
contains six chunks of 4127–4408 characters. Each reproduced string_too_long in
ReportSource.excerpt's obsolete 2400-character constraint, before a paid Report
operation. That per-source limit is removed, preserving exact evidence and total
request budgets. Generating/failed revision DTOs also sent removed translated_markdown,
causing a second ValidationError; those stale fields are removed. Unexpected input
validation now logs only field paths/types, never values. The user had already
reset this debate to Preview Ready; original final speeches/report revisions no
longer exist, so no original full Report was replayed or regenerated here.

Validation: 81 focused rules/protocol/recovery/database checks, 63 editor/setup/
Stage frontend checks and 37 Report checks passed. Report fixtures verify six
long evidence chunks reach actual request construction unchanged; live retained
chunks reproduced the original limit. Types, targeted lint/mypy and contract
checks pass. No new paid or full browser classroom acceptance was performed.

## Real ruleset effect check

A controlled Chinese opening comparison used identical synthetic Topic, Persona
and RAG, changing only frozen Markdown: default produced five paragraphs; custom
produced the requested Decision/Evidence/Review structure with numerical allocation
and one-week monitoring. Two valid calls used 3287 tokens. One preceding accepted
call was lost to an experiment recording bug; actual total is three calls, not
two. No classroom records or Provider settings changed. Full outputs and limits:
[Ruleset effect evidence](validation/RULESET_EFFECT_2026-09-08.md).

The custom answer exposed S1 after its teacher rules omitted citation wording.
New execution Prompts now reserve S IDs for metadata; no backend text filter was
added. Existing frozen lessons are unchanged; this addition has offline coverage,
not another paid rerun. One opening comparison is not four-round quality acceptance.
Ruleset styling now uses gold card, white documents/switch, gold selection and
purple actions. Thirteen frozen-rule checks and two editor checks passed.

Creation now defaults to Chinese in both form and API. Ruleset language can change
only while Details is closed; CN/EN text remains independently saved in the form,
with no extra Prompt CN/EN headings. Editing Chinese then selecting English uses
the untouched English prompt. Existing draft language is preserved on updates
that omit output_language. Topic, Background, Published Agents, Selected Order and
Ruleset share one title-divider style and alignment. The duplicate Open explanation
caption is removed; its button remains. 43 frontend and 25 backend targeted checks
passed, including language switching and frozen-language selection; no paid retest.
