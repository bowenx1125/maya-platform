import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({
    children,
    href,
    ...props
  }: {
    children: React.ReactNode;
    href: string;
  }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));
vi.mock("next/navigation", () => ({ usePathname: () => "/teacher/studyform" }));

import { VersionTile } from "../components/studyform-layout";

afterEach(() => cleanup());

describe("agent last-edited hover", () => {
  // The Studyform list card carries "Last edited by"; the home card omits it.
  it("keeps Last edited by on the card and does not attach a hover tip", () => {
    render(
      <VersionTile
        variant="list"
        name="Laozi"
        href="/teacher/agents/laozi"
        title="Last edited by: Maya"
        editedBy="Maya"
        label="V1.3"
        pending={false}
        visibility="public"
        deleteLabel="Delete Laozi"
      />,
    );
    const link = screen.getByRole("link", { name: "Laozi" });
    expect(link.getAttribute("title")).toBeNull();
    expect(link.getAttribute("data-ui-guide")).toBeNull();
    expect(link.getAttribute("data-ui-guide-text")).toBeNull();
    expect(screen.getByText("Last edited by: Maya")).toBeTruthy();
  });
});
