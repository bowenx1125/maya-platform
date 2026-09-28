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
import { AppShell } from "../components/app-shell";

vi.mock("next/navigation", () => ({
  useRouter: () => ({}),
  usePathname: () => "/student/groups/group-id/knowledge",
}));

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
    source_owner_role: "student",
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
  teacherReadOnly = false,
) {
  useSessionMock.mockReturnValue({ api });
  return render(
    <LocaleProvider initialLocale={locale}>
      <AppShell role="student">
        <KnowledgeLibrary
          groupId="group-id"
          teacherReadOnly={teacherReadOnly}
        />
      </AppShell>
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
      expect(
        screen.getByRole("button", { name: "New" }).hasAttribute("disabled"),
      ).toBe(false),
    );
    expect(screen.queryByRole("button", { name: /^Add$/ })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "New" }));
    fireEvent.change(screen.getByPlaceholderText("evidence.md"), {
      target: { value: "shared.md" },
    });
    fireEvent.change(
      screen.getByRole("textbox", { name: "Markdown content" }),
      {
        target: { value: "# Shared evidence" },
      },
    );
    fireEvent.click(await screen.findByRole("button", { name: "Done" }));

    await waitFor(() =>
      expect(createLibraryKnowledge).toHaveBeenCalledTimes(1),
    );
    expect(createLibraryKnowledge.mock.calls[0][0]).toBe("group-id");
    const file = createLibraryKnowledge.mock.calls[0][1] as File;
    expect(file.name).toBe("shared.md");
    expect(file.type).toBe("text/markdown");
    await waitFor(() => expect(screen.getByText("shared.md")).toBeTruthy());
    expect(screen.queryByRole("heading", { name: "New" })).toBeNull();
    expect(screen.queryByRole("button", { name: /^Add$/ })).toBeNull();
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "New" }).hasAttribute("disabled"),
      ).toBe(false),
    );
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
      expect(textboxes).toHaveLength(1);
      expect(textboxes[0]).toHaveProperty("value", "# Original\n\nSource");
      return textboxes[0];
    });
    fireEvent.change(screen.getByPlaceholderText("evidence.md"), {
      target: { value: "updated.md" },
    });
    fireEvent.change(editContent, { target: { value: "# Updated" } });
    fireEvent.click(await screen.findByRole("button", { name: "Done" }));

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

  it("keeps one editor active and gives changed content a new mutation identity", async () => {
    const createLibraryKnowledge = vi
      .fn()
      .mockRejectedValue(new TypeError("connection reset"));
    renderLibrary({
      knowledge: vi.fn().mockResolvedValue([documentFixture()]),
      createLibraryKnowledge,
    });
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "New" }).hasAttribute("disabled"),
      ).toBe(false),
    );
    fireEvent.click(await screen.findByRole("button", { name: "New" }));
    expect(screen.queryByRole("button", { name: "Edit" })).toBeNull();
    const editor = screen.getByRole("textbox", { name: "Markdown content" });
    fireEvent.change(editor, { target: { value: "# First" } });
    fireEvent.click(await screen.findByRole("button", { name: "Done" }));
    fireEvent.click(await screen.findByRole("button", { name: "Retry" }));
    await waitFor(() =>
      expect(createLibraryKnowledge).toHaveBeenCalledTimes(2),
    );
    const firstKey = createLibraryKnowledge.mock.calls[0][2].idempotency.key;
    expect(createLibraryKnowledge.mock.calls[1][2].idempotency.key).toBe(
      firstKey,
    );
    await screen.findByRole("button", { name: "Done" });
    fireEvent.change(editor, { target: { value: "# Changed" } });
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() =>
      expect(createLibraryKnowledge).toHaveBeenCalledTimes(3),
    );
    expect(createLibraryKnowledge.mock.calls[2][2].idempotency.key).not.toBe(
      firstKey,
    );
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
      screen.getByRole("textbox", { name: "Markdown content" }),
      {
        target: { value: "# Changed" },
      },
    );
    fireEvent.click(await screen.findByRole("button", { name: "Done" }));

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
      expect(
        screen.getByRole("button", { name: "New" }).hasAttribute("disabled"),
      ).toBe(false),
    );
    fireEvent.click(screen.getByRole("button", { name: "New" }));
    expect(screen.queryByRole("button", { name: /^Add$/ })).toBeNull();
    fireEvent.change(screen.getByPlaceholderText("evidence.md"), {
      target: { value: "error.md" },
    });
    fireEvent.change(screen.getByRole("textbox", { name: "Markdown 内容" }), {
      target: { value: "# Error" },
    });
    fireEvent.click(await screen.findByRole("button", { name: "Done" }));
    await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
    expect(screen.getByRole("alert").textContent).toContain("network failure");
    expect(
      screen.getByRole("textbox", { name: "Markdown 内容" }),
    ).toHaveProperty("value", "# Error");
    fireEvent.click(await screen.findByRole("button", { name: "Back" }));
    expect(screen.queryByRole("textbox", { name: "Markdown 内容" })).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(await screen.findByRole("button", { name: "New" })).toBeTruthy();
  });

  it("lets a teacher reindex failed courseware while keeping it read only", async () => {
    const reindex = vi.fn().mockResolvedValue({ id: "job-id" });
    const teacherDocument = documentFixture({
      source_owner_role: "teacher",
      index_status: "failed",
    });
    renderLibrary(
      {
        knowledge: vi.fn().mockResolvedValue([teacherDocument]),
        reindex,
        hideKnowledge: vi.fn(),
        downloadKnowledge: vi.fn(),
      },
      "en",
      true,
    );

    const reindexButton = await screen.findByRole("button", {
      name: "Reindex",
    });
    expect(screen.queryByRole("button", { name: "Edit" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
    fireEvent.click(reindexButton);
    await waitFor(() =>
      expect(reindex).toHaveBeenCalledWith("document-id", expect.anything()),
    );
  });
});
