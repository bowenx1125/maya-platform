import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { create } from "qrcode";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LocaleProvider } from "../components/locale";
import { PlatformApiError } from "../lib/api";
import {
  AudienceInteractionForm,
  QrCode,
  TeacherInteractionPanel,
  type AudienceInteractionApi,
  type TeacherInteraction,
} from "../components/interaction";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const participants = [
  { id: "participant-a", slot: "A" as const, name: "Bowen" },
  { id: "participant-b", slot: "B" as const, name: "Kaikai" },
];

const openInteraction: TeacherInteraction = {
  status: "open",
  public_url: "http://192.168.1.25:8080/classroom/v1.example",
  votes: [
    { participant_id: "participant-a", count: 2, percentage: 66.7 },
    { participant_id: "participant-b", count: 1, percentage: 33.3 },
  ],
  barrages: [
    {
      id: "message-1",
      turn_id: null,
      nickname: "Learner",
      raw_text: "I want to hear both sides.",
      sequence: 1,
      submitted_at: "2026-08-29T00:00:00Z",
    },
  ],
};

function audienceApi(): AudienceInteractionApi {
  return {
    getForm: vi.fn(async () => ({
      topic: "Should classrooms use anonymous questions?",
      current_turn_id: null,
      round_no: null,
      barrage_open: true,
      participants: participants.map((participant) => ({
        participant_id: participant.id,
        slot: participant.slot,
        name: participant.name,
      })),
    })),
    submitVote: vi.fn(async () => ({ vote_submitted: true as const })),
    submitBarrage: vi.fn(async () => ({ barrage_submitted: true as const })),
  };
}

describe("M13 teacher interaction panel", () => {
  it("renders QR, aggregate totals, and raw named barrages while open", () => {
    const onClose = vi.fn();
    render(
      <TeacherInteractionPanel
        debateId="debate-1"
        interaction={openInteraction}
        participants={participants}
        onClose={onClose}
      />,
    );

    expect(screen.getByRole("img", { name: /^Scan to join:/ })).toBeTruthy();
    // The totals are a pie now; the legend carries the count and the share.
    expect(screen.getByText("2 · 67%")).toBeTruthy();
    expect(screen.getByText("Learner")).toBeTruthy();
    const rawHeading = screen.getByText("Raw barrages");
    const voteHeading = screen.getByText("Live vote");
    expect(
      rawHeading.compareDocumentPosition(voteHeading) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Conclude/ }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("only offers opening for a closed window", () => {
    const onOpen = vi.fn();
    render(
      <TeacherInteractionPanel
        debateId="debate-1"
        interaction={{
          status: "closed",
          public_url: null,
          votes: [],
          barrages: [],
        }}
        participants={participants}
        onOpen={onOpen}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Interaction" }));
    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: /End collection/ })).toBeNull();
  });

  it("renders a real qrcode module matrix with a four-module quiet zone", () => {
    const value = "http://192.168.1.25:8080/classroom/v1.example";
    const moduleCount = create(value, { errorCorrectionLevel: "M" }).modules
      .size;
    render(<QrCode value={value} />);

    const svg = screen.getByRole("img", { name: /^Scan to join:/ });
    expect(svg.getAttribute("viewBox")).toBe(
      `0 0 ${moduleCount + 8} ${moduleCount + 8}`,
    );
    const darkCells = [...svg.querySelectorAll("g rect")];
    expect(darkCells.length).toBeGreaterThan(0);
    expect(
      darkCells.every(
        (cell) =>
          Number(cell.getAttribute("x")) >= 4 &&
          Number(cell.getAttribute("y")) >= 4,
      ),
    ).toBe(true);
  });

  it("auto-scrolls raw barrages, pauses on hover, and respects reduced motion", () => {
    vi.useFakeTimers();
    vi.stubGlobal(
      "matchMedia",
      vi.fn(() => ({ matches: false })),
    );
    render(
      <TeacherInteractionPanel
        debateId="debate-1"
        interaction={{
          ...openInteraction,
          barrages: [
            ...openInteraction.barrages,
            {
              ...openInteraction.barrages[0],
              id: "message-2",
              sequence: 2,
            },
          ],
        }}
        participants={participants}
      />,
    );
    const feed = screen.getByLabelText("Raw barrages");
    Object.defineProperty(feed, "scrollHeight", {
      configurable: true,
      value: 500,
    });
    Object.defineProperty(feed, "clientHeight", {
      configurable: true,
      value: 200,
    });
    feed.scrollTop = 0;
    act(() => vi.advanceTimersByTime(160));
    expect(feed.scrollTop).toBeGreaterThan(0);

    fireEvent.mouseEnter(feed);
    const pausedAt = feed.scrollTop;
    act(() => vi.advanceTimersByTime(240));
    expect(feed.scrollTop).toBe(pausedAt);
    fireEvent.mouseLeave(feed);
    act(() => vi.advanceTimersByTime(160));
    expect(feed.scrollTop).toBeGreaterThan(pausedAt);

    cleanup();
    const interval = vi.spyOn(window, "setInterval");
    vi.stubGlobal(
      "matchMedia",
      vi.fn(() => ({ matches: true })),
    );
    render(
      <TeacherInteractionPanel
        debateId="debate-2"
        interaction={{
          ...openInteraction,
          barrages: [
            ...openInteraction.barrages,
            {
              ...openInteraction.barrages[0],
              id: "message-reduced",
              sequence: 2,
            },
          ],
        }}
        participants={participants}
      />,
    );
    expect(interval).not.toHaveBeenCalled();
  });
});

describe("M13 anonymous audience form", () => {
  it("keeps the mobile message composer first, keyboard reachable, and announces errors", async () => {
    const api = audienceApi();
    const form = {
      ...(await api.getForm("token")),
      current_turn_id: "turn-1",
      round_no: 1,
    };
    vi.mocked(api.getForm).mockResolvedValue(form);
    vi.mocked(api.submitBarrage).mockRejectedValueOnce(
      new Error("Please try again"),
    );
    render(<AudienceInteractionForm accessToken="token" api={api} />);
    const nickname = await screen.findByLabelText("Nickname");
    fireEvent.change(nickname, { target: { value: "Learner" } });
    fireEvent.keyDown(nickname, { key: "Enter" });
    const message = screen.getByRole("textbox", { name: "Barrage" });
    expect(document.activeElement).toBe(message);
    expect(message.getAttribute("maxlength")).toBe("300");
    const messageForm = screen.getByRole("form", { name: "Barrage" });
    const voteForm = screen.getByRole("form", { name: "Vote" });
    expect(
      messageForm.compareDocumentPosition(voteForm) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    fireEvent.change(message, { target: { value: "Hello" } });
    expect(screen.getByText("5 / 300")).toBeTruthy();
    fireEvent.submit(messageForm);
    expect(await screen.findByRole("alert")).toHaveProperty(
      "textContent",
      "Please try again",
    );
    expect(message.getAttribute("aria-invalid")).toBe("true");
    expect(message.getAttribute("aria-describedby")).toContain("message-error");
    expect(message).toHaveProperty("value", "Hello");
    expect(api.submitVote).not.toHaveBeenCalled();
  });

  it("refreshes a refused stale turn without discarding the student's text", async () => {
    const api = audienceApi();
    const form = {
      ...(await api.getForm("token")),
      current_turn_id: "turn-old",
      round_no: 1,
    };
    vi.mocked(api.getForm)
      .mockResolvedValueOnce(form)
      .mockResolvedValue({ ...form, current_turn_id: "turn-new", round_no: 2 });
    vi.mocked(api.submitBarrage).mockRejectedValueOnce(
      new PlatformApiError(409, "Turn changed", {
        code: "barrage_turn_changed",
      }),
    );
    render(<AudienceInteractionForm accessToken="token" api={api} />);
    await screen.findByRole("heading", { name: form.topic });
    fireEvent.change(screen.getByLabelText("Nickname"), {
      target: { value: "Learner" },
    });
    fireEvent.change(screen.getByRole("textbox", { name: "Barrage" }), {
      target: { value: "How does the source support this?" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await screen.findByText("Round 2");
    expect(
      (
        screen.getByRole("textbox", {
          name: "Barrage",
        }) as HTMLTextAreaElement
      ).value,
    ).toBe("How does the source support this?");
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(api.submitBarrage).toHaveBeenCalledTimes(2));
    const calls = vi.mocked(api.submitBarrage).mock.calls;
    expect(calls[0][1].turn_id).toBe("turn-old");
    expect(calls[1][1].turn_id).toBe("turn-new");
    expect(calls[0][1].client_submission_id).not.toBe(
      calls[1][1].client_submission_id,
    );
  });

  it("sends multiple turn-bound barrages and distinguishes a network loss from Final", async () => {
    const api = audienceApi();
    const form = {
      ...(await api.getForm("token")),
      current_turn_id: "turn-1",
      round_no: 1,
    };
    vi.mocked(api.getForm).mockResolvedValue(form);
    render(<AudienceInteractionForm accessToken="token" api={api} />);
    await screen.findByRole("heading", { name: form.topic });
    fireEvent.change(screen.getByLabelText("Nickname"), {
      target: { value: "Learner" },
    });
    for (const message of ["First question", "Another question"]) {
      fireEvent.change(screen.getByRole("textbox", { name: "Barrage" }), {
        target: { value: message },
      });
      fireEvent.click(screen.getByRole("button", { name: "Send" }));
      await waitFor(() =>
        expect(
          (
            screen.getByRole("textbox", {
              name: "Barrage",
            }) as HTMLTextAreaElement
          ).value,
        ).toBe(""),
      );
    }
    expect(api.submitBarrage).toHaveBeenCalledTimes(2);
    const calls = vi.mocked(api.submitBarrage).mock.calls;
    expect(calls.map((call) => call[1].turn_id)).toEqual(["turn-1", "turn-1"]);
    expect(calls[0][1].client_submission_id).not.toBe(
      calls[1][1].client_submission_id,
    );
    vi.useFakeTimers();
    // Remount with timers controlled so each poll observes one authoritative state.
    cleanup();
    render(<AudienceInteractionForm accessToken="token" api={api} />);
    await act(async () => {});
    fireEvent.change(screen.getByLabelText("Nickname"), {
      target: { value: "Learner" },
    });
    vi.mocked(api.getForm).mockRejectedValueOnce(new Error("offline"));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(screen.getByRole("status").textContent).toContain(
      "Connection interrupted",
    );
    expect(screen.queryByText("Collection closed")).toBeNull();
    vi.mocked(api.getForm).mockResolvedValue({
      ...form,
      current_turn_id: "turn-2",
      round_no: 2,
      barrage_open: false,
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(screen.getByText("Collection closed")).toBeTruthy();
    expect(screen.queryByText(/Connection interrupted/)).toBeNull();
    const send = screen.getByRole("button", {
      name: "Send",
    }) as HTMLButtonElement;
    const vote = screen.getByRole("button", {
      name: /^Vote$/,
    }) as HTMLButtonElement;
    expect(send.disabled).toBe(true);
    expect(vote.disabled).toBe(false);
    fireEvent.change(screen.getByRole("textbox", { name: "Barrage" }), {
      target: { value: "Too late" },
    });
    fireEvent.submit(screen.getByRole("form", { name: "Barrage" }));
    expect(api.submitBarrage).toHaveBeenCalledTimes(2);
    vi.useRealTimers();
    fireEvent.click(vote);
    await waitFor(() => expect(api.submitVote).toHaveBeenCalledTimes(1));
  });

  it("does not reveal vote or barrage sections before a nickname is entered", async () => {
    const api = audienceApi();
    render(<AudienceInteractionForm accessToken="token" api={api} />);
    await screen.findByRole("heading", {
      name: "Should classrooms use anonymous questions?",
    });

    expect(screen.queryByText("Vote")).toBeNull();
    expect(screen.queryByText("Barrage")).toBeNull();
    expect(screen.getByLabelText("Nickname")).toBeTruthy();
  });

  it("renders audience controls in the active locale without bilingual labels", async () => {
    const api = audienceApi();
    render(
      <LocaleProvider initialLocale="zh">
        <AudienceInteractionForm accessToken="token" api={api} />
      </LocaleProvider>,
    );
    await screen.findByRole("heading", {
      name: "Should classrooms use anonymous questions?",
    });

    fireEvent.change(screen.getByLabelText("昵称"), {
      target: { value: "同学" },
    });
    expect(screen.getByLabelText("昵称")).toBeTruthy();
    expect(screen.getAllByText("投票")).toHaveLength(2);
    expect(screen.getByText("弹幕")).toBeTruthy();
    expect(screen.getByRole("button", { name: "投票" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "发送" })).toBeTruthy();
    expect(screen.queryByText("Vote / 投票")).toBeNull();
    expect(screen.queryByText("Barrage / 弹幕")).toBeNull();
  });

  it("keeps vote and barrage submissions independent", async () => {
    const api = audienceApi();
    render(<AudienceInteractionForm accessToken="token" api={api} />);
    await screen.findByRole("heading", {
      name: "Should classrooms use anonymous questions?",
    });

    const nickname = screen.getByLabelText("Nickname");
    fireEvent.change(nickname, { target: { value: "Class 1" } });
    const voteButton = screen.getByRole("button", {
      name: /^Vote$/,
    });
    const barrageButton = screen.getByRole("button", { name: /^Send$/ });
    expect((voteButton as HTMLButtonElement).disabled).toBe(false);
    expect((barrageButton as HTMLButtonElement).disabled).toBe(true);

    fireEvent.click(voteButton);
    await waitFor(() => expect(api.submitVote).toHaveBeenCalledTimes(1));
    expect((barrageButton as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText("Submitted")).toBeTruthy();

    fireEvent.change(screen.getByRole("textbox", { name: "Barrage" }), {
      target: { value: "A useful question" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^Send$/ }));
    await waitFor(() => expect(api.submitBarrage).toHaveBeenCalledTimes(1));
    expect(api.submitBarrage).toHaveBeenCalledWith(
      "token",
      expect.objectContaining({
        nickname: "Class 1",
        raw_text: "A useful question",
      }),
    );
    const message = screen.getByRole("textbox", { name: "Barrage" });
    await waitFor(() => expect(message).toHaveProperty("value", ""));
    fireEvent.change(message, { target: { value: "Another useful question" } });
    fireEvent.click(screen.getByRole("button", { name: /^Send$/ }));
    await waitFor(() => expect(api.submitBarrage).toHaveBeenCalledTimes(2));
    const calls = vi.mocked(api.submitBarrage).mock.calls;
    expect(calls[0][1].client_submission_id).not.toBe(
      calls[1][1].client_submission_id,
    );
    expect(api.submitVote).toHaveBeenCalledTimes(1);
  });

  it("reuses valid UUID submission identities after an ambiguous failure", async () => {
    const api = audienceApi();
    vi.mocked(api.submitVote)
      .mockRejectedValueOnce(new Error("connection reset"))
      .mockResolvedValueOnce({ vote_submitted: true });
    render(<AudienceInteractionForm accessToken="token" api={api} />);
    await screen.findByRole("heading", {
      name: "Should classrooms use anonymous questions?",
    });
    fireEvent.change(screen.getByLabelText("Nickname"), {
      target: { value: "Retry learner" },
    });

    const voteButton = screen.getByRole("button", {
      name: /^Vote$/,
    });
    fireEvent.click(voteButton);
    await screen.findByText("connection reset");
    fireEvent.click(voteButton);
    await waitFor(() => expect(api.submitVote).toHaveBeenCalledTimes(2));

    const firstPayload = vi.mocked(api.submitVote).mock.calls[0]?.[1];
    const secondPayload = vi.mocked(api.submitVote).mock.calls[1]?.[1];
    expect(firstPayload).toEqual(secondPayload);
    expect(firstPayload?.client_submission_id).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
    );
  });

  it("locks vote and barrage after Conclude rejects a submit", async () => {
    const api = audienceApi();
    const ended = new PlatformApiError(
      410,
      "Classroom interaction collection has ended.",
      { code: "interaction_finalized" },
    );
    vi.mocked(api.submitVote).mockRejectedValue(ended);
    render(<AudienceInteractionForm accessToken="token" api={api} />);
    await screen.findByRole("heading", {
      name: "Should classrooms use anonymous questions?",
    });
    fireEvent.change(screen.getByLabelText("Nickname"), {
      target: { value: "Learner" },
    });
    fireEvent.change(screen.getByRole("textbox", { name: "Barrage" }), {
      target: { value: "Still open" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^Vote$/ }));
    await screen.findByText("Collection closed");
    const send = screen.getByRole("button", {
      name: "Send",
    }) as HTMLButtonElement;
    const vote = screen.getByRole("button", {
      name: /^Vote$/,
    }) as HTMLButtonElement;
    expect(send.disabled).toBe(true);
    expect(vote.disabled).toBe(true);
    expect(screen.queryByText(/Connection interrupted/)).toBeNull();
    fireEvent.click(vote);
    fireEvent.submit(screen.getByRole("form", { name: "Barrage" }));
    expect(api.submitVote).toHaveBeenCalledTimes(1);
    expect(api.submitBarrage).not.toHaveBeenCalled();
  });

  it("locks both submits when a refresh reports the window finalized", async () => {
    const api = audienceApi();
    render(<AudienceInteractionForm accessToken="token" api={api} />);
    await screen.findByRole("heading", {
      name: "Should classrooms use anonymous questions?",
    });
    vi.useFakeTimers();
    cleanup();
    render(<AudienceInteractionForm accessToken="token" api={api} />);
    await act(async () => {});
    fireEvent.change(screen.getByLabelText("Nickname"), {
      target: { value: "Learner" },
    });
    vi.mocked(api.getForm).mockRejectedValue(
      new PlatformApiError(410, "Classroom interaction collection has ended.", {
        code: "interaction_finalized",
      }),
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(screen.getByText("Collection closed")).toBeTruthy();
    expect(screen.queryByText(/Connection interrupted/)).toBeNull();
    expect(
      (screen.getByRole("button", { name: "Send" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    expect(
      (screen.getByRole("button", { name: /^Vote$/ }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    fireEvent.submit(screen.getByRole("form", { name: "Barrage" }));
    fireEvent.submit(screen.getByRole("form", { name: "Vote" }));
    expect(api.submitBarrage).not.toHaveBeenCalled();
    expect(api.submitVote).not.toHaveBeenCalled();
  });

  it("keeps Vote and Send locked when a stale open poll follows Conclude", async () => {
    const api = audienceApi();
    const open = await api.getForm("token");
    render(<AudienceInteractionForm accessToken="token" api={api} />);
    await screen.findByRole("heading", { name: open.topic });
    vi.useFakeTimers();
    cleanup();
    render(<AudienceInteractionForm accessToken="token" api={api} />);
    await act(async () => {});
    fireEvent.change(screen.getByLabelText("Nickname"), {
      target: { value: "Learner" },
    });
    vi.mocked(api.getForm).mockRejectedValueOnce(
      new PlatformApiError(410, "Classroom interaction collection has ended.", {
        code: "interaction_finalized",
      }),
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(screen.getByText("Collection closed")).toBeTruthy();
    vi.mocked(api.getForm).mockResolvedValue({ ...open, barrage_open: true });
    const pollsBefore = vi.mocked(api.getForm).mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(vi.mocked(api.getForm).mock.calls.length).toBeGreaterThan(
      pollsBefore,
    );
    expect(screen.getByText("Collection closed")).toBeTruthy();
    expect(
      (screen.getByRole("button", { name: "Send" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    expect(
      (screen.getByRole("button", { name: /^Vote$/ }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    fireEvent.submit(screen.getByRole("form", { name: "Barrage" }));
    fireEvent.submit(screen.getByRole("form", { name: "Vote" }));
    expect(api.submitBarrage).not.toHaveBeenCalled();
    expect(api.submitVote).not.toHaveBeenCalled();
  });

  it("renders one locale at a time for teacher interaction controls", () => {
    render(
      <LocaleProvider initialLocale="en">
        <TeacherInteractionPanel
          debateId="debate-1"
          interaction={openInteraction}
          participants={participants}
        />
      </LocaleProvider>,
    );
    expect(screen.getByText("Raw barrages")).toBeTruthy();
    expect(screen.queryByText("原始弹幕")).toBeNull();
    expect(screen.queryByText(/Raw barrages\s*\/\s*原始弹幕/)).toBeNull();

    cleanup();
    render(
      <LocaleProvider initialLocale="zh">
        <TeacherInteractionPanel
          debateId="debate-1"
          interaction={openInteraction}
          participants={participants}
        />
      </LocaleProvider>,
    );
    expect(screen.getByText("原始弹幕")).toBeTruthy();
    expect(screen.queryByText("Raw barrages")).toBeNull();
    expect(screen.queryByText(/Raw barrages\s*\/\s*原始弹幕/)).toBeNull();
    expect(screen.getByRole("img", { name: /^扫码加入:/ })).toBeTruthy();
  });
});
