import { describe, expect, it } from "vitest";

import { lastEditor } from "../components/knowledge/rag-album";
import type { KnowledgeDocument } from "../lib/api/platform";

const doc = (extra: Partial<KnowledgeDocument>) =>
  ({ id: "d1", source_filename: "a.md", ...extra }) as KnowledgeDocument;

describe("RAG card Last edited by", () => {
  it("prefers last_edited_by_username", () => {
    expect(
      lastEditor(doc({ last_edited_by_username: "li", owner_username: "xu" })),
    ).toBe("li");
  });
  it("falls back to owner_username", () => {
    expect(
      lastEditor(doc({ last_edited_by_username: null, owner_username: "xu" })),
    ).toBe("xu");
  });
  it("is empty when neither is set", () => {
    expect(lastEditor(doc({}))).toBeNull();
    expect(
      lastEditor(doc({ last_edited_by_username: null, owner_username: null })),
    ).toBeNull();
  });
});
