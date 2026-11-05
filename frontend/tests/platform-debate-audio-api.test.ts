import { afterEach, expect, it, vi } from "vitest";
import { IdempotencyHandle, PlatformApi } from "../lib/api";

afterEach(() => vi.restoreAllMocks());

it("restores the saved idempotency key and retains it while audio is queued", async () => {
  const fetch = vi.spyOn(globalThis, "fetch").mockImplementation(
    async () =>
      new Response(JSON.stringify({ status: "queued", audio_ready: false }), {
        status: 200,
      }),
  );
  const api = new PlatformApi({
    baseUrl: "http://localhost/api/v1",
    csrfToken: "test-csrf",
  });
  const handle = new IdempotencyHandle("persisted-audio-request");
  await api.regenerateDebateTurnAudio(
    "debate",
    "turn",
    { expected_revision: 2 },
    { idempotency: handle },
  );
  await api.regenerateDebateTurnAudio(
    "debate",
    "turn",
    { expected_revision: 2 },
    { idempotency: handle },
  );
  expect(fetch).toHaveBeenCalledTimes(2);
  for (const [request] of fetch.mock.calls) {
    expect((request as Request).headers.get("Idempotency-Key")).toBe(
      "persisted-audio-request",
    );
  }
});
