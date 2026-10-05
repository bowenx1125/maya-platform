import {
  cleanup,
  fireEvent,
  render as renderComponent,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { buildMarkdownFile, MarkdownEditor } from "../components/knowledge";
import { AppShell } from "../components/app-shell";
vi.mock("next/navigation", () => ({
  useRouter: () => ({}),
  usePathname: () => "/student/groups/group/knowledge",
}));
vi.mock("../components/session-provider", () => ({ useSession: () => ({}) }));
function render(ui: Parameters<typeof renderComponent>[0]) {
  return renderComponent(<AppShell role="student">{ui}</AppShell>);
}

afterEach(cleanup);

describe("MarkdownEditor", () => {
  it("builds a Markdown File for a library create without selecting a draft", async () => {
    const onCreate = vi.fn().mockResolvedValue(undefined);
    render(<MarkdownEditor onCreate={onCreate} />);

    expect(
      (screen.getByRole("button", { name: "Done" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    fireEvent.change(screen.getByPlaceholderText("evidence.md"), {
      target: { value: "lesson.md" },
    });
    fireEvent.change(
      screen.getByRole("textbox", { name: /Markdown content/ }),
      {
        target: { value: "# Lesson\n\nShared evidence." },
      },
    );
    fireEvent.click(await screen.findByRole("button", { name: "Done" }));

    await waitFor(() => expect(onCreate).toHaveBeenCalledTimes(1));
    const file = onCreate.mock.calls[0][0] as File;
    expect(file.name).toBe("lesson.md");
    expect(file.type).toBe("text/markdown");
    expect(await file.text()).toContain("Shared evidence.");
    expect(screen.queryByRole("button", { name: "Add" })).toBeNull();
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
      expect(screen.getByRole("button", { name: "Done" })).toBeTruthy(),
    );
    fireEvent.change(
      screen.getByRole("textbox", { name: /Markdown content/ }),
      {
        target: { value: "# New\n\nReplacement" },
      },
    );
    fireEvent.click(screen.getByRole("button", { name: "Done" }));

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

  it("announces conversion and resets the parent mutation only for a changed file", async () => {
    let finishFirstImport!: () => void;
    const firstImport = new Promise<void>((resolve) => {
      finishFirstImport = resolve;
    });
    const onCreate = vi
      .fn()
      .mockReturnValueOnce(firstImport)
      .mockResolvedValue(undefined);
    const onChange = vi.fn();
    render(<MarkdownEditor onCreate={onCreate} onChange={onChange} />);

    const input = screen.getByLabelText("Import a file");
    const pdf = new File(["course text"], "slides.pdf", {
      type: "application/pdf",
    });
    fireEvent.change(input, { target: { files: [pdf] } });
    expect(
      await screen.findByText(
        "Uploading, converting to Markdown (including local OCR for scanned PDF pages), and indexing…",
      ),
    ).toBeTruthy();
    expect(onChange).toHaveBeenCalledTimes(1);
    finishFirstImport();
    await waitFor(() => expect(onCreate).toHaveBeenCalledTimes(1));

    fireEvent.change(input, { target: { files: [pdf] } });
    await waitFor(() => expect(onCreate).toHaveBeenCalledTimes(2));
    expect(onChange).toHaveBeenCalledTimes(1);

    const docx = new File(["course text"], "slides.docx", {
      type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    });
    fireEvent.change(input, { target: { files: [docx] } });
    await waitFor(() => expect(onCreate).toHaveBeenCalledTimes(3));
    expect(onChange).toHaveBeenCalledTimes(2);
    expect(
      screen.getByText(/Maya converts text to Markdown locally/i),
    ).toBeTruthy();
  });
});
