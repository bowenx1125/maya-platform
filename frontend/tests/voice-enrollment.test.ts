// @vitest-environment node

import { afterEach, describe, expect, it, vi } from "vitest";
import { PlatformApi } from "../lib/api/platform";

afterEach(() => vi.unstubAllGlobals());

describe("voice enrollment API defaults", () => {
  it("omits the sample language while retaining upload consent and idempotency", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id: "voice-id", status: "enrolling" }), {
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const client = new PlatformApi({
      baseUrl: "http://maya.test/api/v1",
      csrfToken: "test-csrf",
    });
    await client.enrollVoice(
      "group-a",
      new File(["sample"], "sample.wav", { type: "audio/wav" }),
      "voice-consent-v1",
    );
    const request = fetchMock.mock.calls[0][0] as Request;
    expect(request.method).toBe("POST");
    expect(request.headers.get("Idempotency-Key")).toBeTruthy();
    expect(request.headers.get("X-CSRF-Token")).toBe("test-csrf");
    const form = await request.formData();
    expect(form.has("language")).toBe(false);
    expect(form.get("consent_accepted")).toBe("true");
    expect(form.get("consent_copy_version")).toBe("voice-consent-v1");
    expect(form.get("file")).toHaveProperty("name", "sample.wav");
  });
});
