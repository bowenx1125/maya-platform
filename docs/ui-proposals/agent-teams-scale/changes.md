# 37 · Agent card G nameplate + Teams scale — final-v2 (implemented)

Continues the 37 handoff (final v1 mockups, card width left open). `compare.png`
puts main, the handoff's final v1 mockup and this implementation side by side;
`detail.png` zooms into the cards. Both use real app screenshots at 1440×900
with the same mocked data.

## What final-v2 settles

| #   | Decision                                                                                                                                                             |
| --- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Card width stays the current four-column grid (1fr, about 228px at 1440), so the right edge sits at the banner's edge as it does today; v1 overshot it by about 50px |
| 2   | G look: tone head band with a white version chip and the name; Public/Private ribbon on the art; cream foot with a dashed top                                        |
| 3   | Studyform list foot: group (teachers) and `Last edited by`; home foot: group (teachers) or a plain sliver (students); home never shows Last edited                   |
| 4   | Teacher home cards now show Public/Private                                                                                                                           |
| 5   | Teams: three columns, same gaps and right edge as Agents; photo well 150px like the Agent art; the version tag stays                                                 |
| 6   | Teams empty reuses the Agents empty frame (user, 2026-10-27: align the two empty cards), replacing v1's vertical centring                                            |

Copy, test ids, accessible names and behaviour are unchanged. Teacher list group
names come from `PublishedAgentSummary.group_name`, or the course groups for
unpublished Agents. A student list with only shared Agents now shows `Last edited by`
too; the code had left it out on that path.
