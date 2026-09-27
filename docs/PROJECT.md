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

Browser evidence below is dated; complete RAG/content quality needs owner review.
Main delivery/Docker updates are authorized; usage reset is not.

## Established classroom behavior

Next interrupts/reuses audio; visible/focused lists refresh. Reports use debate-language
Markdown without raw HTML/prose rejection (0025); stage names omit A/B/C. Replay reuses
media without new barrages/Open Message. Immerse has right-edge controls and Transcript.

## Classroom actions

- **Devocalize** removes audio, preserving speech/sources.
- **Delete** accepts every state/current revision using ID; removes after commit
  despite pending cleanup/other classrooms. Materialize legacy playback; fence late
  workers before cancellation without waiting for suppliers. Preserve ownership/file/
  path guards. Sent calls cannot be retracted; late work cannot recreate deleted data.
- **Rebirth** preserves completed rounds 1–3 exactly, unpublishes, removes final/
  classroom/report data, and returns Preview-ready draft with closed messages and
  new final identities/allowance. No Provider/Preview rerun.
- **Remake** remains a guarded API; no bulk retry/recovery UI or read-triggered
  generation. Preserve charges/results/unknown-acceptance stop. End means stop;
  auth/CSRF/identity/control guards remain.

## Playback and retrieval

Visible Preview polls; ordered WebSocket events apply speech/speaker atomically,
ignoring stale media callbacks. Barrages freeze transactionally. Each round queries
its own KB at high/low/medium/high Prompt priority; up to three queries share a batch.
Remake preserves charges/caches, rebinds dependencies and rejoins scheduling;
failures never become cache successes. Conclude creates Report v1; Regenerate/Review
remain. Rebirth restores immutability triggers on commit/rollback. Deleted
diagnostics stay deleted; audio actions retain consent/identity/state guards.
These are engineering behavior, not real-service acceptance.

## Runtime and established UI

Next.js/FastAPI/SQLite/files/Caddy share 8080. Inspect SQLite inside its active
container; preserve config/knowledge/runtime data. Real core calls need authorization;
embedding dimension is 1024. Transcript Escape restores focus; bubbles last until Next,
Interact/Hide retains QR. Conclude shows Evaluation/Report History. Audio Ready means
retained audio. Failure preserves classroom rows.

## Remaining scope

徐伯闻 owns content acceptance, 古月 3D/voice/TTS, Kaikai accounts/student UI.
RAG quality, classroom load, deployment, monitoring, backup/restore and real speech
remain unverified. Stable design: [Architecture](ARCHITECTURE.md),
[contracts](../contracts/), [ADRs](adr/).

## Topic and Background

Topics accept arbitrary visible scripts/symbols. Topic/optional Background are
separate (0026); titles show Topic only. Outbound NFC/control/whitespace cleanup
preserves meaningful punctuation; Background is unverified scenario data. Draft
edits invalidate Preview plans. Creation uses separate Topic/Background cards,
sidebar Back/Done and Ruleset language selection. Budget ceilings were later removed.

## Frozen Markdown Ruleset and current Report repair

Defaults are backend/app/modules/debates/default_rules/zh.md and en.md; reading
makes no Provider call. Agents Order precedes language/Edit/Save. Display complete
Markdown; edit raw text. Save affects that language; Back discards. Done creates,
is hidden during Edit and never saves an unsaved Ruleset Edit.

Creation freezes both files/eight System messages in rule_snapshot_json. Send intact
Markdown plus language/round/JSON/source/routing execution rules, without the old
parser/Prompt. Draft rules cannot replace frozen snapshots. Migration 0027 preserves
custom rules/speeches/non-four-round records; recovery/repair retains messages and
appends frozen feedback. Reject executable HTML/unsafe links; compliance is manual.

“RAG证实”/“RAG提示”/“我感觉” are editable evidence guidance: answer from evidence,
otherwise Agent.md without inventing facts or widening claims. Reports retain full
evidence; bibliographic prose is not a secret leak. Chinese defaults with independent
CN/EN drafts, linked-height inputs and newest-first Agents Order. Beta redirects to
Debates. Back/reentry reconnects without automatic retry/advance. Replay/Conclude
require completion; Live start/handoff clears replay cursors.

## Obsolete protocol removal — September 10, 2026

Old RuleSets and their branches are removed. Only
`ordered_multi_expert_mutual_learning_v1` is accepted; new Debates use four-round
`segments_v2`. Migration files and stored-result readers remain for retained data.

## Account integration — September 12, 2026

Single-course Demo supports open registration, five-character passwords and separate
unknown-user/wrong-password errors; multi-course deferred. Catalog accounts remain
managed. Migration 0029 enforces canonical username/group uniqueness, stopping on
collisions without changing logins. Teacher access survives sync; Enter grants teacher
CRUD, Homeward returns to Accounts. Auth/CSRF/publication/course/consent guards remain.

## Classroom display — September 18, 2026

PR 29 (ed22231): two to five licensed courtyard scholars; jaw/bubble/Transcript
follow audio, preserving readable text on media failure. /local-roundtable accepts
local WAVs. Cloned voices are uploader-owned; Gaussian packs remain optional ADR-007
experiments. Obsolete skipped tests/plans were removed; manual acceptance remains.

## Operation panel and browser acceptance — September 22, 2026

Owner-approved three-Agent lesson completed four rounds/12 turns, classroom controls,
Conclude/Report v1 and Replay/reload, reusing nine Preview speeches. Seven charged
calls succeeded: 3 Embedding, 3 final LLM, 1 Report; reopening/replay added none.
TTS/Voice were Mock; no student messages/votes. Retained turns 5/6 and 8/9 match
ignoring whitespace; list says “2 Rounds”; neither was rewritten. This dated
acceptance excludes later changes, RAG quality, real speech and load.

## Working — workspace, private Chats and Live

0030 provides private history, encrypted preferences and 20-second Live leases.
Chat freezes version/snapshot with identity/revision fences and cost/unknown-state
tracking. Live shares history/audio without spectator generation/control.
Components switches core providers; speech is environment-managed. Ready Chat voices
support TTS (120s timeout; generic 30s). Avatar editing stays in Workspace.

Warm-paper/display-serif retains Mayaform. Encrypted key entry makes no call/mode
change; environment key wins. Check skips Ready/deferred, confirms calls and stops
on failure. Contextual New/Back/Done flow is specified below; failed creation retains
text/retry identity. Libraries use pencil/download/X.

Dated deployment checked identities/private history, Components/Accounts, mobile/
desktop, Replay/Live and Docker/assets. 11 assistant calls: 4 Chat Embedding,
4 Chat LLM, 1 LLM Check, 2 Report Checks; repeats added none. Decimal multiplication
fixed a pre-send second-message budget failure. Concurrent user work raised that
dated ledger to 17 (7 Embedding, 10 LLM/checks), not a current count.

## Working — free Markdown and Agent deletion

Agent.md reaches Chat/Debate intact (12,000 characters), with an optional template
and no chapter/field/semantic gates or executed ToT/ReAct. Persona/Compile/Confirm/
Test Chat UI is removed; old codecs/routes read retained data. RAG permits 100,000
characters/file with access/non-execution guards. 0031 tombstones remove shared Agent
access while retaining immutable assets/read-only chats; Debate references/publication
block deletion under the writer lock. Chats restores history; New starts fresh.
Send clears the composer, errors restore text/request identity. No cross-chat memory.

Dated validation: backend 1391/21 skipped; frontend 373/1 skipped plus 23 focused;
static/contracts/migrations and backed-up Docker/0031/readiness/integrity passed.
No new paid calls, live deletion or generation; provider quality unverified.

## Working — Chats without product I/O caps (observed 2026-09-23)

SiyaH encountered context ceilings and an educational “Authorization” prose false
positive. Removed 20-turn/100-per-day/4,000-character/32,000-byte stops and fixed
max_tokens: 1500; retain complete unsummarized history. Prose scanning is removed;
auth/CSRF/ownership/header/unknown-acceptance guards and deduplication remain.
Reservations use unbounded scopes; SendChat drops maxLength/429. Focused tests
passed; no charged post-rebuild SiyaH or RAG quality acceptance. Supplier capacity
still applies.

## Working — quiet workspace UI (observed in code 2026-09-24)

Mayaform: Welcome then Members. File X removes library access, preserving snapshots;
Agent version becomes X on hover/focus. Debate cards open Preview, hiding only its
title. AGENT.md/Evidence/snapshot downloads remain. Chats retains floating composer
and separate Send row. Current revisions appear below.

## Snapshot publication history — September 23, 2026

Snapshot ceilings were removed; batches remain 10 items/30,000 estimated tokens.
罗燕玲 staged one batch before HTTP 500; a later build accepted five, timed out at
30s and left two not_sent. Next click sent nothing at attempt 2/2. Continuation now
permits three attempts for unstaged unknown batches, charging resends; timeout 120s.
New draft build accepted nine batches at 07:28 UTC: eaa37c26-c30a-4332-826c-2533820dcc13,
text-embedding-v4/1024/12 chunks. Old timeout was not resent. SiyaH's two stages
survived commit failure; cc072330-3885-4a39-ba28-adb0136fd976 published at 07:39 UTC,
same model/dimension, seven chunks, no new call.

Debates use AGENT.md, not compiled Persona. Prompt/output/query/LLM scope stops,
embedding input-size rejection and 256 KiB recovery ceiling were removed. Failed
drafts cannot steal another warmer; proven-not-sent queries get one retry; stages reuse.

## Next atomic task

LLM_MODEL selects Chat/Debate/Report (default qwen3.8-max-2026-09-02) without price
lookup; embedding/speech stay pinned. No charged acceptance establishes this snapshot.
Planned model/effort UI and audited UI/Agno reuse follow
[ADR-008](adr/ADR-008-agent-chat-live-provider-controls.md), with server keys/no cloud history.

## Checked-in streaming and speech capability

Streaming and JSON Chat routes commit assistant text once before text_done, release
the conversation lock and hold no DB session across LLM/TTS. One TTS attempt follows;
failure preserves text; tts_ready returns audio_url. Voice IDs stay encrypted; drafts
bind profiles. DashScope speech shares DASHSCOPE_API_KEY; checked-in defaults are Mock.
Qwen placeholder RIFF/data sizes near 2**31 are normalized before audio validation.
TTS uses Chinese/English; enrollment uses zh/en. Debate's English contract is unchanged.
BASELINE_DEFAULT_VOICES maps characters to ready profiles, falling back to
FALLBACK_VOICE_PROFILE_ID. Key rotation requires restart, not voice-row edits.
No charged call established this capability.

## Workspace UI/import — September 27, 2026

Bilingual help covers workspace/Debate. Uploads remain Markdown-only;
PDF/Word extraction/OCR is deferred.

## Local/GitHub integration — September 27, 2026

Merged local 7236a97/composer checkpoint 4fd1968, GitHub main a2b397d and entaiaki
dfac2b4; sibling/revert branches excluded. Fixed deleteConversation fixture/ledger
transitions, stale budget assertions and Compose voice mapping. README/AGENTS updated.

## Unbounded provider accounting — September 27, 2026

Owner removed request/token/CNY ceilings for Chat/Debate/Report/Embedding. Reservations,
actual usage and legacy max_* fields are accounting only; LLM/Report omit output caps.
0033_budget_accounting_unbounded removes allocation/call-ordinal ceilings, retaining
history. Report call_no maximum was removed with contract/types/fixture synchronization.
Permissions/disclosure/deduplication/retry authorization/unknown recovery and supplier
batch shapes remain; no paid acceptance authorized by this change.

pnpm check/boundary probe passed: backend 1412/21 skipped, frontend 391/1 skipped.
Migration preserved 59 tables with integrity/FK checks; tests cover concurrent
accounting/usage above estimates. Backed-up Docker, homepage/readiness, 0033 and DB
integrity passed; no real-provider acceptance. Preview correction passed 391 frontend
tests/1 skipped and static checks; rebuilt Preview showed nine cards/Immerse without
title. An older record still has a state error; data retained.

## Workspace polish and speech configuration — September 27, 2026

Code/configuration changes were rebuilt and deployed; backend/frontend are healthy.
No real Provider request was made in this change.

Initial Draft and Published details use sidebar New to open an existing draft or
create the next one; inline Draft Edit/Delete removed. Done still saves/publishes;
Back still confirms dirty edits, without an Unsaved local changes label. Chats
removes its 3D panel/picker; Workspace keeps AvatarEditor. History shows dates
normally, replacing them with Delete only on hover/keyboard focus using mutually
exclusive visibility; mouse-click focus cannot pin Delete. Touch hides the date.
Knowledge hides Ready only in the UI and puts all three actions at card top-right.
Voices drops Empty decoration/nested cards and displays the existing v1 consent
text fully, without tooltip. Help and Immerse controls use warm-paper styling;
help clears on pointer leave, route/DOM change, scroll, blur and Escape. Mouse
focus cannot pin it; keyboard/touch support remains. Debate links have no underline.

The latest stalled draft made one embedding query, rejected remotely with HTTP
403; its ledger counts one charged request and no LLM call. No local budget/content
rule caused that rejection; precise remote cause is unknown and it was not retried.
Local TTS/Voice selectors are dashscope; adapter construction passed offline. Real
speech displays unchecked, not Ready; no Voice Profiles or default voice exist.
The configured services still need a permitted supplier account and enrolled voice;
no real speech request or voice upload was made in this change.

Full pnpm check and generated-file boundary probe passed: backend 1414 passed/21
skipped; frontend 402 passed/1 skipped. Runtime was backed up before recreation.
Browser checks confirmed no Chats 3D panel, mutually exclusive date/Delete before,
during and after hover, keyboard tooltip/Escape/navigation cleanup, compact
Knowledge actions without Ready, and Voices form with full existing consent text.
Narrow-layout pages had no horizontal overflow. Cloud speech acceptance remains
unverified; configuration/adapter construction is not proof of successful audio.
