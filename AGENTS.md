# Maya Platform Agent Rules

1. Before changing this repository, read `../Project.md` completely, including the embedded original requirements. Current implementation authority is `../Project.md` sections 0, 5 and 8 plus `../docs/pre-code-contracts/`.
2. Do not copy any source-code fragment from the reference repositories under `../`. References are read-only for design, interaction and test ideas. Implement from Maya contracts.
3. Work only inside the files explicitly assigned by the main agent. Other agents are working in the same checkout; do not revert, overwrite or reformat their changes.
4. Keep the frontend provider-neutral. No provider name, model ID, external voice ID, API key or supplier URL may enter browser-facing DTOs.
5. Do not create or commit real `.env`, credentials, student audio, private reference code or local data. Use `.env.example` and Mock providers.
6. Run the assigned deterministic checks before reporting completion. A worker cannot approve its own Gate; final status belongs to the main agent after Sol audit.
7. Do not edit `../Project.md` or the frozen pre-code contracts unless the main agent explicitly assigns that file.
