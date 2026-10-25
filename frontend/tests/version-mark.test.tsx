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

import { VersionTile } from "../components/studyform-layout";

afterEach(() => cleanup());

describe("version mark", () => {
  it("opens from the card link, shows [V1.0 | Private] and deletes from the round ×", () => {
    const onDelete = vi.fn();
    render(
      <>
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
      </>,
    );
    const open = screen.getByRole("link", { name: "Laozi" });
    expect(open.getAttribute("href")).toBe("/student/agents/laozi");
    // PR0: the whole card is the link; the strip reads [V1.0 | Private].
    expect(open.textContent).toContain("V1.0");
    expect(open.textContent).toContain("Private");
    fireEvent.click(screen.getByRole("button", { name: "Delete Laozi" }));
    expect(onDelete).toHaveBeenCalledTimes(1);
  });
});
