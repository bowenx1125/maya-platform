import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../components/session-provider", () => ({
  useSession: () => ({
    user: {
      id: "me",
      display_name: "Kaikai",
      groups: [{ group_id: "group", role: "member" }],
    },
    api: {
      group: vi.fn().mockResolvedValue({
        members: [
          { user_id: "me", display_name: "Kaikai" },
          { user_id: "bowen", display_name: "Bowen" },
        ],
      }),
    },
  }),
}));

import { CardTable } from "../components/card-table/card-table";
import { SECRET, SecretDoor } from "../components/card-table/secret-door";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("the card room", () => {
  it("opens when the phrase is typed outside a field and closes on Escape", async () => {
    render(<SecretDoor />);
    for (const key of SECRET) fireEvent.keyDown(window, { key });
    const room = await screen.findByRole("dialog", { name: "Card table" });
    // The group sits down, topped up with a scholar to make three.
    expect(
      await within(room).findByText("Bowen", {}, { timeout: 5000 }),
    ).toBeTruthy();
    expect(within(room).getByText("Laozi")).toBeTruthy();
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("ignores the phrase typed into a field", () => {
    render(
      <>
        <input aria-label="Notes" />
        <SecretDoor />
      </>,
    );
    const field = screen.getByLabelText("Notes");
    for (const key of SECRET) fireEvent.keyDown(field, { key });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("deals, lets the player act, and plays the hand out", () => {
    vi.useFakeTimers();
    render(
      <CardTable
        players={[
          { id: "me", name: "Kaikai", human: true },
          { id: "a", name: "Bowen", human: false },
          { id: "b", name: "Jade", human: false },
        ]}
        onLeave={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Deal" }));
    // Three-handed, the button speaks first before the flop.
    expect(screen.getByRole("button", { name: "Call 20" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Fold" }));
    for (let tick = 0; tick < 60; tick += 1) {
      if (screen.queryByRole("button", { name: "Next hand" })) break;
      act(() => vi.advanceTimersByTime(1500));
    }
    expect(screen.getByRole("button", { name: "Next hand" })).toBeTruthy();
    expect(screen.getByRole("status").textContent).toMatch(/wins \d+/);
  });
});
