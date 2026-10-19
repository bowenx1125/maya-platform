import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PlatformApiError } from "../lib/api";
import {
  AudienceInteractionForm,
  type AudienceInteractionApi,
} from "../components/interaction";
import {
  FORM_POLL_MAX_MS,
  FORM_POLL_MIN_MS,
  nextFormPollDelay,
  resetAudienceIdForTests,
  submitRetryDelay,
} from "../components/interaction/audience-backoff";

// Load plan 2026-10-19: 60 viewers polled every 2 s and nothing was resent
// on a 503. The form now backs off and resends under the same submission id.

const form = {
  topic: "Should classrooms use anonymous questions?",
  current_turn_id: null,
  round_no: null,
  barrage_open: true,
  participants: [
    { participant_id: "participant-a", slot: "A" as const, name: "Bowen" },
    { participant_id: "participant-b", slot: "B" as const, name: "Kaikai" },
  ],
};

function busy(seconds = 1): PlatformApiError {
  return new PlatformApiError(503, "busy", {
    code: "debate_interaction_busy",
    details: { retry_after_seconds: seconds },
  });
}

function audienceApi(): AudienceInteractionApi {
  return {
    getForm: vi.fn(async () => form),
    submitVote: vi.fn(async () => ({ vote_submitted: true as const })),
    submitBarrage: vi.fn(async () => ({ barrage_submitted: true as const })),
  };
}

async function settle(): Promise<void> {
  await act(async () => {});
}

async function advance(ms: number): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

beforeEach(() => {
  resetAudienceIdForTests();
  window.localStorage.clear();
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("audience back-off schedule", () => {
  it("doubles from 2 s to 10 s on failures and resets after a success", () => {
    const failure = new Error("offline");
    const seen: number[] = [];
    let delay = FORM_POLL_MIN_MS;
    for (let index = 0; index < 5; index += 1) {
      delay = nextFormPollDelay(delay, failure);
      seen.push(delay);
    }
    expect(seen).toEqual([4000, 8000, 10000, 10000, 10000]);
    expect(nextFormPollDelay(FORM_POLL_MAX_MS, null)).toBe(FORM_POLL_MIN_MS);
  });

  it("waits at least the server's Retry-After", () => {
    expect(nextFormPollDelay(FORM_POLL_MIN_MS, busy(15))).toBe(15000);
    expect(submitRetryDelay(0, busy(3))).toBe(3000);
    expect(submitRetryDelay(5, busy(1))).toBe(10000);
  });
});

describe("audience form under load", () => {
  it("polls the form less often while the server is busy, then back at 2 s", async () => {
    vi.useFakeTimers();
    const api = audienceApi();
    render(<AudienceInteractionForm accessToken="token" api={api} />);
    await settle();
    const calls = () => vi.mocked(api.getForm).mock.calls.length;
    expect(calls()).toBe(1);

    vi.mocked(api.getForm)
      .mockRejectedValueOnce(busy(3))
      .mockRejectedValueOnce(busy(1));
    await advance(2000); // first poll: refused (Retry-After 3 s)
    expect(calls()).toBe(2);
    await advance(3999); // next waits max(4 s, 3 s)
    expect(calls()).toBe(2);
    await advance(1); // second poll: refused again
    expect(calls()).toBe(3);
    await advance(7999); // then 8 s
    expect(calls()).toBe(3);
    await advance(1); // succeeds
    expect(calls()).toBe(4);
    await advance(2000); // back to every 2 s
    expect(calls()).toBe(5);
  });

  it("resends a vote refused with 503 under the same submission id", async () => {
    vi.useFakeTimers();
    const api = audienceApi();
    vi.mocked(api.submitVote)
      .mockRejectedValueOnce(busy(1))
      .mockRejectedValueOnce(busy(2))
      .mockResolvedValueOnce({ vote_submitted: true });
    render(<AudienceInteractionForm accessToken="token" api={api} />);
    await settle();
    fireEvent.change(screen.getByLabelText("Nickname"), {
      target: { value: "Learner" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^Vote$/ }));
    await settle();
    expect(screen.getByText("It's busy right now, retrying…")).toBeTruthy();
    expect(
      (screen.getByRole("button", { name: /Submitting/ }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    await advance(1000); // first resend after max(1 s, Retry-After 1 s)
    await advance(2000); // second after max(2 s, Retry-After 2 s)
    expect(api.submitVote).toHaveBeenCalledTimes(3);
    const payloads = vi
      .mocked(api.submitVote)
      .mock.calls.map((call) => call[1]);
    expect(
      new Set(payloads.map((item) => item.client_submission_id)).size,
    ).toBe(1);
    expect(screen.queryByText("It's busy right now, retrying…")).toBeNull();
    expect(screen.getByText("Submitted")).toBeTruthy();
  });

  it("stops after five busy answers and keeps the vote for a manual resend", async () => {
    vi.useFakeTimers();
    const api = audienceApi();
    vi.mocked(api.submitVote).mockRejectedValue(busy(1));
    render(<AudienceInteractionForm accessToken="token" api={api} />);
    await settle();
    fireEvent.change(screen.getByLabelText("Nickname"), {
      target: { value: "Learner" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^Vote$/ }));
    await advance(60_000);
    expect(api.submitVote).toHaveBeenCalledTimes(5);
    expect(screen.queryByText("It's busy right now, retrying…")).toBeNull();
    expect(screen.getByText("busy")).toBeTruthy();
    expect(
      (screen.getByRole("button", { name: /^Vote$/ }) as HTMLButtonElement)
        .disabled,
    ).toBe(false);
  });

  it("asks a fast barrage sender to wait and does not resend it", async () => {
    vi.useFakeTimers();
    const api = audienceApi();
    vi.mocked(api.submitBarrage).mockRejectedValueOnce(
      new PlatformApiError(429, "slow down", {
        code: "debate_rate_limited",
        details: { retry_after_seconds: 3 },
      }),
    );
    render(<AudienceInteractionForm accessToken="token" api={api} />);
    await settle();
    fireEvent.change(screen.getByLabelText("Nickname"), {
      target: { value: "Learner" },
    });
    fireEvent.change(screen.getByRole("textbox", { name: "Barrage" }), {
      target: { value: "Again!" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await settle();
    expect(
      screen.getByText("Sending too fast. Wait 3 s and send again."),
    ).toBeTruthy();
    await advance(10_000);
    expect(api.submitBarrage).toHaveBeenCalledTimes(1);
    expect(
      (screen.getByRole("textbox", { name: "Barrage" }) as HTMLTextAreaElement)
        .value,
    ).toBe("Again!");
  });

  it("sends one stable X-Maya-Audience id with votes and barrages", async () => {
    const seen: Array<{ url: string; headers: Record<string, string> }> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        seen.push({
          url,
          headers: (init?.headers ?? {}) as Record<string, string>,
        });
        const body = url.endsWith("/votes")
          ? { vote_submitted: true }
          : url.endsWith("/barrages")
            ? { barrage_submitted: true }
            : form;
        return new Response(JSON.stringify(body), {
          status:
            url.endsWith("/votes") || url.endsWith("/barrages") ? 201 : 200,
          headers: { "Content-Type": "application/json" },
        });
      }),
    );
    render(<AudienceInteractionForm accessToken="token" />);
    await screen.findByRole("heading", { name: form.topic });
    fireEvent.change(screen.getByLabelText("Nickname"), {
      target: { value: "Learner" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^Vote$/ }));
    await screen.findByText("Submitted");
    fireEvent.change(screen.getByRole("textbox", { name: "Barrage" }), {
      target: { value: "Hello" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await screen.findAllByText("Submitted");
    const posts = seen.filter(
      (item) => item.url.endsWith("/votes") || item.url.endsWith("/barrages"),
    );
    expect(posts).toHaveLength(2);
    const ids = posts.map((item) => item.headers["X-Maya-Audience"]);
    expect(ids[0]).toBeTruthy();
    expect(ids[1]).toBe(ids[0]);
    expect(window.localStorage.getItem("maya-audience-id")).toBe(ids[0]);
  });
});
