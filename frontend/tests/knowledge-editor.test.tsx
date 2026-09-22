import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { buildMarkdownFile, MarkdownEditor } from "../components/knowledge";

afterEach(cleanup);

describe("MarkdownEditor", () => {
  it("builds a Markdown File for a library create without selecting a draft", async () => {
    const onCreate = vi.fn().mockResolvedValue(undefined);
    render(<MarkdownEditor onCreate={onCreate} />);

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /^Add$/ })).toBeTruthy(),
    );
    fireEvent.change(screen.getByPlaceholderText("evidence.md"), {
      target: { value: "lesson.md" },
    });
    fireEvent.change(
      screen.getByRole("textbox", { name: /Markdown content/ }),
      {
        target: { value: "# Lesson\n\nShared evidence." },
      },
    );
    fireEvent.click(screen.getByRole("button", { name: /^Add$/ }));

    await waitFor(() => expect(onCreate).toHaveBeenCalledTimes(1));
    const file = onCreate.mock.calls[0][0] as File;
    expect(file.name).toBe("lesson.md");
    expect(file.type).toBe("text/markdown");
    expect(await file.text()).toContain("Shared evidence.");
    expect(screen.getByRole("button", { name: "Add" })).toBeTruthy();
  });

  it("passes old document CAS values to the copy-on-write callback", async () => {
    const onReplace = vi.fn().mockResolvedValue(undefined);
    render(
      <MarkdownEditor
        document={{
          id: "old-document",
          source_filename: "old.md",
          char_count: 8,
          workspace_state: "active",
          index_status: "ready",
          content_hash: "a".repeat(64),
          index_revision: 3,
        }}
        initialContent="# New"
        onReplace={onReplace}
      />,
    );

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /^Save$/ })).toBeTruthy(),
    );
    fireEvent.change(
      screen.getByRole("textbox", { name: /Markdown content/ }),
      {
        target: { value: "# New\n\nReplacement" },
      },
    );
    fireEvent.click(screen.getByRole("button", { name: /^Save$/ }));

    await waitFor(() => expect(onReplace).toHaveBeenCalledTimes(1));
    const request = onReplace.mock.calls[0][0];
    expect(request.documentId).toBe("old-document");
    expect(request.expectedContentHash).toBe("a".repeat(64));
    expect(request.expectedIndexRevision).toBe(3);
    expect(request.file.name).toBe("old.md");
  });

  it("keeps the File helper provider-neutral", async () => {
    const file = buildMarkdownFile("文化.md", "# evidence");
    expect(file.name).toBe("文化.md");
    expect(await file.text()).toBe("# evidence");
  });
});
