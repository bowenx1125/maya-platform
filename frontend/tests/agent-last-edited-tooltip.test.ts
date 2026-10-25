import { describe, expect, it } from "vitest";
import { agentLastEditedTitle, formatVersionLabel } from "../lib/agent-tooltip";
import { tm } from "../lib/i18n";

const en = (k: "agentLastEditedTooltip", v?: Record<string, string>) =>
  tm(k, v ?? {});

describe("agentLastEditedTitle", () => {
  it("shows the latest version as V1.x and the latest editor", () => {
    const agent = {
      last_edited_by_name: "Kaikai",
      current_version_label: "V1.2",
    };
    expect(agentLastEditedTitle(en, agent)).toBe(
      "Latest version: V1.2 · Last edited by: Kaikai",
    );
  });

  it("names a teacher who edited a student's public Agent", () => {
    expect(
      agentLastEditedTitle(en, {
        last_edited_by_name: "Maya",
        current_version_label: "V1.3",
      }),
    ).toBe("Latest version: V1.3 · Last edited by: Maya");
  });

  it("names the student creator before anyone else edited", () => {
    // The server reports the creator as the latest editor until then.
    expect(
      agentLastEditedTitle(
        en,
        { last_edited_by_name: "Bowen", current_version_label: null },
        "1.0",
      ),
    ).toBe("Latest version: V1.0 · Last edited by: Bowen");
  });

  it("is absent only when no editor name is known", () => {
    expect(
      agentLastEditedTitle((k) => k, {
        last_edited_by_name: null,
        current_version_label: "V1.0",
      }),
    ).toBeUndefined();
  });
});

describe("formatVersionLabel", () => {
  it("keeps one decimal with a V prefix", () => {
    expect(formatVersionLabel("1.3")).toBe("V1.3");
    expect(formatVersionLabel("v2.0")).toBe("V2.0");
    expect(formatVersionLabel("V1.9")).toBe("V1.9");
  });
});
