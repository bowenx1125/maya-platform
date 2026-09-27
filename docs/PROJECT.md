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

Preview retains rounds1–3 text/audio; round4 is live. Opening is independent; later
turns see all successful predecessors, including same-round turns, after complete
previous-round barriers. Speaking order rotates; identities/question targets stay
fixed. Scheduling/SQL Next/input hashes/recovery share one prefix and reuse accepted
results without charging again.

| Round      | Chinese upper guidance | English upper guidance |
| ---------- | ---------------------- | ---------------------- |
| Opening    | 500 characters         | 320 words              |
| Discussion | 450 characters         | 280 words              |
| Response   | 550 characters         | 350 words              |
| Conclusion | 650 characters         | 420 words              |

Lengths guide only the System Prompt, with no minimum. Count segment text: Chinese
nonspace characters/punctuation; English alphanumeric words with internal apostrophes/
hyphens. Require readable nonempty paragraphs, never reject/repair/truncate/pad by
length. Drop/ungrade bad auxiliary metadata without rejecting speech; valid bindings/
sources stay exact. Unreadable JSON/text gets at most one authorized frozen repair;
one-call authorization gains none, unknown acceptance is never silently resent.

Questions are separate from barrage reply_to. Round3 memory contains position/change/
reason/influence/unresolved_question, never speech/TTS/Agent.md/version/knowledge;
round4/Report receive separate session_discussion_memory. Agents see only their own
KB/Persona and others' public speeches, never private receipts/Persona.0024 removes
only the speaker/snapshot FK, preserving other ownership/uniqueness constraints.
Direct+5/contextual+2/no_match+0 measure evidence support, not accuracy.
[Prompts](contracts/FOUR_ROUND_PROMPTS.md)/[examples](contracts/four-round-example.json)
support manual review of answers/new points/evidence/disagreement, without keyword/
similarity gates.

## Verification boundary

Browser evidence below is dated; complete RAG/content quality needs owner review.
Main delivery/Docker updates are authorized; usage reset is not.

## Established classroom behavior

Next interrupts/reuses audio; visible/focused lists refresh. Reports use the debate
language and Markdown without HTML/prose rejection(0025). Stages omit A/B/C. Replay
reuses media without new barrages/Open Message. Immerse has right-edge controls and
Transcript; Escape restores focus, bubbles last until Next, Interact/Hide retains QR.
Conclude creates Reportv1 with Evaluation/History; Regenerate/Review remain.

- **Devocalize:** remove audio, retain speech/sources.
- **Delete:** every state/current revision, by ID; remove after commit despite pending
  cleanup/other classrooms. Materialize legacy playback; fence late workers before
  cancellation without waiting for suppliers. Keep ownership/file/path guards.
  Sent calls cannot be retracted; late work cannot recreate deleted data.
- **Rebirth:** preserve completed rounds1–3 exactly, unpublish, remove final/classroom/
  report data; return Preview-ready draft with closed messages/new final identities.
  No Provider/Preview rerun; restore immutability triggers on commit/rollback.
- **Remake:** guarded API, no bulk retry/recovery UI/read-triggered generation. Preserve
  charges/results/unknown-acceptance stop. End stops; auth/CSRF/control guards remain.

Visible Preview polls; ordered WebSocket speech/speaker updates ignore stale media
callbacks. Barrages freeze transactionally. Each round queries only its KB with
high/low/medium/high Prompt priority; up to3 queries/batch. Remake rebinds dependencies
and rejoins scheduling, preserving caches; failures never become cache successes,
deleted diagnostics stay deleted. Audio actions retain consent/identity/state guards;
Audio Ready means retained audio. Failed classroom actions retain rows.

Next.js/FastAPI/SQLite/files/Caddy share8080. Inspect active SQLite inside its container;
preserve config/knowledge/runtime data. Real core calls require authorization,
embedding dimension1024. These facts are not real-service acceptance.

## Remaining scope

徐伯闻 owns content acceptance, 古月 3D/voice/TTS, Kaikai accounts/student UI.
RAG quality, classroom load, deployment, monitoring, backup/restore and real speech
remain unverified. Stable design: [Architecture](ARCHITECTURE.md),
[contracts](../contracts/), [ADRs](adr/).

## Topic and Background

Topic/optional Background are separate(0026); titles show Topic only. Accept visible
scripts/symbols; NFC/control/whitespace cleanup preserves punctuation. Background is
unverified scenario data. Draft edits invalidate Preview. Creation uses separate
cards, sidebar Back/Done and Ruleset language. Budget ceilings were later removed.

## Frozen Markdown Ruleset and current Report repair

Defaults: backend/app/modules/debates/default_rules/zh.md and en.md; reads make no
Provider call. Agents Order precedes language/Edit/Save. Display full Markdown;
edit raw text, Save that language, Back discards. Done creates, hides during Edit
and never saves an unsaved Ruleset Edit.

Creation freezes both files/eight System messages in rule_snapshot_json. Send intact
Markdown plus language/round/JSON/source/routing rules, without old parser/Prompt.
Drafts cannot replace frozen rules. Migration0027 preserves old custom rules/speeches;
recovery/repair retains messages and appends frozen feedback. HTML/unsafe links are
rejected; model compliance remains manual.

“RAG证实”/“RAG提示”/“我感觉” guide evidence use, else Agent.md; never invent/widen
claims. Reports keep full evidence; bibliography is not secret leakage. Creation:
Chinese default, separate CN/EN drafts, linked inputs/newest-first Agents. Beta→Debates.
Reentry reconnects without retry/advance; Replay/Conclude require completion;
Live clears replay cursors.

Only `ordered_multi_expert_mutual_learning_v1` remains; new Debates use four-round
`segments_v2`. Old protocols were removed September10; migrations/readers retain data.

## Account integration — September 12, 2026

Single-course Demo: open registration/five-character passwords/separate unknown-user
and wrong-password errors; multi-course deferred, catalog managed. Migration0029
stops canonical username/group collisions without changing logins. Teacher access
survives sync; Enter grants teacher CRUD, Homeward returns to Accounts. Auth/CSRF/
publication/course/consent guards remain.

## Classroom display — September 18, 2026

PR29(ed22231):2–5 licensed courtyard scholars; jaw/bubble/Transcript follows audio,
with text on media failure. /local-roundtable accepts WAVs. Voice clones stay
uploader-owned; Gaussian packs are optional ADR-007 experiments.

## Operation panel and browser acceptance — September 22, 2026

Owner-approved three-Agent lesson completed four rounds/12 turns, classroom controls,
Conclude/Report v1 and Replay/reload, reusing nine Preview speeches. Seven charged
calls succeeded: 3 Embedding, 3 final LLM, 1 Report; reopening/replay added none.
TTS/Voice were Mock; no student messages/votes. Retained turns 5/6 and 8/9 match
ignoring whitespace; list says “2 Rounds”; neither was rewritten. This dated
acceptance excludes later changes, RAG quality, real speech and load.

## Working — workspace, private Chats and Live

0030 adds private history/encrypted preferences/20s Live leases. Chat freezes version/
snapshot with identity/revision/cost/unknown-state tracking. Live shares history/audio
without spectator generation/control. Components switches core providers; speech is
environment-managed(TTS timeout120s, generic30s). Avatar editing stays in Workspace.
Warm-paper/display-serif retains Mayaform. Key entry makes no call/mode change;
environment key wins. Check skips Ready/deferred, confirms calls and stops on failure.
Failed creation retains text/retry identity; libraries use pencil/download/X.

Dated deployment checked workspace/Live/responsive behavior and Docker.11 assistant
calls:4 Chat Embedding,4 Chat LLM,1 LLM Check,2 Report Checks; repeats added none.
Decimal arithmetic fixed a pre-send budget failure. Concurrent user work raised that
dated ledger to17(7 Embedding,10 LLM/checks), not a current count.

Agent.md reaches Chat/Debate intact(12,000 characters); template optional, no chapter/
field/semantic gates or executed ToT/ReAct. Persona/Compile/Confirm/Test Chat UI is
removed; old codecs/routes read retained data. RAG permits100,000 characters/file,
retaining access/non-execution guards.0031 tombstones remove shared access but retain
assets/read-only chats; Debate references/publication block deletion under writer lock.
Chats restores history; New starts fresh. Send clears the composer; errors restore
text/request identity. No cross-chat memory. Dated deterministic/Docker0031 checks
passed without paid calls/live deletion/generation; quality remained unverified.

September23: SiyaH context ceilings and an educational “Authorization” false positive
led to removing20-turn/100-per-day/4,000-character/32,000-byte stops, fixed max_tokens:1500
and prose scanning. Retain full unsummarized history, auth/CSRF/ownership/header/
unknown-acceptance/deduplication guards. Reservations use unbounded scopes; SendChat
has no maxLength/429. Focused tests passed; no paid post-rebuild SiyaH/RAG acceptance.
Supplier capacity still applies.

## Working — quiet workspace UI (observed in code 2026-09-24)

Mayaform: Welcome then Members. File X preserves snapshots; Agent version becomes X
on hover/focus. Debate opens Preview, hiding only its title. AGENT.md/Evidence/snapshot
downloads and Chats floating composer/separate Send remain.

## Snapshot publication history — September 23, 2026

Snapshot ceilings were removed; batches remain 10 items/30,000 estimated tokens.
罗燕玲 staged one batch before HTTP 500; a later build accepted five, timed out at
30s and left two not_sent. Next click sent nothing at attempt 2/2. Continuation now
permits three attempts for unstaged unknown batches, charging resends; timeout 120s.
New draft accepted nine batches at07:28UTC: text-embedding-v4/1024/12 chunks; old
timeout was not resent. SiyaH's two retained stages published at07:39UTC after commit
failure: same model/dimension, seven chunks, no new call.

Debates use AGENT.md, not compiled Persona. Prompt/output/query/LLM scope stops,
embedding input-size rejection and 256 KiB recovery ceiling were removed. Failed
drafts cannot steal another warmer; proven-not-sent queries get one retry; stages reuse.

## Next atomic task

LLM_MODEL selects Chat/Debate/Report(default qwen3.8-max-2026-09-02), without price
lookup; embedding/speech stay pinned. Model/effort UI plans:
[ADR-008](adr/ADR-008-agent-chat-live-provider-controls.md), server keys/no cloud history.
No charged acceptance establishes this model snapshot.

## Checked-in streaming and speech capability

Streaming/JSON Chat commits text once before text_done, releases its lock, and holds
no DB session across LLM/TTS. One TTS attempt follows; failure retains text,
tts_ready returns audio_url. Encrypted voice IDs bind drafts. DashScope speech shares
DASHSCOPE_API_KEY; checked-in defaults Mock. Normalize Qwen RIFF/data placeholders
near2**31 before validation. TTS uses Chinese/English, enrollment zh/en; Debate's
English contract is unchanged. BASELINE_DEFAULT_VOICES maps characters to ready
profiles, else FALLBACK_VOICE_PROFILE_ID. Key rotation needs restart, not row edits.
Original integration lacked charged acceptance; later technical evidence is below.

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

pnpm check/boundary and backed-up Docker/0033/readiness/integrity passed, without
real-provider acceptance. Migration preserved59 tables; tests cover concurrency/
usage above estimates. Preview correction passed frontend/static checks and showed
nine cards/Immerse without title. An older record retained its state error/data.

## Workspace polish and speech configuration — September 27, 2026

Draft/Published details use sidebar New to open/create a draft, without inline
Edit/Delete. Done saves/publishes; Back protects dirty edits without an Unsaved
label. Chats has no 3D panel; Workspace retains AvatarEditor. History date/Delete
are mutually exclusive on hover/keyboard focus; mouse focus cannot pin Delete,
touch shows Delete. Knowledge hides Ready and puts actions top-right. Voices reuses
Knowledge cards/count/tiles with preview/confirm/delete icons; New replaces the list,
Back restores it. No Empty decoration; full existing v1 consent stays visible.
Warm-paper Help/Immerse clears tooltips on leave, route/DOM change, scroll, blur and
Escape. Debate links have no underline.

Chats has no 820px height ceiling: desktop insets48px/24px; mobile minimum
max(600px,75dvh). Browser verified taller desktop/mobile layouts without overflow.
Voice recording guidance is10–15s passage/16-bit WAV/MP3/M4A/max10MB; server still
accepts10–20s/10MiB. This wording does not change the upload contract.

The inspected stalled Debate made one charged Embedding query (HTTP403), no LLM.
No local budget/content rule caused it; remote cause unknown, no retry. Real speech
selectors constructed offline; settings remain unchecked, not Ready. No profiles/
fallback existed then; later enrollment is below. UI work made no Provider call.

Dated full/static/contracts/migrations/boundary and backed-up Docker checks passed;
browser checks covered Chats/tooltips/Knowledge/Voices responsive forms. Populated
voice actions were Mock-tested, not enrolled. Four lint warnings remained.

## Voice filenames, editing and optional Debate audio — September 27, 2026

Multipart filenames use UTF-8/legacy Latin-1. A backed-up filename repair preserved
audio/state/mapping/request hashes. Click filenames for owner-scoped metadata edits;
Voice IDs stay hidden.

User enrollment succeeded once (request1/charged1). Preview download failed
because container DNS returned proxy Fake-IP; the public-address guard correctly
rejected it. A backed-up backend-only DNS override now resolves public addresses;
SSRF validation is unchanged. One authorized service-level diagnostic made one
TTS POST/HTTP200 without retry, storing8.72s/418604-byte PCM16/24kHz mono audio.
It used the existing active owner/session context, not browser authentication.
Profile remains preview_ready for user confirmation. Earlier failed preview charges
cannot be reconstructed: previews have no provider-operation ledger.

Debate uses custom/system voice or explicit text-only playback: no fake media,
automatic Next/repeated generation. Revision-CAS draft save/upload syncs name H1
with Agent metadata, preserving old versions/Debate names; templates start with H1,
old identity headings never rename. No Sample language selector: enrollment default,
English preview, Ruleset-language Debate. Delete/publish race tests check tombstones/
hidden access while preserving draft/RAG/charged records.
pnpm check/boundary passed: backend1484/21 skipped, frontend411/1 skipped;
backed-up Docker/readiness, Voices layout and recreated-container DNS guard passed.

## Agent names and next-version voices — September 27, 2026

Undeleted names are Workspace-unique by
NFKC/strip/casefold on create/Markdown first-line rename;409 agent_name_conflict.
Next drafts can use the owner's ready voice or null(platform default); old versions
stay unchanged.

With user authorization and backup, the normal delete service soft-deleted the
unpublished duplicate Bowen, preserving the published one; no Provider call occurred.
Final combined verification follows below.

## Interaction and long-speech recovery — September 27, 2026

Interaction uses warm-paper mobile layout, 16px inputs/48px controls and accessible
feedback. Isolated375×812/812×375 checks verified overflow-free layout,18px radios
and failed-input preservation/retry. No test messages entered a real classroom.
Retry turn is now a refresh icon with accessible label.

SQL/Mock integration covers HTTP submission, persisted messages/WS events, Final
freeze, model input, stored reply_to and public output. Transcript reply_text quotes
only the referenced frozen anonymous message, never nickname or rewritten speech.
Conclusion uses the existing 300-character input/12-candidate pool. This proves
plumbing, not real-model quality or immediate replies to every message.

Speaker/AGENT.md binding was correct. Attribution guidance now lives in editable
zh/en Rulesets, not Execution contract; removing it never triggers hidden
reinsertion. Existing frozen prompts/speeches stay exact. Gates: backend1500/21 skipped (known race rerun), frontend420/1 skipped; Docker and
both Ruleset views verified. No new model calls or semantic-quality claim.

The next stalled Debate had accepted text but TTS reused the preview1–60s check.
A single authorized TTS POST returned HTTP200 and produced113.12s/5,429,804bytes,
proving the old duration rejection. After backup, HTTP-disabled single-turn promotion reused the saved bytes/text,
with no new Embedding/LLM or adjacent enqueue. Earlier failed-TTS charges remain
unknown. Speech validation now retains format/nonempty/quality checks
without the preview duration ceiling;20MiB download and SSRF safeguards remain.
Typed TTS failure jobs await explicit Retry instead of automatic reclamation.
Docker was switched to this code before continued Preview generation.

Checks: backend1498/21 skipped (restart assertion and known SQLite race passed
focused reruns), frontend420/1 skipped; remaining gates/boundary passed. Docker
ready; live duplicate rejection and repaired turn verified.
