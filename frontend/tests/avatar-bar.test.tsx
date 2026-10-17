import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { AvatarConfig } from "../components/avatar";
import { AvatarBar } from "../components/stage2d/avatar-bar";
import { normalizeAvatarState } from "../components/stage2d/normalize-avatar-state";
import type { StageCharacter } from "../components/stage3d/scholar-stage";

afterEach(() => cleanup());

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
    expect(view.container.querySelector('[data-avatar-bar]')).toBeTruthy();
    expect(view.container.querySelector('[data-avatar-bar-hud]')).toBeTruthy();
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
});
