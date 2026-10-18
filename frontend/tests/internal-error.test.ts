import { describe, expect, it } from "vitest";

import { localizeError } from "../lib/i18n";
import { isBusyResponse } from "../lib/request-cache";

describe("internal_error (unexpected server failure)", () => {
  it("names a server error instead of an unavailable platform capability", () => {
    const error = { status: 500, code: "internal_error" };
    expect(localizeError(error, "zh")).toBe("服务器出错，请稍后重试。");
    expect(localizeError(error, "en")).toBe(
      "Something went wrong on the server. Please try again.",
    );
    expect(localizeError(error, "zh")).not.toContain("平台能力");
  });

  it("maps a bare 500 without a known code to the server-error text", () => {
    expect(
      localizeError({ status: 500, code: "temporary_failure" }, "zh"),
    ).toBe("服务器出错，请稍后重试。");
    expect(localizeError({ status: 500 }, "en")).toBe(
      "Something went wrong on the server. Please try again.",
    );
  });

  it("keeps real provider outages and other 5xx as provider_unavailable", () => {
    expect(
      localizeError({ status: 503, code: "provider_unavailable" }, "zh"),
    ).toBe("平台能力暂时不可用。");
    expect(localizeError({ status: 502 }, "en")).toBe(
      "A platform capability is temporarily unavailable.",
    );
  });

  it("leaves busy / pressure codes and their retry semantics alone", () => {
    expect(
      localizeError({ status: 503, code: "host_memory_pressure" }, "zh"),
    ).toMatch(/稍后重试/);
    expect(isBusyResponse({ status: 503 })).toBe(true);
    expect(isBusyResponse({ status: 429 })).toBe(true);
    // A server bug is not load shedding, so it is not auto-retried as busy.
    expect(isBusyResponse({ status: 500 })).toBe(false);
  });
});
