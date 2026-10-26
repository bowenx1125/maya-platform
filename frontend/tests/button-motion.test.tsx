import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Button, PRESS_MOTION } from "../components/ui/button";
import { RoundX } from "../components/ui/error-kit";

describe("shared button motion (DESIGN-RULES L28, L44-49)", () => {
  it("gives the default Button the press motion and no soft shadow", () => {
    render(<Button>New</Button>);
    const cls = screen.getByRole("button", { name: "New" }).className;
    for (const c of PRESS_MOTION.split(" ")) expect(cls).toContain(c);
    expect(cls).not.toContain("shadow-[var(--shadow)]");
    expect(cls).not.toContain("transition-all");
  });

  it("keeps RoundX an icon button: no shadow, colour transition only", () => {
    render(<RoundX aria-label="Close" />);
    const cls = screen.getByRole("button", { name: "Close" }).className;
    expect(cls).not.toMatch(/shadow-\[/);
    expect(cls).toContain("transition-colors");
    expect(cls).toContain("border-2");
  });
});
