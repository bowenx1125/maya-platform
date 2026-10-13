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
  it("opens from the card body and keeps Delete on the version bubble", () => {
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
    expect(open.className).toContain("agent-tile-body");
    fireEvent.click(screen.getByRole("button", { name: "Delete Laozi" }));
    expect(onDelete).toHaveBeenCalledTimes(1);
  });
});
