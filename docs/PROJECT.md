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

Sidebar New/Done/Back preserve drafts; Chats has no3D, Workspace retains AvatarEditor.
History date/Delete exclusive on hover/focus; touch supports Delete. Knowledge hides
Ready; Voices reuse tiles/actions and existing consent. Tooltips clear on leave,
navigation/DOM change, scroll, blur/Escape. Chats has no820px ceiling; dated desktop/
mobile overflow checks passed. Voice guidance10–15s differs from server10–20s/10MiB.
A stalled Debate's Embedding403 retained its charge without retry; no LLM or local
budget cause. Dated static/Docker/browser checks passed with Mock Voice/four warnings.

## Preserved adjacent work — September 27, 2026

Historical Voice enrollment/preview/113.12s speech succeeded; promotion reused
the saved stage and unknown charges were not retried. Owner/SSRF/snapshots,
normalized names/duplicate409 and old versions remain. Historical Mock checks
are not current quality proof. A Report200 failed content without retry.
Live keeps QR/Final cutoff; Chat has no language field or TTS.

## MayaForm W0 — 2026-09-27

Agno3.0.11 pinned; 11 probes pass (ADR-009). Team `additional_input` preserves
history; direct `Message[]` drops assistant turns.

## MayaForm W2a Chat reliability — 2026-09-27

Unknown timeouts never auto-resend; same-ID replay/new-ID follow-up. History/status,
usage-fault handling, CAS/refund/save/SSE and GET recovery persist. Actor/course switch
clears Chat; same-actor navigation retains. R4: 40 files, 42 focused, 449 frontend/1
skip; full check/boundary0, Sol clean. Mock recovery only; 0 real calls.

## MayaForm W2b authored lengths — 2026-09-27

W2b removes Agent.md/RAG caps; 14,343/108,350/123,080-char fixtures persist losslessly.
0034 preserves data; oversized downgrade refuses. Supplier batches stay ≤10/30k estimated
tokens via codepoint chunks. Sol/check/boundary passed; no Provider; IME NOT_RUN.

## MayaForm W1 owner-first workspace — accepted R5

0035 adds owner/course/scope/visibility epochs, personal Agents/sources and frozen Chat names;
legacy Group owner remains NULL. Private-derived drafts stay owner-only until owner Done; source
ACL gates sharing. Teacher personal/no-RAG, withdrawal history/send fence and group-only Debate
passed. Student Agent.md is allowed; no Toolkit/approval. R5: 70 files, full check/boundary, Sol
ACL/migration, 80 Mock requests and Teacher Chat/mobile passed; no Provider/Docker; IME NOT_RUN.
K1: four immutable types, teacher-only Rubric/reference answer, read-only Graph in Concepts, one
store across entry points. P09/source verification/0036 cleanup/replay passed; see
`docs/contracts/KNOWLEDGE_SETS_CONTRACT.md`.

## MayaForm K2a — accepted

0037 adds owner-only Jobs/runs, stable input reuse and leases. Only explicit intent enqueues;
ordinary Done with RAG creates no Job. Publish, Private Set/link and run are atomic. No Provider
means zero calls/assets. R2 check, Sol and HTTP/browser passed.

## MayaForm K2b1 — accepted Provider stage

0038 binds one confirmed `llm_knowledge_generate` operation to the run. Agno 3.0.11 calls once;
canonical bytes equal stored hash and `post_bytes`. ACL/disclosure, accounting, unknown recovery
and sanitized stage passed. No Assets in K2b1. Full check, populated migration/HTTP and Sol passed;
no real Provider/Docker.

## MayaForm recovery — 2026-10-03

K2b2 a975e38 and K3-A83de097/evidence1b1bfca remain committed; actual branch
feat/mayaform-v14. K3-B1/B2,0041–0053 and learning/Tools are checkpointed f59df82,
not deployed acceptance. Lost reviews were replaced by current same-version review.
Preserve foreign Debate/Voice/UI changes; one writer owns each shared file.
Main switched to GPT-6.1 Sol on October5; Luna/max implements, independent Sol audits.

[Resume v2](contracts/MAYAFORM_V14_BRAINFORM_ASSESSMENT.md) replaces old categories,
no-Memory entry, manual-head preservation and active-attempt hints. Brainform lists
RAG/Knowledge/Memory together; canonical Markdown versions bind asset projections.
Bound RAG saves/manual regenerate replace manual current only after a valid newer
success, retaining history. Private/Public configured attempts persist independently
of Chat/run; plain abandon ends only, abandon-and-redo creates a new attempt.

The [latest Tool/resource correction](contracts/MAYAFORM_V14_TOOL_RESOURCE_AUTHORIZATION.md)
requires Public/Student/Teacher: Student gets Public+Student, Teacher Public+Teacher.
Tool mounting, target resource ACL and attempt execution grant are separate. Formal
evaluator/Boundary summarizer grants bind actual participant/version/answer/attempt,
never names or creator role. Self-read and Teacher Public-read do not grant edit.
Target-attempt safe projections apply across Agents, Memory and downloads. No new
practice UI, role Planner, generic database editor or approval ceremony.

Independent R3 passed160 runtime cases,92 boundary probes and47 Provider scope cases
(overlapping). Authorized sends occur once; late revocation sends nothing/charge0;
readable old snapshots remain valid. SSE drains one snapshot without replay calls.
Resume retains original answers/turn identity. Owner answers expose answer_text/
created_at only; source-free recovery allows own answers/progress or abandon, never
resume/hints. Legacy query scopes retain exact Teacher/course checks; Private Single
denies Teacher. General Chat uses natural lifecycle messages, no assessment controls
or special composer. BF MD import14 independent and Setext/HTTP tests passed.
Final isolated Linux backend1909 passed/21 skipped (499.64s, exit0); integrated
frontend559/1 skipped and6 independent UI probes passed;281 frontend hashes stable.
Browser and real Provider remain pending; no end-to-end acceptance claimed.
[BF/AT/RS](validation/MAYAFORM_V14_INTEGRATED_ACCEPTANCE.md) and
[S01–22](validation/MAYAFORM_V14_SUPPLEMENT.md) separate current targets from history.

Docker remains at0033 with original container IDs; no resumed paid call, rebuild or push.
October5 SQLite backup API/integrity/FK passed. A private backup copy upgraded
0033→0053 preserving all59 original tables/6,421 original rows and original-column
bytes; integrity/FK passed. Final deployment still needs fresh in-flight checks.
Selected PDF origin/entaiaki eb7e1429ac891cf8b8e3ce2007f23d5fbadfba0a and
UI origin/w5/ui/06-home-academy817282e7c53313e2c2e5233dc5be64d404dab90a
(UI03/04/05 included): PDF ancestry merged b648efc; UI source is integrated and
independently accepted, retaining Brainform sidebar New and General Chat.
Linux conversion22 and UI Sol102/Roster/Profile probes passed before final delta;
macOS memory guard remains. Migrations0052/0053 append without rewriting history.
Final frontend559/1 skipped; types, lint(0 errors/4 existing warnings),
Prettier, backend Ruff/format493/mypy247, all152 actual API semantics/19 negatives,
generated/strict privacy/boundary and7 migration/bootstrap/reset gates passed.
Locked Agno3.0.11 is used through public SDK. Independent runtime source freeze:
912 files, manifest db6b792d3bb895f6aae42c43f0ce15f3a6c8f791692f0e828d13ac70210a1c56;
All502 backend files retain that freeze; UI22 changed files have new evidence. Query Embedding
uses separate exact Teacher course-purpose consent, not LLM consent or per-message
approvals. Migration0050 permits only llm_agent_chat/embedding_query; independent
populated0033→0053 and18 atomicity tests passed. Production remains0033 pending rollout;
latest backup is20261005T033431Z, integrity/FK OK. Historical unknown3 are never resent.
