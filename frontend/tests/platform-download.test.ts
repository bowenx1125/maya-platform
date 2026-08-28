import { afterEach, describe, expect, it, vi } from "vitest";

import { PlatformApi, responseDownloadFilename } from "../lib/api/platform";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("server Content-Disposition filename parsing", () => {
  it("prefers a valid UTF-8 filename* from a real Response", () => {
    const response = new Response("body", {
      headers: {
        "Content-Disposition":
          "attachment; filename=\"fallback.md\"; filename*=UTF-8''%E8%AF%81%E6%8D%AE--Agent.md",
      },
    });
    expect(responseDownloadFilename(response, "fallback.md")).toBe(
      "证据--Agent.md",
    );
  });

  it("accepts the ASCII filename fallback", () => {
    const response = new Response("body", {
      headers: { "Content-Disposition": 'attachment; filename="Agent--V1.md"' },
    });
    expect(responseDownloadFilename(response, "fallback.md")).toBe(
      "Agent--V1.md",
    );
  });

  it.each([
    "attachment; filename*=UTF-8''%E0%A4%A",
    'attachment; filename="../escape.md"',
    "attachment; filename*=UTF-8''..%2Fescape.md",
    'attachment; filename="nested\\\\escape.md"',
    "attachment; filename*=UTF-8''safe%00.md",
  ])("falls back for malformed or unsafe server names: %s", (header) => {
    const response = new Response("body", {
      headers: { "Content-Disposition": header },
    });
    expect(responseDownloadFilename(response, "safe-fallback.md")).toBe(
      "safe-fallback.md",
    );
  });

  it("uses the caller fallback when the response has no filename", () => {
    expect(responseDownloadFilename(new Response("body"), "safe.md")).toBe(
      "safe.md",
    );
  });

  it("uses the server response filename instead of the caller fallback", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response("# retained source", {
        headers: {
          "Content-Disposition": 'attachment; filename="server-source.md"',
        },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const api = new PlatformApi({ baseUrl: "http://maya.test/api/v1" });
    const downloaded = await api.downloadKnowledge(
      "11111111-1111-4111-8111-111111111111",
      "caller-fallback.md",
    );

    expect(downloaded.filename).toBe("server-source.md");
    expect(downloaded.filename).not.toBe("caller-fallback.md");
    expect(downloaded.content).toBe("# retained source");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
