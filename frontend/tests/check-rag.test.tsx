import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const chatTurnModelInput = vi.fn();
vi.mock("../components/session-provider", () => ({
  useSession: () => ({ api: { chatTurnModelInput } }),
}));

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

afterEach(cleanup);

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

  // 2026-11-05: Details sits under the documents and shows everything else
  // this reply sent to the model, loaded only when opened.
  it("shows Details last and loads the model input on open", async () => {
    chatTurnModelInput.mockResolvedValue({
      calls: [
        {
          speaker_name: "Nikola Tesla",
          system_prompt:
            "You are Nikola Tesla, the Agent defined by agent_markdown.",
          agent_md: "# Nikola Tesla",
          knowledge: null,
          attachments: "<chat_attachments>\nnotes\n</chat_attachments>",
          tools: [
            {
              name: "read_agent_memory",
              description: "Read saved notes.",
              parameters: "{}",
            },
          ],
          tool_messages: [],
        },
      ],
    });
    render(
      <CheckRag
        sources={sources}
        details={{ conversationId: "chat-1", turnId: "turn-1" }}
      />,
    );
    const outer = screen.getByText("Check RAG").closest("details")!;
    const children = Array.from(outer.children).map(
      (node) => node.querySelector(":scope > summary")?.textContent ?? "",
    );
    expect(children.slice(1)).toEqual([
      "ethics-week-3.pdf",
      "seminar-notes.md",
      "Details",
    ]);
    expect(chatTurnModelInput).not.toHaveBeenCalled();

    const details = screen.getByText("Details").closest("details")!;
    details.open = true;
    fireEvent(details, new Event("toggle"));
    expect(chatTurnModelInput).toHaveBeenCalledWith(
      "chat-1",
      "turn-1",
      undefined,
    );
    expect(await screen.findByText("System prompt")).toBeTruthy();
    expect(screen.getByText("AGENT.md")).toBeTruthy();
    expect(screen.getByText("Attachments")).toBeTruthy();
    expect(screen.getByText("Tools (1)")).toBeTruthy();
    expect(screen.queryByText("Knowledge")).toBeNull();
    expect(screen.getByText("# Nikola Tesla")).toBeTruthy();
  });

  it("opens with Details alone when a reply used no RAG", () => {
    render(
      <CheckRag
        sources={[]}
        details={{ conversationId: "chat-1", turnId: "turn-2", resultId: "r" }}
      />,
    );
    expect(screen.getByText("Check RAG").closest("summary")?.textContent).toBe(
      "Check RAG0",
    );
    expect(screen.getByText("Details")).toBeTruthy();
  });
});
