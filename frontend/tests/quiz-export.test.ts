import { afterEach, describe, expect, it, vi } from "vitest";

import { QuizApi } from "../lib/api/quiz";
import { PlatformApi, PlatformApiError } from "../lib/api/platform";
import {
  exportQuizAttemptsPath,
  shouldShowExportDownload,
} from "../lib/quiz-urls";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("shouldShowExportDownload", () => {
  it("shows Download only when quiz_id is present", () => {
    expect(
      shouldShowExportDownload("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"),
    ).toBe(true);
    expect(shouldShowExportDownload(undefined)).toBe(false);
    expect(shouldShowExportDownload(null)).toBe(false);
    expect(shouldShowExportDownload("")).toBe(false);
    expect(shouldShowExportDownload("   ")).toBe(false);
  });
});

describe("exportQuizAttemptsPath", () => {
  it("builds the attempts/export path with encoded ids", () => {
    expect(exportQuizAttemptsPath("course/1", "quiz 2")).toBe(
      "courses/course%2F1/quizzes/quiz%202/attempts/export",
    );
  });
});

describe("QuizApi.exportAttempts", () => {
  it("fetches a zip blob and reads Content-Disposition filename", async () => {
    const zipBytes = new Uint8Array([0x50, 0x4b, 0x03, 0x04]);
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(zipBytes, {
        status: 200,
        headers: {
          "Content-Type": "application/zip",
          "Content-Disposition":
            'attachment; filename="quiz-demo-attempts.zip"',
        },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const platform = new PlatformApi({ baseUrl: "http://maya.test/api/v1" });
    vi.spyOn(platform, "getCsrfToken").mockReturnValue("csrf-token");
    const quizApi = new QuizApi(platform);

    const result = await quizApi.exportAttempts("course-1", "quiz-abcdef01");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(path).toBe(
      "/api/v1/courses/course-1/quizzes/quiz-abcdef01/attempts/export",
    );
    expect(init.method).toBe("GET");
    expect(init.credentials).toBe("include");
    expect((init.headers as Record<string, string>)["X-CSRF-Token"]).toBe(
      "csrf-token",
    );
    expect(result.filename).toBe("quiz-demo-attempts.zip");
    expect(result.blob).toBeInstanceOf(Blob);
    expect(result.blob.type).toContain("zip");
  });

  it("throws PlatformApiError on non-OK without parsing JSON body as success", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: { message: "Forbidden" } }), {
        status: 403,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const platform = new PlatformApi({ baseUrl: "http://maya.test/api/v1" });
    const quizApi = new QuizApi(platform);

    await expect(
      quizApi.exportAttempts("course-1", "quiz-1"),
    ).rejects.toBeInstanceOf(PlatformApiError);
  });
});
