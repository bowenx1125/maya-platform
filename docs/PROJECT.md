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

## MayaForm recovery — 2026-10-03

K2b2 a975e38 and K3-A83de097/evidence1b1bfca remain committed; actual branch
feat/mayaform-v14. K3-B1/B2,0041–0053 and learning/Tools are checkpointed f59df82 and
deployed; deployment is not end-to-end acceptance. Lost reviews have current replacements.
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

Independent R3:160 runtime/92 boundary/47 Provider cases (overlapping); late revocation
sends nothing/charge0, old readable snapshots remain valid, SSE drains without replay.
Resume retains answers/turns; owner answer DTO exposes answer_text/created_at only.
Source-free allows own records/progress/abandon, never resume/hints. Exact legacy
Teacher/course scope remains; Private Single denies Teacher. General Chat has natural
lifecycle messages, no assessment controls/composer. BF import14/Setext/HTTP passed.
Linux backend1909/21 old skips (499.64s, exit0); pre-removal frontend559/1 skip,
6 independent UI probes.
Full student/Teacher browser and Provider closure remains pending; no end-to-end acceptance.
[BF/AT/RS](validation/MAYAFORM_V14_INTEGRATED_ACCEPTANCE.md) and
[S01–22](validation/MAYAFORM_V14_SUPPLEMENT.md) separate current targets from history.

October5 Maya backend/frontend rebuilt; effective environment/DNS/gateway preserved.
Backup20261005T042605Z preceded rollout; sending0. Live0053/readiness200/integrity/FK OK.
All59 original tables/6,423 rows retain content/ledgers; one Debate running→pending
metadata change is accepted-result startup recovery. Historical unknown3 untouched.
Real synthetic RAG:1 charged Embedding; exact confirmation resumed the same Knowledge
run once,1 charged accepted LLM/usable Markdown. Manual edit saved seq2; RAG update
intent2 blocked before sending, retaining seq2. Full closure/GitHub push pending.
Disclosure navigation works without browser competition. UI backup20261005T064211Z OK.
Selected PDF origin/entaiaki eb7e1429ac891cf8b8e3ce2007f23d5fbadfba0a and
UI origin/w5/ui/06-home-academy817282e7c53313e2c2e5233dc5be64d404dab90a
(UI03/04/05 included): actual ancestry merges b648efc/8987cf8 preserve both selected
refs, Brainform sidebar New and General Chat. d170a96 corrects stale import guidance.
Latest UI instruction: retain colleagues' MayaForm design, add no replacement elements;
remove all user-visible Components/Key/Check/mode/status UI; maintenance APIs stay.
Components removed, no replacement:555 frontend/1 old skip; types/lint/Prettier PASS.
5 old UI tests removed,1 Dashboard test added; Sol source/25 focused PASS.
1d92a2f deployed frontend only; real Home DOM/screenshot has no Components/controls.
Other container IDs/MayaForm UI unchanged; full A–K polish spec is proposal only.
0052/0053 append only. Types/lint(0 errors/4 old warnings), Prettier,
Ruff/format493/mypy247,152 actual API semantics/19 negatives, generated/
privacy/boundary and7 migration/bootstrap/reset gates passed. Agno3.0.11 public SDK.
Freeze912 files, manifest db6b792d3bb895f6aae42c43f0ce15f3a6c8f791692f0e828d13ac70210a1c56;
At1d92a2f all502 backend files matched; UI22 had fresh evidence. Query Embedding has
separate Teacher course-purpose consent.0050 permits llm_agent_chat/embedding_query;
independent populated0033→0053/18 atomicity tests passed.

Pending rollout: RAG Job hydration/disclosure and historical Team RAG fixes passed
Sol review (Team75+9 probes). Manual fixture now captures real fences and stable
baseline members;63 assertions unchanged,37+1 independent cases passed. R2's26
failures resolved. Frozen R3:1926 passed/21 old skips/exit0 (428.52s), no code drift;
frontend557/1 old skip/types/lint/contracts and7 migration/script gates passed.
Real paths and UI-v2 implementation remain pending; no end-to-end acceptance.
[UI v2](contracts/MAYAFORM_FINAL_UI_POLISH_SPEC_V2.md) is deferred until functionality
is verified complete: Studyform=Workform, Agents then Voices; mature RAG in three-column
Brainform, no page title/sidebar New; preserve Knowledge edit and global hover1500ms.
