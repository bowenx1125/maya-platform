# 38 · Sign-in and registration in Arcade (design only, nothing implemented)

The sign-in page (`/`: `app/page.tsx` with `LoginForm` and `RegisterForm`) is the
last page still in the old Academy look (cream, gold, serif). Every sheet is a real
frontend render using the app's fonts, mascots, U3 error bubble and copy.

## v2 (current): bold, game-like, mascots react to the form

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

`src/page.demo.tsx` is the v2 mockup page. Apply `src/mascot-mood.patch` (a held
`mood` for `MascotFigure`, needed by schemes 1 and 2), copy the page to
`frontend/app/auth-proposals/page.demo.tsx`, run `next dev`, then
`node src/shoot.js <out-dir>`.
