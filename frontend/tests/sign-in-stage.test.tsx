import { act, render } from "@testing-library/react";
import { useEffect } from "react";
import { describe, expect, it } from "vitest";

import {
  AcademyMoodProvider,
  useSetAcademyMood,
} from "../components/academy/mood";
import type { AcademyMood } from "../components/academy/mood";
import { SignInStage } from "../components/academy/sign-in-stage";

const handle: { setMood: (mood: AcademyMood) => void } = {
  setMood: () => undefined,
};
function MoodHandle() {
  const setMood = useSetAcademyMood();
  useEffect(() => {
    handle.setMood = setMood;
  }, [setMood]);
  return null;
}

function renderStage(picked: number) {
  return render(
    <AcademyMoodProvider>
      <MoodHandle />
      <SignInStage picked={picked} />
    </AcademyMoodProvider>,
  );
}

describe("sign-in stage reacts to the form (proposal 38 v3)", () => {
  it("shows the four scholars face up, named for screen readers", () => {
    const { container, getByRole } = renderStage(1);
    expect(container.querySelectorAll("svg[data-mascot]")).toHaveLength(4);
    expect(getByRole("img").getAttribute("aria-label")).toMatch(/face down/);
  });

  it("turns every card face down while a password is typed", () => {
    const { container } = renderStage(1);
    act(() => handle.setMood("discreet"));
    expect(container.querySelectorAll("svg[data-mascot]")).toHaveLength(0);
    act(() => handle.setMood("idle"));
    expect(container.querySelectorAll("svg[data-mascot]")).toHaveLength(4);
  });

  it("lifts only the picked card, and none on a refusal", () => {
    const { container, rerender } = renderStage(1);
    const lifted = () =>
      [...container.querySelectorAll<HTMLElement>("[role=img] > div")].map(
        (card) => card.style.transform.includes("scale(1.1)"),
      );
    expect(lifted()).toEqual([false, true, false, false]);
    rerender(
      <AcademyMoodProvider>
        <MoodHandle />
        <SignInStage picked={2} />
      </AcademyMoodProvider>,
    );
    expect(lifted()).toEqual([false, false, true, false]);
    act(() => handle.setMood("refused"));
    expect(lifted()).toEqual([false, false, false, false]);
  });
});
