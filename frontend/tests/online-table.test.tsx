import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PlatformApiError, type CardRoom } from "../lib/api/platform";

const api = {
  createCardRoom: vi.fn(),
  joinCardRoom: vi.fn(),
  cardRoom: vi.fn(),
  leaveCardRoom: vi.fn(),
  startCardRoom: vi.fn(),
  actInCardRoom: vi.fn(),
  rebuyInCardRoom: vi.fn(),
};

vi.mock("../components/session-provider", () => ({
  useSession: () => ({ user: { id: "me", display_name: "Kaikai" }, api }),
}));

import {
  OnlineLobby,
  OnlineTable,
} from "../components/card-table/online-table";

const NOW = "2026-10-10T12:00:00Z";
const ME = "00000000-0000-4000-8000-000000000001";
const BOWEN = "00000000-0000-4000-8000-000000000002";

function seat(
  userId: string,
  name: string,
  overrides: Partial<CardRoom["seats"][number]> = {},
): CardRoom["seats"][number] {
  return {
    user_id: userId,
    name,
    avatar: null,
    stack: 4000,
    bet: 0,
    folded: false,
    all_in: false,
    sitting_out: false,
    last_action: null,
    hole: [],
    hole_count: 0,
    host: false,
    leaving: false,
    ...overrides,
  };
}

function room(overrides: Partial<CardRoom> = {}): CardRoom {
  return {
    code: "0427",
    status: "waiting",
    revision: 3,
    you: 0,
    seats: [seat(ME, "Kaikai", { host: true }), seat(BOWEN, "Bowen")],
    board: [],
    pot: 0,
    button: null,
    to_act: null,
    street: "waiting",
    current_bet: 0,
    small_blind: 10,
    big_blind: 20,
    hand_number: 0,
    legal: null,
    now: NOW,
    deadline: null,
    next_hand_at: null,
    payouts: [],
    showdown: false,
    ...overrides,
  };
}

/** Bowen to act first heads-up, then you with 42 seconds on the clock. */
function yourTurn(): CardRoom {
  return room({
    status: "playing",
    revision: 7,
    street: "preflop",
    hand_number: 1,
    button: 0,
    to_act: 0,
    current_bet: 20,
    pot: 30,
    seats: [
      seat(ME, "Kaikai", {
        host: true,
        stack: 3990,
        bet: 10,
        hole: [
          { rank: 14, suit: "s" },
          { rank: 13, suit: "s" },
        ],
        hole_count: 2,
      }),
      seat(BOWEN, "Bowen", { stack: 3980, bet: 20, hole_count: 2 }),
    ],
    legal: {
      can_check: false,
      to_call: 10,
      can_raise: true,
      min_raise_to: 40,
      max_raise_to: 4000,
    },
    deadline: "2026-10-10T12:00:42Z",
  });
}

beforeEach(() => {
  for (const call of Object.values(api)) call.mockReset();
  api.cardRoom.mockImplementation(() => new Promise(() => undefined));
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("online card rooms", () => {
  it("sits down by a four-digit code, keeping only digits", async () => {
    api.joinCardRoom.mockResolvedValue(room());
    render(<OnlineLobby onLeave={() => undefined} />);
    const sit = screen.getByRole("button", { name: "Sit down" });
    fireEvent.change(screen.getByLabelText("Room code"), {
      target: { value: "04a27" },
    });
    expect((screen.getByLabelText("Room code") as HTMLInputElement).value).toBe(
      "0427",
    );
    fireEvent.click(sit);
    await screen.findByText("Room 0427");
    expect(api.joinCardRoom).toHaveBeenCalledWith("0427");
  });

  it("says when no open room has the code", async () => {
    api.joinCardRoom.mockRejectedValue(
      new PlatformApiError(404, "Not found", { code: "not_found" }),
    );
    render(<OnlineLobby onLeave={() => undefined} />);
    fireEvent.change(screen.getByLabelText("Room code"), {
      target: { value: "9999" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sit down" }));
    expect((await screen.findByRole("alert")).textContent).toBe(
      "No open room has that code.",
    );
  });

  it("asks for a reload when another tab signed in as someone else", async () => {
    api.joinCardRoom.mockRejectedValue(
      new PlatformApiError(403, "The CSRF check failed.", {
        code: "csrf_failed",
      }),
    );
    render(<OnlineLobby onLeave={() => undefined} />);
    fireEvent.change(screen.getByLabelText("Room code"), {
      target: { value: "5673" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sit down" }));
    expect((await screen.findByRole("alert")).textContent).toBe(
      "You signed in again in another tab. Reload this page.",
    );
  });

  it("lets only the host deal the first hand", async () => {
    api.startCardRoom.mockResolvedValue(yourTurn());
    const { unmount } = render(
      <OnlineTable initial={room()} onLeave={() => undefined} />,
    );
    expect(screen.getByText("2/6 seated")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Deal" }));
    await waitFor(() => expect(api.startCardRoom).toHaveBeenCalledWith("0427"));
    unmount();

    render(
      <OnlineTable
        initial={room({
          you: 1,
          seats: [seat(BOWEN, "Bowen", { host: true }), seat(ME, "Kaikai")],
        })}
        onLeave={() => undefined}
      />,
    );
    expect(screen.queryByRole("button", { name: "Deal" })).toBeNull();
    expect(screen.getByText("Waiting for the host")).toBeTruthy();
  });

  it("shows only your cards, counts your clock down, and acts on the table you saw", async () => {
    vi.useFakeTimers({
      now: Date.parse(NOW),
      toFake: ["Date", "setInterval", "setTimeout"],
    });
    api.actInCardRoom.mockResolvedValue(
      room({ ...yourTurn(), revision: 8, legal: null, to_act: 1 }),
    );
    render(<OnlineTable initial={yourTurn()} onLeave={() => undefined} />);

    expect(screen.getAllByRole("img", { name: "A of spades" })).toHaveLength(1);
    expect(screen.getAllByRole("img", { name: "Face-down card" })).toHaveLength(
      2,
    );
    expect(screen.getByText("42")).toBeTruthy();
    act(() => vi.advanceTimersByTime(2000));
    expect(screen.getByText("40")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Call 10" }));
    expect(api.actInCardRoom).toHaveBeenCalledWith("0427", {
      type: "call",
      to: null,
      expected_revision: 7,
    });
    await act(async () => undefined);
    expect(screen.queryByRole("button", { name: "Call 10" })).toBeNull();
  });

  it("polls the room and closes when it is gone", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "setTimeout"] });
    api.cardRoom.mockRejectedValue(
      new PlatformApiError(404, "Not found", { code: "not_found" }),
    );
    render(<OnlineTable initial={room()} onLeave={() => undefined} />);
    await act(async () => vi.advanceTimersByTime(1000));
    expect(api.cardRoom).toHaveBeenCalledWith("0427");
    expect(screen.getByText("Room closed")).toBeTruthy();
  });

  it("leaves the seat on the way out", async () => {
    api.leaveCardRoom.mockResolvedValue(undefined);
    const onLeave = vi.fn();
    render(<OnlineTable initial={room()} onLeave={onLeave} />);
    const header = screen.getByRole("banner");
    fireEvent.click(within(header).getByRole("button", { name: "Leave" }));
    await waitFor(() => expect(onLeave).toHaveBeenCalled());
    expect(api.leaveCardRoom).toHaveBeenCalledWith("0427");
  });
});
