import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import {
  act,
  cleanup,
  fireEvent,
  render,
  waitFor,
} from "@testing-library/react";
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
    cameraInputs: { command: string; active: boolean }[];
    cameraResets: number;
    overviewToggles: number;
    cameraClears: number;
    scenePacks: string[];
    disposed: boolean;
  };

  const instances: StageInstance[] = [];

  class MockScholarStage {
    readonly options: StageOptions;
    readonly rosters: unknown[][] = [];
    readonly visuals: { id: string; state: string }[] = [];
    readonly resting: boolean[] = [];
    readonly cameraMoves: string[] = [];
    readonly cameraInputs: { command: string; active: boolean }[] = [];
    cameraResets = 0;
    overviewToggles = 0;
    cameraClears = 0;
    readonly scenePacks: string[] = [];
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

    moveStageCamera(command: string): void {
      this.cameraMoves.push(command);
    }

    setStageCameraInput(command: string, active: boolean): void {
      this.cameraInputs.push({ command, active });
    }

    clearStageCameraInput(): void {
      this.cameraClears += 1;
    }

    resetStageCamera(): void {
      this.cameraResets += 1;
    }

    toggleStageOverview(): void {
      this.overviewToggles += 1;
    }

    setScenePack(id: string): void {
      this.scenePacks.push(id);
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

  it("wires fixed-world splat camera movement to buttons and keyboard", async () => {
    window.history.replaceState(null, "", "/?splat=1");
    const view = renderScene(
      [character("participant-a", "A", "River Keeper")],
      { "participant-a": "idle" },
    );
    await waitFor(() => expect(stageMock.instances).toHaveLength(1));
    const stage = stageMock.instances[0];
    stage.options.onReady?.();

    const forward = await view.findByRole("button", { name: "镜头向前移动" });
    fireEvent.click(forward);
    fireEvent.keyDown(window, { key: "a" });
    fireEvent.keyUp(window, { key: "a" });
    fireEvent.keyDown(window, { key: "d" });
    fireEvent.keyUp(window, { key: "d" });
    fireEvent.keyDown(window, { key: "ArrowLeft" });
    fireEvent.keyUp(window, { key: "ArrowLeft" });
    fireEvent.keyDown(window, { key: "q" });
    fireEvent.keyUp(window, { key: "q" });
    fireEvent.keyDown(window, { key: "e" });
    fireEvent.keyUp(window, { key: "e" });
    expect(stage.cameraMoves).toEqual(["forward"]);
    expect(stage.cameraInputs).toEqual([
      { command: "left", active: true },
      { command: "left", active: false },
      { command: "right", active: true },
      { command: "right", active: false },
      { command: "turn-left", active: true },
      { command: "turn-left", active: false },
      { command: "turn-left", active: true },
      { command: "turn-left", active: false },
      { command: "turn-right", active: true },
      { command: "turn-right", active: false },
    ]);

    fireEvent.click(view.getByRole("button", { name: "切换鸟瞰" }));
    fireEvent.keyDown(window, { key: "Home" });
    expect(stage.overviewToggles).toBe(1);
    expect(stage.cameraResets).toBe(1);

    fireEvent.change(view.getByRole("combobox", { name: "切换院落场景" }), {
      target: { value: "procedural" },
    });
    expect(stage.scenePacks).toEqual(["procedural"]);
    expect(window.location.search).toContain("scene=procedural");
  });
});

describe("ScholarScene long names", () => {
  it("bounds neighbouring names without dropping the complete DOM text", async () => {
    const names = [
      "VeryLongName".repeat(12),
      "知识边界研究者".repeat(12),
      "RightEdgeName".repeat(12),
    ];
    const view = renderScene(
      names.map((name, index) => character(String(index), "A", name)),
      {},
    );
    await waitFor(() => expect(stageMock.instances).toHaveLength(1));
    Object.defineProperty(
      view.container.querySelector("canvas"),
      "clientWidth",
      { value: 390 },
    );
    act(() => {
      stageMock.instances[0].options.onReady?.();
      stageMock.instances[0].options.onAnchors?.([
        { id: "0", x: 24, y: 150, visible: true },
        { id: "1", x: 104, y: 150, visible: true },
        { id: "2", x: 370, y: 150, visible: true },
      ]);
    });
    const labels = names.map((name) => view.getByText(name).parentElement!);
    expect(labels.map((label) => label.style.maxWidth)).toEqual([
      "52px",
      "160px",
      "141px",
    ]);
    expect(labels[0].style.getPropertyValue("--name-plate-left")).toBe("-16px");
    expect(labels[0].style.getPropertyValue("--name-plate-right")).toBe("36px");
    expect(labels[2].style.getPropertyValue("--name-plate-right")).toBe("12px");
    labels.forEach((label, index) => {
      expect(label.textContent).toBe(names[index]);
      expect(label.title).toBe(names[index]);
    });
  });

  it("does not shorten names for an anchor on a separate vertical row", async () => {
    const view = renderScene(
      [character("a", "A", "Upper"), character("b", "B", "Lower")],
      {},
    );
    await waitFor(() => expect(stageMock.instances).toHaveLength(1));
    Object.defineProperty(
      view.container.querySelector("canvas"),
      "clientWidth",
      { value: 390 },
    );
    act(() => {
      stageMock.instances[0].options.onReady?.();
      stageMock.instances[0].options.onAnchors?.([
        { id: "a", x: 100, y: 100, visible: true },
        { id: "b", x: 110, y: 200, visible: true },
      ]);
    });
    expect(view.getByText("Upper").parentElement!.style.maxWidth).toBe("160px");
    expect(view.getByText("Lower").parentElement!.style.maxWidth).toBe("160px");
  });

  it("stably separates coincident names without reordering ordinary anchors", async () => {
    const view = renderScene(
      [
        character("a", "A", "First full name"),
        character("b", "B", "Second full name"),
        character("c", "C", "Separate name"),
      ],
      {},
    );
    await waitFor(() => expect(stageMock.instances).toHaveLength(1));
    Object.defineProperty(
      view.container.querySelector("canvas"),
      "clientWidth",
      { value: 390 },
    );
    const anchors = [
      { id: "b", x: 100, y: 150, visible: true },
      { id: "a", x: 100, y: 150, visible: true },
      { id: "c", x: 300, y: 150, visible: true },
    ];
    act(() => {
      stageMock.instances[0].options.onReady?.();
      stageMock.instances[0].options.onAnchors?.(anchors);
    });
    const tops = () =>
      ["First full name", "Second full name", "Separate name"].map(
        (name) => view.getByText(name).parentElement!.style.top,
      );
    expect(tops()).toEqual(["150px", "198px", "150px"]);
    act(() =>
      stageMock.instances[0].options.onAnchors?.([...anchors].reverse()),
    );
    expect(tops()).toEqual(["150px", "198px", "150px"]);
  });

  it("gives a cramped middle name its own row instead of a zero-width box", async () => {
    const view = renderScene(
      [
        character("a", "A", "Left"),
        character("b", "B", "Middle"),
        character("c", "C", "Right"),
      ],
      {},
    );
    await waitFor(() => expect(stageMock.instances).toHaveLength(1));
    Object.defineProperty(
      view.container.querySelector("canvas"),
      "clientWidth",
      { value: 390 },
    );
    act(() => {
      stageMock.instances[0].options.onReady?.();
      stageMock.instances[0].options.onAnchors?.([
        { id: "a", x: 100, y: 150, visible: true },
        { id: "b", x: 110, y: 150, visible: true },
        { id: "c", x: 120, y: 150, visible: true },
      ]);
    });
    const labels = ["Left", "Middle", "Right"].map(
      (name) => view.getByText(name).parentElement!,
    );
    expect(labels.map((label) => label.style.top)).toEqual([
      "150px",
      "198px",
      "246px",
    ]);
    expect(labels.map((label) => label.style.maxWidth)).toEqual([
      "160px",
      "160px",
      "160px",
    ]);
  });

  it("bounds padding and preserves an unmeasurable name without drawing a box", async () => {
    const view = renderScene(
      [character("a", "A", "Complete accessible name")],
      {},
    );
    await waitFor(() => expect(stageMock.instances).toHaveLength(1));
    const canvas = view.container.querySelector("canvas")!;
    Object.defineProperty(canvas, "clientWidth", {
      configurable: true,
      value: 30,
    });
    const anchors = [{ id: "a", x: 15, y: 150, visible: true }];
    act(() => {
      stageMock.instances[0].options.onReady?.();
      stageMock.instances[0].options.onAnchors?.(anchors);
    });
    const label = view.getByText("Complete accessible name").parentElement!;
    expect(label.style.maxWidth).toBe("14px");
    expect(label.style.getPropertyValue("--name-plate-width")).toBe("14px");
    const css = readFileSync(
      resolve(process.cwd(), "components/stage3d/stage3d.module.css"),
      "utf8",
    );
    const compactCss = css.replace(/\s+/g, "");
    for (const padding of [14, 8]) {
      expect(compactCss).toContain(
        `padding-inline:min(${padding}px,max(0px,calc((var(--name-plate-width)-2px)/4)));`,
      );
    }
    Object.defineProperty(canvas, "clientWidth", {
      configurable: true,
      value: 16,
    });
    act(() => stageMock.instances[0].options.onAnchors?.([...anchors]));
    expect(view.getByText("Complete accessible name").className).toBe(
      "sr-only",
    );
  });

  it("keeps name clamping on mobile and lets speech and speaker names wrap", () => {
    const css = readFileSync(
      resolve(process.cwd(), "components/stage3d/stage3d.module.css"),
      "utf8",
    );
    expect(css.match(/var\(--name-plate-left\)/g)).toHaveLength(2);
    expect(css.match(/var\(--name-plate-right\)/g)).toHaveLength(2);
    expect(css).toMatch(
      /\.namePlateText\s*\{[^}]*overflow:\s*hidden;[^}]*text-overflow:\s*ellipsis;/,
    );
    expect(css).toMatch(/\.bubble\s*\{[^}]*overflow-wrap:\s*anywhere;/);
  });
});
