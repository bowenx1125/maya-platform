# 437 · Student sidebar: Mayaform + music match teacher capsule

Issue: https://github.com/bowenx1125/maya-platform/issues/437

## Current state

- Teacher desktop: `ClassSwitcher` capsule — Mayaform home + class segment
  (`data-testid="class-switcher-home"`, `class-switcher-trigger`).
- Student desktop: separate Mayaform `ITEM` key + floating `MusicKey`
  (`data-music-key="workspace"`, `data-music-state`, `data-playing`).
- Student has no class switcher; music is the control that should occupy the
  visual class-segment slot.

Assets:

- Product refs: `assets/current-student-home-product-1440.png`,
  `assets/teacher-home-product-1440.png`, sidebar crops
- Mock current: `assets/current-1440.png`, `assets/current-390.png`
- Teacher capsule reference: `assets/teacher-ref-1440.png`
- Interactive sheet: `mockups.html`

## Options (pick one)

### A · Capsule Twin

Exact teacher capsule chrome. Left: Mayaform (pink when lit). Right: music
segment (`music-stop` purple / `music-play` lime / `music-empty` grey) in the
class-switcher slot. Pixel note buddy inside the segment.

- `assets/option-a-1440.png`, `assets/option-a-390.png`

### B · Capsule Compact

Same capsule, but music segment is a fixed 44px note key (matches teacher class
trigger minimum). Brand side keeps flex room for “Mayaform”.

- `assets/option-b-1440.png`, `assets/option-b-390.png`

### C · Capsule Note-Face

Capsule with MusicKey face states inset in the segment (stop / play / empty),
including awake note face while playing. Strongest continuity with today’s
MusicKey personality, inside teacher geometry.

- `assets/option-c-1440.png`, `assets/option-c-390.png`

## Numbered change notes (all options)

1. Reuse `ClassSwitcher` capsule styles / shared press motion; do not invent a
   second brand control.
2. Student class-segment slot renders `MusicKey` (or MusicKey face) — **not** a
   class menu. Students still have no `class-switcher-trigger`.
3. Preserve: `data-music-key`, `data-music-state`, `data-playing`, aria
   play/pause/unavailable labels, collapsed `sidebar-music-notes`, toggle
   behavior, localStorage channel rules.
4. Preserve home lit/active treatment (pink capsule home when on Mayaform).
5. No new secondary text, descriptions, or `?` icons.
6. Mobile drawer may keep absolute MusicKey placement if capsule width is tight;
   desktop must match the approved capsule mockup.
7. Existing error copy and core navigation logic unchanged.

## What stays the same

- Teacher ClassSwitcher behavior and test ids.
- Music availability / empty state semantics.
- Nav groups, items, and page content below the header.
