import { describe, expect, it } from "vitest";

import { localizeError } from "../lib/i18n";

describe("server busy / pressure errors", () => {
  for (const code of [
    "llm_admission_busy",
    "write_pressure",
    "host_memory_pressure",
    "create_admission_busy",
    "host_load_pressure",
    "adaptive_admission_busy",
  ]) {
    it(`${code} tells the student to retry and that input was kept`, () => {
      const error = { status: 503, code };
      const zh = localizeError(error, "zh");
      const en = localizeError(error, "en");
      expect(zh).toMatch(/稍后重试/);
      expect(zh).toMatch(/保留/);
      expect(en).toMatch(/try again/i);
      expect(en).toMatch(/kept/);
    });
  }

  it("busy codes say 人多 in zh", () => {
    expect(
      localizeError({ status: 503, code: "llm_admission_busy" }, "zh"),
    ).toContain("人多");
    expect(
      localizeError({ status: 503, code: "write_pressure" }, "zh"),
    ).toContain("人多");
    expect(
      localizeError({ status: 503, code: "create_admission_busy" }, "zh"),
    ).toContain("人多");
    expect(
      localizeError({ status: 503, code: "host_load_pressure" }, "zh"),
    ).toContain("人多");
    expect(
      localizeError({ status: 503, code: "adaptive_admission_busy" }, "zh"),
    ).toContain("人多");
  });
});
