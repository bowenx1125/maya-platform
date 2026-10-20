import { describe, expect, it } from "vitest";

import { localizeError, t } from "../lib/i18n";

describe("deleting a RAG file a published Agent still uses", () => {
  it("explains why instead of a generic failure", () => {
    const error = {
      code: "document_in_use_by_published_agent",
      status: 409,
      details: { agent_names: ["Confucius"] },
    };
    expect(localizeError(error, "zh")).toContain("正被已发布的 Agent 使用");
    expect(localizeError(error, "en")).toContain("used by a published Agent");
  });

  it("no longer promises published Agents keep working after a hide", () => {
    expect(t("brainformRagHideConfirm", "en")).not.toContain(
      "remain available",
    );
    expect(t("brainformRagHideConfirm", "zh")).not.toContain("仍然可用");
  });
});
