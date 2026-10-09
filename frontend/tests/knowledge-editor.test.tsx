import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  buildMarkdownFile,
  downloadKnowledgeMarkdown,
  KnowledgeFilenameField,
  KnowledgeMarkdownField,
} from "../components/knowledge";
import { LocaleProvider } from "../components/locale";

const originalCreateObjectURL = Object.getOwnPropertyDescriptor(
  URL,
  "createObjectURL",
);
const originalRevokeObjectURL = Object.getOwnPropertyDescriptor(
  URL,
  "revokeObjectURL",
);

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  if (originalCreateObjectURL) {
    Object.defineProperty(URL, "createObjectURL", originalCreateObjectURL);
  } else {
    Reflect.deleteProperty(URL, "createObjectURL");
  }
  if (originalRevokeObjectURL) {
    Object.defineProperty(URL, "revokeObjectURL", originalRevokeObjectURL);
  } else {
    Reflect.deleteProperty(URL, "revokeObjectURL");
  }
});

describe("shared Knowledge Markdown fields and file helpers", () => {
  it("keeps filename and body controls controlled for the Brainform full-page editor", () => {
    const onFilenameChange = vi.fn();
    const onMarkdownChange = vi.fn();
    render(
      <LocaleProvider initialLocale="en">
        <KnowledgeFilenameField
          value="lesson.md"
          describedBy="filename-help"
          onChange={onFilenameChange}
        />
        <KnowledgeMarkdownField
          value="# Lesson"
          rows={16}
          onChange={onMarkdownChange}
        />
      </LocaleProvider>,
    );

    const filename = screen.getByPlaceholderText("evidence.md");
    fireEvent.change(filename, { target: { value: "renamed.md" } });
    const markdown = screen.getByRole("textbox", { name: "Markdown content" });
    fireEvent.change(markdown, { target: { value: "# Updated lesson" } });

    expect(onFilenameChange).toHaveBeenCalledWith("renamed.md");
    expect(onMarkdownChange).toHaveBeenCalledWith("# Updated lesson");
    expect(filename.getAttribute("aria-describedby")).toBe("filename-help");
    expect(markdown.getAttribute("rows")).toBe("16");
  });

  it("builds a Markdown file without losing Unicode text", async () => {
    const file = buildMarkdownFile("文化.md", "# 课程\n\n保留原始资料。");
    expect(file.name).toBe("文化.md");
    expect(file.type).toBe("text/markdown");
    expect(await file.text()).toBe("# 课程\n\n保留原始资料。");
  });

  it("downloads the server-provided Markdown body using the canonical filename", () => {
    const createObjectURL = vi.fn(() => "blob:knowledge");
    const revokeObjectURL = vi.fn();
    Object.assign(URL, { createObjectURL, revokeObjectURL });
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(function (this: HTMLAnchorElement) {
        expect(this.download).toBe("lesson--Agent--V1.0.md");
        expect(this.href).toBe("blob:knowledge");
      });

    downloadKnowledgeMarkdown("# Canonical", "lesson--Agent--V1.0.md");

    expect(createObjectURL).toHaveBeenCalledWith(expect.any(Blob));
    expect(click).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:knowledge");
  });
});
