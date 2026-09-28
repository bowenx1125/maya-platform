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

Next interrupts/reuses audio; visible/focused lists refresh. Reports preserve Debate
language/Markdown without HTML/prose rejection(0025); stages omit A/B/C. Replay reuses
media without new barrages/Open Message. Immerse keeps Transcript, right-edge controls,
focus/QR behavior. Conclude creates Reportv1 Evaluation/History; Regenerate/Review remain.

- **Devocalize:** remove audio, retain speech/sources.
- **Delete:** current revision by ID; remove after commit. Materialize legacy playback;
  fence workers without awaiting suppliers. Keep owner/file/path guards; sent calls cannot
  be retracted or recreate data.
- **Rebirth:** preserve rounds1–3, remove final/classroom/report data, return Preview-ready
  with new final IDs. No Provider/Preview rerun; restore immutability triggers on commit/
  rollback.
- **Remake:** guarded; no bulk retry/recovery UI/read-triggered generation. Preserve
  charges/results/unknown stop. End, auth/CSRF and control guards remain.

Visible Preview polls; WebSocket speech/speaker updates ignore stale media callbacks.
Barrages freeze transactionally. Each round queries its KB at high/low/medium/high
priority, up to3 queries/batch. Remake rebinds and preserves caches; failures never become
cache successes, deleted diagnostics stay gone. Audio consent/identity/state guards remain;
Audio Ready means retained audio. Failed classroom actions retain rows.

Next.js/FastAPI/SQLite/files/Caddy share8080. Inspect active SQLite inside its container;
preserve config/knowledge/runtime data. Real core calls require authorization,
embedding dimension1024. These facts are not real-service acceptance.

## Remaining scope

徐伯闻 owns content acceptance; 古月 3D/voice/TTS, Kaikai accounts/student UI.
RAG quality, classroom load, deployment/monitoring, backup/restore and real speech
remain unverified. Architecture: [overview](ARCHITECTURE.md), [contracts](../contracts/), [ADRs](adr/).

## Topic and Background

Topic/optional Background are separate(0026); titles show Topic only. Accept visible
scripts/symbols; NFC/control/whitespace cleanup preserves punctuation. Background is
unverified scenario data. Draft edits invalidate Preview. Creation uses separate
cards, sidebar Back/Done and Ruleset language. Budget ceilings were later removed.

## Frozen Markdown Ruleset and current Report repair

Defaults are `backend/app/modules/debates/default_rules/{zh,en}.md`; reads make no
Provider call. Agents Order precedes language/Edit/Save. Display full Markdown; edit
raw text, Save language, Back discards. Done creates, hides in Edit and never saves
unsaved Ruleset edits. Freeze both files/eight System messages; send intact Markdown
plus round/JSON/source/routing rules, with language in Rulesets. Drafts cannot replace
frozen rules. Migration0027 preserves old custom rules/speeches; recovery/repair
retains messages and appends frozen feedback. Reject HTML/unsafe links; model
compliance stays manual.

“RAG证实”/“RAG提示”/“我感觉” guide evidence, else Agent.md; never invent/widen
claims. Reports keep full evidence; bibliography is not secret leakage. Creation:
Chinese default, separate CN/EN drafts, linked inputs/newest-first Agents, Beta→Debates.
Reentry reconnects without retry/advance; Replay/Conclude require completion; Live
clears replay cursors.

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

Three-Agent acceptance:12 turns, Conclude/Report and Replay; nine Preview speeches
reused. Seven calls(3 Embedding/3 LLM/1 Report); reopening/replay added none.
TTS/Voice were Mock; no student messages/votes. Retained turns 5/6 and 8/9 match
ignoring whitespace; list says “2 Rounds”; neither was rewritten. This dated
acceptance excludes later changes, RAG quality, real speech and load.

## Working — workspace, private Chats and Live

0030 adds private history, encrypted preferences and 20s Live leases. Chat freezes
version/snapshot, actor, revision and unknown-state; Live shares history/audio without
spectator generation/control. Providers are core modules; speech settings are
environment-managed (TTS120s, generic30s). Avatar editing stays in Workspace; the
warm-paper/display-serif design remains. Key entry makes no call/mode change; env key
wins. Check skips Ready/deferred, confirms calls and stops on failure. Failed creation
keeps text/retry identity; libraries use pencil/download/X. Dated workspace/Live checks
used11 calls; concurrent owner work raised the historical ledger to17.

Agent.md has no total cap; template is optional, with no chapter/semantic gates or
executed ToT/ReAct. Persona UI is removed; old codecs no longer reject by total size.
RAG has no file/aggregate character cap; ACL/non-execution guards remain. Supplier
batches stay at 10 items/30,000 estimated tokens. 0031 tombstones remove shared access
but retain assets/read-only Chats; Debate references/publication block deletion under
writer lock. Chats restores history; New starts fresh; Send clears the composer and
errors restore text/request identity. No cross-chat memory. Historical deterministic/
Docker0031 checks used no paid calls/live deletion/generation; quality stayed unverified.

September23 removed Chat ceilings/fixed output caps and prose scanning; retain full
history, auth/CSRF/ownership/header/unknown-acceptance/dedup/retry guards. Reservations
are accounting only; SendChat has no maxLength/429. Focused tests passed; no paid
post-rebuild SiyaH/RAG acceptance.

## Working — quiet workspace UI (observed in code 2026-09-24)

Mayaform: Welcome then Members. File X preserves snapshots; Agent version becomes X
on hover/focus. Debate opens Preview, hiding only its title. AGENT.md/Evidence/snapshot
downloads and Chats floating composer/separate Send remain.

## Snapshot publication history — September 23, 2026

Snapshot totals are unbounded; supplier batches remain 10/30,000 estimated tokens.
罗燕玲 staged one batch before HTTP500; a later build accepted five, timed out at30s and
left two not_sent. Next clicked sent nothing at attempt2/2; continuation later allowed
three attempts for unstaged unknown batches and120s timeout. A new draft accepted nine
batches (text-embedding-v4/1024/12 chunks). SiyaH's two retained stages published after
commit failure with seven chunks and no new call. Debate uses AGENT.md, not compiled
Persona. Prompt/output/query/LLM caps and embedding byte rejection were removed; failed
drafts cannot steal another warmer; proven-not-sent queries get one retry; stages reuse.

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

Merged local7236a97/checkpoint4fd1968, GitHub main a2b397d and entaiaki dfac2b4;
excluded sibling/revert branches. Fixed delete fixture/ledger, stale budgets and
Compose voice mapping; README/AGENTS updated.

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

Draft/Published use sidebar New, no inline Edit/Delete; Done saves/publishes, Back
protects dirty edits. Chats no 3D; Workspace keeps AvatarEditor. History date/Delete
exclusive hover/focus; touch shows Delete. Knowledge hides Ready, actions top-right.
Voices reuse Knowledge cards/count/tiles and preview/confirm/delete; New/Back switch
list/editor. No Empty decoration; v1 consent remains. Help/Immerse clears tooltips on
leave, route/DOM change, scroll, blur/Escape; Debate links no underline.

Chats has no 820px ceiling (desktop insets48/24px; mobile min max(600px,75dvh));
desktop/mobile overflow checks passed. Voice guidance is10–15s, 16-bit WAV/MP3/M4A,
max10MB; server accepts10–20s/10MiB. Wording does not alter upload contract.

Stalled Debate: one charged Embedding query (HTTP403), no LLM; no local budget/content
cause, remote unknown, no retry. Speech selectors offline/unchecked, no profile/
fallback (enrollment below). UI made no Provider call. Static/contracts/migration/
boundary, backed-up Docker and responsive browser checks passed. Voice remained Mock;
four lint warnings.

## Voice filenames, editing and optional Debate audio — September 27, 2026

Multipart names accept UTF-8/legacy Latin-1; a backed-up repair preserved audio,
mapping and request hashes. Owner-scoped metadata edits keep Voice IDs hidden.
Enrollment succeeded once (1 charged request). Preview DNS returned rejected Fake-IP;
the backed-up public-DNS fix kept SSRF checks unchanged. One authorized owner/session
TTS POST/200 stored 8.72s/418,604B PCM16/24kHz mono; preview awaits owner confirmation.
Older failed-preview charges are unknown (no ProviderOperation ledger).

Debate uses custom/system voice or explicit text-only playback, never fake media,
automatic Next or repeated generation. CAS H1 sync preserves old versions/names;
old identity headings do not rename. Voice63/backend/frontend427/contracts/migration/
boundary passed; ready200, other containers kept, no real TTS/LLM acceptance. Delete/
publish retains drafts/RAG/charges/tombstones. Chat language follows the final message;
Chat50/End12 passed/deployed. No age-based Stalled; End=Completed. Format gate blocked.

## Agent names and next-version voices — September 27, 2026

Names normalize NFKC/strip/casefold; duplicate creates and Markdown H1 renames return 409. Next drafts may use the owner's ready voice or null/platform default; old versions
stay unchanged. Backed-up normal soft-delete removed only the unpublished duplicate Bowen.

## Interaction and long-speech recovery — September 27, 2026

Interaction uses warm-paper mobile layout, 16px inputs/48px controls; 375×812 and
812×375 checks passed, no real classroom messages. Retry is an accessible refresh icon.
SQL/Mock covers HTTP, persisted messages/WS, Final freeze, model input, reply_to and
public output; replies quote only the referenced frozen anonymous message. Conclusion
keeps a 300-char input/12-candidate pool. This proves plumbing, not quality.

Speaker/AGENT.md binding is correct; attribution stays in editable zh/en Rulesets,
not Execution contract, and removal never reinserts it. Backend1500/21 skipped (known
race rerun), frontend420/1 skipped; Docker/Ruleset views passed, no model calls.

A stalled Debate accepted text but TTS reused a preview 1–60s check. One authorized TTS
POST returned HTTP200, 113.12s/5,429,804 bytes. After backup, HTTP-disabled promotion
reused saved bytes/text without Embedding/LLM or adjacent enqueue; old failed-TTS charges
remain unknown. Speech removes preview duration cap but keeps format/nonempty/quality,
20MiB and SSRF guards; Retry stays explicit. Docker switched before Preview continued.

## Debate entry and Immerse controls — September 27, 2026

Preview links keep warm hover/focus/press and reduced motion; no manual barrage pause,
Final freezes collection. Missing grades show No match+0; unscored counts are removed
without rewriting. Report failed `report_response_resource` after HTTP200; no real retry.
Student Live reuses QR form (same-course, active, non-replay); Final hides it. Messages
are uncapped/idempotent. Chats follow each message's language; no UI language field/TTS.

## MayaForm W0 — 2026-09-27

Agno3.0.11 pinned; 11 probes pass (ADR-009). Team `additional_input` preserves
history; direct `Message[]` drops assistant turns.

## MayaForm W2a Chat reliability — 2026-09-27

Unknown timeouts are not auto-resent; same-ID replay/new-ID follow-up. History/status
persist; valid stop tolerates usage faults, invalid fails after200. CAS/refund/save/SSE,
GET recovery; charged calls recorded, usage unclaimed. Actor/course switch clears Chat;
same-actor navigation retains. R4 `8bbcdfd00d804db574789a2a27b98bbf10d5c9d66da83587937d776c0d2cd9a8`/40 files:
42 focused, 449 frontend/1 skipped, `pnpm check`/boundary0. Sol review clean (9+42);
Mock recovery passed, 0 real calls.

## MayaForm W2b authored lengths — 2026-09-27

W2b removes Agent.md/RAG caps; fixtures 14,343/108,350/123,080 chars; persisted Agent.md
14,353. PATCH→download lossless. 0034 preserves data; oversized downgrade refuses;
batches ≤10/30k tokens via codepoint chunks. Sol accepted; check/boundary0, frontend449/1,
desktop/375 no overflow; no Provider; IME NOT_RUN.

## MayaForm W1 owner-first workspace — 2026-09-27

0035: owner/course/scope/visibility epochs; nullable personal Agent/source; Chat name
snapshot; legacy groups Public/owner NULL. Teacher personal Agent CRUD.
Sticky `draft_visibility`/`can_read_version`: Private-origin content stays owner-only through
Public changes; current Public release/source gates clones; untouched Public drafts collaborate.
Owner history kept. No-RAG: NULL snapshot/empty evidence; withdrawal freezes
name/history, denies sends. Debate group-only.

R5: 70 files; full check/boundary, Sol ACL/migration, 80 Mock requests and Teacher no-RAG
Chat/mobile passed. No Provider/Docker; IME NOT_RUN. Student Agent.md
allowed, no Toolkit binding/approval.
K1 R3 active: four shared immutable/CAS types; Question Rubric/answer teacher-only;
Graph read-only in Concepts. Global and Agent entry points share the store. Contract:
`docs/contracts/KNOWLEDGE_SETS_CONTRACT.md`. R2 covered P09 projection, student source load,
excerpt hashes, source-revoke ACL and 0036 cleanup; full check 464/1 and boundary passed.
Sol's only R2 reject was Asset replay timestamp drift. R3 replays exact accepted POST/PATCH
JSON only after current ACL/source checks; V1/V2 exact-body and revoked-404 focused tests pass.
Sol accepted R3; full check and boundary passed. No Provider/Docker/deployment.

## MayaForm K2a — accepted

0037: owner-scoped Job/run, input-key uniqueness, lease/startup recovery. Intent is
an optional API field; ordinary Teacher Done with RAG creates no Job. Explicit intent
atomically saves a Private Set/link and Job/run; owner GET returns safe status. Absent
Provider blocks `provider_not_configured`: 0 calls/assets. K2b NOT_RUN. R2 full
check/boundary, Sol, HTTP/browser passed. No Docker/real Provider.
