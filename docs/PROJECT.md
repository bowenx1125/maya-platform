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
embedding dimension1024. Not real-service acceptance.

## Remaining scope

徐伯闻 owns content acceptance; 古月 3D/voice/TTS, Kaikai accounts/student UI.
RAG quality, classroom load, deployment/monitoring, backup/restore and real speech
remain unverified. Architecture: [overview](ARCHITECTURE.md), [contracts](../contracts/), [ADRs](adr/).

## Topic and Background

Topic/optional Background are separate(0026); titles show Topic only. Accept visible
scripts/symbols; NFC/control/whitespace cleanup preserves punctuation. Background is
unverified scenario data. Draft edits invalidate Preview. Creation uses separate
cards, Back/Done and Ruleset language. Budget ceilings were later removed.

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
stops canonical username/group collisions without changing logins. Teacher course role survives sync; Enter selects group scope without bypassing
resource-owner ACL. Mayaform returns Home. Self-service password changes retain the
current session, revoke others and store a DB override without changing the catalog.
Auth/CSRF/publication/course/consent guards remain.

## Classroom display — September 18, 2026

PR29(ed22231):2–5 licensed courtyard scholars; jaw/bubble/Transcript follows audio,
with text on media failure. /local-roundtable accepts WAVs. Voice clones stay
uploader-owned; Gaussian packs are optional ADR-007 experiments.

## Operation panel and browser acceptance — September 22, 2026

Historical three-Agent12-turn Conclude/Report/Replay used seven calls and reused
nine Preview speeches; reopening added none. TTS/Voice were Mock; no student input.
Old retained turns/list labels were not rewritten. This excludes current changes,
RAG quality, real speech and load.

## Working — workspace, private Chats and Live

0030 adds private history, encrypted preferences and 20s Live leases. Chat freezes
version/snapshot, actor, revision and unknown-state; Live shares history/audio without
spectator generation/control. Providers are core modules; speech settings are
environment-managed (TTS120s, generic30s). Account settings retain preset avatars and self-service passwords; Workspace
3D editing stays separate. Warm-paper and compact typography remain. Key entry makes no call/mode change; env key
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

Snapshot totals are unbounded; supplier batches remain10/30,000 estimated tokens.
Historical 罗燕玲/SiyaH stages retained accepted batches across timeout/commit failure;
stage promotion reused paid results. Drafts cannot steal another warmer; proven-not-sent
queries get one retry. Agents use AGENT.md, not compiled Persona. Prompt/output/query/
LLM caps and embedding byte rejection were removed. Historical success is not current
Provider acceptance.

## Chat and speech boundaries

Chats is text-only: no Chat TTS dispatch, audio event or hidden language instruction.
Streaming saves accepted text and keeps usage separate; unknown acceptance affects
one request, never subsequent messages. Voice/Debate speech stays separately scoped.

## Workspace/integration history — September 27, 2026

Bilingual help covered workspace/Debate; imports were then Markdown-only.
Merged local7236a97/checkpoint4fd1968, main a2b397d/entaiaki dfac2b4;
excluded sibling/revert branches. Delete ledger, budgets and Compose voice mapping fixed.

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

Drafts preserved; text-only Chats, Workspace AvatarEditor. History date/Delete exclusive
on hover/focus, touch supported; Knowledge hid Ready, Voices retained consent.
Tooltip clears on leave/navigation/DOM/scroll/blur/Escape; dated desktop/mobile PASS.
Voice guidance10–15s vs server10–20s/10MiB. Debate Embedding403 charge retained without
retry; dated Mock Voice/static/Docker/browser PASS with4 warnings.

## Preserved adjacent work — September 27, 2026

Historical Voice enrollment/preview/113.12s succeeded; promotion reused paid stages,
unknown charges never retried. Owner/SSRF/snapshot/name/duplicate409 guards remain.
Mock history is not current quality proof; one Report200 failed content without retry.
Live keeps QR/Final cutoff; Chat has no language field/TTS.

## MayaForm W0 — 2026-09-27

Agno3.0.11 pinned; 11 probes pass (ADR-009). Team `additional_input` preserves
history; direct `Message[]` drops assistant turns.

## MayaForm W2a Chat reliability — 2026-09-27

No automatic unknown resend; same-ID replay/new-ID follow-up, history/usage/CAS/refund/
SSE/GET recovery retained. Actor/course switch clears Chat; same-actor navigation retains.
R4:42 focused/449 frontend+1skip, full check/boundary/Sol PASS; Mock only,0 real calls.

## MayaForm W2b authored lengths — 2026-09-27

W2b removes Agent.md/RAG caps; 14,343/108,350/123,080-char fixtures persist losslessly.
0034 preserves data; oversized downgrade refuses. Supplier batches stay ≤10/30k estimated
tokens via codepoint chunks. Sol/check/boundary passed; no Provider; IME NOT_RUN.

## MayaForm W1 owner-first workspace — accepted R5

0035: personal ownership/epochs/frozen Chat names; legacy Group owner NULL. Private drafts
stay owner-only until Done; sharing checks source ACL. Student Agent.md allowed, no Toolkit
approval. R5: full check/boundary/Sol ACL+migration/80 Mock/Teacher Chat+mobile PASS;
no Provider/Docker, IME NOT_RUN. K1: immutable types, Teacher Rubric/reference,
read-only Graph/one store; P09/source/0036/replay PASS. See
`docs/contracts/KNOWLEDGE_SETS_CONTRACT.md`.

## MayaForm K2a — accepted

0037: owner-only Jobs/runs/reuse/leases; explicit intent only, ordinary Done creates no
Job. Publish/Private Set/link/run atomic; no Provider→zero calls/assets. R2/Sol/HTTP/browser PASS.

## MayaForm K2b1 — accepted Provider stage

0038: confirmed llm_knowledge_generate, public Agno3.0.11 once; bytes/hash/post_bytes
match. ACL/disclosure/accounting/unknown/sanitized stage, check/migration/HTTP/Sol PASS;
K2b1 had no Assets or real Provider/Docker.

## MayaForm recovery — current October5

Branch feat/mayaform-v14; committed K2b2 a975e38, K3-A83de097/evidence1b1bfca retained.
K3-B1/B2,0041–0053 and learning/Tools checkpoint f59df82, later fixes e40d2a1,
0eafea9/30db274; implementation baseline36f10cb for ongoing UI/backend work. Foreign
Debate/Voice/UI edits protected. Main GPT-6.1 Sol, Luna/max writes, independent Sol
reviews. One writer per file; no new Astra subtask.

Resume v2 preserves Brainform RAG/Knowledge/Memory, canonical Markdown and versions;
bound RAG/manual regenerate may replace manual head only on valid newer success,
history retained. Current actor/source read/edit checks, task-specific evaluator and
Boundary grants remain; Student Public+Student tools, Teacher Public+Teacher.
Private excluded from Teacher queries/reports; ordinary Public excluded from formal
reports. General Chat stays text-only with natural-language attempt actions, no state
cards/dashboard/lifecycle buttons. Owner records/progress are phase-safe; histories
and completed evidence stay immutable. Latest abandoned-attempt rule:
discard abandoned learning records; existing retention code still needs later change.

Integrated PDF eb7e1429ac891cf8b8e3ce2007f23d5fbadfba0a and selected colleague UI
817282e7c53313e2c2e5233dc5be64d404dab90a via b648efc/8987cf8; UI03/04/05 preserved.
Components UI removed1d92a2f; maintenance APIs stay. No GitHub final push yet.

Same frozen R5 source:1930 passed/21 existing skips/exit0,398.40s; R4 known race
passed unchanged in retry and R5. Frontend559/1 skip/types/lint/format, Ruff/format493,
mypy247,152 API semantics/19 negatives, privacy/boundary/generated and7 migration/
bootstrap/reset gates passed. Sol independently reviewed KB recovery52backend/20front,
Team75+9, learning fixture37+1 (63 assertions retained), Chat guidance41, identity
handoff35. These are code/deterministic evidence, not complete real product acceptance.

Maya backend/frontend30db274 deployed only; other containers/env preserved. Schema0053,
readiness200/integrity/FK passed, Agno3.0.11 public SDK. Backup20261005T110321Z healthy;
sending/pending0, historical unknown3 not retried. Real synthetic RAG used1 charged
Embedding and2 accepted charged Knowledge LLM calls. Gen2 resumed same run; AIseq3
replaced manualseq2, preserving history. Public synthetic first send denied uniformly
for consent,4 member failures/no ORM error/input enabled/0calls/charges. Real natural
Team/assessment/Teacher statistics/download and Private exclusion still unaccepted.
User explicitly authorized specified synthetic Team payload and new Private test-body
read; old auto-review permission blocks resolved. User now performs Team creation/review.

User requested cleanup: backup20261005T130151Z via SQLite backup API/integrity/FK OK.
Precisely1 synthetic Team+publication,1Set,4Agents,2failed testChats withdrawn/archived;
1blocked generation cancelled. Source RAG already referenced by nonfixture Agent draft
was preserved. Provider ledger unchanged457 operations/457 total charged requests;
these are whole-runtime accounting totals, not this validation run's cost. Only exact
fixture IDs touched; no user/colleague records or original evidence physically purged.

[Current UI contract](contracts/MAYAFORM_FINAL_UI_POLISH_SPEC_V2.md) overrides prior UI
planning: same Studyform/Brainform structure for both roles, permissions differ.
Studyform owns Agent/Team creation; Chats selects existing resources. Reuse sidebar
New/Back/Done; New bright when useful/dim otherwise, Back/Done only contextual. Voice
New is module-right exception; Home Voices Guide goes directly to its new form.
Colleague Mayaform Home preserved except Components, Guide destinations and data-use
entry moved to Brainform. All decorative heading explanations become immediate help;
no1500ms wait. Brainform three columns, no page title/eyebrow; RAG fully reuses original
Knowledge view/edit/download/delete and PDF/DOCX. View/New/edit replaces main content
in independent deep-link mode, not a bottom panel. Knowledge uses asset-name entry,
shows authorized Agent consumers, edits one canonical object; Agent Knowledge entry
also remains. Create AI Knowledge/New Agent one flow, Private/Public labels only;
Brainform source picker accepts RAG or Knowledge. Updates affect future Agent use; active/paused Team attempts announce changed
Knowledge and require answering again; old answers/late results cannot evaluate.
Completed attempts stay unchanged; invalidation hook not yet implemented. Current frontend changes uncommitted/unaccepted.

Teacher explicit save/generate/regenerate must authorize exact Knowledge generation
without additional provider confirmation page. Current ACL/policy/manifest/accounting/
idempotency/unknown protections remain; backend implementation in progress, not yet
deployed. Existing AgentKnowledgeSet references/current asset heads support future
updates; manual Markdown vs live asset heads/partial generation needs focused probe.
UI and backend writers own separate files; independent current-version audit and actual
browser desktop/mobile checks still required. No pending path is labelled complete.
