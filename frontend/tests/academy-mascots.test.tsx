import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AcademyMascots } from "../components/academy/mascots";
import {
  AcademyMoodProvider,
  useSetAcademyMood,
  type AcademyMood,
} from "../components/academy/mood";

const LABEL = "scholars";

function MoodButtons() {
  const setMood = useSetAcademyMood();
  const moods: AcademyMood[] = ["idle", "attentive", "discreet", "refused"];
  return (
    <>
      {moods.map((mood) => (
        <button key={mood} type="button" onClick={() => setMood(mood)}>
          {mood}
        </button>
      ))}
    </>
  );
}

function mount() {
  return render(
    <AcademyMoodProvider>
      <MoodButtons />
      <AcademyMascots label={LABEL} />
    </AcademyMoodProvider>,
  );
}

function stubReducedMotion() {
  vi.stubGlobal(
    "matchMedia",
    (query: string) =>
      ({
        matches: query.includes("prefers-reduced-motion"),
        media: query,
        addEventListener: () => undefined,
        removeEventListener: () => undefined,
        addListener: () => undefined,
        removeListener: () => undefined,
        onchange: null,
        dispatchEvent: () => false,
      }) as unknown as MediaQueryList,
  );
}

function stubLayout() {
  // jsdom reports a zero-sized box, which the component treats as "not laid
  // out yet"; give it a real one so the pointer maths can run.
  vi.spyOn(SVGElement.prototype, "getBoundingClientRect").mockReturnValue({
    x: 0,
    y: 0,
    top: 0,
    left: 0,
    right: 440,
    bottom: 214,
    width: 440,
    height: 214,
    toJSON: () => ({}),
  } as DOMRect);
}

/**
 * Horizontal pupil offsets. They are written straight onto the group's style
 * from an animation frame rather than through React, so the cx attributes stay
 * put and the transform is what moves.
 */
function pupilOffsets() {
  return Array.from(document.querySelectorAll(".academy-pupils")).map(
    (group) => {
      const match = /translate\((-?[\d.]+)px/.exec(
        (group as SVGGElement).style.transform,
      );
      return match ? Number(match[1]) : 0;
    },
  );
}

/** Advance the easing loop far enough for it to have converged. */
async function settle(frames = 40) {
  for (let index = 0; index < frames; index += 1) {
    await act(async () => {
      await new Promise((resolve) =>
        requestAnimationFrame(() => resolve(null)),
      );
    });
  }
}

describe("academy mascots", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("varies the four scholars in height, width and silhouette", () => {
    stubLayout();
    mount();
    expect(document.querySelectorAll(".academy-block")).toHaveLength(4);

    const group = Array.from(document.querySelectorAll(".academy-scholar"));
    // The group should not read as one block repeated four times.
    expect(
      new Set(group.map((node) => node.getAttribute("data-height"))).size,
    ).toBe(4);
    expect(
      new Set(group.map((node) => node.getAttribute("data-width"))).size,
    ).toBe(4);
    expect(
      new Set(group.map((node) => node.getAttribute("data-shape"))),
    ).toEqual(new Set(["block", "round", "arch", "pillar"]));
  });

  it("stands every scholar on the same floor line", () => {
    stubLayout();
    mount();
    const shadows = Array.from(document.querySelectorAll(".academy-shadow"));
    expect(shadows).toHaveLength(4);
    expect(
      new Set(shadows.map((shadow) => shadow.getAttribute("cy"))).size,
    ).toBe(1);
  });

  it("follows the pointer while idle", async () => {
    stubLayout();
    mount();
    await settle();
    expect(pupilOffsets().every((value) => Math.abs(value) < 0.1)).toBe(true);

    await act(async () => {
      window.dispatchEvent(
        new MouseEvent("mousemove", { clientX: 430, clientY: 200 }),
      );
    });
    await settle();

    // A pointer to the lower right pulls every pupil that way.
    pupilOffsets().forEach((value) => expect(value).toBeGreaterThan(0.5));
  });

  it("looks towards the form while a field is being filled in", async () => {
    stubLayout();
    mount();
    fireEvent.click(screen.getByRole("button", { name: "attentive" }));
    await settle();
    // Every scholar turns the same way, towards the form, not the cursor.
    pupilOffsets().forEach((value) => expect(value).toBeGreaterThan(1));
  });

  it("closes its eyes while a password is on screen", () => {
    stubLayout();
    mount();
    expect(document.querySelectorAll(".academy-pupil")).toHaveLength(8);
    fireEvent.click(screen.getByRole("button", { name: "discreet" }));
    // Closed eyes are drawn as arcs, so there is no pupil left to track with.
    expect(document.querySelectorAll(".academy-pupil")).toHaveLength(0);
    expect(screen.getByRole("img", { name: LABEL }).dataset.mood).toBe(
      "discreet",
    );
  });

  it("turns each scholar away from the form while a password is on screen", () => {
    stubLayout();
    mount();
    fireEvent.click(screen.getByRole("button", { name: "discreet" }));
    const turns = Array.from(document.querySelectorAll(".academy-scholar")).map(
      (node) => (node as SVGGElement).style.transform,
    );
    expect(turns.every((value) => /rotate\(-\d+deg\)/.test(value))).toBe(true);
    // Not all by the same amount, or the four pivot as one object.
    expect(new Set(turns).size).toBeGreaterThan(1);
  });

  it("marks the refusal so the shake and the frown can react", () => {
    stubLayout();
    mount();
    fireEvent.click(screen.getByRole("button", { name: "refused" }));
    expect(screen.getByRole("img", { name: LABEL }).dataset.mood).toBe(
      "refused",
    );
  });

  it("stops tracking the pointer when motion is not wanted", async () => {
    stubLayout();
    stubReducedMotion();
    mount();

    await act(async () => {
      window.dispatchEvent(
        new MouseEvent("mousemove", { clientX: 430, clientY: 200 }),
      );
    });
    await settle(10);

    expect(pupilOffsets().every((value) => value === 0)).toBe(true);
    expect(screen.getByRole("img", { name: LABEL }).dataset.reduced).toBe(
      "true",
    );
  });
});
