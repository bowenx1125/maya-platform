import { describe, expect, it } from "vitest";
import { agentLastEditedTitle } from "../lib/agent-tooltip";
import { tm } from "../lib/i18n";

describe("agentLastEditedTitle", () => {
  it("formats zh and en tooltips with the version number", () => {
    const agent = {
      last_edited_by_name: "Kaikai",
      current_version_label: "V1.2",
    };
    expect(agentLastEditedTitle((k, v) => tm(k, v ?? {}, "zh"), agent)).toBe(
      "最新编辑：Kaikai，Version：1.2",
    );
    expect(agentLastEditedTitle((k, v) => tm(k, v ?? {}, "en"), agent)).toBe(
      "Last edited: Kaikai, Version: 1.2",
    );
  });
  it("is absent until someone edited", () => {
    expect(
      agentLastEditedTitle((k) => k, {
        last_edited_by_name: null,
        current_version_label: "1.0",
      }),
    ).toBeUndefined();
  });
});
