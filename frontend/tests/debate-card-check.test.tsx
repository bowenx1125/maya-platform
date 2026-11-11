import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import {
  DebatePreview,
  type DebatePreviewSnapshot,
} from "../components/debate/preview";

afterEach(() => cleanup());

const card = {
  identity: "A retired school nurse.",
  position: "Phones stay in lockers during lessons.",
  reasoning: ["Health before convenience."],
  speaking_style: "Warm and practical.",
  voice_style: "A calm, low voice.",
  dropped: [
    {
      excerpt: "Always answer in exactly 500 words.",
      reason: "length_limit" as const,
    },
    { excerpt: "Fill source_ids with S1.", reason: "output_format" as const },
  ],
};

function snapshot(
  participants: DebatePreviewSnapshot["participants"],
): DebatePreviewSnapshot {
  return {
    topic: "Should schools ban phones?",
    participants,
    preview: { prepared_turns: 0, expected_turns: 6, ready: false },
    preview_turns: [],
  };
}

function renderPreview(detail: DebatePreviewSnapshot) {
  return render(
    <DebatePreview
      detail={detail}
      openClassroomHref="/teacher/debates-beta/debate-a/control"
    />,
  );
}

describe("debate cards on the teacher preview", () => {
  it("shows each Agent's card state under its name", () => {
    renderPreview(
      snapshot([
        { id: "a", agent_name: "Ada", card_status: "ready", card },
        { id: "b", agent_name: "Bao", card_status: "compiling", card: null },
        { id: "c", agent_name: "Chen", card_status: "fallback", card: null },
      ]),
    );
    expect(
      screen.getAllByTestId("debate-card-status").map((tag) => tag.textContent),
    ).toEqual(["Ready", "Compiling", "Fallback"]);
    const [ready, compiling, fallback] =
      screen.getAllByTestId("debate-card-check");

    fireEvent.click(within(ready).getByText("Check card"));
    expect(within(ready).getByText(card.identity)).toBeTruthy();
    expect(within(ready).getByText(card.position)).toBeTruthy();
    expect(within(ready).getByText("Dropped from AGENT.md")).toBeTruthy();
    expect(within(ready).getByText("Length limit")).toBeTruthy();
    expect(within(ready).getByText(card.dropped[0].excerpt)).toBeTruthy();
    expect(within(ready).getByText("Output format")).toBeTruthy();

    expect(
      within(compiling).getByText(/The card is still compiling\./),
    ).toBeTruthy();
    expect(
      within(fallback).getByText(
        "Fallback: this Agent speaks from its original AGENT.md.",
      ),
    ).toBeTruthy();
  });

  it("names the Agent on the disclosure and lists nothing dropped plainly", () => {
    renderPreview(
      snapshot([
        {
          id: "a",
          agent_name: "Ada",
          card_status: "ready",
          card: { ...card, dropped: [], position: "", voice_style: null },
        },
      ]),
    );
    expect(screen.getByLabelText("Check Ada card")).toBeTruthy();
    expect(screen.getByText("Nothing was dropped.")).toBeTruthy();
    expect(screen.queryByText("Position")).toBeNull();
    expect(screen.queryByText("Voice")).toBeNull();
  });

  it("adds nothing for a Debate created before cards", () => {
    renderPreview(
      snapshot([
        { id: "a", agent_name: "Ada" },
        { id: "b", agent_name: "Bao", card_status: null },
      ]),
    );
    expect(screen.queryByTestId("debate-card-check")).toBeNull();
    expect(screen.getByText("Ada")).toBeTruthy();
  });
});
