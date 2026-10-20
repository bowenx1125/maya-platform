import { describe, expect, it } from "vitest";

import { deleteConfirmText } from "../lib/affected-agents";

const affects = (names: string) => `会影响这些 Agent：${names}。`;

describe("deleteConfirmText", () => {
  it("lists affected Agents after the base text", async () => {
    const text = await deleteConfirmText(
      "删除 a.md？",
      async () => [
        { agent_id: "1", name: "Confucius" },
        { agent_id: "2", name: "Zhu Xi" },
      ],
      affects,
    );
    expect(text).toBe("删除 a.md？\n\n会影响这些 Agent：Confucius、Zhu Xi。");
  });

  it("keeps the plain text when nothing is affected or the lookup fails", async () => {
    expect(await deleteConfirmText("删除？", async () => [], affects)).toBe(
      "删除？",
    );
    expect(
      await deleteConfirmText(
        "删除？",
        async () => {
          throw new Error("offline");
        },
        affects,
      ),
    ).toBe("删除？");
  });
});
