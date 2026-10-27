import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

describe("Avatar preview label layout", () => {
  it("wraps long preview names instead of hard single-line clipping", () => {
    const source = readFileSync(
      resolve(process.cwd(), "components/avatar/avatar-canvas.tsx"),
      "utf8",
    );
    expect(source).toContain("whitespace-normal");
    expect(source).toContain("[overflow-wrap:anywhere]");
    expect(source).toContain("line-clamp-2");
  });
});
