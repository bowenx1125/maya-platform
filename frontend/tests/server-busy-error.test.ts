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

// 2026-11-03: the AI service itself answered 429 or 503 at rush hour. The
// chat names it and asks the person to send again; nothing retries for them.
describe("AI service busy errors", () => {
  it("names a rate limit", () => {
    expect(localizeError({ status: 503, code: "provider_rate_limited" })).toBe(
      "The AI service is limiting requests right now. Wait a minute, then send again.",
    );
  });
  it("names a busy service", () => {
    expect(localizeError({ status: 503, code: "provider_busy" })).toBe(
      "The AI service is busy right now. Wait a moment, then send again.",
    );
  });
});
