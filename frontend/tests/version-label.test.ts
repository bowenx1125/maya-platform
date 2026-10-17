import { describe, expect, it } from "vitest";

import { teamVersionLabel, versionLabel } from "../components/studyform-layout";

describe("version labels", () => {
  it("reads the nth version as 1.0 + (n - 1) × 0.1 with one decimal", () => {
    expect(versionLabel(1)).toBe("V1.0");
    expect(versionLabel(2)).toBe("V1.1");
    expect(versionLabel(6)).toBe("V1.5");
    expect(versionLabel(10)).toBe("V1.9");
    expect(versionLabel(11)).toBe("V2.0");
    expect(versionLabel(12)).toBe("V2.1");
    expect(versionLabel(13)).toBe("V2.2");
    expect(versionLabel(101)).toBe("V11.0");
  });

  it("never reads below V1.0", () => {
    expect(versionLabel(0)).toBe("V1.0");
    expect(versionLabel(-3)).toBe("V1.0");
  });

  it("counts Team versions from version_seq 1", () => {
    expect(teamVersionLabel(1)).toBe("V1.0");
    expect(teamVersionLabel(11)).toBe("V2.0");
    expect(teamVersionLabel(12)).toBe("V2.1");
  });
});
