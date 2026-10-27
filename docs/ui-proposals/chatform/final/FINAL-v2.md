# Chatform FINAL v2 — two empty/newconv variants

list / create / error / peeking title-row: **unchanged** from approved final (Scheme A + light peeking title + Check status in U3 sticker).

Only **empty** and **newconv** differ between the two variants (plus shared empty art).

## Shared fix (both variants)

| State       | Change                                                                                                                                                   |
| ----------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **empty**   | Replaced the single radiant-disk with **C’s ORIGINAL empty**: three grey ghost / character-select dashed slots (`scheme-C/empty-*.png`). Copy unchanged. |
| **newconv** | Radiant-disk kept, but **properly centered** in the chat panel (flex center above the composer). Light peeking title row kept.                           |

## How the two variants differ (newconv only)

|                   | **final-v2a**          | **final-v2b**                                                   |
| ----------------- | ---------------------- | --------------------------------------------------------------- |
| Disk size         | 192px (w-48)           | **Larger** 224px (w-56) + hard shadow                           |
| Vertical air      | Tight center           | **More air** (extra top/bottom margin)                          |
| Character on disk | Shared mascot (`M[0]`) | **Agent’s own avatar** (Socrates `M[1]` on peach sun `#F2B79A`) |
| Empty page        | Identical (C ghosts)   | Identical (C ghosts)                                            |

Pick one newconv treatment; empty is the same in both.

## Files

- `final/final-v2a/{empty,newconv}-{1440,390}.png` (+ approved list/create/error copies)
- `final/final-v2b/{empty,newconv}-{1440,390}.png` (+ approved list/create/error copies)
- Generators: `src/gen-final-v2a.mjs`, `src/gen-final-v2b.mjs`
- Audit: `audit/FINAL-v2-RESULT.txt` → 0 missing

Locked decisions from FINAL.md still apply (Check status in sticker / no auto-collapse; History above conversation on mobile; A base + C borrows as above).
