import { cleanup, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AvatarState, AvatarConfig } from "../components/avatar";
import { ScholarScene } from "../components/stage3d/scholar-scene";
import type { StageCharacter } from "../components/stage3d/scholar-stage";

const stageMock = vi.hoisted(() => {
  type StageOptions = {
    canvas: HTMLCanvasElement;
    onReady?: () => void;
    onError?: (error: Error) => void;
    onAnchors?: (anchors: unknown[]) => void;
  };
  type StageInstance = {
    options: StageOptions;
    rosters: unknown[][];
    visuals: { id: string; state: string }[];
    resting: boolean[];
    disposed: boolean;
  };

  const instances: StageInstance[] = [];

  class MockScholarStage {
    readonly options: StageOptions;
    readonly rosters: unknown[][] = [];
    readonly visuals: { id: string; state: string }[] = [];
    readonly resting: boolean[] = [];
    disposed = false;

    constructor(options: StageOptions) {
      this.options = options;
      instances.push(this);
    }

    setCharacters(next: readonly unknown[]): void {
      this.rosters.push([...next]);
    }

    setVisual(id: string, state: string): void {
      this.visuals.push({ id, state });
    }

    setResting(value: boolean): void {
      this.resting.push(value);
    }

    dispose(): void {
      this.disposed = true;
    }
  }

  return { instances, MockScholarStage };
});

vi.mock("../components/stage3d/scholar-stage", () => ({
  ScholarStage: stageMock.MockScholarStage,
}));

afterEach(() => cleanup());

beforeEach(() => {
  stageMock.instances.length = 0;
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
): StageCharacter {
  return { id, slot, name, config: avatarConfig };
}

function renderScene(
  characters: StageCharacter[],
  visuals: Record<string, AvatarState>,
  resting = true,
) {
  return render(
    <ScholarScene
      characters={characters}
      loadingLabel="Loading"
      resting={resting}
      unavailableLabel="Unavailable"
      visuals={visuals}
    />,
  );
}

describe("ScholarScene asynchronous initialization", () => {
  it("passes the initial roster to a stage created after the effects run", async () => {
    const initial = [character("participant-a", "A", "River Keeper")];
    const view = renderScene(initial, { "participant-a": "idle" });

    await waitFor(() => expect(stageMock.instances).toHaveLength(1));
    const stage = stageMock.instances[0];
    expect(stage.rosters.at(-1)).toEqual(initial);
    expect(stage.resting.at(-1)).toBe(true);
    expect(
      view.container.querySelector("canvas")?.parentElement?.className,
    ).toContain("canvasViewport");

    stage.options.onReady?.();
    await waitFor(() =>
      expect(
        view.container.querySelector('[data-scene-status="ready"]'),
      ).toBeTruthy(),
    );
    expect(stage.rosters.at(-1)).toEqual(initial);
    expect(stage.visuals.at(-1)).toEqual({
      id: "participant-a",
      state: "idle",
    });
  });

  it("uses the latest roster and visual state when props change during loading", async () => {
    const initial = [character("participant-a", "A", "River Keeper")];
    const view = renderScene(initial, { "participant-a": "idle" });
    await waitFor(() => expect(stageMock.instances).toHaveLength(1));
    const stage = stageMock.instances[0];
    const latest = [
      character("participant-a", "A", "River Keeper"),
      character("participant-b", "B", "Market Steward"),
    ];

    view.rerender(
      <ScholarScene
        characters={latest}
        loadingLabel="Loading"
        resting={false}
        unavailableLabel="Unavailable"
        visuals={{ "participant-a": "speaking", "participant-b": "idle" }}
      />,
    );

    await waitFor(() => expect(stage.rosters.at(-1)).toEqual(latest));
    expect(stage.resting.at(-1)).toBe(false);
    stage.options.onReady?.();
    await waitFor(() =>
      expect(stage.visuals.at(-1)).toEqual({
        id: "participant-b",
        state: "idle",
      }),
    );
    expect(stage.visuals).toContainEqual({
      id: "participant-a",
      state: "speaking",
    });
    expect(stage.rosters.at(-1)).toEqual(latest);
  });

  it("disposes the stage and ignores a late ready callback after unmount", async () => {
    const view = renderScene(
      [character("participant-a", "A", "River Keeper")],
      { "participant-a": "idle" },
    );
    await waitFor(() => expect(stageMock.instances).toHaveLength(1));
    const stage = stageMock.instances[0];
    const rosterCount = stage.rosters.length;

    view.unmount();
    expect(stage.disposed).toBe(true);
    stage.options.onReady?.();
    expect(stage.rosters).toHaveLength(rosterCount);
  });
});
