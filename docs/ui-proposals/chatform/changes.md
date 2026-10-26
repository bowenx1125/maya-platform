# Chatform shared chat page — proposal round 1 (design only, nothing implemented)
Scope: ONE shared page (`/student/chat`, `/teacher/chat`, both sidebar items "Chat with Agent"/"Chat with Team" open it). No Agent/Team split, no route/logic/API change, no entry_kind.
Baseline: origin/ui/agents 114e4f04 (worktree /workspace/maya-chatform/chatform-design). Mock English data only.
Rules followed: DESIGN-RULES §0.1–0.3 (copy/testid/logic unchanged), §1.1 one primary (Send; New in header), §3 page actions in header not sidebar, §5 Chat = weakest game zone (white reading area, 2px border), Decisions: continuity first then most game-like; one control in one place; no invented copy; parts must be mixable; Agent card A + Teams card echo.

## Code verification (components/agent-chat.tsx 3584 lines, chats/chat-target-picker.tsx, chats/chat-attachments.tsx)
| State | Exists? | Code | Renders now | Copy / a11y / testid |
|---|---|---|---|---|
| 1 List (History + conversation) | YES | agent-chat.tsx ~2923–3580, `styles.layout` aside+section | History aside (rows: label button, date, pin, delete) + conversation (header title + kind chip, role=log, composer) | "History"; aside aria-label "History"; row aria-current=page; rename input aria-label "Chat name" (dbl-click/F2); "Pin chat"/"Unpin chat"; "Delete chat"; data-ui-guide chat.history/chat.pin/chat.delete; composer aria-label/placeholder "Message"; send aria-label "Send"/"Read-only"/"This Public Team Chat is read-only."; `data-testid="chat-attachment-input"` (only testid in Chatform) |
| 2 Create (pick Agent/Team) | YES (not a separate route; `?mode=new` / newChatRouteState) | ChatTargetPicker; PageAction back/done ~2875 | Two ModuleCards "Agents" / "Teams" with agent-tile buttons (aria-pressed, name + version pill, check mark); Back + Done (Done disabled until pick) | "Agents", "Teams", "No Agents yet.", "No Teams yet."; Back/Done PageAction names; createPicked → api.createConversation / createTeamConversation |
| 3 Empty (no chats) | PARTIAL: no dedicated empty page; same layout with placeholders | historyItems.length===0 → `historyEmpty`; !hasTarget → `blankHint` | Empty History box + blank conversation pane with hint | "No chats yet."; "Choose a chat from History, or press New to start one." |
| 4 New empty conversation | YES but no own UI: after Done it is just a conversation with 0 turns | closeNewEntry(true) after create | Header title (chat title or "New chat") + "Agent"/"Team" chip; empty log; composer | "New chat" (title fallback), kind chip "Agent"/"Team" |
| Error | YES | ErrorNotice (`error && !showConversation` top; transient inside log); `chatCheckStatus` button when request uncertain; DismissibleAlert brainformMemoryInvalid | U3 tray sticker beside mascot (current shot 5) + separate "Check status" button at page top | error strings come from ErrorNotice/i18n verbatim; "Check status"; "Scoring…"; "Recipients" menu (team @mention); "Resume" |
Loading: `<WorkspaceAction name="new" disabled/> + <LoadingCard/>`. Note: on ui/agents the New is still a sidebar WorkspaceAction (MayaUI is moving it to the header) — mockups show final state.
Team chat inside the same page differs only by data: team session (members + available, @mention Recipients menu, can_send/read_only, Resume, scoring notice); kind chip "Team".

Current-state PNGs: current/1-list, 1b-conversation, 2-create (1440), 3-empty, 4-new-empty-conv (1440), 5-error-send (*-1440/390[-fold].png). 390 for create/new-conv not captured (New is inside the mobile drawer).

## Scheme A · Banner Desk (echo Agents A1 / H2 banner)
1. Page header = H2 sunburst banner (#FFF1A8, 3px, 6px hard shadow) with "Chatform" (PageIntro title, already exists) + header actions top-right: New (primary pink), or Back/Done on create. Sidebar unchanged.
2. History = white card with tilted yellow tape title "History"; each row = 3px bordered row with mascot avatar (deterministic §8) + label + kind sticker (Agent white / Team #FDBA74 category) + date + pin (ghost icon) + delete (round × like Agent card A). Current row = pink + small shadow (selected state).
3. Conversation = white, 2px border (weak game zone); header: avatar + name on yellow tape + kind sticker; bubbles 2px border (user #FFE4EE, agent white with avatar).
4. Composer: 3px input, pink focus hard shadow; attachment = neutral icon button; Send = only primary 3D button.
5. Create: Agents/Teams cards reuse Agent card A (version tag + yellow name tape + sunburst portrait) and Teams card (member avatars); picked = pink outline + round check sticker. Back/Done header.
6. Empty: History shows "No chats yet." dashed slot; pane shows dashed sunburst mascot slot (aria-hidden) + existing hint.
7. New empty conversation: big sunburst portrait card of the Agent in the empty log (aria-hidden, no new copy).
8. Error: U3 chat-bubble sticker + mascot bottom-right; "Check status" moves INTO the sticker as its action (interaction change, needs approval) → never collapses; mobile in flow below panel.

## Scheme B · Keycap Cabinet (white cards + halftone + keycaps)
1. Header: "Chatform" as tilted white plate; actions right.
2. History: halftone-header card; rows separated by 2px dashed (Row-list rule §3); numbered keycaps 1–n (aria-hidden decoration); current row yellow.
3. Conversation header halftone strip + name keycap; agent bubbles no avatar (quietest).
4. Create: keycap tiles — picked tile is "pressed" (translateY 4px, yellow). Teams tiles same as A (Teams card).
5. Empty: three blank keycaps 1-2-3 (aria-hidden) + hint. New conversation: 3 dashed "typing slots" (aria-hidden).
6–8. Composer, error sticker as A.

## Scheme C · Character Select (HUD, echo Agents/Teams "select" feel, light theme kept)
1. Header: black HUD bar with yellow "Chatform", pink hard shadow.
2. History panel orange (#FDBA74 = Chatform category colour) with avatar slots; current = pink ring.
3. Conversation header = black "stage" strip with agent portrait cut-out and yellow name.
4. User bubbles yellow, agent bubbles white.
5. Create: character-select cards (black frame, portrait, name + version); picked = pink ring + "P1" sticker (decorative, aria-hidden — new decorative text, needs approval).
6. Empty: three greyed ghost portraits (aria-hidden) + hint. New conversation: agent on a big sunburst "spotlight" disc.
7–8. Composer/error as A.

Mixable parts: header (A banner / B plate / C HUD), history row style, create card style, empty art, new-conversation art.
Backend fields needed: none (avatar = deterministic mascot from existing avatar_config/id). Nothing for API-CHANGES.md.
Open questions: (1) Move "Check status" into the error sticker or keep separate? (2) On mobile, keep History above the conversation (current) or collapse it? (3) OK to add aria-hidden decoration (keycap numbers / P1)?
