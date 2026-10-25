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
      const message = localizeError({ status: 503, code });
      expect(message).toMatch(/try again/i);
      expect(message).toMatch(/kept/);
    });
  }
});
