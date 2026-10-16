import { afterEach, describe, expect, it } from "vitest";
import {
  LOGIN_QUEUE_STORAGE_KEY,
  clearLoginQueue,
  loadLoginQueue,
  loginQueueProgress,
  saveLoginQueue,
} from "../lib/login-queue";

const TICKET = "3f2b8c1e-8d1a-4c3e-9a77-1b2c3d4e5f60";

describe("login queue persistence", () => {
  afterEach(() => window.sessionStorage.clear());

  it("keeps the ticket and username but never the password", () => {
    const saved = saveLoginQueue(
      "maya",
      {
        ticket: TICKET,
        position: 5,
        retryAfterSeconds: 2,
        queueLength: 9,
        estimatedWaitSeconds: 12,
        ticketExpiresInSeconds: 180,
      },
      null,
      1_000,
    );
    expect(saved?.initialPosition).toBe(5);
    const raw = window.sessionStorage.getItem(LOGIN_QUEUE_STORAGE_KEY) ?? "";
    expect(raw).not.toMatch(/password/i);
    const loaded = loadLoginQueue(2_000);
    expect(loaded).toMatchObject({
      ticket: TICKET,
      username: "maya",
      position: 5,
    });

    // Moving forward keeps the original baseline for the progress bar.
    const later = saveLoginQueue(
      "maya",
      {
        ticket: TICKET,
        position: 2,
        retryAfterSeconds: 2,
        queueLength: 6,
        estimatedWaitSeconds: 6,
        ticketExpiresInSeconds: 180,
      },
      loaded,
      3_000,
    );
    expect(later?.initialPosition).toBe(5);
    expect(later?.position).toBe(2);
  });

  it("drops expired or malformed tickets", () => {
    saveLoginQueue(
      "maya",
      {
        ticket: TICKET,
        position: 1,
        retryAfterSeconds: 2,
        queueLength: 2,
        estimatedWaitSeconds: 4,
        ticketExpiresInSeconds: 10,
      },
      null,
      0,
    );
    expect(loadLoginQueue(20_000)).toBeNull();
    expect(window.sessionStorage.getItem(LOGIN_QUEUE_STORAGE_KEY)).toBeNull();
    window.sessionStorage.setItem(
      LOGIN_QUEUE_STORAGE_KEY,
      JSON.stringify({
        ticket: "x",
        username: "m",
        expiresAt: Date.now() + 9e6,
      }),
    );
    expect(loadLoginQueue()).toBeNull();
    clearLoginQueue();
  });

  it("progress grows as the position falls and stays within bounds", () => {
    const start = loginQueueProgress(10, 10);
    const mid = loginQueueProgress(5, 10);
    const near = loginQueueProgress(0, 10);
    expect(start).toBeGreaterThan(0);
    expect(mid).toBeGreaterThan(start);
    expect(near).toBeGreaterThan(mid);
    expect(near).toBeLessThan(1);
  });
});
