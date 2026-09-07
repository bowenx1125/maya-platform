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

| Round       | Chinese non-whitespace characters including punctuation | English words |
| ----------- | ------------------------------------------------------- | ------------- |
| RAG Opening | 100–160                                                 | 65–100        |
| Discussion  | 80–140                                                  | 50–90         |
| Response    | 100–160                                                 | 65–100        |
| Conclusion  | 120–180                                                 | 75–115        |

Only displayed segment text counts. English counts alphanumeric runs with
internal apostrophes/hyphens as one word. Prompt and validator share these limits.
No truncation or padding rewrites provider text. Length, structure and reference
errors share one authorized repair with frozen input and explicit feedback.
One-call authorization cannot gain another call. Failed repairs retain diagnostics
and recoverable preparation state; unknown acceptance is never silently resent.

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

An unexpected task failure previously failed the revision/job but left its
aggregate generating. A sanitized live read found two generating aggregates
with zero generating revisions, alongside three ready reports. The fix updates
aggregate failure and reconciles orphan states at startup without another
Provider call, preserving valid in-progress jobs. The frontend independently
reads Report status, ignores stale responses and prevents a failed/hung revision
history read from masking success. Report remains a separate Conclude operation.

## Verification and delivery boundary

Stopped at the owner's **30% remaining quota boundary** with implementation
integrated but real acceptance incomplete:

- Frontend: 261 tests and typecheck passed; lint zero errors, four existing
  warnings. Backend Ruff and mypy (187 modules) passed after integration fixes.
- Initial full backend run: 62 failures, including obsolete two-round creation
  fixtures/schema-head assertions and new integration defects. The current-flow
  batch covered 84 cases; its one synthetic fixture mismatch was fixed and the
  focused recheck passed. The entire old backend suite is NOT green.
- Current checks cover length boundaries, routing, sequential context, targeted
  retrieval, memory/hash propagation, one repair cap, accepted recovery, shared
  sources, EN/ZH Mock lessons, audio retention and Report state correction.
- Real case 731791c9-7f85-46a3-b529-8c22a369a23e saved two opening speeches with
  four succeeded Provider operations, all attempt one. Round two failed before
  its LLM call: the no-retrieval phase still built an empty query manifest.
  This step is now removed and rebuilt. Resume of that failed record returned
  invalid_state. No completed speech was regenerated. Full real acceptance
  FAILED and remains outstanding; this was not a successful classroom test.
- The runner's initial empty Preview-plan race was corrected. Its first setup
  used an unreachable LAN origin; localhost transport with the configured
  Origin header reached the API without changing configuration.
- Docker is healthy at schema 0024. Two orphan Report aggregates now show failed,
  not endless generating; three prior ready reports remain ready.
- The task's database backup was deleted as requested. No backups, runtime
  records, credentials or raw provider responses are committed.

Next after explicit quota resumption: remove obsolete two-round/old-protocol
tests and write constraints while retaining effective authorization, integrity
and cost checks; fix recovery of the failed no-query-manifest case; complete one
four-round real lesson through barrages and Report. Latest UI request is pending:
Delete Voice/All failures must restore the row without explanations, like Resume.
Do not claim all requested work or classroom/content acceptance complete.

The owner now requests all implementation first, then one consolidated validation
batch and necessary failure fixes. Paid/browser tests are authorized but should
be limited to useful acceptance evidence, not repetitive expensive experiments.
The latest quota stop is **30% remaining**: finish the nearest atomic boundary,
push GitHub, restart Docker, inspect current status and report precise limitations.
No quota reset is authorized. The real-call results above are observed evidence;
the supplier billing console and operation ledger remain authoritative.

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
