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
import { JestersTable } from "../components/card-table/jesters-table";
import { SEQUENCE, SecretDoor } from "../components/card-table/secret-door";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

/** The home's hero with its four scholars, as the door listens for them. */
function Hero() {
  return (
    <section className="home-hero">
      <svg>
        {SEQUENCE.map((id) => (
          <g key={id} className="academy-scholar" data-scholar={id}>
            <rect data-testid={id} width="10" height="10" />
          </g>
        ))}
      </svg>
    </section>
  );
}

describe("the card room", () => {
  it("opens when the four scholars are clicked in order, and closes on Escape", async () => {
    render(
      <>
        <Hero />
        <SecretDoor />
      </>,
    );
    for (const id of SEQUENCE) fireEvent.click(screen.getByTestId(id));
    const room = await screen.findByRole("dialog", { name: "Card room" });
    fireEvent.click(
      await within(room).findByRole(
        "button",
        { name: /Training/ },
        { timeout: 5000 },
      ),
    );
    // The group sits down, topped up with a scholar to make three.
    expect(await within(room).findByText("Bowen")).toBeTruthy();
    expect(within(room).getByText("Laozi")).toBeTruthy();
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("stays shut when the scholars are clicked out of order", () => {
    render(
      <>
        <Hero />
        <SecretDoor />
      </>,
    );
    for (const id of [...SEQUENCE].reverse())
      fireEvent.click(screen.getByTestId(id));
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

  it("plays a Jesters hand and counts the score into the round", () => {
    vi.useFakeTimers();
    render(<JestersTable onLeave={vi.fn()} />);
    const hand = within(screen.getByLabelText("Your hand")).getAllByRole(
      "button",
    );
    expect(hand).toHaveLength(8);
    fireEvent.click(hand[0]);
    expect(hand[0].getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: "Play" }));
    for (let tick = 0; tick < 20; tick += 1)
      act(() => vi.advanceTimersByTime(400));
    expect(screen.getByRole("button", { name: "Play" })).toBeTruthy();
    // One hand spent; whatever it scored is now on the board.
    expect(document.body.textContent).toMatch(/Hands\s*3/);
  });

  it("ends a training session on a summary of the hands played", () => {
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
    const end = screen.getByRole("button", {
      name: "End",
    }) as HTMLButtonElement;
    expect(end.disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Deal" }));
    fireEvent.click(screen.getByRole("button", { name: "Fold" }));
    for (let tick = 0; tick < 60; tick += 1) {
      if (screen.queryByRole("button", { name: "Next hand" })) break;
      act(() => vi.advanceTimersByTime(1500));
    }
    fireEvent.click(screen.getByRole("button", { name: "End" }));
    expect(screen.getByText("Session")).toBeTruthy();
    expect(screen.getByText("Hands").previousElementSibling?.textContent).toBe(
      "1",
    );
    expect(screen.getByRole("button", { name: "Again" })).toBeTruthy();
  });
});
