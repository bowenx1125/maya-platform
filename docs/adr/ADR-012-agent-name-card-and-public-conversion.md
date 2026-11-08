# ADR-012: Agent name on its own card; Private can become Public

Status: ACCEPTED  
Date: 2026-11-08  
Decision: product owner

## Context

An Agent's name was rewritten from the first `# heading` of AGENT.md every
time the draft was saved or uploaded, so editing persona text could rename
the Agent. Private or Public was fixed at creation (`agent_visibility_locked`),
so moving a private Agent to the group meant rebuilding it by hand.

## Decision

1. **The name lives on the Name card.** The Agent editor shows a Name card
   (name and Private / Public) for existing Agents as well as new ones. Done
   saves a changed name through `PATCH /agents/{agent_id}` before it
   publishes. AGENT.md never renames the Agent; its first heading is plain
   content. The AGENT.md template no longer starts with `# {name}`.
2. **Private → Public, once, by the creator.** The same PATCH with
   `visibility: "public"` turns a private Agent public. It is meant to equal
   an identical public copy that replaces the private one:
   - its RAG files go public with it (the creator's private files bound to
     its draft or published version; their authorization epoch moves on);
   - its AGENT.md, Avatar and Voice stay;
   - its name moves to the public namespace (`Name-2` on a clash);
   - Done then publishes a new public version (the editor does this right
     after the switch).
     It is done in place, not as copy + delete, so chats, Teams and Debates
     that already use the Agent carry on.
3. **Public is final.** Asking for Private on a public Agent is **409**
   `agent_public_is_final`, which replaces `agent_visibility_locked`.
   Groupmates and teachers who may edit a public Agent still cannot change
   its visibility (**404** for them, as before).

## Consequences

- A RAG file shared by two of the creator's private Agents becomes public
  when one of them is made public.
- The structured Persona compiler (`compile_persona`, used by the demo
  baseline fixtures) still checks its H1 against the Agent name; live
  publishing does not run it.
