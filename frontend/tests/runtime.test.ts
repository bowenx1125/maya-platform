import { describe, expect, it } from "vitest";

import {
  classifyBackendFailure,
  classifyBackendResponse,
} from "../lib/runtime";

describe("runtime service probes", () => {
  it("treats an authenticated response as a reachable platform API", () => {
    expect(classifyBackendResponse(200).state).toBe("ready");
    expect(classifyBackendResponse(401).state).toBe("ready");
  });

  it("does not turn unexpected responses into a fake success", () => {
    expect(classifyBackendResponse(404)).toEqual({
      state: "unavailable",
      detail: "Platform API returned HTTP 404.",
    });
  });

  it("preserves a useful failure detail", () => {
    expect(classifyBackendFailure(new Error("connection refused"))).toEqual({
      state: "unavailable",
      detail: "connection refused",
    });
  });
});
