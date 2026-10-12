# MayaForm v1.4 K3 evidence ledger

This record separates implemented Team behavior from work still in progress.
The latest v1.4 supplement governs Tool classes and Team privacy; older
single-target and no-Tool Custom Team descriptions do not.

## K3-A: Team definition and entry scaffold — PASS within scope

Commit `83de097` stores immutable Team versions, member and shared Knowledge
bindings, course publications, and per-member invoke grants. A Teacher's
personal Public Team for their own course enters the Maya Team directory in
the same transaction. Student Public Teams, Teacher Private Teams, and Teams
edited in a student Group do not. Current course, owner, Agent, raw Source,
Knowledge Set, and publication authorization is checked before invocation;
pure renames retain the old frozen grant, while permission changes revoke it.

`backend/tests/test_mayaform_teams.py` covers invalid membership, one Leader,
course and scope isolation, immutable versions, CAS/idempotency, publication
rollback, selected-target isolation, and raw Source/Set epoch revocation.
`backend/tests/test_cleanup_debate_runtime.py` verifies that Debate cleanup
preserves all six Team tables. The Chats New UI shows Agent, Team, and Maya Team
choices; Create/Update use the generated Team OpenAPI contract. Update omits
the create-only `group_id`, which the strict backend schema rejects.

The 19-file frozen Team R1 manifest passed an independent Sol review, including
a populated 0039→0040 migration, failure rollback, and 17 focused backend plus
37 focused frontend checks. An isolated A-only revision passed `pnpm check`
(backend suite, frontend 493 passed/1 skipped, contracts, migrations, route
surface) and `node scripts/check_repo_boundary.mjs --probe-generated` with an
absolute snapshot `PYTHONPATH`. No real Provider call or Docker rollout was
part of this acceptance.

The Team entry UI currently does not start a Team Chat. It remains visibly
disabled until the Conversation and runtime slices connect; it never falls
back to a single Agent Chat.

## Next acceptance boundaries

- K3-B: Team Conversation creation/read, owner-only Private and Teacher
  read-only Public projections; retain old Single Chat history and request
  reliability through populated 0041 migration.
- K3-C: durable per-member results and events, selected/all `@` routing,
  partial/unknown recovery, and late-result isolation through 0042.
- K3-D: Agno 3.0.11 public coordinate path, member Own + Team Shared retrieval,
  current-actor Tools, exact Provider disclosure/ledger and a real smoke.
- K3-E: browser creation and use of Team and Maya Team Chats, multi-target
  composer, member answers, IME/mobile and privacy evidence.

Passing a Fake model or migration test does not prove a real Provider response,
learning quality, or a successful production deployment.
