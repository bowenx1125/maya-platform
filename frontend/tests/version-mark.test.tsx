import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({
    children,
    href,
  }: {
    children: React.ReactNode;
    href: string;
  }) => <a href={href}>{children}</a>,
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
});
