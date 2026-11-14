import { cleanup, render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { afterEach, expect, it, vi } from "vitest";

import { PageTransition } from "../components/page-transition";

const route = vi.hoisted(() => ({ pathname: "/classroom/one" }));
vi.mock("next/navigation", () => ({ usePathname: () => route.pathname }));
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

it("restarts only page-rise on pathname changes without replacing content or focus", () => {
  const rise = { animationName: "page-rise", cancel: vi.fn(), play: vi.fn() };
  const other = { animationName: "spin", cancel: vi.fn(), play: vi.fn() };
  Object.defineProperty(HTMLElement.prototype, "getAnimations", {
    configurable: true,
    value: vi.fn(() => [rise, other]),
  });
  route.pathname = "/classroom/one";
  const view = render(
    <PageTransition>
      <button>Content</button>
    </PageTransition>,
  );
  const button = screen.getByRole("button");
  expect(rise.play).not.toHaveBeenCalled();
  button.focus();
  const boundary = button.parentElement;
  expect(boundary?.className).toBe("page-transition");
  expect(boundary?.dataset.pageTransition).toBe("/classroom/one");
  route.pathname = "/classroom/two";
  view.rerender(
    <PageTransition>
      <button>Content</button>
    </PageTransition>,
  );
  expect(screen.getByRole("button")).toBe(button);
  expect(document.activeElement).toBe(button);
  expect(boundary?.dataset.pageTransition).toBe("/classroom/two");
  expect(rise.play).toHaveBeenCalledTimes(1);
  expect(other.play).not.toHaveBeenCalled();
  view.rerender(
    <PageTransition>
      <button>Content</button>
    </PageTransition>,
  );
  expect(rise.play).toHaveBeenCalledTimes(1);
  delete (HTMLElement.prototype as Partial<HTMLElement>).getAnimations;
});

it.each([
  "/teacher/agents",
  "/student/quiz",
  "/teacher/debates-beta/id/control",
])("leaves %s to its content boundary", (pathname) => {
  route.pathname = pathname;
  render(
    <PageTransition>
      <main>Content</main>
    </PageTransition>,
  );
  expect(screen.getByRole("main").parentElement?.className).not.toContain(
    "page-transition",
  );
});

it("keeps the original animation, stagger and reduced-motion override in one place", () => {
  const css = readFileSync(`${process.cwd()}/app/globals.css`, "utf8");
  expect(css).toContain("animation: page-rise 520ms var(--ease-out) both");
  expect(css).toMatch(
    /@media \(prefers-reduced-motion: reduce\)\s*\{\s*\.page-transition > :not\(\.mayaform-home\),[\s\S]*?animation: none/,
  );
  expect(css).toContain("animation-delay: 240ms");
  const old = readFileSync(
    `${process.cwd()}/components/workspace-theme.module.css`,
    "utf8",
  );
  expect(old).not.toContain("animation: page-rise");
});
