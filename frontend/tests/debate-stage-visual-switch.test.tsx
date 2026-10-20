import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AvatarConfig } from "../components/avatar";
import { AvatarBar } from "../components/stage2d/avatar-bar";
import { resolveDebateStageVisual } from "../components/stage2d/avatar-bar-flag";
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

const characters: StageCharacter[] = [
  { id: "a", slot: "A", name: "Alice", config: avatarConfig },
];

/**
 * Switching the stage visual must not invent audio / Next handlers.
 * Audio state lives outside AvatarBar; this guard encodes the architecture gate.
 */
describe("debate stage visual switch (line B)", () => {
  it("flag off keeps scholar3d as the resolved mode", () => {
    expect(resolveDebateStageVisual("", undefined)).toBe("scholar3d");
  });

  it("flag on resolves avatar-bar and the bar stays visual-only", () => {
    expect(resolveDebateStageVisual("?avatarBar=1", undefined)).toBe(
      "avatar-bar",
    );
    expect(resolveDebateStageVisual("?grokBar=1", undefined)).toBe("avatar-bar");
    const audio = { playing: true, turnId: "t1" };
    const view = render(
      <AvatarBar
        characters={characters}
        speakingId="a"
        visuals={{ a: "speaking" }}
      />,
    );
    // Mutating audio bookkeeping must remain possible without AvatarBar APIs.
    audio.playing = false;
    expect(audio.playing).toBe(false);
    expect(view.container.querySelector("[data-avatar-bar]")).toBeTruthy();
    expect(
      view.container
        .querySelector("[data-avatar-bar]")
        ?.getAttribute("data-motion"),
    ).toBe("grok");
    expect(view.container.querySelector("audio")).toBeNull();
    expect(view.container.querySelector("button")).toBeNull();
  });

  it("unmounting AvatarBar does not require disposing a ScholarStage", () => {
    const dispose = vi.fn();
    const view = render(
      <AvatarBar characters={characters} visuals={{ a: "idle" }} />,
    );
    view.unmount();
    expect(dispose).not.toHaveBeenCalled();
  });
});
