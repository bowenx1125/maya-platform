# Polish-3 (after #302)

Branch: `ui/polish-3` → PR to `main`. No deploy from this pass.

## User ask

Sidebar should match the preferred screenshot: **idle flat** (icon + bold
label only), not Logout-style white keys on every row. Keep roomier polish-2
spacing / ~240px / press motion. Active stays pink key. Logout + Meet Problems
stay key chrome. Idle gets hover + press (reveal key + lift / sink).

## What changed

`frontend/components/app-shell.tsx` only:

| Token            | polish-2                                                        | polish-3                                                                          |
| ---------------- | --------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| `ITEM_IDLE`      | `border-border bg-surface shadow-arc-s` + shared `PRESS_MOTION` | `border-transparent bg-transparent` + `FLAT_PRESS` (hover key + lift, press sink) |
| `ITEM_ACTIVE`    | `border-border bg-main shadow-arc-s`                            | `border-border bg-main` + `PRESS_MOTION`                                          |
| `ITEM_KEY` (new) | —                                                               | `border-border bg-surface` + `PRESS_MOTION` for Logout / Meet Problems            |
| Sizing / gaps    | `min-h-12`, `px-3 py-2`, `size-12`, `gap-1.5` / `gap-2.5`       | unchanged                                                                         |

Disabled Live row stays flat with no hover chrome.

## Gates

- `tsc --noEmit` green
- Prettier on touched files green
- vitest green (sidebar nav-chrome assertion added)

## Out of scope

Deploy (MayaBackend after user confirm). Studyform card / loading / login.
