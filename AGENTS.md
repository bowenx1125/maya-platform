# Maya Platform Agent Rules

1. Read repository-root `PROJECT_STATUS.md`, then the current Issue/Task Packet and
   only the ADRs/contracts/code named by that packet. `PROJECT.md` is the authority
   index. Do not read `docs/worklog/` or `docs/archive/` unless the task explicitly
   needs historical evidence.
2. Work in the branch and independent worktree assigned to the Issue. Do not edit the
   main checkout, another Agent's worktree, or files outside explicit ownership.
3. Models, migrations, OpenAPI, WebSocket schemas, public configuration, generated
   clients and root status are main-window/integrator-owned unless the Task Packet
   assigns them explicitly.
4. Do not copy any source fragment from reference repositories. References are
   read-only inputs for interaction, architecture and test ideas. Implement from Maya
   contracts.
5. Keep the frontend provider-neutral. Supplier names, model IDs, external resource
   IDs, API keys, supplier URLs and private paths may not enter browser-facing DTOs.
6. Never create or commit a real `.env`, credentials, student audio, runtime data,
   databases, generated media, logs or private reference code. Use `.env.example` and
   isolated test/Mock inputs.
7. Every turn continues to receive the complete text of all predecessor turns. Do not
   replace history with summaries. Prompt work may remove duplicate serialization and
   reuse stable retrieval on a structure-only retry only when the active contract says
   so.
8. Run the assigned local deterministic checks before reporting completion. Debug and
   retest within the Gate until its criteria pass; never weaken a test or contract to
   make it green. Intermediate Wave 4 branches stay local. GitHub CI runs once on the
   complete final integration Pull Request, not on each worker/fix commit.
9. A worker cannot approve its own Gate. Sol audit is read-only, and final status
   belongs to the main window after the exact candidate/merge SHA is verified.
10. Do not edit `PROJECT.md`, `PROJECT_STATUS.md`, active Gate packets or shared
    contracts unless the Task Packet makes you their named owner.
