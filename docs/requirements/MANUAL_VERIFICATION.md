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

- Use the single sidebar **New** for the current page: Chat, Debate, Agent/version,
  knowledge or voice creation. It is disabled where no creation is available;
  no duplicate in-content New button remains. Creation forms support cancellation.
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
