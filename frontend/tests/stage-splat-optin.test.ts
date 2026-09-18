import { describe, expect, it } from "vitest";

import { splatBackdropRequested } from "../components/stage3d/scholar-stage";

describe("splatBackdropRequested", () => {
  it("is off by default and needs exactly splat=1", () => {
    expect(splatBackdropRequested()).toBe(false);
    for (const search of [
      "",
      "?splat=true",
      "?splat=0",
      "?SPLAT=1",
      "?splat=1&x=2",
    ]) {
      window.history.replaceState(null, "", `/${search}`);
      expect(splatBackdropRequested(), `search=${search}`).toBe(
        search === "?splat=1&x=2",
      );
    }
    window.history.replaceState(null, "", "/");
  });
});
