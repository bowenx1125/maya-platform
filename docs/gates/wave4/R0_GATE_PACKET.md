# Wave 4 R0 Documentation and Reproducibility Gate

Gate: `w4-r0-2026-08-30`

Status: `R0 PASS / READY FOR W4-G0 / PRODUCT CODE NOT AUTHORIZED BY THIS GATE / REAL CALLS 0`

Issue: `#5 W4-R0: canonical docs and reproducible development workflow`

## Goal

Protect the full Wave 3 checkpoint, establish one repository-root authority, remove
stale path assumptions, preserve the complete historical record outside default task
context, and restore a full-source private development branch with tests and CI.

## Non-goals

- no Agent/Persona/RAG/Prompt/Provider product implementation;
- no database migration or API/WebSocket change;
- no real Provider call;
- no rewrite of historical Wave Gate conclusions;
- no runtime data or private-input restoration.

## Invariants

1. `a235c29` remains recoverable from a verified local bundle and protected tag.
2. Runtime-only `2fd8078` remains recoverable from remote protection refs.
3. `PROJECT.md` is the only portable authority entry; it owns current
   facts; archive/worklog are excluded from default context.
4. Wave 3 G3 evidence and product semantics remain unchanged.
5. Tests, CI, migrations, contracts and Gate evidence remain in the development tree.
6. `.env`, accounts, audio, data, databases, logs and private references remain
   excluded.
7. Workers use Issues, branches and independent worktrees and never self-sign.

## Acceptance

- root `PROJECT.md` and `docs/ARCHITECTURE.md` are present and concise;
- exact old monolith is archived with a verified SHA-256;
- current authority contains no Pause/Continue, live-only Replay waiting, M13–M15
  pending, `53+13`, or completed-cleanup-as-next-step drift;
- active `AGENTS.md` and README use repository-root paths and minimal context;
- machine contracts remain under `contracts/`; historical pre-code contracts are
  explicitly marked baseline-only;
- document authority/link check runs locally and in CI;
- full existing deterministic suite passes on the candidate;
- private remote has a full-source PR/CI candidate and protected runtime handoff;
- independent Sol High returns `PASS / P0=0 / P1=0`;
- main window audits and signs the final merged SHA.

## Stop conditions

Stop R0 on content loss, hash mismatch, secret/runtime inclusion, rewritten historical
evidence, missing tests/contracts, ambiguous authority, a dirty source checkout, remote
ref mismatch or any product-code/provider change.

## G1.5 evidence

- authority/link/checksum check: `DOCUMENT_AUTHORITY_OK`;
- Prettier and `git diff --check`: PASS;
- OpenAPI parent/SHA/generated client/Redocly and 69-operation response checks: PASS;
- strict FastAPI route surface: `53 implemented / 0 later-wave placeholders`; all
  negative comparator fixtures passed;
- WebSocket events `30/18`, commands `6/7`, private results `5/6`, generated clean
  diff and Latin tables: PASS;
- repository/private credential/secret boundary probes: PASS over the full development
  source candidate;
- frontend ESLint, TypeScript, `28 files / 193 tests`, Next production build: PASS;
- backend Ruff format/check, mypy `109 source files`, `433` tests: PASS;
- bootstrap safety, 0001–0007 fresh/repeat/populated/downgrade/re-upgrade migration
  probes, historical fingerprints and foreign-key checks: PASS;
- Compose configuration: PASS;
- real Provider calls: `0`.

## G2 candidate evidence

- audited candidate: `3c07fe16de24833d4a903e0a78822ab0ff34f52f`;
- independent Sol High read-only audit: `PASS / P0=0 / P1=0 / P2=0`;
- private push CI run `33310837178`: PASS on the audited candidate;
- private PR CI run `33310839438`: PASS on the audited candidate;
- PR head, local branch head, both CI runs and the Sol audit referenced the same SHA;
- PR `#6` was mergeable when the candidate was signed;
- at G2, final R0 remained unsigned until the resulting `dev-main` merge SHA passed
  the same deterministic CI and the main window verified the integrated tree.

## Main-window integration evidence

- PR `#6` merged as `5a681f324e6b1ec034af8f8c021ee58889e053fb`;
- deterministic CI run `33311493356` on the exact `dev-main` merge SHA: PASS;
- guarded canonical-main update required the previously verified runtime-only SHA as
  its force-with-lease value;
- deterministic CI run `33311811470` on canonical `main` at the same SHA: PASS;
- remote `main` and `dev-main` both resolved to `5a681f3` after the update;
- runtime-only `2fd8078` remained protected by both branch and tag
  `runtime-handoff-20260830`;
- canonical local checkout fast-forwarded cleanly to `5a681f3` and tracks
  `origin/main`;
- parent `Project.md` matched the immutable Git archive checksum before it and the
  stale parent pre-code contracts were moved to the recoverable R0 backup;
- repository root `PROJECT.md` is now the single portable authority entry;
- main-window final audit: `R0 PASS / P0=0 / P1=0 / REAL CALLS 0`.
