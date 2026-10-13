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
| Opening    | 50 characters          | 320 words              |
| Discussion | 50 characters          | 280 words              |
| Response   | 50 characters          | 350 words              |
| Conclusion | 100 characters         | 420 words              |

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

## Preserved classroom and account behavior

Classroom/Voice work remains separate from v1.4 Chats. Next reuses/intercepts
retained audio; failed audio retains text. Preview polls only while visible;
Final freezes eligible barrages transactionally. Conclude creates Report with
version/history; model/object/usage metadata do not reject usable Report content.
Replay reuses media without new input or generation. Immerse retains Transcript,
right-edge controls, QR/Interact and leases; no manual barrage pause control.

Devocalize removes audio only. Rebirth preserves rounds1–3, resets Final/classroom/
Report locally with new final IDs and no Preview call. Delete fences workers and
removes only the authorized revision after commit; sent calls cannot be retracted.
Remake/recovery preserves charged/accepted/unknown receipts and explicit retry
identity. Audio fallback never bypasses supplier-download SSRF protection.

Topic and Background are separate (0026). Default Rulesets live in
`backend/app/modules/debates/default_rules/{zh,en}.md` as editable, frozen content,
not hidden Chat instructions. Legacy IDs/data remain; Report Markdown/sources stay
complete; other contributors' Classes/config/3D work is preserved.

Single-course Demo registration and usernames/group normalization retain collision
checks (0029). Teacher Enter keeps the Teacher role and resource ACL; restarting
catalog sync preserves memberships. Password changes keep the current session and
revoke other sessions. Only a voice's creator manages it; live classroom access does
not grant student generation/control. Next.js/FastAPI/SQLite/files/Caddy share
localhost:8080.

Agent.md and RAG have no authored-text caps. Embedding batches keep the supplier
shape (10 items/30,000 estimated tokens). 0031
Agent tombstones preserve historical Chats/snapshots. Chats is text-only, with full
history, current-message language and no hidden locale/language suffix; Voice/Debate
speech is separate. Unknown acceptance affects one request, not later sends.

0033 removes product request/token/CNY/call-ordinal ceilings while preserving
reservations, actual usage, exact manifests, deduplication and authorization.
Output token caps remain absent. An HTTP 200 or accepted charge alone is not a
successful generation/report. .env updates require scoped recreation; backup and
sending/job/turn inspection precede deployment. Other services and private config
must remain unchanged.

Billed failures are never silently retried. Real RAG/classroom load/voice quality remain unverified.徐伯闻 owns teaching content, 古月 3D/voice/TTS,
Kaikai accounts/student UI. [Architecture](ARCHITECTURE.md), [contracts](contracts/),
[ADRs](adr/) retain the implementation agreements.

## Preserved v1.4 accepted work

W0 pins Agno3.0.11/public SDK (ADR-009); Team history uses `additional_input`, since
direct Message arrays dropped assistant turns. W1 owner-first workspace (0035)
keeps personal drafts, publication/ACL, frozen names and identity fencing. W2a
keeps request replay, history, usage/CAS/refund and SSE/GET recovery; W2b removes
Agent.md/RAG limits (0034) without changing supplier batch constraints. No Toolkit
approval or fixed Agent.md chapters.

K1 retains immutable Set/Asset/Version, actual Sources, Question-contained Rubric,
visual-only Graph and one shared store. K2a/K2b persist jobs, claims and exact
Provider stages; K2b2/K3-A materialization and published assets are committed.
Latest generation/current-version behavior is in
[Knowledge generation](contracts/KNOWLEDGE_GENERATION_CONTRACT.md), rather than
old separate confirmation or manual-head-preservation descriptions. Accepted W0,
W1, W2, K1, K2 and K3-A are not being reimplemented.

## MayaForm recovery — current October7

Branch feat/mayaform-v14; committed K2b2 a975e38, K3-A83de097/evidence1b1bfca retained.
K3-B1/B2,0041–0053 and learning/Tools checkpoint f59df82, later fixes e40d2a1,
0eafea9/30db274; implementation baseline36f10cb for ongoing UI/backend work. Foreign
Debate/Voice/UI edits protected.

Resume v2 preserves Brainform RAG/Knowledge/Memory, canonical Markdown and versions;
bound RAG/manual regenerate may replace manual head only on valid newer success,
history retained. Current actor/source read/edit checks, task-specific evaluator and
Boundary grants remain; Student Public+Student tools, Teacher Public+Teacher.
Formal attempts reach Teacher reports whatever a legacy Chat label says; ordinary
chats never do. General Chat stays text-only with natural-language attempt actions, no state
cards/dashboard/lifecycle buttons. Owner records/progress are phase-safe; histories
and completed evidence stay immutable. October9 diagnosis decisions (implemented,
0055 `submitted_at`, not yet real-accepted): survey round (all ≤3, else half), then
evaluator-chosen server-validated follow-ups before Boundary; "end" submits answered
work, only abandon/redo deletes that attempt's learning records (accounting kept);
Boundary and reports separate mastery/weak/not-yet-verified; server replies follow the
student's majority language; off-topic/progress questions get help, never answers.

Integrated PDF eb7e142 and selected colleague UI 817282e via b648efc/8987cf8; UI03/04/05 preserved.
Components UI removed1d92a2f; maintenance APIs stay. October 9 pushed the v14
line, including the colleague merges below; `main` is that same line.

Maya backend/frontend30db274 deployed only; other containers/env preserved. Schema0053,
readiness200/integrity/FK passed, Agno3.0.11 public SDK. Backup20261005T110321Z healthy;
sending/pending0, historical unknown3 not retried. Real synthetic RAG used1 charged
Embedding and2 accepted charged Knowledge LLM calls. Gen2 resumed same run; AIseq3
replaced manualseq2, preserving history. Public synthetic first send denied uniformly
for consent,4 member failures/no ORM error/input enabled/0calls/charges. Real natural
Team/assessment/Teacher statistics/download and Private exclusion still unaccepted.
User explicitly authorized specified synthetic Team payload and new Private test-body
read; old auto-review permission blocks resolved. The latest October7 instruction now authorizes a fresh dedicated synthetic four-Agent
Team/multi-student real workflow. Older no-Team-creation instructions are superseded.
Do not read unrelated Private Chat bodies or use real learner data.

Cleanup (backup20261005T130151Z, integrity/FK OK) withdrew exact synthetic fixtures only.
Provider ledger unchanged: 457 operations/457 charged requests (whole-runtime totals).

[Current UI contract](contracts/MAYAFORM_FINAL_UI_POLISH_SPEC_V2.md) overrides prior UI
planning: same Studyform/Brainform structure for both roles, permissions differ.
October9 user decisions: Studyform creates Agents/Voices and Teachers publish Maya
Teams there; Chats is renamed Chatform. Since October 11 New opens a Teams and Agents
page whose Done creates a Chat only its owner reads. Brainform has no
disclosure entry; operator `PROVIDER_STANDING_CONSENT` covers classroom/production,
otherwise Teachers confirm at the unlinked approvals route. Teacher Accounts (read-only
Public group visit, temporary membership removed on return) and Debates are restored.
Sidebar New/Back/Done; Back/Done only contextual. Voice
New is module-right exception; Home Voices Guide goes directly to its new form.
Colleague Mayaform Home preserved except Components, Guide destinations and data-use
entry moved to Brainform. All decorative heading explanations become immediate help;
no1500ms wait. Brainform three columns, no page title/eyebrow; RAG fully reuses original
Knowledge view/edit/download/delete and PDF/DOCX. View/New/edit replaces main content
in independent deep-link mode, not a bottom panel. Knowledge uses asset-name entry,
shows authorized Agent consumers, edits one canonical object; Agent Knowledge entry
also remains. Create AI Knowledge/New Agent one flow, Private/Public labels only;
Brainform accepts RAG or Knowledge. A Teacher Agent writes a question bank and
knowledge graph into Knowledge with a Tool. Other Agents may carry that Knowledge
or only AGENT.md. A Maya Team's shared RAG or Knowledge is added beside each
member's own material. Maya Team versions match Agent versions. Students and
Teachers create Teams the same way; only a Teacher publishes a Maya Team, which
keeps that label. A Teacher update while a student is answering on the old version
makes the Leader say the database changed and to answer again, and deletes that
unfinished assessment. Completed attempts stay. Teacher report reads stored answers
and statistics for that student, Maya Team name and time, not the raw chat.

Teacher explicit save/generate/regenerate must authorize exact Knowledge generation
without additional provider confirmation page. Current ACL/policy/manifest/accounting/
idempotency/unknown protections remain; backend implementation in progress, not yet
deployed. Canonical Single/Team runtime passed frozen Sol review44checks. Generation
49focused and independent Sol34checks passed, including real fresh-action race/no
duplicate run/charge. UI core Sol72checks passed, including pending-edit target switch;
Full UI r5:573pass/1skip, types/lint/format/build passed; A–K found Voices/help gaps.
Attempt27focused/longRAG1/migration3 passed; internal0054 pointer handles empty selections.
The newer backend freeze passed78focused and independent61checks (42 original+19
independent), including20different users/cookies/DB sessions, races, late-grant fences,
rollback and0054preservation. Deployed DB remains0053. These are not classroom load tests.
Final full gates, browser, real Team/report, GitHub and Docker rollout remain incomplete.

## Current delivery closure — October7

Acceptance is now a launchable website with the existing warm-paper UI, independent
review, exact-version gates, real four-Agent workflow, GitHub integration and final
scoped Docker/manual verification. Public DNS/TLS/off-host operation needs its own
actual evidence; local Demo health is not public launch acceptance.

Teacher `generate_agent_knowledge` now uses actual generation services/accepted Tool
receipts and wakes after commit. First ordinary published Agent generation works
without a prior Set. Independent Sol found and closed selected-source retry/revoked
receipt replay defects. Final39-file Tool freeze passed140focused; independent
30Tool+47generation+2additional executions passed. Source ACL, current publication,
exact manifest, idempotency, actual billing and unknown no-resend remain. Not deployed.

The Knowledge editor keeps the shared RAG editor, pending-save lock and draft fence.

Separate production profile rejects Demo/quick-login/auto-confirm, validates exact
public HTTPS origin, hides Demo identity routes, requires independent strong Teacher
credentials and dedicated production data/config mounts, and bounds auth abuse only.
Open-course enrollment/classroom password policy is unchanged. New auth rules never
limit Chat, Tool, authored content or Provider use. Independent C1 review passed41
backend+4locale checks and found two required fixes: active auth-limit bucket eviction
and Caddy overriding stricter classroom no-referrer. Original author is fixing these;
no public deployment or live configuration change has occurred.

Backup113435Z (SQLite,250files,238receipts, config) restored offline 0053→0054 with
readiness/integrity/FK passing; all457 Provider records kept; 1 incomplete Debate call
became unknown without sending; original3unknown stay unretried; no new charge.

C1 isolated HTTPS/SQLite mock test: 60 registrations/parallel sends/replays, SSE
reconnect, restart; integrity/FK pass, 0 Provider calls. Not a class-size claim.

Teacher statistics/report download in a fresh browser run is still open.
Colleague line `15f5450`: pose
`e9b000a` keeps one canvas; preset voice `b8f65e7` is `0056` and Chat stays
text-only; TTS bar `054f420` and the revert were not taken.

October 9: Brainform, Chatform and Studyform use the Debates card. Local browser imported the week 6–10 PDF as RAG and published Maya Team Keynotes from Studyform. A Private Keynotes turn called `read_memory` and paused with `team_no_progress`. Unseeable requests get 看不到。; missing functions get 做不到。 A complete published recipe opens with the Leader whoever opens the Chat; without it the Team waits for the first message. No @ asks only the Leader. A Knowledge update deletes an unfinished attempt; completed attempts stay. Team dispatch commits before `BEGIN IMMEDIATE`, avoiding `database is locked`. Tool classes stay permission-based: students get Public+Student, teachers get Public+Teacher. A student-published public Agent is for that group and teachers; a teacher-published public Agent is for the course; private is the owner. The publishing account opens Agent.md, Brainform, Avatar and Voice, with Back and Done. Anyone else gets that page read-only: view or download Agent.md and attached Brainform, an eye opens rendered Markdown, Avatar is view-only, and Voice, Done and New are absent. Done publishes only for the publisher; Back saves no draft. Teams are one Studyform list. Private or Public is chosen only when the Team is created. Private stays with the owner. A student Public Team is read-only for that group and teachers. A teacher Public Team is read-only for the course. A reader sees the saved Team read-only, with no Done. Brainform Memory opens a new chat. Notes belong to the account and speaking Agent, outside Debates and assessments. Deleting a Team or its Agents leaves its chats read-only. Card room `0058`: tables by 4-digit code. Students rename themselves; new accounts get one tour. `https://app.mayaform.net/` serves `1f34fea` (HTTP 200, backend ready 200, healthy, schema `0057`, backup20261011T045859Z integrity ok).

October 11: PR #50 (`f6b1338`) merged onto `762a810` as `556fdc5`. Reports count old Private formal attempts. Formal answers survive a textless Leader reply or flat Tool arguments. Versions: gold diamond Public, open Private. RAG rows show only a checkbox and name. Done keeps the Chat it created. Double-click or F2 renames a history Chat; a pin keeps it on top (`0059`). RAG is uploaded only in its Agent and takes that Agent's Private or Public, fixed at creation; Accounts visits put teachers in the group, reading Private. `0060` soft-retires all prior Agents, Chats, RAG, Teams, Knowledge, Debates, attempts and notes (downgrade restores); only the Demo keeps Laozi, Plato and Socrates. The model judges when to keep an Agent note; it must quote the user.

October 12: From 4d0c981; mock Demo, 0 Provider calls. Debates 404: setup required a group that teacher Studyform Agents lack; 0061 makes debate_participants.group_id nullable (FK-checked rebuild); setup and generation use the Agent's course. Lost assessment answers: the Leader replied in prose (assessment_action_required); the first assessment model call now forces its action tool (not revoked-source). User decision: every Public Team, Maya Teams included, takes only Public Agents (team_member_private); Private Teams mix both. Deleted Agents take their unshared RAG; Brainform lists no Private RAG; removed accounts leave member lists. zh round caps 50/50/50/100. DOCX/PDF ingest tests fail locally on main too.
0062 adds teacher personal voices (personal scope, owner-only); students choose groupmates' ready voices but manage only their own; a missing voice never blocks publishing or Debates. 我不知道/忘了 is a scored answer, not a skip.
After the last answer the server runs scorer then summarizer as the student's live sign-in; assessment_stage drives progress; results show points, feedback, summary. Teachers read raw test messages (Private too); the server adds report links. A test asks every Knowledge Question (no sampling). The Leader sets reply_language. Publishing an Agent moves its Teams along. Open tests run the Leader alone; attempts stay apart.

October 13: Brainform: New adds .md Knowledge; click edits, double-click renames. Saved RAG republishes its Agents; Teams follow. Agent editors offer only Brainform's library. Rubric "Follow-up for Question N; at most K" items follow wrong answers; scoring reruns. Cut replies fail visibly. Test Teams hide Questions from Agents; follow-up picking shows no bar; reports list answers; old Team versions' results stay readable. Bare letters/numbers always answer; answer sheets are server-written. Answers take one call; a new Chat starts a new test; 0063 stores names. Answers must fit the Question's form; others are named unrecorded. Teams New matches Agents New; refused Team members log why. The latest sentence sets the language. Leaders carry report links.
