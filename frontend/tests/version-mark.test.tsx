import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({
    children,
    href,
    ...props
  }: {
    children: React.ReactNode;
    href: string;
    className?: string;
    "aria-label"?: string;
  }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

import { LocaleProvider } from "../components/locale";
import { VersionTile } from "../components/studyform-layout";

afterEach(() => cleanup());

describe("version mark", () => {
  it.each([
    ["public", "Public"],
    ["private", "Private"],
  ] as const)("says %s in words, not by colour alone", (visibility, word) => {
    render(
      <LocaleProvider initialLocale="en">
        <ul>
          <VersionTile
            name="Laozi"
            href="/student/agents/laozi"
            label="V1.0"
            pending={false}
            visibility={visibility}
            deleteLabel="Delete"
          />
        </ul>
      </LocaleProvider>,
    );
    const mark = screen.getByTitle(word);
    expect(mark.getAttribute("data-visibility")).toBe(visibility);
    expect(mark.textContent).toBe(`V1.0 · ${word}`);
  });

  it("opens from the name link and keeps Delete on the version bubble", () => {
    const onDelete = vi.fn();
    render(
      <LocaleProvider initialLocale="en">
        <ul>
          <VersionTile
            name="Laozi"
            href="/student/agents/laozi"
            label="V1.0"
            pending={false}
            visibility="private"
            deleteLabel="Delete Laozi"
            onDelete={onDelete}
          />
        </ul>
      </LocaleProvider>,
    );
    const open = screen.getByRole("link", { name: "Laozi" });
    expect(open.getAttribute("href")).toBe("/student/agents/laozi");
    expect(open.className).toContain("agent-tile-name");
    expect(open.className).toContain("text-link");
    fireEvent.click(screen.getByRole("button", { name: "Delete Laozi" }));
    expect(onDelete).toHaveBeenCalledTimes(1);
  });
});
