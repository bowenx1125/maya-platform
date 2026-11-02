# Chatform split — design only

Static mockups for a separate Agent chat create screen, a separate Team chat
create screen, a larger chat type size, and a clearer Check RAG. Nothing here
is wired into the app. Do not merge this branch and do not deploy it.

Open `index.html` beside this file. Screenshots of the same pages live outside
the repo. Example names, versions, and excerpts are labeled on each page.

## What the product does today

Chatform is one page, `frontend/components/agent-chat.tsx`, for both kinds of
chat. The sidebar already has two rows, "Chat with Agent" and "Chat with
Team", and both use the same `chatHref` in `frontend/components/app-shell.tsx`.
New (`?mode=new`) renders `frontend/components/chats/chat-target-picker.tsx`,
which puts Agents and Teams in two columns of one sticker board.

Chat copy is 14px in `.userMessage` and `.reply`, 15px in the composer, and
12px on Check RAG (`frontend/components/agent-chat.module.css`). An Agent turn
with `sources` shows a native `<details>`: "Check RAG · N", then each
`ChatSource` as a filename and an excerpt. `ChatSource` is only `chunk_id`,
`filename`, and `excerpt`. Team member results carry the same `sources` array,
and the team bubble does not render them.

Debate Check RAG (`frontend/components/evidence/segment-rag-inspector.tsx` and
`evidence-trace-inspector.tsx`) is a different, richer inspector. These
mockups stay on the chat source shape.

## A — Sticker split

Keep the arcade board and give each session type its own New page. Agent cards
show name, version label, Public/Private, and Available. Team cards add the
leader and member names. Chat text is 18px. Check RAG stays under the reply:
collapsed it already names the files; open, each file can show or hide its
excerpt.

Landing this is a mode on the existing picker plus the type and RAG styles.
Sidebar rows need distinct targets (`?kind=agent` and `?kind=team`, or two
routes) so New knows which board to open. No API change. The picker must
receive team members when it does not already; Maya teams have them, ordinary
team summaries may only have a count.

## B — Reading rows

Same two screens, drawn as a paper list instead of stickers: search, a
horizontal row, a radio. Chat text is 19px on an open column, history loses
the hard shadow, and Check RAG is a quote stack. Search filters the lists the
page already loaded.

Same files as A, with a larger stylesheet replacement limited to Chatform.
The yellow sidebar stays.

## C — Stage and drawer

Create is a poster of the selected Agent or Team beside a dark list. Chat
text is 20px. History shrinks to an avatar rail. Check RAG is a right-hand
drawer: a vertical tab when shut, filename plus excerpt when open. Orange
numbers in the reply are a proposal. They can be 1..n over `sources` without
a contract change. They are not evidence-trace spans; chat sources have no
character offsets. A real highlight inside the sentence would need a new
field.

This is the largest of the three: the create layout and the chat grid both
change, and team replies should grow the same RAG block because their
payload already includes sources.

## Files a real landing would touch

- `frontend/components/app-shell.tsx` — separate Agent and Team chat targets
- `frontend/components/agent-chat.tsx` — New route, message type, RAG markup; team results currently skip `sources`
- `frontend/components/chats/chat-target-picker.tsx` — two boards, or two components
- `frontend/components/agent-chat.module.css` — type scale and RAG
- `frontend/components/chatform-chrome.tsx` — only if the header chrome changes
- `frontend/lib/i18n.ts` — any new English labels
- `frontend/tests/team-chat.test.tsx`, `frontend/tests/workspace.test.tsx`, `frontend/tests/sidebar-lit.test.ts`

A and B are a Chatform-scoped CSS and picker change. C adds a new chat grid
and, only if sentence highlights are required, a contract change. None of
the three belong on `main` until one is chosen.
