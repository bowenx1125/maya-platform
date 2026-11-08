# MayaForm v1.4 supplement: S01–S22 reproduction map

> **Historical evidence, not current status.** This map was written for the
> `feat/mayaform-v14` resume revision (added in `f59df827` on 2026-10-05,
> last revised in `13c8c4bb` on 2026-10-09). "Current" below means current
> at that date. On 2026-11-08, 29 of the 30 test files named below still
> exist on `main`. `test_v14_migration_atomicity.py` (S22) does not, and the
> files that remain have changed since. The entries are coverage targets, not
> PASS claims, and none has been re-run as a set since. Current progress and acceptance are in [PROJECT](../PROJECT.md).

The current [Brainform contract](../contracts/MAYAFORM_V14_BRAINFORM_ASSESSMENT.md),
[UI contract](../contracts/MAYAFORM_FINAL_UI_POLISH_SPEC_V2.md) and
[Tool resource contract](../contracts/MAYAFORM_V14_TOOL_RESOURCE_AUTHORIZATION.md)
replace conflicting historical supplement clauses. The old four-tab UI,
manual-head preservation, permanent identical-input caching, absent Memory entry
and two-class Tool assumptions are not current requirements. Accepted K1/K2
history remains in its dedicated evidence records and Git history, not a second
active PASS table.

Actual current code/version and acceptance results are recorded in
[PROJECT](../PROJECT.md); the map below is reproducible coverage, not a claim
that a changed tree, browser or Provider workflow has already passed.

## Current resume reproduction map

The following files are the current reproducible entry points for S01–S22, with
conflicting historical semantics replaced by the latest BF/AT/RS and Tool contract.
These mappings are coverage targets, not same-version PASS claims. The final run
must bind tests, independent review and browser evidence to one frozen tree.
Backend paths below are relative to `backend/tests/`; frontend paths are relative
to `frontend/tests/`. Real Provider and browser observations remain separate.

| ID  | Current regression entry points and browser obligation                                                                                                                                                                        |
| --- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| S01 | `test_workspace.py`, `test_mayaform_team_turns.py`; `team-chat.test.tsx`, `chat-sse-stream.test.ts`. Browser full history, multi-@, unknown follow-up.                                                                        |
| S02 | `test_knowledge_generation.py`, `test_knowledge_generation_agno.py`, `test_runtime_tool_knowledge.py`; `agent-ai-knowledge-flow.test.tsx`. Browser explicit initial generation, ordinary Done unchanged.                      |
| S03 | `test_knowledge_generation_materialization.py`, `test_knowledge_generation_brainform.py`. Browser successful content immediately usable; failure retains prior content.                                                       |
| S04 | `test_knowledge_sets.py`, `test_knowledge_generation_brainform.py`; `brainform-workspace.test.tsx`. Browser canonical Markdown sections/Graph fallback, no asset-state labels.                                                |
| S05 | `test_knowledge_sets.py`; `brainform-workspace.test.tsx`. Browser single-click name edit without confirmation.                                                                                                                |
| S06 | `test_mayaform_assessment_attempts.py`. `test_mayaform_knowledge_attempt_invalidation.py`. Browser successful relevant Knowledge change notifies active/paused rounds and requires reanswer; completed versions remain fixed. |
| S07 | `test_knowledge_generation_brainform.py`, `test_mayaform_learning_evidence.py`. Current regeneration can overwrite manual current; immutable history and evidence remain.                                                     |
| S08 | `test_knowledge_generation_brainform.py`; `brainform-workspace.test.tsx`, `platform-brainform-api.test.ts`. Browser global/Agent same canonical object and ACL.                                                               |
| S09 | `test_team_context.py`, `test_team_sdk_bridge.py`. Actual runtime Own+Shared retrieval; private other-member materials excluded.                                                                                              |
| S10 | `test_knowledge_generation.py`, `test_knowledge_generation_brainform.py`. Repeated event/action idempotent; a later intentional manual generation may create a new generation.                                                |
| S11 | `test_runtime_builtin.py`, `test_runtime_tool_registry.py`. Public+Student versus Public+Teacher and current actor/resource authority.                                                                                        |
| S12 | `test_team_coordinate_runtime.py`, `test_mayaform_assessment_attempts.py`. Actual SDK delegation and explicitly editable synthetic practice resource; no teacher inheritance.                                                 |
| S13 | `test_team_assessment_projection.py`, `test_mayaform_assessment_attempts.py`. Private and Public formal participation; stable evaluator/summarizer grants, no hints.                                                          |
| S14 | `test_mayaform_team_conversations.py`; `team-chat.test.tsx`. Browser New Agent/Team/Maya Team and genuine send through one General Chat UI.                                                                                   |
| S15 | `test_mayaform_teams.py`. Browser own-course Teacher Public Team automatically appears in student Maya Team choices.                                                                                                          |
| S16 | `test_mayaform_team_conversations.py`, `test_mayaform_assessment_attempts.py`. Browser separate student sessions, original Private attempt reentry stays Private.                                                             |
| S17 | `test_runtime_builtin.py`, `test_mayaform_assessment_attempts.py`, `test_chat_withdrawal.py`. Browser teacher statistics exclude Private/ordinary Public and invalidate withdrawn evidence.                                   |
| S18 | `test_runtime_builtin.py`; `brainform-memory-assessment.test.tsx`. Browser Brainform Memory one-shot shortcut and Teacher Kaikai report/download in ordinary Chats; no Memory/Insights page.                                  |
| S19 | `test_runtime_tool_recovery.py`, `test_team_provider_stage.py`, `test_chat_withdrawal.py`. Actual saved receipts/recovery/late isolation; unknown never silently resent.                                                      |
| S20 | `test_workspace.py`, `test_team_coordinate_runtime.py`; `agent-ai-knowledge-flow.test.tsx`. Browser ordinary Agent/Team freedom, text-only and natural-language attempt actions only in assessment recipe.                    |
| S21 | `brainform-workspace.test.tsx`, `brainform-memory-assessment.test.tsx`, `ui-guide-tooltip.test.tsx`. Real mobile, keyboard, IME, identity change and ordinary Chat errors.                                                    |
| S22 | `test_v14_migration_atomicity.py`, contract/generated/route gates and latest startup procedure. Frozen full suite, independent review, populated backup migration, GitHub, scoped Docker and real Provider evidence.          |
