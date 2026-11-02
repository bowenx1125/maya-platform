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
  it("names the files while collapsed and folds each excerpt on its own", () => {
    render(<CheckRag sources={sources} />);
    const summary = screen.getByText("Check RAG").closest("summary");
    expect(summary?.textContent).toContain("ethics-week-3.pdf");
    expect(summary?.textContent).toContain("seminar-notes.md");
    expect(
      screen.getByText("Courage is a habit.").closest("details"),
    ).toHaveProperty("open", false);

    fireEvent.click(screen.getByText("Check RAG"));
    fireEvent.click(screen.getAllByText("ethics-week-3.pdf").at(-1)!);
    expect(
      screen.getByText("Courage is a habit.").closest("details"),
    ).toHaveProperty("open", true);
    expect(
      screen.getByText("Practice makes it theirs.").closest("details"),
    ).toHaveProperty("open", false);
  });
});
