import { describe, expect, it } from "vitest";

import { safeTeamsReturn, teamDraftKey } from "../lib/team-return";

describe("Create Agent ?return= from Teams", () => {
  it("accepts only Teams page paths", () => {
    expect(
      safeTeamsReturn("/student/teams?group_id=g1&mode=team-new"),
    ).toBe("/student/teams?group_id=g1&mode=team-new");
    expect(safeTeamsReturn("/teacher/teams")).toBe("/teacher/teams");
    for (const bad of [
      "https://evil.example/teacher/teams",
      "//evil.example",
      "/teacher/agents",
      "/teacher/teamsx",
      "/teacher/teams/../agents",
      "/teacher/teams?x=1//evil",
      "javascript:alert(1)",
      "",
      undefined,
    ])
      expect(safeTeamsReturn(bad)).toBeUndefined();
  });

  it("keys a draft by scope and Team", () => {
    expect(teamDraftKey("g1", null)).toBe("teamDraft:g1:new");
    expect(teamDraftKey("course", "team-1")).toBe("teamDraft:course:team-1");
  });
});
