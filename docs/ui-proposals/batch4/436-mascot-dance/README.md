# 436 · Four mascots dance while music plays

Issue: https://github.com/bowenx1125/maya-platform/issues/436

## Current state

- Home hero shows four scholars (`scroll`, `wreath`, `tablet`, `wave`) with idle
  bob / wave-arm only (`AcademyMascots`).
- Workspace music is toggled by `MusicKey` (`data-music-key`, `data-music-state`,
  `data-playing`).
- Music on/off does not change mascot motion today.
- `prefers-reduced-motion` already disables academy animations.

Assets:

- Product crop: `assets/current-mascots-crop.png`
- Product home: `assets/current-student-home-1440.png`
- Idle preview: `assets/current-idle.png`, `assets/current-idle.gif`,
  `assets/current-idle.mp4`
- Interactive sheet: `animations.html`

## Options (pick one) — no copy changes

### A · Bounce Band

Staggered hop + squash/stretch on a ~0.55s beat. Energetic, readable on the lime
floor, closest to “they’re bouncing to the track”.

- Preview: `assets/option-a.gif` / `assets/option-a.mp4`
- Still: `assets/option-a-still.png`

### B · Groove Sway

Side-to-side lean + small lift on a ~0.7s groove. Softer than A; keeps faces
readable; fits the fresco scholar look.

- Preview: `assets/option-b.gif` / `assets/option-b.mp4`
- Still: `assets/option-b-still.png`

### C · Stomp Line

Alternating step squash (even/odd) on a stepped ~0.48s beat. Most “dance line”
feel; punchier silhouette changes.

- Preview: `assets/option-c.gif` / `assets/option-c.mp4`
- Still: `assets/option-c-still.png`

## Numbered change notes (all options)

1. Drive dance class from the same music-on signal as `useMusicOn("workspace")`
   (and stage channel if mascots appear there later).
2. When music stops, remove dance class; return to existing idle bob.
3. Under `prefers-reduced-motion: reduce`, never run dance keyframes (keep
   current still/idle policy).
4. No new labels, badges, or helper text on the hero.
5. Keep SecretDoor / scholar hit targets working; animation is transform-only on
   existing figures.
6. Shared CSS next to existing `.academy-jelly` rules; no new mascot assets
   required (reuse current SVGs).

## Reduced motion

All previews respect `prefers-reduced-motion`. Implementation must gate dance
the same way globals already gate `.academy-jelly`.
