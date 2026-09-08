import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useState } from "react";
import {
  RulesetEditor,
  type TeachingPrompts,
} from "../components/debate/setup/ruleset-editor";

afterEach(cleanup);

function Harness({ saved = vi.fn(), editing = vi.fn() } = {}) {
  const [prompts, setPrompts] = useState<TeachingPrompts>({
    zh: "# 中文规则\n\n**证据优先**",
    en: "# English rules\n\nAnswer directly.",
  });
  const [language, setLanguage] = useState<"zh" | "en">("zh");
  return (
    <RulesetEditor
      prompts={prompts}
      language={language}
      onLanguageChange={setLanguage}
      onSave={(value) => {
        setPrompts(value);
        saved(value);
      }}
      onEditingChange={editing}
    />
  );
}

describe("per-debate Markdown rules editor", () => {
  it("shows only the selected language and preserves edits across collapsed language switches", () => {
    const saved = vi.fn();
    const editing = vi.fn();
    render(<Harness saved={saved} editing={editing} />);
    expect(
      (screen.getByRole("button", { name: "Edit" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    expect(screen.queryByText("Prompt CN")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Details" }));
    expect(screen.getByRole("heading", { name: "中文规则" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "English rules" })).toBeNull();
    expect(
      (screen.getByRole("button", { name: "English" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    expect(screen.queryByText("Prompt CN")).toBeNull();
    expect(screen.queryByText("Prompt EN")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    expect(editing).toHaveBeenLastCalledWith(true);
    expect(
      (screen.getByRole("button", { name: "Details" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    fireEvent.change(screen.getByRole("textbox", { name: "中文规则" }), {
      target: { value: "# 本场新规则\n\n给一个例子。" },
    });
    expect(saved).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(editing).toHaveBeenLastCalledWith(false);
    expect(saved).toHaveBeenCalledWith({
      zh: "# 本场新规则\n\n给一个例子。",
      en: "# English rules\n\nAnswer directly.",
    });
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.getByRole("heading", { name: "本场新规则" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Details" }));
    expect(screen.queryByText("Prompt CN")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "English" }));
    fireEvent.click(screen.getByRole("button", { name: "Details" }));
    expect(screen.getByRole("heading", { name: "English rules" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "本场新规则" })).toBeNull();
    expect(
      (screen.getByRole("button", { name: "中文" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Details" }));
    fireEvent.click(screen.getByRole("button", { name: "中文" }));
    fireEvent.click(screen.getByRole("button", { name: "Details" }));
    expect(screen.getByRole("heading", { name: "本场新规则" })).toBeTruthy();
    expect(saved).toHaveBeenCalledTimes(1);
  });

  it("renders Markdown as text and formatting without executable HTML or script links", () => {
    const { container } = render(
      <RulesetEditor
        prompts={{
          zh: "<script>alert(1)</script>\n\n# 中文\n\n[Unsafe](javascript:alert%281%29)",
          en: "# English",
        }}
        language="zh"
        onLanguageChange={vi.fn()}
        onSave={vi.fn()}
        onEditingChange={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Details" }));
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector('a[href^="javascript:"]')).toBeNull();
    expect(screen.getByRole("heading", { name: "中文" })).toBeTruthy();
  });
});
