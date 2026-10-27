import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import {
  BUSY_MOTION,
  BUSY_MOTION_PRIMARY,
  Button,
  PRESS_MOTION,
} from "../components/ui/button";
import { RoundX } from "../components/ui/error-kit";

afterEach(cleanup);

describe("shared button motion (DESIGN-RULES L28, L44-49)", () => {
  it("gives the default Button the press motion and no soft shadow", () => {
    render(<Button>New</Button>);
    const cls = screen.getByRole("button", { name: "New" }).className;
    for (const c of PRESS_MOTION.split(" ")) expect(cls).toContain(c);
    expect(cls).not.toContain("shadow-[var(--shadow)]");
    expect(cls).not.toContain("transition-all");
  });

  it("gives the default Button the primary F busy fill treatment", () => {
    render(<Button>Create</Button>);
    const cls = screen.getByRole("button", { name: "Create" }).className;
    for (const c of BUSY_MOTION_PRIMARY.split(" ")) expect(cls).toContain(c);
  });

  it("gives the neutral Button the yellow F busy fill treatment", () => {
    render(<Button variant="neutral">Save</Button>);
    const cls = screen.getByRole("button", { name: "Save" }).className;
    for (const c of BUSY_MOTION.split(" ")) expect(cls).toContain(c);
  });

  it("sets aria-busy and disables when busy", () => {
    render(
      <Button busy aria-label="Done">
        Done
      </Button>,
    );
    const btn = screen.getByRole("button", { name: "Done" });
    expect(btn.getAttribute("aria-busy")).toBe("true");
    expect(btn).toHaveProperty("disabled", true);
  });

  it("keeps RoundX an icon button: no shadow, colour transition only", () => {
    render(<RoundX aria-label="Close" />);
    const cls = screen.getByRole("button", { name: "Close" }).className;
    expect(cls).not.toMatch(/shadow-\[/);
    expect(cls).toContain("transition-colors");
    expect(cls).toContain("border-2");
  });
});
