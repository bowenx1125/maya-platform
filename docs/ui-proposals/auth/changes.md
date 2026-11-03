# 38 · Sign-in and registration in Arcade (design only, nothing implemented)

The sign-in page (`/`: `app/page.tsx` with `LoginForm` and `RegisterForm`) is the
last page still in the old Academy look (cream, gold, serif). Every sheet is a real
frontend render using the app's fonts, mascots, U3 error bubble and copy.

## v3 (current): scheme 1 with the game beats of 2 and 3

User picked v2 scheme 1 and asked for the game-feel elements of schemes 2 and 3.
`v3/scheme-1-plus.png` (mockup `?s=4`) keeps scheme 1's sunburst, outlined pink
nameplate with stars, full-width lime stage, tilted taped form card, yellow
speech-bubble heading and step coins, and adds:

- from 2: the four character cards standing on the stage; the picked card lifts
  with a pink ring and arrow; all cards flip face down (pink dotted backs with the
  brand dot) while the password is typed; the picked card follows the
  registration step; a pink burst behind the form card;
- from 3: a white comic burst behind the nameplate; speed lines towards the form
  while typing; "!" over the picked card; on a failed sign-in the whole scene turns
  the grey-blue rain panel, the cards scatter and the mascots frown and sweat
  (plus the U3 bubble).

### Implemented

`app/page.tsx` + `components/academy/sign-in-stage.tsx`; the forms keep their
logic and are dressed by `.auth-arcade` in `app/globals.css`. Differences from the
mockup, all visible in `v3/approved-vs-impl.png`: the refusal rain lasts the
forms' existing 900 ms `refused` beat; the group list sits in the flow (Create
account stays below it, the list scrolls past five rows); the cast gets an
accurate label (`signInCastLabel`), since the cards flip rather than follow the
cursor.

> The v1 and v2 mockup images were removed on 2026-11-03 (superseded by v3);
> they are in git history.

## v2: bold, game-like, mascots react to the form

User feedback on v1: wanted more game feel, more youth and energy, bigger mascots
that react to what you type, a far bolder design; v1 scheme A was "OK" and is the
base of scheme 1.

| Sheet             | Scheme                                                                                                                                                                          |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `v2/overview.png` | Today's page next to the three schemes                                                                                                                                          |
| `v2/scheme-1.png` | Title Screen MAX: full sunburst, huge outlined pink "Mayaform" nameplate with stars, big mascots on a full-width lime stage, tilted taped form card, heading as a speech bubble |
| `v2/scheme-2.png` | Character Select: cyan stripes, four tall character cards fanned out, the picked card lifts with a pink ring and arrow, form panel with a yellow title bar                      |
| `v2/scheme-3.png` | Comic Pop: pink halftone page, a tilted comic panel with a burst title and the live (eye-tracking) mascots, form panel with a comic speech bubble                               |

Each scheme sheet shows the linkage (open, typing the username, typing the
password, sign-in failed), both registration steps at 1440, and three states at 390.

| Moment            | 1 · Title Screen MAX         | 2 · Character Select                  | 3 · Comic Pop                           |
| ----------------- | ---------------------------- | ------------------------------------- | --------------------------------------- |
| Typing username   | Mascots jump, lean in, "!"   | Picked card lifts, ring + arrow       | Speed lines, "!" over heads             |
| Typing password   | Mascots turn away, eyes shut | All cards flip face down (pink backs) | Eyes shut, "···"                        |
| Sign-in failed    | Shake, frown, sweat + U3     | Cards scatter, frown, sweat + U3      | Panel turns grey-blue rain + sweat + U3 |
| Registration step | Step coins ① ② + step text   | Picked card follows the step          | Step coins ① ② + step text              |

All three keep the copy word for word, the fields and flow, the existing mood
hooks (`attentive` / `discreet` / `refused`), the U3 error bubble and one pink
primary button, and use no large black blocks. Decorations (stars, bursts, "!",
"···", sweat, arrows, card backs) are aria-hidden. The brand dot replaces the old
ring emblem; it is the sidebar's mark.

## v1 (superseded)

`v1/`: A Title Screen, B Player Card, C Arcade Cabinet — judged too tame.

## Reproduce

`src/page.demo.tsx` is the v2/v3 mockup page (`?s=1|2|3` for v2, `?s=4` for v3). Apply `src/mascot-mood.patch` (a held
`mood` for `MascotFigure`, needed by schemes 1 and 2), copy the page to
`frontend/app/auth-proposals/page.demo.tsx`, run `next dev`, then
`SCHEMES=4 node src/shoot.js <out-dir>` (default `1,2,3`).
