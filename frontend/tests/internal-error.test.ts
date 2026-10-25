import { describe, expect, it } from "vitest";

import { localizeError } from "../lib/i18n";
import { isBusyResponse } from "../lib/request-cache";

const SERVER_ERROR = "Something went wrong on the server. Please try again.";

describe("internal_error (unexpected server failure)", () => {
  it("names a server error instead of an unavailable platform capability", () => {
    const error = { status: 500, code: "internal_error" };
    expect(localizeError(error)).toBe(SERVER_ERROR);
    expect(localizeError(error)).not.toContain("platform capability");
  });

  it("maps a bare 500 without a known code to the server-error text", () => {
    expect(localizeError({ status: 500, code: "temporary_failure" })).toBe(
      SERVER_ERROR,
    );
    expect(localizeError({ status: 500 })).toBe(SERVER_ERROR);
  });

  it("keeps real provider outages and other 5xx as provider_unavailable", () => {
    expect(localizeError({ status: 503, code: "provider_unavailable" })).toBe(
      "A platform capability is temporarily unavailable.",
    );
    expect(localizeError({ status: 502 })).toBe(
      "A platform capability is temporarily unavailable.",
    );
  });

  it("leaves busy / pressure codes and their retry semantics alone", () => {
    expect(
      localizeError({ status: 503, code: "host_memory_pressure" }),
    ).toMatch(/try again/i);
    expect(isBusyResponse({ status: 503 })).toBe(true);
    expect(isBusyResponse({ status: 429 })).toBe(true);
    // A server bug is not load shedding, so it is not auto-retried as busy.
    expect(isBusyResponse({ status: 500 })).toBe(false);
  });
});
