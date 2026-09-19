import { cleanup, fireEvent, render, waitFor } from "@testing-library/react";
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
    cameraMoves: string[];
    cameraResets: number;
    disposed: boolean;
  };

  const instances: StageInstance[] = [];

  class MockScholarStage {
    readonly options: StageOptions;
    readonly rosters: unknown[][] = [];
    readonly visuals: { id: string; state: string }[] = [];
    readonly resting: boolean[] = [];
    readonly cameraMoves: string[] = [];
    cameraResets = 0;
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

    moveDepthCamera(direction: string): void {
      this.cameraMoves.push(direction);
    }

    resetDepthCamera(): void {
      this.cameraResets += 1;
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

  it("marks the local preview layout without changing classroom defaults", () => {
    const view = render(
      <ScholarScene
        characters={[]}
        layout="preview"
        loadingLabel="Loading"
        resting
        unavailableLabel="Unavailable"
        visuals={{}}
      />,
    );
    expect(
      view.container.querySelector('[data-layout="preview"]'),
    ).toBeTruthy();
  });

  it("wires depth camera buttons and keyboard movement to the stage", async () => {
    window.history.replaceState(null, "", "/?depth=1");
    const view = renderScene(
      [character("participant-a", "A", "River Keeper")],
      { "participant-a": "idle" },
    );
    await waitFor(() => expect(stageMock.instances).toHaveLength(1));
    const stage = stageMock.instances[0];
    stage.options.onReady?.();

    const forward = await view.findByRole("button", { name: "相机向前" });
    fireEvent.click(forward);
    fireEvent.keyDown(window, { key: "ArrowLeft" });
    expect(stage.cameraMoves).toEqual(["forward", "left"]);

    fireEvent.click(view.getByRole("button", { name: "复位相机" }));
    expect(stage.cameraResets).toBe(1);
  });
});
