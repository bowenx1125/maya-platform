import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PlatformApiError, type KnowledgeDocument } from "../lib/api";
import { LocaleProvider } from "../components/locale";
import { KnowledgeLibrary } from "../components/knowledge";

const useSessionMock = vi.hoisted(() => vi.fn());

vi.mock("../components/session-provider", () => ({
  useSession: useSessionMock,
}));

afterEach(() => {
  cleanup();
  useSessionMock.mockReset();
  vi.restoreAllMocks();
});

function documentFixture(
  overrides: Partial<KnowledgeDocument> = {},
): KnowledgeDocument {
  return {
    id: "document-id",
    group_id: "group-id",
    source_filename: "lesson.md",
    char_count: 24,
    content_hash: "a".repeat(64),
    index_revision: 1,
    index_status: "ready",
    workspace_state: "active",
    created_at: "2026-08-28T00:00:00Z",
    ...overrides,
  };
}

function renderLibrary(
  api: Record<string, unknown>,
  locale: "en" | "zh" = "en",
) {
  useSessionMock.mockReturnValue({ api });
  return render(
    <LocaleProvider initialLocale={locale}>
      <KnowledgeLibrary groupId="group-id" />
    </LocaleProvider>,
  );
}

describe("KnowledgeLibrary integration", () => {
  it("creates a reusable library document without an Agent target", async () => {
    const created = documentFixture({
      id: "new-document",
      source_filename: "shared.md",
    });
    const createLibraryKnowledge = vi.fn().mockResolvedValue({
      document: created,
      agent_version: null,
    });
    renderLibrary({
      knowledge: vi.fn().mockResolvedValue([]),
      createLibraryKnowledge,
      reindex: vi.fn(),
      hideKnowledge: vi.fn(),
      downloadKnowledge: vi.fn(),
    });

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /^Add$/ })).toBeTruthy(),
    );
    fireEvent.change(screen.getByPlaceholderText("evidence.md"), {
      target: { value: "shared.md" },
    });
    fireEvent.change(
      screen.getByRole("textbox", { name: "Markdown content" }),
      {
        target: { value: "# Shared evidence" },
      },
    );
    fireEvent.click(screen.getByRole("button", { name: /^Add$/ }));

    await waitFor(() =>
      expect(createLibraryKnowledge).toHaveBeenCalledTimes(1),
    );
    expect(createLibraryKnowledge.mock.calls[0][0]).toBe("group-id");
    const file = createLibraryKnowledge.mock.calls[0][1] as File;
    expect(file.name).toBe("shared.md");
    expect(file.type).toBe("text/markdown");
    await waitFor(() => expect(screen.getByText("shared.md")).toBeTruthy());
    expect(
      screen.getByRole("heading", {
        name: "New",
      }),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: /^Add$/ })).toBeTruthy();
  });

  it("downloads the original before editing and submits document CAS values", async () => {
    const source = documentFixture();
    const replacement = documentFixture({
      id: "replacement-id",
      source_filename: "updated.md",
      content_hash: "b".repeat(64),
      index_revision: 1,
    });
    const downloadKnowledge = vi.fn().mockResolvedValue({
      content: "# Original\n\nSource",
      filename: "lesson--Agent--V1.0.md",
    });
    const replaceKnowledgeDocument = vi.fn().mockResolvedValue(replacement);
    renderLibrary({
      knowledge: vi.fn().mockResolvedValue([source]),
      downloadKnowledge,
      replaceKnowledgeDocument,
      reindex: vi.fn(),
      hideKnowledge: vi.fn(),
    });

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Edit" })).toBeTruthy(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    const editContent = await waitFor(() => {
      const textboxes = screen.getAllByRole("textbox", {
        name: "Markdown content",
      });
      expect(textboxes).toHaveLength(2);
      expect(textboxes[1]).toHaveProperty("value", "# Original\n\nSource");
      return textboxes[1];
    });
    fireEvent.change(screen.getAllByPlaceholderText("evidence.md")[1], {
      target: { value: "updated.md" },
    });
    fireEvent.change(editContent, { target: { value: "# Updated" } });
    fireEvent.click(screen.getByRole("button", { name: /^Save$/ }));

    await waitFor(() =>
      expect(replaceKnowledgeDocument).toHaveBeenCalledTimes(1),
    );
    expect(downloadKnowledge).toHaveBeenCalledWith("document-id");
    const [id, file, hash, revision] = replaceKnowledgeDocument.mock.calls[0];
    expect(id).toBe("document-id");
    expect((file as File).name).toBe("updated.md");
    expect(hash).toBe("a".repeat(64));
    expect(revision).toBe(1);
    await waitFor(() => expect(screen.getByText("updated.md")).toBeTruthy());
  });

  it("refreshes the authoritative list after a replacement conflict", async () => {
    const source = documentFixture();
    const refreshed = documentFixture({
      id: "fresh-document",
      source_filename: "fresh.md",
    });
    const knowledge = vi
      .fn()
      .mockResolvedValueOnce([source])
      .mockResolvedValueOnce([refreshed]);
    const replaceKnowledgeDocument = vi
      .fn()
      .mockRejectedValue(
        new PlatformApiError(409, "stale", { code: "stale_revision" }),
      );
    renderLibrary({
      knowledge,
      downloadKnowledge: vi.fn().mockResolvedValue({
        content: "# Original",
        filename: "lesson--Agent--V1.0.md",
      }),
      replaceKnowledgeDocument,
      reindex: vi.fn(),
      hideKnowledge: vi.fn(),
    });

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Edit" })).toBeTruthy(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    await waitFor(() =>
      expect(screen.getByDisplayValue("# Original")).toBeTruthy(),
    );
    fireEvent.change(
      screen.getAllByRole("textbox", { name: "Markdown content" })[1],
      {
        target: { value: "# Changed" },
      },
    );
    fireEvent.click(screen.getByRole("button", { name: /^Save$/ }));

    await waitFor(() => expect(knowledge).toHaveBeenCalledTimes(2));
    expect(screen.getByText(/source changed elsewhere/i)).toBeTruthy();
    expect(screen.getByText("fresh.md")).toBeTruthy();
  });

  it("renders all editor copy through the selected locale and exposes failures", async () => {
    const createLibraryKnowledge = vi
      .fn()
      .mockRejectedValue(new Error("network failure"));
    renderLibrary(
      {
        knowledge: vi.fn().mockResolvedValue([]),
        createLibraryKnowledge,
        reindex: vi.fn(),
        hideKnowledge: vi.fn(),
        downloadKnowledge: vi.fn(),
      },
      "zh",
    );

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /添加到资料库/ })).toBeTruthy(),
    );
    expect(screen.queryByRole("button", { name: /^Add$/ })).toBeNull();
    fireEvent.change(screen.getByPlaceholderText("evidence.md"), {
      target: { value: "error.md" },
    });
    fireEvent.change(screen.getByRole("textbox", { name: "Markdown 内容" }), {
      target: { value: "# Error" },
    });
    fireEvent.click(screen.getByRole("button", { name: /添加到资料库/ }));
    await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
    expect(screen.getByRole("alert").textContent).toContain("network failure");
  });
});
