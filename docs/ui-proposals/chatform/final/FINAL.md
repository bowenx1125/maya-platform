# Chatform — FINAL draft (Scheme A + C empty/title mix)

Design only. No app code, routes, logic, copy, or testids change until approved for implementation.

## Locked decisions (user 2026-10-27)

1. **"Check status" lives inside the U3 error sticker** (mascot bubble). Because that notice has an action button, it **never auto-collapses**.
2. **Mobile: History stays above the conversation** (unchanged page flow).
3. Pure-decoration keycap numbers (B) and "P1" stickers (C) are allowed in those schemes; **final uses Scheme A**, so only what A needs. C’s empty-state art (and title-row silhouette) is borrowed below.

## Final mix

- **Base for ALL states:** Scheme A — Banner Desk (H2 sunburst banner, yellow History tape, pink current History row, A composer, A create picker).
- **Empty page + newly-created empty conversation:** borrow **C’s radial-burst large avatar** (character-on-radiant-disk) in the **right-hand chat window** only.
- **Conversation title row** (list view, newconv, error — anywhere the chat title appears): borrow **C’s peeking-avatar title strip** (avatar rising out of the header), restyled in **A light colors** — white strip, yellow tape title, light accents. **Do not** use C’s dark/black HUD stage.
- **Shell:** real B-final app-shell sidebar / mobile top bar (`../src/real-shell/`, sidebar **New** removed; New is a page header action).
- **No errfold** in the final set (decision 1).

## States rendered

| State | 1440 | 390 |
|---|---|---|
| list (open conversation) | `list-1440.png` | `list-390.png` |
| create (ChatTargetPicker) | `create-1440.png` | `create-390.png` |
| empty (no chats) | `empty-1440.png` | `empty-390.png` |
| newconv (newly-created empty conversation) | `newconv-1440.png` | `newconv-390.png` |
| error (expanded sticker, Check status inside) | `error-1440.png` | `error-390.png` |

Generator: `../src/gen-final.mjs`. Matching `.html` beside each PNG. Copy/a11y audit: `../audit/FINAL-RESULT.txt` → **0 missing**.

## Numbered changes vs current UI

1. **Page header:** H2 Banner Desk (“Chatform” on sunburst yellow) with page actions **New** / **Back**+**Done** (create). Shared Button motion (shadow 0 6px 0 → hover −2px → active translateY(6px)).
2. **Sidebar:** real B-final shell; **New / Back / Done leave the sidebar** (WorkspaceAction → page header). No route or nav change.
3. **History:** yellow tape title; current row pink; pin + delete keep existing a11y names; mobile History remains **above** the conversation.
4. **Conversation title row:** peeking avatar out of a **light** header strip + yellow tape title + Agent chip (C silhouette, A palette — not dark HUD).
5. **Empty chat panel** (empty + newconv): C radiant-disk character illustration; empty copy unchanged: “Choose a chat from History, or press New to start one.”
6. **Composer:** Message aria-label/placeholder; Attach a file button + title; hidden `data-testid="chat-attachment-input"`; Send.
7. **Create picker:** Agents / Teams columns (A cards); “No Teams yet.” kept in markup (hidden when list non-empty).
8. **Error (U3):** Kind sticker + mascot; message copy unchanged; **Check status** button **inside** the sticker; Dismiss; **never auto-collapses**.
9. **Mobile tray:** error sticker sits in page flow below the chat (not a floating overlay that covers History).

## Out of scope (unchanged)

Routes, `entry_kind`, Agent/Team page split, i18n strings, testids, business logic.
