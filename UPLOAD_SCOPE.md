# Maya Platform private handoff scope

This repository is a private, review-only handoff snapshot requested for the
Maya Demo. It preserves the existing Maya Git history and includes the current
working tree, including uncommitted Wave 3 and playback changes.

Included by explicit request:

- `Project.md`, the original requirements document, contracts, gate packets,
  manual tests, historical `outputs/` and `archive/` artifacts, and the current
  development workbook;
- the local `.env`, `backend/config/demo-accounts/accounts.private.md`, and
  `backend/config/demo_users.yaml`;
- `data/` and `backend/data/`, including SQLite/WAL/SHM files, snapshots,
  Markdown knowledge files, generated audio, and local runtime history;
- `private-inputs/`, including the local voice sample used by the Demo.

Excluded from this Maya repository:

- unrelated reference or sibling projects: `RomanticSimulation`,
  `OpenMAIC-main`, `OpenAvatarChat-main`, `parallax-main`, `motion-engine-main`,
  `TalkingHead-main`, and `Document Validation Agent`;
- OS/editor metadata such as `.DS_Store`, dependency directories, build
  outputs, caches, and transient lock files.

The included credentials and personal audio are Demo-only material. Keep this
repository private and rotate any real supplier credential before sharing the
repository with anyone outside the intended review group.
