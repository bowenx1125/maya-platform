# Current Manual Verification

This checklist verifies the local classroom Demo after deterministic checks and a
fresh Docker build. It does not establish learning effect, production readiness or
real-provider acceptance.

## Start

1. Follow the [current startup procedure](../validation/MAYAFORM_V14_STARTUP.md)
   for validation, SQLite backup and the scoped Docker rebuild.
2. Confirm `docker compose ps` shows healthy backend and frontend.
3. Open [localhost:8080](http://localhost:8080) and sign in as the teacher.

## Accounts and group access

- Create or use a student account and confirm case-insensitive duplicate usernames
  are rejected without changing the existing session.
- In **Accounts → Groups**, use **Enter** and confirm the visible scope follows
  the selected group. The actual teacher role and resource read/edit permissions
  remain separate; Enter does not grant access to student Private records or
  ownership of their sources. **Mayaform** returns to the teacher home.
- Confirm teacher group access survives a container restart.

## Agent workspace

- Ordinary pages use **New** at the list/empty state and **Back / Done** with the
  page/editor they act on. Preserve the existing sidebar actions for
  Brainform and General Chat: Brainform's left **New** creates only Markdown RAG.
  Chats retains its existing New, history, composer and Send interactions.
  Fullscreen Immerse, file pickers and Provider consent remain separately scoped.
- In Workspace, New creates an Agent. Opening an Agent shows its current version
  directly, without Info or a version chooser. New there creates the next version,
  or opens its existing draft instead of making a duplicate.
- Save authored Agent.md and authorized source selections using Done. No Persona
  or Capability approval is required. Explicit Create AI Knowledge uses its
  generation intent; ordinary Agent Done does not silently start generation.
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
- In an assessment recipe, send natural-language start, pause, continue, abandon,
  abandon-and-redo and submitted-record queries through ordinary Chats. No new
  assessment cards, status controls, dedicated input or Maya Team layout appears.

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

## Chat, maintenance configuration and Live

- In teacher and student **Chat**, choose an existing published Agent.
  Send two messages, inspect **Check RAG**, leave/reenter, and confirm the
  conversation and bound version survive. Another identity must not read it.
- Teacher Home has no Components, API Key editor, Check, Real/Mock selector or
  provider readiness badges, and opening it sends no configuration/check request.
  Preserve the existing guide, profile, Agents and other page actions. Provider
  configuration stays in the maintenance layer; exact data-call disclosure remains
  accessible where required. Removing controls must not change saved settings.
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
- Confirm **Delete** removes only the selected Debate and leaves independent Agents
  and knowledge documents intact.

## Record the boundary

Record the tested commit, browser, screen sizes, provider composition and any failed
step in `docs/PROJECT.md`. Never record credentials, private paths, provider response
bodies, student data or generated audio.
