# Maya Platform

Maya is a local teaching platform: groups publish culture-focused Agents with
Persona and immutable Markdown knowledge; teachers run multi-Agent lessons,
collect classroom messages and conclude with an independent Report.
This file is the progress authority. [AGENTS.md](../AGENTS.md) defines repository
work; the user's latest explicit instruction overrides older plans.

## Approved four-round teaching flow — September 8, 2026

New debates have exactly four rounds and two to five Agents. The complete round
selector is removed. New snapshots record `teaching_protocol=four_round_v1`;
paragraph storage remains `segments_v2`. The owner waived historical playback
and recovery compatibility. Existing records are not silently regenerated/deleted.

1. RAG Opening: independent claim, own-KB evidence and its relevance. Culture is
   a perspective, not proof; acknowledge missing evidence.
2. Discussion: no new retrieval. Respond to specific earlier claims with their
   linked evidence. Ask a clear question of a cyclically assigned stable Agent
   ID. No moderator or question-planning model is added.
3. Response: prioritize round-two questions. Query the speaker's own knowledge
   with the actual question or challenged point. State retained, qualified or
   revised position and why. Save concise session memory in the same LLM output.
4. Conclusion: no new retrieval. Use history, shared evidence and session memory;
   name another Agent's point, explain agreement/criticism and learning. Freeze
   earlier barrages once; each Agent substantively answers one eligible message
   when available. No messages means no invented reply; disagreement may remain.

Preview saves exact text and Mock audio for rounds one through three; round four
is generated live. Opening is independent. Later turns see all successful prior
turns, including the same round, with complete previous-round barriers. Speaking
order rotates but identities/question targets stay stable. Scheduling, SQL Next,
input hashes and recovery use the same prefix. Completed results/accepted stages
are reused rather than charged again.

| Round       | Chinese upper guidance | English upper guidance |
| ----------- | ---------------------- | ---------------------- |
| RAG Opening | 160 characters         | 100 words              |
| Discussion  | 140 characters         | 90 words               |
| Response    | 160 characters         | 100 words              |
| Conclusion  | 180 characters         | 115 words              |

The owner's latest decision removes all backend speech-length validation and
all minimum lengths. These upper bounds appear in the actual System Prompt only.
Chinese guidance counts non-whitespace characters including punctuation; English
counts alphanumeric runs with internal apostrophes/hyphens as one word. Only
segment text counts. The backend neither rejects nor repairs a response because
of its length, and never truncates or pads it. Nonempty text, structure, source
references, question routing and state integrity remain enforced. Structure and
reference errors share at most one authorized repair with frozen input and
explicit feedback. One-call authorization cannot gain another call; unknown
acceptance is never silently resent.

Question routing is separate from barrage reply_to. Third-round memory contains
position/change/reason/influence/unresolved_question, never classroom speech/TTS,
Agent.md, published versions or knowledge. Round four and Report read it under a
separate session_discussion_memory outbound manifest class.

Cross-Agent source reuse requires an originating validated own-KB receipt in a
successful preceding turn of the same debate. Aliases deduplicate snapshot/chunk.
Migration 0024 removes only the obsolete speaker/snapshot FK, retaining turn
ownership, chunk/snapshot and unique constraints. direct +5, contextual +2 and
no_match +0 are evidence-support categories, not factual correctness scores.

Actual outbound prompts and synthetic I/O:
[FOUR_ROUND_PROMPTS.md](contracts/FOUR_ROUND_PROMPTS.md),
[four-round-example.json](contracts/four-round-example.json).
Content acceptance reviews actual answers, new points, evidence and reasoned
disagreement; string similarity and keyword counts are not hard failure gates.

## Report loading correction

The owner removed the blanket `https://` rejection from Report input checks.
Original bibliographic URLs and source prose now pass unchanged; there is no URL
omission projection. A real Report with these URLs completed successfully.
Unexpected task logs now record exception type rather than validation input bodies.

An unexpected task failure previously failed the revision/job but left its
aggregate generating. A sanitized live read found two generating aggregates
with zero generating revisions, alongside three ready reports. The fix updates
aggregate failure and reconciles orphan states at startup without another
Provider call, preserving valid in-progress jobs. The frontend independently
reads Report status, ignores stale responses and prevents a failed/hung revision
history read from masking success. Report remains a separate Conclude operation.

## Verification and delivery boundary — September 8 continuation

The four-round real case `a2e6b748-91d7-40ce-b1db-70525224bde1` completed
all eight speeches, retained audio, frozen classroom messages, final-round replies
and the HTTP/WebSocket playback sequence. Its six Preview turns took about 38s.
Eight Debate LLM operations and four query-Embedding operations succeeded on
attempt one. No completed speech was regenerated. Independent Report revision 3
is ready with original source URLs preserved. Two Report calls succeeded in total:
one tested an intermediate URL-omission projection, the second tested the final
owner-approved removal of the blanket URL check. The first failed revision never
reached the Report Provider. Supplier billing and the operation ledger are authoritative.

The browser showed all eight public speeches, two 3D figures, the speech bubble,
separate scrolling speech/control areas and Conclude. A retained-audio replay began
successfully; restarting Docker during replay exposed an existing recovery issue:
controls can remain disabled until an explicit release/reload. A complete eight-turn
browser audio replay has NOT been accepted. Report can now read the original frozen
final input after a completed lesson's replay is released; live generation still
requires the cancellation fence. Never treat replay's control generation as a reason
to regenerate the already frozen classroom messages.

Current checks:

- 63 focused backend generation/routing/recovery tests passed, including one real
  SQL accepted-stage recovery with a fake supplier proving one LLM call only.
- 26 focused Report tests passed, including source URL preservation, memory,
  orphan status reconciliation and completed-history/live-fence separation.
- Full frontend: 264 tests passed; typecheck passed; lint has zero errors and
  four existing warnings. Backend Ruff/mypy passed (187 modules); formatter
  checked 319 files. Backend/frontend Docker builds and health checks passed.
- Full backend suite still has 47 failing cases. Many depend on obsolete two-round
  creation or old protocol fixtures; others need investigation. Current-contract
  tests passing does not make that suite green. Only the shared recovery fixture
  needed by the current SQL test was migrated to explicit four-round Preview.
- Formatting, document-authority and repository secret/runtime boundaries passed.
  No database backups or runtime/provider payloads are added to Git.

Other observed cases are failures, not successful lessons:
`731791c9-7f85-46a3-b529-8c22a369a23e` has five of six Preview speeches saved;
its last response exhausted its two attempts on question/barrage routing errors.
The repaired Prompt now states only the current phase's metadata requirements,
with explicit null values and actionable repair feedback. Its ledger has four
succeeded query operations, five succeeded LLM operations and four failed LLM
operations. `34d0a285-c148-4a9e-8098-2b9891d963ae` reached seven speeches; its
last request has acceptance_unknown and was not resent. That incomplete test was
ended through the normal API. A Chinese case failed at 96/77 characters under the
old 100-character floor; no speech-length rejection remains in the paragraph path.

Remaining: migrate/remove obsolete tests while preserving current authorization,
cost, source and concurrency coverage; repair interrupted browser replay recovery;
review RAG teaching quality with topic-matched Persona/knowledge fixtures. The real
case above intentionally exposed mismatched relationship-psychology material for a
classroom-history topic: some answers correctly acknowledged the gap, one opening
followed the Persona's unrelated scenario, and later conclusions were repetitive.
This is functional run evidence, NOT evidence that RAG relevance, natural debate
quality, all requirements or a universal 100% success rate have been accepted.

Work is paused at the owner's explicit request after this atomic change; do not
start new development or paid tests until the owner resumes it.
The owner prefers consolidated validation and proportionate failure follow-ups.
Paid and browser tests are authorized. The quota stop boundary is removed; future
Chat GPT-6 continuation uses Bridge MCP and can continue until usage is exhausted.
No quota reset is authorized. The owner explicitly requested the external
`/Users/xubosmell/Desktop/Maya/HANDOFF.md` be overwritten with operational state
and parallel Luna Max ownership/integration instructions; no Codex access setup.

## Runtime and established UI

Next.js, FastAPI, SQLite/local files and Caddy share port 8080. Inspect active
SQLite only inside its container. Preserve private configuration, knowledge and
runtime data. TTS/Voice remain Mock; Debate LLM, Embedding and Report are configured
real DashScope adapters with independent authorization. Current Embedding is
text-embedding-v4, 1024 dimensions.

Teacher lists/creation use yellow rows on white paper. Delete Voice/All sit beside
Resume; Open Stage uses their action styling. Failed Resume preserves Stalled.
Stage titles are removed; speech scrolls above compact gold controls and bubbles
persist until Next. Open Message/Hide preserves its QR session. Conclude contains
Report and scores; Audio Ready indicates retained audio. This change adds only
fixed-four-round and phase-label UI work.

## Prior evidence and remaining work

The previous protocol baseline recorded 1,244 backend and 253 frontend checks
before later UI patches. One real two-Agent/two-round lesson completed with four
query, four LLM and one Report operations, all first attempt; a later real Report
also completed. That evidence does not validate this new four-round protocol.
Formal RAG experiments stopped at 31/72 and 21/72 on acceptance-unknown and were
not resent. Full RAG quality acceptance remains incomplete. Ledgers and private
artifacts/backups stay outside Git.

[NEXT_WAVE_PLAN.md](contracts/NEXT_WAVE_PLAN.md) remains history; this plan
supersedes conflicting old barriers, retrieval/round and length rules. The module
workbook uses DDL 9.10 and acceptance owner 徐伯闻. 古月 owns 3D/voice/TTS, Kaikai
owns accounts/student UI, 徐伯闻 owns remaining modules.

Production concurrency, classroom-scale load, public deployment, monitoring,
backup/restore, real speech and data/licensing governance remain outside this
local Demo scope. [ARCHITECTURE.md](ARCHITECTURE.md), [contracts](../contracts/)
and [ADRs](adr/) retain stable design references.
