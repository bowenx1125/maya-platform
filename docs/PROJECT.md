# Maya Platform

Maya combines Agent Markdown, RAG, classroom debate and reports. Progress authority;
[AGENTS.md](../AGENTS.md) defines work. Latest user decisions prevail.

## Approved four-round teaching flow — September 8, 2026

New debates: exactly four rounds, two to five Agents, no round selector;
four_round_v1/segments_v2 snapshots. Historical playback/recovery compatibility
was waived; existing records are never silently regenerated/deleted.

1. Opening: independent claim/relevance from high-priority own-KB evidence;
   culture is perspective, not proof; acknowledge missing evidence.
2. Discussion: low-priority new own-KB retrieval; build on the opening, address
   specific claims and ask the cyclically assigned stable Agent ID a question.
   No moderator or question-planning model.
3. Response: medium-priority RAG on actual round-two questions/challenges;
   explain retained/qualified/revised positions and save concise session memory
   in the same output.
4. Conclusion: fresh high-priority own-KB retrieval plus public speeches/memory;
   explain agreement, criticism and learning from another Agent. Freeze earlier
   barrages once; answer one eligible message per Agent if available. Do not
   invent replies; disagreement may remain.

Preview saves exact text/Mock audio for rounds 1–3; round 4 is live. Opening is
independent; later turns see all successful predecessors including the same round,
with complete previous-round barriers. Speaking order rotates, identities/question
targets stay stable. Scheduling, SQL Next, input hashes and recovery share the
same prefix; reuse accepted results/stages without charging again.

| Round      | Chinese upper guidance | English upper guidance |
| ---------- | ---------------------- | ---------------------- |
| Opening    | 500 characters         | 320 words              |
| Discussion | 450 characters         | 280 words              |
| Response   | 550 characters         | 350 words              |
| Conclusion | 650 characters         | 420 words              |

Length guidance is System-Prompt-only, with no minimum. Count Chinese nonspace
characters/punctuation and English alphanumeric words with internal apostrophes/
hyphens, using segment text only. Backend requires readable nonempty paragraphs;
never reject/repair/truncate/pad by length. Bad auxiliary metadata is dropped or
ungraded, not speech-rejecting; valid bindings/source text remain exact. Unreadable
JSON/text gets at most one authorized repair with frozen input/feedback; one-call
authorization cannot gain another; unknown acceptance is not silently resent.

Question routing is separate from barrage reply_to. Round-three memory contains
position/change/reason/influence/unresolved_question, never speech/TTS, Agent.md,
published versions or knowledge; round four/Report receive it as separate
session_discussion_memory. Agents see only their own knowledge/Persona and others'
public speeches, not others' private receipts/Persona. Migration 0024 removes only
the obsolete speaker/snapshot FK, retaining ownership/chunk/snapshot/uniqueness.
Direct +5/contextual +2/no_match +0 measure evidence support, not factual accuracy.
[Actual prompts](contracts/FOUR_ROUND_PROMPTS.md) and
[synthetic I/O](contracts/four-round-example.json) support manual content review:
answers, new points, evidence and reasoned disagreement; no similarity/keyword gates.

## Verification boundary

Operational browser acceptance is recorded below; complete RAG/content quality
still needs the owner's review. Main delivery and Docker updates are authorized;
no usage reset is authorized.

## Established classroom behavior

Next interrupts audio and recovers saved media; lists refresh while visible/on
focus. Language, length and source aliases are Prompt-only; S IDs stay metadata.
Reports follow debate language and render Markdown without raw HTML or prose
length/rhetorical rejection (migration 0025). Stage names omit A/B/C. Replay
uses saved media, hides Open Message and collects no new barrages. Fixed-size
right-edge Immerse controls and a separate Transcript replace the bottom panel.

## Classroom actions

- **Devocalize** removes audio, preserving speech/sources.
- **Delete** accepts every state/current transactional revision using only ID;
  removes the row after commit despite pending cleanup/other active classrooms.
  Materialize missing legacy playback; fence deletion before worker cancellation,
  without waiting for suppliers. Preserve teacher/course/shared-file/path guards.
  Sent requests cannot be retracted; late work cannot recreate the graph.
- **Rebirth** preserves completed lessons' first three rounds exactly (text,
  evidence, memory/audio), unpublishes them and removes final/classroom/report
  data. Return a Preview-ready draft with closed messages, new final identities
  and one final-round allowance within attempt caps. No Provider/Preview rerun.
- **Remake** stays a guarded API; no Refresh/bulk retry/recovery UI or read-triggered
  generation. Preserve charges, saved results and unknown-acceptance stop. End
  means stop; auth/CSRF/identity/control guards remain.

## Playback and retrieval

Visible Preview polls; ordered WebSocket events apply speech/speaker atomically
and ignore stale media callbacks. Final barrages freeze transactionally. Each
round queries its own KB at high/low/medium/high Prompt priority; up to three
queries share a batch within the initial 4N allowance. Remake uses fresh-turn
allowance, keeps charges/accepted caches, rebinds dependencies and rejoins
scheduling; failed responses are not cache successes and deleted diagnostics
stay deleted. Conclude creates Report revision 1; Regenerate/Review remain.
Rebirth resets final dependencies under one writer transaction, restoring
immutability triggers on success/rollback. Invalid auxiliary bindings stay
ungraded. Devocalize/Revocalize preserve consent, cost, identity and state guards;
these checks are not real-service acceptance.

## Runtime and established UI

Next.js/FastAPI/SQLite/local files/Caddy share port 8080. Inspect active SQLite
inside its container; preserve private configuration, knowledge and runtime data.
The previously accepted stack used Mock TTS/Voice and separately authorized real
DashScope LLM/Embedding/Report; embedding dimension is 1024. Current checked-in
speech capability is described below, without claiming new runtime acceptance.

Devocalize/Delete sit beside Rebirth; failed actions preserve rows. Immerse topic
is fixed bottom-left; standalone fixed-size controls sit far right. Transcript
shows Public Debate/status/progress/Check RAG; Escape closes and restores focus.
Bubbles persist until Next. Interact/Hide retains the QR session. Conclude shows
score-sorted Evaluation without name prefixes and Report Version/History;
Audio Ready means retained audio.

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

Defaults: backend/app/modules/debates/default_rules/zh.md and en.md, teacher-only
read endpoint, no Provider calls. After Agents Order: language, pencil Edit,
checkmark Save. Render full Markdown; Edit raw text. Checkmark saves that language,
Back discards, Done creates and is hidden during Edit. Warm-paper Topic/Background.

Create freezes both files/eight System messages in rule_snapshot_json. Send intact
Markdown with only language/current-round/JSON/source/routing execution rules; no
parser or old Prompt. Reject draft rule replacement; defaults cannot change saved
snapshots. Migration 0027 preserves custom rules/speeches/non-four-round records.
Hashes/recovery/repair retain frozen messages, appending repair feedback.
Reject executable HTML/unsafe links; model compliance is manual.

“RAG证实”/“RAG提示”/“我感觉” are editable direct/contextual/no_match guidance. Answer
from evidence first; otherwise use Agent.md without inventing facts or widening
source claims. Transcript has current/total and nonvisual connection status.
Back/reentry recovers network; never auto-retry/advance saved generation. Reports
keep complete evidence within budgets; bibliographic prose is not a secret leak.
Creation defaults Chinese with independent CN/EN drafts/omitted language,
linked-height inputs, newest-first Agents Order and mobile stacking. Beta redirects
to Debates. Profile/RAG downloads and classroom actions remain. Replay/Conclude
require completion; Live start/handoff clears replay cursors.

## Obsolete protocol removal — September 10, 2026

Old RuleSets and their branches are removed. Only
`ordered_multi_expert_mutual_learning_v1` is accepted; new Debates use four-round
`segments_v2`. Migration files and stored-result readers remain for retained data.

## Account integration — September 12, 2026

Single-course Demo: open registration, five-character passwords, separate unknown
user/wrong password errors; multi-course deferred. Catalog accounts stay managed.
Migration 0029 enforces canonical username/group uniqueness and stops on collisions
without altering logins. Teacher access survives sync; Enter grants CRUD as the
teacher, Homeward returns to Accounts. CSRF/publication/course/consent/cost guards
and TTS/Voice configuration remain.

## Classroom display — September 18, 2026

PR 29 merged at ed22231: two to five licensed scholars surround the courtyard
table; jaw/bubble/Transcript follow audio, with readable text on media failure.
/local-roundtable accepts local WAVs. Cloned voices are uploader-owned. Gaussian
packs remain optional ADR-007 experiments. Two fully skipped obsolete tests and
completed plans were removed; current assertions/manual checklist remain.

## Operation panel and browser acceptance — September 22, 2026

With owner approval, one three-Agent lesson completed Start/Next/Interact/Hide/
Check RAG, four rounds/12 turns, Conclude and Report v1; Replay/reload preserved it.
Nine Preview speeches were reused. Seven confirmed charged calls succeeded:
3 Embedding queries, 3 final LLM turns, 1 Report; reopening/replay added none.
TTS/Voice were Mock; no student messages/votes. Retained turns 5/6 and 8/9 have
identical text ignoring whitespace, and the list says “2 Rounds”; neither was
rewritten. Performance/RAG quality/real speech/load remain open.
[ADR-008](adr/ADR-008-agent-chat-live-provider-controls.md) defines reuse boundaries.
This dated acceptance does not cover later changes.

## Working — workspace, private Chats and Live

0030 adds private history, encrypted preferences and 20-second Live leases.
Chat freezes version/snapshot with identity/revision fences and cost/unknown-state
tracking. Live shares public history/audio without spectator generation/control.
Components switches LLM/Embedding/Report; TTS/Voice deferred. Ready Chat voices
support TTS (120s timeout, generic 30s). Three avatars persist per user/Agent;
Elder Scholar for Socrates/Laozi, Noble for Plato. Startup changes only old factory
configs; no new speech/browser acceptance.

Minimalist display-serif/warm-paper (#fdfaf3) workspace, original Mayaform mark;
no extra wordmark/titles/Refresh. Accounts: username/group/status/accessible Enter.
Encrypted installation-wide API Key entry makes no call/mode change; environment
key wins. Check skips Ready/deferred, confirms calls, stops on failure. New fades
when disabled; Back/Done contextual. Agent New opens next draft; Done saves/publishes
returned revision, Back warns on unsaved work. Libraries use pencil/download/X.
Failed creation retains text/retry identity.

Earlier deployment checked both identities/private history, Components/Accounts,
375px/desktop, Replay/Live, Docker/assets and 104x44 Immerse buttons. 11 assistant
calls: 4 Chat Embedding, 4 Chat LLM, 1 LLM Check, 2 Report Checks; repeats added none.
Decimal multiplication fixed a pre-send second-message budget failure. Concurrent
user work raised that dated ledger to 17 (7 Embedding, 10 LLM/checks), not a current count.

## Working — free Markdown and Agent deletion

Agent.md goes intact to Chat/Debate (12,000 characters); optional identity/
characteristics/four-question template, no chapter/field/semantic gates or executed
ToT/ReAct. Persona/Compile/Confirm/Test Chat UI removed; old codecs/routes serve
saved data only. RAG caps 100,000 characters per file with access/non-execution.
0031 tombstones remove shared Agent access, preserving immutable assets/files and
read-only chats; Debate references/publication block deletion under the writer lock.
Chats restores history, New starts fresh; Send clears draft/shows pending text,
network errors restore identity/text. No cross-chat memory.

Dated checks: backend 1391/21 skipped, frontend 373/1 skipped plus 23 focused;
static/contracts/migrations passed. After backup: Docker/0031/readiness/integrity
passed. Chats 1440px/375px had no overflow and a 44x44 arrow. No new paid calls,
live deletion or classroom generation; provider quality unverified.

## Working — Chats without product I/O caps (observed 2026-09-23)

SiyaH hit chat_context_full (32,000-byte JSON and turn/day ceilings), then
export_data_forbidden when educational “Authorization” was scanned as a secret.
Removed 20-turn/100-per-day/4,000-character/JSON-byte stops and max_tokens: 1500;
retain full unsummarized history. Skip prose scanning, retaining auth/CSRF/
ownership/unknown-acceptance/header guards and deduplication. Finite per-call
reservations use unbounded scopes; SendChat drops maxLength: 4000 and 429.
Focused tests including Authorization prose passed; no charged post-rebuild SiyaH
or RAG quality acceptance was observed. Supplier capacity still applies.

## Working — quiet workspace UI (observed in code 2026-09-24)

Mayaform: Welcome then Members. Knowledge: two-column Files · N tiles; X hides or
removes library rows without rewriting snapshots. Agents: six-column warm-paper
tiles with centered name/group/version; green/brown version bubbles become X on
hover/focus. Debate rows open Preview; only its Preview label is hidden. Top-right icons download
AGENT.md, all Evidence files and Knowledge snapshots. Snapshot rows show filename/
characters, not order N; SNAPSHOT/CONTENT/FILES labels sit above values. Chats keeps
the local rounded floating composer and separate Send row. Ruleset checkmark saves
language; Done does not save an unsaved Edit. Contextual sidebar controls remain.

## Snapshot publication history — September 23, 2026

Snapshot ceilings were removed; batching remains 10 items/30,000 estimated tokens.
罗燕玲 staged one batch before HTTP 500; a later build accepted five then timed
out at 30s, leaving two not_sent. The next click sent nothing at attempt 2/2.
Continuation now permits unstaged unknown batches up to three attempts, charging
each resend; timeout is 120s. Saving the draft created a new build: nine batches
succeeded at 07:28 UTC; eaa37c26-c30a-4332-826c-2533820dcc13 published with
text-embedding-v4/1024 dimensions/12 chunks. The old timed-out build was not resent.
SiyaH's two stages survived a local commit failure; at 07:39 UTC draft
cc072330-3885-4a39-ba28-adb0136fd976 published from them with the same model/dimension,
seven chunks and no new call.

Debate identity/prompts use AGENT.md, not compiled Persona. Removed prompt/output
and query/LLM scope stops, embedding input-size rejects and the 256 KiB recovery
ceiling. Failed drafts cannot steal another Debate's warmer; proven-not-sent
queries get one retry. Accepted stages remain reusable.

## Next atomic task

LLM_MODEL selects Chat/Debate/Report, default qwen3.8-max-2026-09-02 without supplier
price lookup. Embedding/speech models stay pinned; no charged acceptance on this
snapshot is recorded. Next: independent model/effort UI with provider capabilities
and server-side keys, audited assistant-ui/AI Elements/Agno reuse (ADR-008), no
cloud history. Face-to-face Bailian Beijing voice follows manual text/UI audit;
Components still defers TTS/Voice. RAG quality, real speech, load and deployment
remain unverified.

## Checked-in streaming and speech capability

POST /api/v1/conversations/{conversation_id}/messages:stream and the existing JSON
messages route share the assistant-text commit, once before text_done. Release the
conversation lock then; hold no DB session across LLM/TTS. TTS runs once afterward;
failure preserves text, and tts_ready carries audio_url, not bytes. lang is zh-CN/en.
Student voice IDs stay encrypted; drafts bind voice_profile_id. DashScope speech
can accompany real core slices using DASHSCOPE_API_KEY; defaults remain mock.
Only Qwen WAV placeholder RIFF/data sizes near 2**31 are rewritten before technical
validation. TTS language_type is Chinese/English; enrollment sends zh/en from
zh-CN/en samples. The earlier Debate “language English” contract remains unchanged.
Rotate the environment key and restart; voice rows hold no key.
BASELINE_DEFAULT_VOICES maps immutable characters to ready profiles; omitted names
use FALLBACK_VOICE_PROFILE_ID. No charged call established this capability.

## Workspace UI/import — September 27, 2026

Bilingual cursor/focus/touch help covers workspace and Debate actions; unit tests
pass. PDF/Word import is deferred: Markdown-only uploads remain, and bounded
extraction/OCR is not implemented.

## Local/GitHub integration — September 27, 2026

Merged local 7236a97/composer checkpoint 4fd1968 with GitHub main a2b397d
and entaiaki dfac2b4. Other siblings/reverts excluded; remote features retained. Fixed the deleteConversation route fixture and absent ledger transitions;
removed stale budget assertions and passed baseline voice mapping into Compose. README/AGENTS refreshed; authority compacted.

## Unbounded provider accounting — September 27, 2026

Owner removed backend request-count, token and CNY budget ceilings across Chat,
Debate, Report and embedding. Reservations/actual usage remain accounting records;
legacy max_* values are estimates, never send/acceptance gates. LLM/Report requests
omit fixed output-token caps; valid usage/cost above estimates is retained.
Migration 0033_budget_accounting_unbounded removes allocation/call-ordinal ceilings
without deleting history. Report continuation drops its OpenAPI call_no maximum;
frozen digest, generated types and fixture are updated together. Permissions,
exact disclosure, deduplication, retry authorization, uncertain-acceptance recovery
and supplier batch shapes remain. This change authorizes no paid acceptance run.

Validation: pnpm check and generated-source boundary probe passed.
Backend 1412 passed/21 skipped; frontend 391 passed/1 skipped.
Migration rehearsal preserved all rows across 59 tables with integrity/FK checks;
new tests cover concurrent accounting and usage above legacy estimates.
Docker/source checks, homepage/readiness, schema 0033 and DB integrity passed
after backup; real-provider acceptance remains unperformed.

Preview correction: 391 frontend tests passed/1 skipped, types/lint/format passed.
Frontend rebuilt; current Preview shows nine turn cards and Immerse without the
Preview label. One older record returns a state error; historical data unchanged.
