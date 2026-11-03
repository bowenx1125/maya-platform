import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CheckRag } from "../components/chats/check-rag";

const sources = [
  {
    chunk_id: "chunk-1",
    filename: "ethics-week-3.pdf",
    excerpt: "Courage is a habit.",
  },
  {
    chunk_id: "chunk-2",
    filename: "seminar-notes.md",
    excerpt: "Practice makes it theirs.",
  },
];

describe("Check RAG", () => {
  // 2026-11-03: two clicks. Closed: "Check RAG" and the count only. First
  // click: the documents. Clicking a document: its text.
  it("shows only the count closed, then documents, then a document's text", () => {
    render(<CheckRag sources={sources} />);
    const outer = screen.getByText("Check RAG").closest("details")!;
    const summary = screen.getByText("Check RAG").closest("summary");
    expect(summary?.textContent).toBe("Check RAG2");
    expect(outer).toHaveProperty("open", false);
    expect(
      screen.getByText("Courage is a habit.").closest("details"),
    ).toHaveProperty("open", false);

    fireEvent.click(screen.getByText("Check RAG"));
    expect(outer).toHaveProperty("open", true);
    expect(
      screen.getByText("Courage is a habit.").closest("details"),
    ).toHaveProperty("open", false);
    fireEvent.click(screen.getByText("ethics-week-3.pdf"));
    expect(
      screen.getByText("Courage is a habit.").closest("details"),
    ).toHaveProperty("open", true);
    expect(
      screen.getByText("Practice makes it theirs.").closest("details"),
    ).toHaveProperty("open", false);
  });
});
