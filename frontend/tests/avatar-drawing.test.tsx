import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DrawingBoard } from "../components/avatar/drawing-board";
import {
  BLANK_DRAWING,
  boardPoint,
  boardPosition,
  clampMouth,
  erasePixels,
  eraseStrokes,
  insideShell,
  strokeHits,
  visibleStrokeAt,
  type Drawing,
} from "../components/avatar/drawing";
import { AvatarCanvas } from "../components/avatar/avatar-canvas";
import { AVATAR_TEMPLATE_DEFAULT_CONFIGS } from "../components/avatar/types";

vi.mock("../components/avatar/egg-canvas", () => ({
  EggCanvas: ({ drawing }: { drawing?: Drawing }) => (
    <div data-testid="egg-ink">{JSON.stringify(drawing)}</div>
  ),
}));
afterEach(cleanup);
const stroke = {
  id: "a",
  color: "#8C4B9E",
  width: 0.02,
  opacity: 0.7,
  erasures: [],
  points: [
    { x: 0.2, y: 0.7 },
    { x: 0.8, y: 0.7 },
  ],
};
const art: Drawing = {
  ...BLANK_DRAWING,
  strokes: [
    stroke,
    {
      ...stroke,
      id: "b",
      color: "#177E83",
      points: [
        { x: 0.2, y: 0.8 },
        { x: 0.8, y: 0.8 },
      ],
    },
  ],
};
beforeEach(() => {
  vi.stubGlobal(
    "ResizeObserver",
    class {
      constructor(private callback: () => void) {}
      observe() {
        Object.defineProperty(HTMLElement.prototype, "clientWidth", {
          configurable: true,
          get: () => 600,
        });
        Object.defineProperty(HTMLElement.prototype, "clientHeight", {
          configurable: true,
          get: () => 600,
        });
        this.callback();
      }
      disconnect() {}
    },
  );
  vi.stubGlobal(
    "PointerEvent",
    class extends MouseEvent {
      pointerId = 1;
      isPrimary = true;
      pointerType = "mouse";
    },
  );
  HTMLElement.prototype.setPointerCapture = vi.fn();
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({
    x: 0,
    y: 0,
    left: 0,
    top: 0,
    width: 600,
    height: 600,
    right: 600,
    bottom: 600,
    toJSON() {
      return {};
    },
  });
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
const sample = (point: { x: number; y: number }) => {
  const p = boardPosition(point, 600, 600);
  return { clientX: p.x, clientY: p.y, pointerId: 1 };
};
function surface() {
  return screen.getByLabelText("Avatar drawing canvas");
}
function ink() {
  return JSON.parse(screen.getByTestId("egg-ink").textContent!) as Drawing;
}
function drawLine(y = 0.2) {
  fireEvent.pointerDown(surface(), sample({ x: 0.4, y }));
  fireEvent.pointerMove(surface(), sample({ x: 0.6, y }));
  fireEvent.pointerUp(surface(), sample({ x: 0.6, y }));
}
function board(
  drawing: Drawing = BLANK_DRAWING,
  onSave = vi.fn().mockResolvedValue(undefined),
) {
  const props = {
    open: true,
    drawing,
    onSave,
    onClose: vi.fn(),
    onPreview: vi.fn(),
  };
  render(<DrawingBoard {...props} />);
  return props;
}
describe("editable shell drawing", () => {
  it("shares C2 projection and clips poles and points outside the silhouette", () => {
    for (const [w, h] of [
      [390, 560],
      [1150, 640],
    ])
      for (const p of [
        { x: 0.5, y: 0.1 },
        { x: 0.2, y: 0.8 },
      ]) {
        const pixel = boardPosition(p, w, h);
        const result = boardPoint(pixel.x, pixel.y, w, h);
        expect(result.x).toBeCloseTo(p.x, 10);
        expect(result.y).toBeCloseTo(p.y, 10);
      }
    expect(insideShell({ x: 0.5, y: 0.5 })).toBe(true);
    for (const p of [
      { x: 0, y: 0.01 },
      { x: 1, y: 0.8 },
      { x: 0.5, y: -0.01 },
      { x: 0.5, y: 1 },
    ])
      expect(insideShell(p)).toBe(false);
    expect(clampMouth({ x: -1, y: 2 })).toEqual({ x: 0.4, y: 0.65 });
  });
  it("erases only visible ink to transparency and retains parent identity/order/opacity", () => {
    const erased = erasePixels(
      art,
      [
        { x: 0.5, y: 0.6 },
        { x: 0.5, y: 0.9 },
      ],
      0.07,
    );
    expect(erased.strokes.map((s) => s.id)).toEqual(["a", "b"]);
    expect(erased.strokes[0].color).toBe(stroke.color);
    expect(erased.strokes[0].opacity).toBe(0.7);
    expect(visibleStrokeAt(erased.strokes[0], { x: 0.5, y: 0.7 })).toBe(false);
    expect(strokeHits(erased.strokes[0], [{ x: 0.5, y: 0.7 }])).toBe(false);
    expect(strokeHits(erased.strokes[0], [{ x: 0.3, y: 0.7 }])).toBe(true);
    expect(erasePixels(art, [{ x: 0.5, y: 0.1 }], 0.02)).toBe(art);
    expect(
      eraseStrokes(erased, new Set(["a"])).strokes.map((s) => s.id),
    ).toEqual(["b"]);
    expect(art.strokes[0].erasures).toEqual([]);
  });
  it("supports controlled open/close and returns the full editable drawing to Save", async () => {
    const props = board();
    drawLine();
    expect(ink().strokes).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(props.onClose).toHaveBeenCalledOnce());
    expect(props.onSave).toHaveBeenCalledWith(
      expect.objectContaining({
        strokes: expect.arrayContaining([
          expect.objectContaining({ color: "#111111" }),
        ]),
      }),
      expect.any(String),
    );
    cleanup();
    render(<DrawingBoard {...props} open={false} />);
    expect(screen.queryByRole("dialog")).toBeNull();
  });
  it("groups the swept whole strokes on release and restores both with one Undo", () => {
    board(art);
    fireEvent.click(screen.getByRole("button", { name: "Stroke" }));
    fireEvent.pointerDown(surface(), sample({ x: 0.3, y: 0.7 }));
    fireEvent.pointerMove(surface(), sample({ x: 0.3, y: 0.8 }));
    expect(ink().strokes).toHaveLength(2);
    fireEvent.pointerUp(surface(), sample({ x: 0.3, y: 0.8 }));
    expect(ink().strokes).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(ink()).toEqual(art);
  });
  it("cancels pixel erasing and groups a complete pixel gesture into one Undo", () => {
    board(art);
    fireEvent.click(screen.getByRole("button", { name: "Pixel" }));
    fireEvent.pointerDown(surface(), sample({ x: 0.5, y: 0.7 }));
    fireEvent.pointerMove(surface(), sample({ x: 0.5, y: 0.8 }));
    expect(ink()).not.toEqual(art);
    fireEvent.pointerCancel(surface());
    expect(ink()).toEqual(art);
    fireEvent.pointerDown(surface(), sample({ x: 0.5, y: 0.7 }));
    fireEvent.pointerMove(surface(), sample({ x: 0.5, y: 0.8 }));
    fireEvent.pointerUp(surface(), sample({ x: 0.5, y: 0.8 }));
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(ink()).toEqual(art);
  });
  it("uses one mouth selection, moves only coordinates and never erases the mouth", () => {
    board(art);
    const mouth = screen.getAllByRole("button", { name: "Mouth" });
    fireEvent.click(mouth[0]);
    expect(mouth.every((b) => b.getAttribute("aria-pressed") === "true")).toBe(
      true,
    );
    fireEvent.pointerDown(surface(), sample(art.mouth));
    fireEvent.pointerMove(surface(), sample({ x: 0.58, y: 0.5 }));
    fireEvent.pointerUp(surface(), sample({ x: 0.58, y: 0.5 }));
    expect(ink().strokes).toEqual(art.strokes);
    expect(ink().mouth).not.toEqual(art.mouth);
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(ink()).toEqual(art);
    fireEvent.click(screen.getByRole("button", { name: "Pixel" }));
    expect(mouth.every((b) => b.getAttribute("aria-pressed") === "false")).toBe(
      true,
    );
    fireEvent.pointerDown(surface(), sample({ x: 0.05, y: 0.435 }));
    fireEvent.pointerMove(surface(), sample({ x: 0.95, y: 0.435 }));
    fireEvent.pointerUp(surface(), sample({ x: 0.95, y: 0.435 }));
    expect(ink().mouth).toEqual(art.mouth);
  });
  it("keeps drawing and undo after Save failure and reuses the retry key", async () => {
    const save = vi.fn().mockRejectedValue({ code: "network_error" });
    board(BLANK_DRAWING, save);
    drawLine();
    const before = ink();
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Save" }).hasAttribute("disabled"),
      ).toBe(false),
    );
    expect(ink()).toEqual(before);
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(save).toHaveBeenCalledTimes(2));
    expect(save.mock.calls[0][1]).toBe(save.mock.calls[1][1]);
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(ink()).toEqual(BLANK_DRAWING);
  });
  it("passes saved ink into every shared Egg avatar renderer", () => {
    render(
      <AvatarCanvas
        config={{ ...AVATAR_TEMPLATE_DEFAULT_CONFIGS.egg, drawing: art }}
      />,
    );
    expect(ink()).toEqual(art);
  });
});
