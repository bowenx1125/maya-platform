# Batch 4 · Design proposals only

Base: `main` @ `92592341b3006cb2032e8d59fabac5f2b52d9615`  
Live reference: https://app.mayaform.net  
Issues: [#434](https://github.com/bowenx1125/maya-platform/issues/434), [#436](https://github.com/bowenx1125/maya-platform/issues/436), [#437](https://github.com/bowenx1125/maya-platform/issues/437)

This batch is **proposal assets only** (mockups, animation previews, write-ups).
No product code, migrations, merges, or deploys.

| Package | Folder | Ask Xu Bowen to pick |
| --- | --- | --- |
| Debate tone + Preview | [`434-debate-tone/`](434-debate-tone/) | A / B / C |
| Mascot dance while music plays | [`436-mascot-dance/`](436-mascot-dance/) | A / B / C |
| Student sidebar Mayaform + music | [`437-student-sidebar/`](437-student-sidebar/) | A / B / C |

UI constraints held for every option: English only, neobrutalism, shared-component
direction, no new helper/`?` copy, existing behavior and test ids preserved unless
an option explicitly renames a visible label.

Reproduce stills/videos: `node docs/ui-proposals/batch4/shoot.mjs` (Chrome + ffmpeg).
Dance GIFs were also captured with Puppeteer frame dumps for clean motion.
