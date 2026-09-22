# Current Manual Verification

This checklist verifies the local classroom Demo after deterministic checks and a
fresh Docker build. It does not establish learning effect, production readiness or
real-provider acceptance.

## Start

1. Run `docker compose up -d --build --wait`.
2. Confirm `docker compose ps` shows healthy backend and frontend.
3. Open [localhost:8080](http://localhost:8080) and sign in as the teacher.

## Accounts and group access

- Create or use a student account and confirm case-insensitive duplicate usernames
  are rejected without changing the existing session.
- In **Accounts → Groups**, use **Enter** and confirm the teacher receives full group
  workspace CRUD under the teacher identity; **Homeward** returns to Accounts.
- Confirm teacher group access survives a container restart.

## Agent workspace

- Create an Agent, edit its Description in **Info → Edit**, compile and confirm its
  Persona, enable at least one indexed Markdown document and publish.
- Confirm drafts remain editable while published versions and snapshots remain
  immutable.
- Enroll a voice and confirm only the uploading student can list, preview, bind,
  confirm or delete that cloned voice.

## Four-round classroom

- Create a Debate with 2–5 published Agents, Topic, optional Background and the
  selected-language Markdown Ruleset.
- Confirm Preview prepares Opening, Discussion and Response, then **Immerse** opens
  the classroom stage.
- Use **Next / Back** and confirm audio, active speaker, jaw motion, speech bubble and
  Transcript stay synchronized. Audio failure must not hide the saved speech.
- Use **Interact**, submit a vote and barrage from the QR page, then confirm the
  Conclusion uses only eligible frozen classroom messages.
- Complete playback and confirm **Conclude** opens Evaluation and Report.

## Recovery and cleanup

- Confirm **Refresh** resumes recoverable failed or stalled work without duplicating
  accepted or acceptance-unknown provider operations.
- Confirm **Rebirth** preserves the first three rounds and removes only the final
  round, classroom interaction and report results.
- Confirm **Devocalize / Revocalize** preserve speech and evidence.
- Confirm **Destroy** removes only the selected Debate and leaves independent Agents
  and knowledge documents intact.

## Record the boundary

Record the tested commit, browser, screen sizes, provider composition and any failed
step in `docs/PROJECT.md`. Never record credentials, private paths, provider response
bodies, student data or generated audio.
