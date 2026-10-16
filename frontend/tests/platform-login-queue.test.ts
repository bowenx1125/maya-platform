import { afterEach, describe, expect, it, vi } from "vitest";

import { PlatformApi } from "../lib/api/platform";
import type { LoginQueueNotice } from "../lib/login-queue";

const TICKET = "3f2b8c1e-8d1a-4c3e-9a77-1b2c3d4e5f60";

function queued(position: number) {
  return new Response(
    JSON.stringify({
      code: "auth_login_queued",
      message: "Waiting to enter.",
      details: {
        position,
        retry_after_seconds: 1,
        queue_length: position + 1,
        estimated_wait_seconds: position + 1,
        ticket: TICKET,
        ticket_expires_in_seconds: 180,
      },
    }),
    { status: 429, headers: { "content-type": "application/json" } },
  );
}

function ticketHeader(call: unknown[]): string | null {
  const [input, init] = call as [RequestInfo | URL, RequestInit | undefined];
  if (input instanceof Request)
    return input.headers.get("X-Auth-Admission-Ticket");
  return new Headers(init?.headers).get("X-Auth-Admission-Ticket");
}

describe("login queue client", () => {
  afterEach(() => vi.restoreAllMocks());

  it("re-sends the same ticket across retries and a brief network drop", async () => {
    const session = { csrf_token: "csrf-1", user: { courses: [] } };
    const fetchMock = vi.spyOn(globalThis, "fetch");
    fetchMock
      .mockResolvedValueOnce(queued(2))
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce(queued(0))
      .mockResolvedValueOnce(
        new Response(JSON.stringify(session), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      );
    const notices: LoginQueueNotice[] = [];
    const api = new PlatformApi({ baseUrl: "http://localhost/api/v1" });
    await api.login("maya", "secret", { onQueued: (n) => notices.push(n) });

    expect(ticketHeader(fetchMock.mock.calls[0])).toBeNull();
    for (const call of fetchMock.mock.calls.slice(1)) {
      expect(ticketHeader(call)).toBe(TICKET);
    }
    expect(notices.map((n) => [n.position, Boolean(n.reconnecting)])).toEqual([
      [2, false],
      [2, true],
      [0, false],
    ]);
    expect(notices[0]).toMatchObject({
      queueLength: 3,
      estimatedWaitSeconds: 3,
    });
  }, 15_000);

  it("resumes with a ticket kept from before a page refresh", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ csrf_token: "c", user: { courses: [] } }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    const api = new PlatformApi({ baseUrl: "http://localhost/api/v1" });
    await api.login("maya", "secret", { ticket: TICKET });
    expect(ticketHeader(fetchMock.mock.calls[0])).toBe(TICKET);
  });

  it("does not retry a network failure when not queued", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(
      new TypeError("offline"),
    );
    const api = new PlatformApi({ baseUrl: "http://localhost/api/v1" });
    await expect(api.login("maya", "secret")).rejects.toBeInstanceOf(TypeError);
  });
});
