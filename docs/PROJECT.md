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

Topic and optional Background are separate (0026). Current default Rulesets are
`backend/app/modules/debates/default_rules/{zh,en}.md`; language and teaching guidance
are editable/frozen Ruleset content, not hidden Chat instructions. Old protocols
were removed; immutable legacy IDs/data remain. Report Markdown and sources stay
complete. Classes/config/3D work owned by other authorized contributors is preserved.

Single-course Demo registration and usernames/group normalization retain collision
checks (0029). Teacher Enter keeps the Teacher role and resource ACL; restarting
catalog sync preserves memberships. Password changes keep the current session and
revoke other sessions. Voice clones stay uploader-owned; live classroom access does
not grant student generation/control. No usage reset or real speech acceptance is
implied. Next.js/FastAPI/SQLite/files/Caddy share localhost:8080.

Agent.md and RAG have no artificial total authored-text caps. Supplier embedding
batches retain their supported shape (10 items/30,000 estimated tokens). 0031
Agent tombstones preserve historical Chats/snapshots. Chats is text-only, with full
history, current-message language and no hidden locale/language suffix; Voice/Debate
speech is separate. Unknown acceptance affects one request, not later sends.

0033 removes product request/token/CNY/call-ordinal ceilings while preserving
reservations, actual usage, exact manifests, deduplication and authorization.
Output token caps remain absent. An HTTP 200 or accepted charge alone is not a
successful generation/report. .env updates require scoped recreation; backup and
sending/job/turn inspection precede deployment. Other services and private config
must remain unchanged.

Historical browser/provider results remain in Git history and are not current
v1.4 acceptance. Prior observed Voice/Report failures and billed calls cannot be
silently retried or converted into success. Real RAG quality/classroom load/voice
quality remain separately unverified.徐伯闻 owns teaching content, 古月 3D/voice/TTS,
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
Debate/Voice/UI edits protected. Main GPT-6.1 Sol, Luna/max writes, independent Sol
reviews. One writer per file; no new Astra subtask.

Resume v2 preserves Brainform RAG/Knowledge/Memory, canonical Markdown and versions;
bound RAG/manual regenerate may replace manual head only on valid newer success,
history retained. Current actor/source read/edit checks, task-specific evaluator and
Boundary grants remain; Student Public+Student tools, Teacher Public+Teacher.
Private excluded from Teacher queries/reports; ordinary Public excluded from formal
reports. General Chat stays text-only with natural-language attempt actions, no state
cards/dashboard/lifecycle buttons. Owner records/progress are phase-safe; histories
and completed evidence stay immutable. October9 diagnosis decisions (implemented,
0055 `submitted_at`, not yet real-accepted): survey round (all ≤3, else half), then
evaluator-chosen server-validated follow-ups before Boundary; "end" submits answered
work, only abandon/redo deletes that attempt's learning records (accounting kept);
Boundary and reports separate mastery/weak/not-yet-verified; server replies follow the
student's majority language; off-topic/progress questions get help, never answers.

Integrated PDF eb7e1429ac891cf8b8e3ce2007f23d5fbadfba0a and selected colleague UI
817282e7c53313e2c2e5233dc5be64d404dab90a via b648efc/8987cf8; UI03/04/05 preserved.
Components UI removed1d92a2f; maintenance APIs stay. October 9 pushed the v14
line, including the colleague merges below; `main` is that same line.

R4/R5 gate counts and Sol review counts are superseded by the October9 gates below.

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

User requested cleanup: backup20261005T130151Z via SQLite backup API/integrity/FK OK.
Precisely1 synthetic Team+publication,1Set,4Agents,2failed testChats withdrawn/archived;
1blocked generation cancelled. Source RAG already referenced by nonfixture Agent draft
was preserved. Provider ledger unchanged457 operations/457 total charged requests;
these are whole-runtime accounting totals, not this validation run's cost. Only exact
fixture IDs touched; no user/colleague records or original evidence physically purged.

[Current UI contract](contracts/MAYAFORM_FINAL_UI_POLISH_SPEC_V2.md) overrides prior UI
planning: same Studyform/Brainform structure for both roles, permissions differ.
October9 user decisions: Studyform creates Agents/Voices and Teachers publish Maya
Teams there; Chats is renamed Chatform, whose New opens a blank chat with a Chat with
picker and inline + New Team for students or Teachers. The first message creates the
chat; the Public/Private toggle starts a new chat, never relabels one. Brainform has no
disclosure entry; operator `PROVIDER_STANDING_CONSENT` covers classroom/production,
otherwise Teachers confirm at the unlinked approvals route. Teacher Accounts (read-only
Public group visit, temporary membership removed on return) and Debates are restored.
Reuse sidebar New/Back/Done; New bright when useful/dim otherwise, Back/Done only contextual. Voice
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
Completed attempts stay unchanged. Frontend work remains uncommitted.

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

UI R13 removed unreachable KnowledgeLibrary/KnowledgeSetWorkspace/TeacherSources,
retaining shared RAG fields/file/download and mutation helpers. R14 closed binary
same-metadata/different-bytes and changed-text-after-unknown nonce defects. R15 locks
only the current pending Knowledge save while allowing selection/copy; independent
44tests passed. C1 full frontend exposed an enabled-sidebar Done stale closure after
file fingerprinting. R16 reads the current committed action and fences the draft;
independent68tests passed, including an old-source failing early-click counterexample.
No new assessment controls or replacement Home design. Real browser acceptance pending.

Separate production profile rejects Demo/quick-login/auto-confirm, validates exact
public HTTPS origin, hides Demo identity routes, requires independent strong Teacher
credentials and dedicated production data/config mounts, and bounds auth abuse only.
Open-course enrollment/classroom password policy is unchanged. New auth rules never
limit Chat, Tool, authored content or Provider use. Independent C1 review passed41
backend+4locale checks and found two required fixes: active auth-limit bucket eviction
and Caddy overriding stricter classroom no-referrer. Original author is fixing these;
no public deployment or live configuration change has occurred.

Complete backup113435Z contains SQLite,250files,238active file receipts, private config
and effective Compose settings. Isolated zero-network service restoration passed
0053→0054, readiness200, file hashes/integrity/FK. All457Provider operation records and
accounting/payloads are retained; startup reclassified1historical incomplete accepted
Debate call as unknown without sending. Original3unknown remain unretried. This is
expected zero-network recovery, not a new charge or a claim that every state is unchanged.

C1 actual isolated HTTPS/SQLite test passed60synthetic registrations/logins,60parallel
Single Chat sends/replays/cross-user denials, SSE disconnect/reconnect, process restart
and60history reads/continued sends. Peak client concurrency20;121unique persisted
intents, no ownership mismatch, integrity/FK pass. Mock only/0Provider operations;
not a real Team throughput or supported class-size claim. Final source rerun pending.

Real acceptance remains NOT_RUN: Teacher Maya Agent calls RAG→Knowledge Tool; three
Agents reference that exact canonical object; dedicated synthetic students start
Public/Private Maya Team Chats and save real answers/evaluations/Boundary evidence;
Teacher Maya Chat reads activity-scoped Public statistics/report/download with Private
excluded. Inputs are prepared, not uploaded. Historical paid calls are not acceptance.

October 9 colleague integration, pushed as `15f5450` on the v14 line:

- `entaiaki-avatar-pose` (`e9b000a`): relaxed standing pose is applied inside the
  current `setAsset` load. The branch's per-model canvas remount was not taken;
  one canvas stays bound for a framing and receives the next model.
- `entaiaki-plato-voice` (`b8f65e7`): migration is `0056_preset_voice_profiles`
  after `0055`. Debate, preview, fallback and the TTS gate send the profile's
  allowlisted model. Preview speech stays the fixed line. Chat stays text-only,
  so that branch's chat-TTS edits were not taken.
- `entaiaki-tts-fix` (`054f420`, ours): chat voice bar and autoplay were not
  taken. Owner decision: chat is not read aloud.
- `revert-task-001-merges` (`15f5450`, ours): current avatars and text-only Chat
  stay. The revert was not applied.

On that merge tree, preset-voice and debate voice-fallback tests passed, and
ruff, format and mypy passed. The full backend suite was not run. This is not
classroom acceptance.

Server facts, not a launch: `app.mayaform.net` resolved to `8.210.57.144`.
That host is Ubuntu 24.04 with Docker 29.9 and Compose 5.6; a 4 GiB swap file
is on. The production stack was not started, no certificate was issued, and no
real Provider call had not been made yet.

October 9: Brainform, Chatform and Studyform use the Debates card. Local browser imported the week 6–10 PDF as RAG and published Maya Team Keynotes from Studyform. Chatform New then selects that Team name. A real Public Keynotes turn answered from the keynotes (two charged `llm_agent_chat` successes). An earlier single-Agent turn was also charged once. A Private Keynotes turn called `read_memory` and paused with `team_no_progress`; the composer shows Resume instead of a spinner. Team dispatch was failing closed on SQLite `database is locked` because a session still held the writer while another connection took `BEGIN IMMEDIATE`; the session now commits and rolls back first. Tool classes stay permission-based: students get Public+Student, teachers get Public+Teacher. Production Compose is up: gateway, frontend and backend healthy; `https://app.mayaform.net/` returned HTTP 200; container `/health/ready` is ready; schema is `0056_preset_voice_profiles`. The public database is new, so the local Keynotes run is not on it. No public Provider call was made.
