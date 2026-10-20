# Maya Platform

Maya combines Agent Markdown, RAG, classroom debate and reports. Progress authority;
[AGENTS.md](../AGENTS.md) defines work. Latest user decisions prevail.

## Approved four-round flow — September8, 2026

New debates: four rounds,2–5 Agents,no selector,four_round_v1/segments_v2. Preserve old
records; historical recovery compatibility waived. Opening: independent high-priority
own-KB evidence,culture as perspective,acknowledge gaps. Discussion: low-priority own-KB,
address claims,ask cyclic stable Agent ID,no moderator/planner. Response: medium-priority
retrieval on actual challenges; memory=position/change/reason/influence/unresolved_question.
Conclusion: fresh high-priority own-KB/public speeches/memory,agreement/criticism/learning;
freeze barrages once,answer one eligible message/Agent,never invent replies.

Preview retains rounds1–3 text/audio; round4 live. Later turns see successful predecessors
including same-round after round barriers. Order rotates,identities/targets fixed.
Next/scheduling/hashes/recovery reuse one accepted prefix without recharging.
Guidance by round,Chinese chars/English words:50/80,50/80,50/100,100/150,no minimum.
Chinese counts nonspace/punctuation; English counts alphanumerics with internal
apostrophes/hyphens. Length never rejects/repairs/truncates/pads readable paragraphs.
Drop bad auxiliary metadata,keep valid sources/bindings exact. Unreadable output gets
at most one authorized frozen repair; one-call adds none; unknown acceptance never resent.
Questions differ from reply_to; memory excludes speech/TTS/Agent.md/version/KB.
Round4/Report get separate session_discussion_memory. Own KB/Persona only; others'
public speeches,never private receipts/Persona.0024 drops only speaker/snapshot FK;
other ownership/uniqueness stays. Evidence support,not accuracy:direct+5/contextual+2/no_match+0.
[Prompts](contracts/FOUR_ROUND_PROMPTS.md)/[examples](contracts/four-round-example.json)
retain manual review,never keyword/similarity gates.

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

Branch feat/mayaform-v14 retained K2b2, K3-A and learning/Tools checkpoints; their
exact refs remain in Git history. Foreign Debate/Voice/UI work stays protected.

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

October5 build30db274/schema0053: ready/integrity/FK passed, Agno3.0.11 public SDK; backups20261005T110321Z and130151Z healthy. Sending/pending0; historical unknown3 retained. Synthetic RAG: 1 charged Embedding, 2 accepted charged Knowledge calls; Gen2/seq3 replaced seq2 with history. Consent-denied sends: 0 calls. Cleanup withdrew exact synthetic fixtures only; runtime ledger 457 operations/457 charged requests unchanged. October7 authorizes a fresh dedicated synthetic four-Agent Team and multi-student workflow. Synthetic reads stay scoped; never real learner data or unrelated Private Chat bodies.

[Current UI contract](contracts/MAYAFORM_FINAL_UI_POLISH_SPEC_V2.md) overrides prior UI
planning: same Studyform/Brainform structure for both roles, permissions differ.
October9 user decisions: Studyform creates Agents/Voices and Teachers publish Maya
Teams there; Chats is renamed Chatform. Since October 11 New opens a Teams and Agents
page whose Done creates a Chat only its owner reads. Brainform has no
disclosure entry; operator `PROVIDER_STANDING_CONSENT` covers classroom/production,
otherwise Teachers confirm at the unlinked approvals route. Teacher Accounts (read-only
Public group visit, temporary membership removed on return) and Debates are restored.
Sidebar New/Back/Done; Back/Done only contextual. Voice New is module-right; its form
skips the sidebar: consent creates, top-right ← cancels. Agent Voice: radio,
None default; groupmates choose/hear ready voices; teachers never.
All decorative heading explanations become immediate help;
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

Teacher save/generate/regenerate authorizes exact Knowledge generation without a second
confirmation page; ACL, policy, manifest, accounting, idempotency and unknown protections
remain. Classroom load and real Team/report acceptance remain open.

## Current delivery closure — October7

Closure retains four-Agent workflow and real classroom acceptance.
Teacher `generate_agent_knowledge` uses accepted receipts and wakes after commit;
first published Agent generation needs no prior Set. Knowledge keeps RAG editor,
pending-save lock and draft fence. Production profile rejects Demo/quick-login/
auto-confirm, exact public HTTPS origin, strong Teacher credentials, dedicated
mounts; auth abuse bounds only. C1 Mock: 60 regs, parallel send/replay, SSE; 0
Provider calls. Backup113435Z offline 0053→0054 kept all Provider records; no new
charge. Colleague: pose `e9b000a` one canvas; preset voice `b8f65e7`=`0056`; Chat
text-only; TTS bar `054f420` not taken.

October 9: Debates on Brainform/Chatform/Studyform. Private `read_memory` can pause
`team_no_progress`; Tool ACL by role; publisher edits Agent.md/Brainform/Avatar/Voice.
Card room `0058`; production `1f34fea` (schema `0057`).

October 11: PR #50 → `556fdc5`. Pills: green Public, gray Private. Chat pin
`0059`. RAG fixed Private/Public at creation; Accounts visits read Private. `0060`
soft-retires prior work (Demo keeps Laozi/Plato/Socrates). Agent notes must quote user.

October 12–13: 0061 nullable personal debaters; Public Teams take only Public Agents. 0062 personal voices are owner-managed; 我不知道/忘了 scores. Scorer then summarizer run as the live sign-in; every Question is asked. Brainform .md edit/rename; rubric follow-ups rerun; 0063 stores names; answers must match the Question form. Leaders carry report links.

PR #52: text playback, Live recovery, Avatar, 0064 slot release; Interact UI 26/26.

UI polish: Teams match Agents; create Done validates; edit Done needs a dirty form; RAG/Knowledge save returns to the library; withdrawn RAG is not selectable; Team create names unavailable members. Accounts visits read public RAG/Knowledge only (publisher edits); Members/Recent activity come from the group overview; members sort by name; Profile moves students only into existing groups and old-group work becomes inaccessible. Below 880px, sideways/upright/sideways within 6s opens the card room. Hidden published RAG fails as knowledge_generation_sources_unavailable. Soft-deleted Agent Knowledge Sets revive on the next authorized generate/publish. PRs #56/#58/#59/#60/#64.

## October14 independent revalidation and release

Oct14: Voice/Rebirth recovery, speech routing, nonvoice, Coding-A locks.
Speech models stay paused after Notice118434.

Voices upload help states sample rules; no side copy.

Knowledge partial promote skips `provider_asset_invalid` assets and still promotes a head when something applied (`prompt_v3`, `minItems:1`). Same published version + source manifest reuses the in-flight run. Teacher Chat shows generation progress; Agent Chat appends report links.

Formal micro-rounds need Guide `# Team Ruleset` → `## Formal assessment` naming `answer_recorder`, `question_guide`, `scorer`, `summarizer`, and `student_round_order` as roster display names. The order is exactly scorer and question_guide; anything else is `assessment_ruleset_incomplete` with no attempt. `answer_recorder` is that scorer: the write Tool, `已记录你的回答。` (receipt only), and the abandon recorder line. Explicit starts (正式测评/测试, 开始测试, 再来一轮/一遍, formal test/assessment) set the ledger first; that turn is Guide-only `收到，第一题是…`. Later messages follow `student_round_order` (the Tool runs before the Guide line). A non-answer is rejected once; the Guide restates it once. All answered: Guide `答题全部结束`, Summarizer `正在总结答案`. Abandon uses that order, then Guide `已放弃作答，你要重新开始吗，或者和我随便聊聊`, then the flag is false. `MAYA-ASSESSMENT-ROLE` does not pick speakers; `assessment_active` is a ledger flag. Ordinary chat (greetings too) asks the leader first, then each member, length by relevance; an empty reply is omitted, not a failure; an @-named member must reply. `## Informal` may change who replies and length. Precedence: ACL, ledger, Ruleset. Only the server appends report links. Later executor turns stay on that scorer and summarizer.

Built `f007a11` (PR #69), then `2c62871` (PRs #71/#72: the items above); backups `maya-20261014T111701Z`/`T135154Z.sqlite3` ok, schema0064, ready/public200.

October 16: Production can move to PostgreSQL (ADR-010) without rewriting `maya.sqlite3`. Postgres 16 stamped `0065_auth_login_admission`
accepted a read-only SQLite head import (111 tables, receipt). Compose runs `BACKEND_REPLICAS` backends
on it (`max_connections=200`). Sign-in DB overload returns
`auth_login_queued` (排队等待入列), not the outage copy.
Formal turns still use `chat_busy`. Real classroom load and the cutover are
not yet accepted.

October 15: New Team chats stay at revision 0, no canned opening. A course teacher lists formal attempts, phase and conversation id without entering a group; private Agents/Teams/RAG/voices still need Enter. Activity titles: Team, Knowledge, V1.n. Outside a live assessment the Guide says what to do next, occasionally offering 正式测评; a live assessment keeps scripted lines. `正在总结答案` is the last student-visible line: no closing `已记录你的回答。`; later executor turns (review line, failed summary, partial banner) stay off the student chat. The summary saves in the background (flat tool payload accepted); a stalled score/summary retries at 30 s/2/10 min and on the next message; chat stops waiting; the sheet shows `summary_not_saved`. A free answer is saved only if the model sets relevant true; else the server speaks that guidance without pasting the question. Choice/scale replies must match their letters or range. A shared Knowledge `## Opening` or `## 开场白` (else prose under the title before `## Questions`, not Concepts/Graph/Notes) is spoken before `收到，第一题是` on formal start or a restart at question 1. Rubrics/reference answers stay unspoken. Word-joiner replies stay off chat. After the attempt casual chat continues; assessment_action does not end the turn: the Guide answers, empty replies omitted, Scorer text (scores too) stays. A student send takes the lock from an executor turn with no model call yet; a running call still returns `chat_busy`.

October 17: One adaptive admission queue fronts login/create/write/LLM. Danger (load >=6 or Mem <500; clears at <=4 and >=550, or after 120 s at load <6) runs 2 slots, scoring first (Mem: 1 if idle); release ramps +1/5 s. Busy chat polls get a 5 s copy. AIMD: x0.7 on danger, load >=4, Mem <900, 30 s write/pool p95 >500 ms; hold at load 3-4, Mem 900-1100, threads >=90%; else +4/+2; starts/idles at 72. A 1 s brake (10 s write/pool p95, running writes, CPU) halves/clamps it. Refused sends (queue full, 180 s wait, chat_busy) store nothing. Chats send only via `messages:stream`. Per process: LLM/write/create 8, max 128, in-flight 48, 256 sync + 96 asyncio threads, pool 15+25; ready probe has its own limiter; nested calls get a fresh backstop wait; admission-refused Debate segments are not_sent; autoheal restarts a hung backend (~100 s).

October 17: Teacher Brainform Record (replaces Memory) lists assessment Teams, then each student's attempt, score, sheet and report; cached, one read per test (0068 index). Accounts/group visits drop Test results. Student Record: own answers only. Revoked/unfinished attempts show; teacher delete hides (0072). A Voice owner can Delete it in Studyform (Agents fall back). Studyform Voices opens with this sign-in's last list, then refreshes. System voices use `qwen3-tts-flash`; new clones enroll for `VOICE_CLONE_MODEL` (default `qwen-audio-3.1-tts-flash`, or 3.0) via `voice-enrollment` (temp upload). Retired `qwen3-tts-vc-2026-01-22` clones fall back. 40/60-student Postgres runs pass; queued creates hold no pooled connection; ledger: 6 commits per model call (was 9). Vote/barrage sequences (`0069`) use `UPDATE … RETURNING`; 40 concurrent submits stored 1–40; collisions retry.

October 18: A picked @mention adds a space; no All in the picker, but `@All`/bare sends reach everyone. Studyform/Brainform/Chat/Voices reads share one per-sign-in cache (6 at once, 10 s reuse, 429/503 back-off). Owner-only per-Chat Team `+` files (`0070`). Team access checks memoized per phase: 812→448 SELECTs/turn. Students use teachers' public Agents only in Teams; old chats read-only.
Oct19: uploaded Voices are ready at once (`0073`); ▷ only listens. A Team model call writes 12 rows (was 16).

## October20 review and release

Base `5dd9690bfa04c7a9d2a101bdb2abce7d01e3b85a`; integrated inputs:

- #225 `f2646b280663b8efc0a194b1c759cac70fd98c4e`
- #229 `566a798f0dd368a144d7a27317f407350936eb5a`
- #227 `bfe8187e8ed7cb77c3cebd2715f9a2a68b434500`
- #230 `a0f2954ceff73e46afeab249f8b6487bd29f1fa6`
- #232 `69d3218d98f920f3d99203492f660c22e2dc92c5`

Answer guard/edits; public Agent editors/audit; title fit; Record independent of Chat;
dead route cleanup. Fixed0076→0075; kept private-source/ownerless fences and editor tooltip.
Review fixes: old-answer edits keep frozen formats; guard state saves with answers
(25 guard +3 PostgreSQL write-count tests passed; ceilings unchanged).

Held#228: injected publish RuntimeError after durable draft parking leaves the owner's
draft superseded; no crash-recovery journal. New affected-agents routes also lack
implemented-route registration (fixture test fails). Dependent#231 held. #215 superseded
by#225; alternative#226 not implicitly selected. Draft#233/#97 and reimplemented
legacy UI#38–41 excluded.
Validation underway. Public-Agent role matrix:28 passed. Actions dispatch39449756136
never started (billing/spending limit).
SSH closes before key exchange:no production Git/data/container changes. Homepage200.
Production Postgres needs backup alongside requested SQLite backup/integrity check.
