import { cleanup, render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it } from "vitest";

import type { AvatarConfig } from "../components/avatar";
import { AvatarBar } from "../components/stage2d/avatar-bar";
import { normalizeAvatarState } from "../components/stage2d/normalize-avatar-state";
import type { StageCharacter } from "../components/stage3d/scholar-stage";

afterEach(() => {
  cleanup();
  window.history.replaceState(null, "", "/");
});

const avatarConfig: AvatarConfig = {
  template_id: "wave1-default-head",
  material_theme: "demo",
  eye_color: null,
  default_expression: "neutral",
  expression_strength: "medium",
  motion_style: "calm",
};

function character(
  id: string,
  slot: StageCharacter["slot"],
  name: string,
  theme: AvatarConfig["material_theme"] = "demo",
): StageCharacter {
  return {
    id,
    slot,
    name,
    config: { ...avatarConfig, material_theme: theme },
  };
}

describe("normalizeAvatarState", () => {
  it("maps unknown tokens to idle", () => {
    expect(normalizeAvatarState("dance")).toBe("idle");
    expect(normalizeAvatarState(undefined)).toBe("idle");
    expect(normalizeAvatarState(null)).toBe("idle");
    expect(normalizeAvatarState(12)).toBe("idle");
  });

  it("keeps the frozen five states", () => {
    for (const state of [
      "idle",
      "listening",
      "speaking",
      "thinking",
      "nod_yes",
    ] as const) {
      expect(normalizeAvatarState(state)).toBe(state);
    }
  });
});

describe("AvatarBar", () => {
  it("renders data-state from visuals and collapses unknown to idle", () => {
    const roster = [
      character("a", "A", "Alice", "warm_sand"),
      character("b", "B", "Bob", "cool_slate"),
      character("c", "C", "Cara", "civic_olive"),
    ];
    const view = render(
      <AvatarBar
        characters={roster}
        speakingId="a"
        bubbleText="Hello arena"
        visuals={{
          a: "speaking",
          b: "thinking",
          c: "not-a-real-state" as never,
        }}
      />,
    );
    const root = view.container.querySelector("[data-avatar-bar]");
    expect(root).toBeTruthy();
    expect(root?.getAttribute("data-motion")).toBe("grok");
    expect(root?.getAttribute("data-intensity")).toBe("med");
    expect(view.container.querySelector("[data-avatar-bar-hud]")).toBeTruthy();
    expect(
      view.container.querySelector('[data-avatar-id="a"]')?.getAttribute(
        "data-state",
      ),
    ).toBe("speaking");
    expect(
      view.container.querySelector('[data-avatar-id="b"]')?.getAttribute(
        "data-state",
      ),
    ).toBe("thinking");
    expect(
      view.container.querySelector('[data-avatar-id="c"]')?.getAttribute(
        "data-state",
      ),
    ).toBe("idle");
    expect(view.container.querySelector("[data-avatar-waves]")).toBeTruthy();
    expect(view.container.querySelector("[data-avatar-think]")).toBeTruthy();
    expect(view.container.querySelector("[data-avatar-bar-bubble]")).toBeTruthy();
    expect(screen.getByText("Hello arena")).toBeTruthy();
  });

  it("exposes intensity via data-intensity (prop)", () => {
    const view = render(
      <AvatarBar
        characters={[character("a", "A", "Alice")]}
        intensity="high"
        visuals={{ a: "idle" }}
      />,
    );
    expect(
      view.container
        .querySelector("[data-avatar-bar]")
        ?.getAttribute("data-intensity"),
    ).toBe("high");
  });

  it("reads arenaIntensity from URL when prop omitted", () => {
    window.history.replaceState(null, "", "/?arenaIntensity=low");
    const view = render(
      <AvatarBar
        characters={[character("a", "A", "Alice")]}
        visuals={{ a: "listening" }}
      />,
    );
    expect(
      view.container
        .querySelector("[data-avatar-bar]")
        ?.getAttribute("data-intensity"),
    ).toBe("low");
  });

  it("switches speaking highlight across participants (data-state)", () => {
    const roster = [
      character("a", "A", "Alice"),
      character("b", "B", "Bob"),
    ];
    const view = render(
      <AvatarBar
        characters={roster}
        speakingId="a"
        visuals={{ a: "speaking", b: "listening" }}
      />,
    );
    expect(
      view.container.querySelector('[data-avatar-id="a"]')?.getAttribute(
        "data-current",
      ),
    ).toBe("true");
    expect(
      view.container.querySelector('[data-avatar-id="b"]')?.getAttribute(
        "data-state",
      ),
    ).toBe("listening");

    view.rerender(
      <AvatarBar
        characters={roster}
        speakingId="b"
        visuals={{ a: "idle", b: "speaking" }}
      />,
    );
    expect(
      view.container.querySelector('[data-avatar-id="b"]')?.getAttribute(
        "data-state",
      ),
    ).toBe("speaking");
    expect(
      view.container.querySelector('[data-avatar-id="b"]')?.getAttribute(
        "data-current",
      ),
    ).toBe("true");
    expect(
      view.container.querySelector('[data-avatar-id="a"]')?.getAttribute(
        "data-state",
      ),
    ).toBe("idle");
  });

  it("renders nod_yes as a single-shot state token", () => {
    const view = render(
      <AvatarBar
        characters={[character("a", "A", "Alice")]}
        visuals={{ a: "nod_yes" }}
      />,
    );
    expect(
      view.container.querySelector('[data-avatar-id="a"]')?.getAttribute(
        "data-state",
      ),
    ).toBe("nod_yes");
  });

  it("does not expose Next / audio controls (visual-only consumer)", () => {
    render(
      <AvatarBar
        characters={[character("a", "A", "Alice")]}
        visuals={{ a: "idle" }}
      />,
    );
    expect(screen.queryByRole("button", { name: /next|start|replay/i })).toBeNull();
    expect(screen.queryByLabelText(/audio/i)).toBeNull();
  });

  it("shows unavailable notice when asked (WebGL fallback path)", () => {
    render(
      <AvatarBar
        characters={[character("a", "A", "Alice")]}
        showUnavailableNotice
        unavailableLabel="3D unavailable"
        visuals={{ a: "listening" }}
      />,
    );
    expect(screen.getByRole("status").textContent).toContain("3D unavailable");
    expect(
      screen.getByText("Alice").closest("[data-state]")?.getAttribute(
        "data-state",
      ),
    ).toBe("listening");
  });

  it("CSS disables looping motion under prefers-reduced-motion", () => {
    const css = readFileSync(
      resolve(process.cwd(), "components/stage2d/avatar-bar.module.css"),
      "utf8",
    );
    expect(css).toContain("@media (prefers-reduced-motion: reduce)");
    expect(css).toMatch(/animation:\s*none\s*!important/);
    expect(css).toMatch(/transition:\s*none\s*!important/);
    // nod is single-shot (not infinite)
    expect(css).toMatch(
      /\.item\[data-state="nod_yes"\][\s\S]*?animation:\s*nod\s+[\d.]+ms\s+ease-in-out\s+1/,
    );
  });
});
