# Maya Platform Agent Rules

1. Read `Project.md` before changing the repository. It is the current operational authority; `AI文化互鉴教学平台-需求文档.md` and `docs/pre-code-contracts/` are historical/reference inputs.
2. Confirm the active Wave, Gate, file ownership, and acceptance criteria before implementation.
3. Do not copy source-code fragments from reference repositories. Implement from Maya contracts and tests.
4. This private team repository intentionally tracks only these private Demo assets:
   - `backend/config/demo-accounts/accounts.private.md`;
   - `backend/config/demo_users.yaml`.
5. Do not commit `.env`, API keys, session secrets, private input files, runtime databases, WAL/SHM files, generated debate audio, runtime snapshots, logs, locks, caches, archives, or output workbooks.
6. Demo passwords may exist in the two approved credential files, but passwords must never appear in browser DTOs, generated frontend clients, API responses, WebSocket events, logs, errors, screenshots, or public documentation.
7. Keep every automated test and CI job Mock-only unless a separate real-provider Gate is explicitly authorized. Never infer permission to spend provider quota from the presence of local credentials.
8. Work only in explicitly assigned files. Other agents may be working in parallel; do not reset, clean, overwrite, or reformat unrelated changes.
9. Avoid broad refactors of Wave 3 code before Full G2. Formatting or structural rewrites must not obscure functional diffs under review.
10. Run the assigned deterministic checks before reporting completion. Report exact commands and failures; do not reuse historical test counts as current evidence.
11. Luna implements and self-tests. Sol reviews high-risk design/code and coordinates Gate decisions. An implementation worker never approves its own Gate.
12. Update `Project.md`, `docs/PROJECT_STATUS.md`, and `开发文档.xlsx` when authoritative status, scope, risk, or next steps change.
13. Never describe Mock success, a narrow audit, or a previous commit's result as Full Wave 3 G2/G3 or real-provider acceptance.
