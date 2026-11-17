import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

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
    ).toEqual(["Ready", "Compiling"]);
    const [ready, compiling, fallback] =
      screen.getAllByTestId("debate-card-check");

    fireEvent.click(within(ready).getByText("Check card"));
    expect(within(ready).getByText(card.identity)).toBeTruthy();
    expect(within(ready).getByText(card.position)).toBeTruthy();
    expect(within(ready).getByText("Tone")).toBeTruthy();
    expect(within(ready).getByText(card.voice_style!)).toBeTruthy();
    expect(within(ready).getByText("Dropped from AGENT.md")).toBeTruthy();
    expect(within(ready).getByText("Length limit")).toBeTruthy();
    expect(within(ready).getByText(card.dropped[0].excerpt)).toBeTruthy();
    expect(within(ready).getByText("Output format")).toBeTruthy();

    expect(
      within(compiling).getByText(/The card is still compiling\./),
    ).toBeTruthy();
    expect(within(fallback).queryByTestId("debate-card-status")).toBeNull();
    expect(within(fallback).queryByText("Fallback")).toBeNull();
    expect(
      within(fallback).getByText(
        "The debate card could not be prepared from this Agent's AGENT.md, so this Agent will speak from its original AGENT.md for now. Open Check card, fix the Agent text if needed, then try again.",
      ),
    ).toBeTruthy();
  });

  it("omits the Fallback status tag on extraction failure while keeping the reason", () => {
    renderPreview(
      snapshot([
        {
          id: "a",
          agent_name: "Ada",
          card_status: "fallback",
          card_teacher_reason: "format_invalid",
          card: null,
        },
      ]),
    );
    const check = screen.getByTestId("debate-card-check");
    expect(within(check).queryByTestId("debate-card-status")).toBeNull();
    expect(within(check).queryByText("Fallback")).toBeNull();
    fireEvent.click(within(check).getByText("Check card"));
    expect(
      within(check).getByText(
        "The card response was not in the expected format, so this Agent will speak from its original AGENT.md for now. Open Check card and try again; if it keeps failing, edit the Agent's AGENT.md and re-check.",
      ),
    ).toBeTruthy();
    expect(screen.getByTestId("debate-card-check")).toBeTruthy();
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
    expect(screen.queryByText("Tone")).toBeNull();
  });

  it("shows a coarse teacher reason for fallbacks without a raw-AGENT.md path", () => {
    renderPreview(
      snapshot([
        {
          id: "a",
          agent_name: "Ada",
          card_status: "fallback",
          card_teacher_reason: "card_too_long",
          card: null,
        },
      ]),
    );
    const check = screen.getByTestId("debate-card-check");
    fireEvent.click(within(check).getByText("Check card"));
    expect(
      within(check).getByText(
        "The extracted card exceeded the safe length limit. Shorten the Agent's AGENT.md, then open Check card and try again.",
      ),
    ).toBeTruthy();
    expect(within(check).queryByText(/This session can continue/)).toBeNull();
    expect(within(check).queryByText("card_too_long")).toBeNull();
    expect(within(check).queryByText("too_long")).toBeNull();
  });

  it("does not display a teacher fallback reason for a ready card", () => {
    renderPreview(
      snapshot([
        {
          id: "a",
          agent_name: "Ada",
          card_status: "ready",
          card_teacher_reason: "other",
          card,
        },
      ]),
    );
    const check = screen.getByTestId("debate-card-check");
    fireEvent.click(within(check).getByText("Check card"));
    expect(within(check).getByText(card.identity)).toBeTruthy();
    expect(
      within(check).queryByText(
        "The debate card could not be prepared from this Agent's AGENT.md, so this Agent will speak from its original AGENT.md for now. Open Check card, fix the Agent text if needed, then try again.",
      ),
    ).toBeNull();
    expect(
      within(check).queryByText(
        "This Agent will use its original AGENT.md. This session can continue.",
      ),
    ).toBeNull();
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

  it("Ready Check card shows Tone without a Preview button", () => {
    renderPreview(
      snapshot([
        {
          id: "a",
          agent_name: "Ada",
          card_status: "ready",
          card,
          effective_voice_profile_id: "voice-1",
        },
      ]),
    );
    const check = screen.getByTestId("debate-card-check");
    fireEvent.click(within(check).getByText("Check card"));
    expect(within(check).getByText("Tone")).toBeTruthy();
    expect(within(check).getByText("A calm, low voice.")).toBeTruthy();
    expect(within(check).queryByRole("button", { name: "Preview" })).toBeNull();
    expect(within(check).queryByTestId("debate-card-tone-preview")).toBeNull();
  });
});
