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
  }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));
vi.mock("next/navigation", () => ({ usePathname: () => "/teacher/studyform" }));

import { VersionTile } from "../components/studyform-layout";
import { UiGuideTooltip } from "../components/ui-guide-tooltip";

afterEach(() => cleanup());

describe("agent last-edited hover", () => {
  it("uses the immediate guide tooltip instead of a delayed title", () => {
    const text = "最新版本：V1.3 · 最新编辑：Maya";
    render(
      <>
        <UiGuideTooltip />
        <VersionTile
          name="Laozi"
          href="/teacher/agents/laozi"
          title={text}
          label="V1.3"
          pending={false}
          visibility="public"
          deleteLabel="Delete Laozi"
        />
      </>,
    );
    const link = screen.getByRole("link", { name: "Laozi" });
    expect(link.getAttribute("title")).toBeNull();
    expect(link.getAttribute("data-ui-guide")).toBe("agent.lastEdited");
    expect(link.getAttribute("data-ui-guide-text")).toBe(text);

    fireEvent.pointerOver(link, {
      pointerType: "mouse",
      clientX: 24,
      clientY: 32,
    });
    expect(screen.getByRole("tooltip").textContent).toBe(text);

    fireEvent.pointerOut(link, { relatedTarget: document.body });
    expect(screen.queryByRole("tooltip")).toBeNull();
  });
});
