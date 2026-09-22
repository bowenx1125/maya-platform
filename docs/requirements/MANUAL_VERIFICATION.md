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

- Verify sidebar **New / Back / Done** appear in this order, only when available;
  no duplicate creation, return or submission button remains in the content.
  Chat has New/Send only; fullscreen Immerse retains its own controls. File pickers
  and explicit safety/consent dialogs remain separate.
- In Workspace, New creates an Agent. Opening an Agent shows its current version
  directly, without Info or a version chooser. New there creates the next version,
  or opens its existing draft instead of making a duplicate.
- Compile saves current edits before compiling. After Persona confirmation and
  indexed knowledge selection, Done saves changes and publishes only if the
  returned server revision passes all checks; success returns to Agent inspection.
- Back warns before discarding unsaved Agent edits. A revision conflict or failed
  request keeps the editor and local content; ambiguous retries keep request identity.
- Knowledge has one active editor; failed creation retains text, Back cancels,
  and changed content uses a new request identity. Voice Done requires file + consent.
- Debate Ruleset editing temporarily uses Back/Done for cancel/save; leaving it
  restores the debate's Back/Done. Saving rules must not create a Debate.
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

## Chat, Components and Live

- In teacher and student **Chat**, choose an existing published Agent.
  Send two messages, inspect **Check RAG**, leave/reenter, and confirm the
  conversation and bound version survive. Another identity must not read it.
- In **Components**, one **Check** skips Ready/deferred items and asks for the
  maximum paid requests before checking the rest; stop on the first failure.
  All-Ready Check makes no provider call. Mode changes invalidate only that item;
  key changes invalidate all. Changes require idle generation and current revision.
  A missing key opens the dialog without selecting Real. TTS/Voice stay **Deferred**.
- With two identities, enter teacher **Immerse**, then student **Live**. Verify the
  current speaker and speech follow **Next**, including late entry and manual
  reentry. The area below the scene shows all published speeches without Refresh.
  Students have no controller actions. Teacher exit closes Live;
  a lost teacher page expires within 20 seconds. Replaying saved content adds no
  generation requests.
- Check 375px and desktop: original Logo, neutral surfaces, login-page warm yellow,
  readable dark-on-yellow buttons, visible keyboard focus, no horizontal overflow,
  and equal fixed-size Immerse buttons on the far right with no backing board.
  **Transcript** toggles the separate sidebar with Public Debate, status and Check
  RAG; Escape closes it and returns focus. Login must remain unchanged.
- No separate sidebar brand header or visible main-page title; the original mark
  occupies the Mayaform navigation icon. Modules align at the top. Chat shows the
  selected Agent name once; Accounts rows retain only the
  username, group and Active/Inactive status alongside authorized actions.
- Real-time voice is deferred; text/3D checks do not establish microphone or TTS
  acceptance.

## Recovery and cleanup

- Confirm list entry/focus reads do not retry stalled work or regenerate reports;
  no Refresh button remains. Returning from a disclosure page rereads approvals
  without automatically sending a provider request.
- Confirm **Rebirth** preserves the first three rounds and removes only the final
  round, classroom interaction and report results.
- Confirm **Devocalize / Revocalize** preserve speech and evidence.
- Confirm **Destroy** removes only the selected Debate and leaves independent Agents
  and knowledge documents intact.

## Record the boundary

Record the tested commit, browser, screen sizes, provider composition and any failed
step in `docs/PROJECT.md`. Never record credentials, private paths, provider response
bodies, student data or generated audio.
