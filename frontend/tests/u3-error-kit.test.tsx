import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DismissibleAlert } from "../components/dismissible-alert";
import { noticeTray } from "../components/notice-tray";
import { Notice } from "../components/ui";
import { KindSticker, TRANSIENT_FOLD_MS } from "../components/ui/error-kit";
import { UserAvatar } from "../components/user-avatar";
import { KnowledgeFilenameField } from "../components/knowledge/markdown-editor";
import { ErrorNotice } from "../components/ui";

function contrastOnWhite(hex: string) {
  const c = [1, 3, 5].map((i) => {
    const v = parseInt(hex.slice(i, i + 2), 16) / 255;
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  });
  const l = 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
  return 1.05 / (l + 0.05);
}

describe("U3 icon-by-kind errors", () => {
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    document.querySelector(".notice-tray")?.remove();
  });

  it("draws one sticker shape per kind, without adding text", () => {
    const { container } = render(
      <>
        <KindSticker kind="field" n={2} />
        <KindSticker kind="field" done />
        <KindSticker kind="file" />
        <KindSticker kind="chat" />
        <KindSticker kind="bell" />
        <KindSticker kind="server" />
      </>,
    );
    const kinds = Array.from(container.querySelectorAll("[data-sticker]"));
    expect(kinds.map((k) => k.getAttribute("data-sticker"))).toEqual([
      "field",
      "field",
      "file",
      "chat",
      "bell",
      "server",
    ]);
    expect(kinds[0].getAttribute("data-n")).toBe("2");
    expect(kinds[1].getAttribute("data-n")).toBe("✓");
    expect(container.textContent).toBe("");
    for (const k of kinds) expect(k.getAttribute("aria-hidden")).toBe("true");
  });

  it("starts a server error with the black ! sticker and a field error with its number", () => {
    render(
      <>
        <Notice tone="error">Server broke.</Notice>
        <Notice tone="error" badge={3}>
          Enter a topic.
        </Notice>
      </>,
    );
    const tray = document.querySelector(".notice-tray")!;
    const stickers = Array.from(tray.querySelectorAll("[data-sticker]"));
    expect(stickers.map((s) => s.getAttribute("data-sticker"))).toEqual([
      "server",
      "field",
    ]);
  });

  it("has no +N chip and shows only the newest bubble", () => {
    const tray = noticeTray();
    expect(tray.className).not.toContain("data-[more]");
    expect(tray.className).toContain("[&>.notice:has(~.notice)]:hidden");
    render(
      <>
        <Notice tone="error">Older</Notice>
        <Notice tone="error">Newer</Notice>
      </>,
    );
    expect(tray.hasAttribute("data-more")).toBe(false);
  });

  it("folds a transient error into the mascot ! after 6 s and reopens on click", () => {
    vi.useFakeTimers();
    render(
      <DismissibleAlert kind="chat" transient>
        Message rejected.
      </DismissibleAlert>,
    );
    const alert = screen.getByRole("alert");
    expect(alert.className).not.toContain("hidden");
    expect(document.querySelector("[data-mascot-badge]")).toBeNull();
    act(() => {
      vi.advanceTimersByTime(TRANSIENT_FOLD_MS);
    });
    expect(alert.className.split(" ")).toContain("hidden");
    const badge = screen.getByRole("button", { name: "Show the message" });
    expect(badge.textContent).toBe("!");
    fireEvent.click(badge);
    expect(alert.className.split(" ")).not.toContain("hidden");
    expect(document.querySelector("[data-mascot-badge]")).toBeNull();
  });

  it("keeps a non-transient error open", () => {
    vi.useFakeTimers();
    render(<Notice tone="error">Stays.</Notice>);
    act(() => {
      vi.advanceTimersByTime(TRANSIENT_FOLD_MS * 2);
    });
    expect(screen.getByRole("alert").className).not.toContain(" hidden");
    expect(document.querySelector("[data-mascot-badge]")).toBeNull();
  });

  it("gives letter avatars a background that passes WCAG AA for white", () => {
    for (const name of [
      "Li",
      "Wang",
      "Ana",
      "Bo",
      "Chen",
      "Dee",
      "Eve",
      "Fu",
    ]) {
      cleanup();
      render(<UserAvatar name={name} size="sm" />);
      const tile = document.querySelector<HTMLElement>(
        ".user-avatar-fallback",
      )!;
      const bg = tile.style.getPropertyValue("--avatar-body");
      expect(contrastOnWhite(bg)).toBeGreaterThanOrEqual(4.5);
    }
  });
});

describe("U3 file errors", () => {
  afterEach(cleanup);
  it("gives an upload refusal the file sticker without changing its text", () => {
    const error = Object.assign(new Error("too large"), {
      code: "attachment_too_large",
    });
    render(<ErrorNotice error={error} />);
    const line = screen.getByRole("alert");
    expect(line.querySelector('[data-sticker="file"]')).toBeTruthy();
    expect(line.querySelector('[data-sticker="server"]')).toBeNull();
  });
  it("puts the file sticker on the filename field only when asked", () => {
    const { rerender, container } = render(
      <KnowledgeFilenameField value="a.md" onChange={() => {}} />,
    );
    expect(container.querySelector('[data-sticker="file"]')).toBeNull();
    rerender(
      <KnowledgeFilenameField value="a.md" onChange={() => {}} fileError />,
    );
    expect(container.querySelector('[data-sticker="file"]')).toBeTruthy();
    expect(screen.getByRole("textbox").getAttribute("aria-invalid")).toBeNull();
  });
});
