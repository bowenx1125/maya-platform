import { afterEach, expect, it, vi } from "vitest";
import { PlatformApi } from "../lib/api";

afterEach(() => vi.restoreAllMocks());

it("awaits and validates defaults from the real API client", async () => {
  const defaults = {
    language: "en",
    participants: 2,
    rate: 1,
    round_unit_caps: [90, 75, 75, 90],
    estimated_duration_minutes: 4.89,
  };
  const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify(defaults), {
      headers: { "Content-Type": "application/json" },
    }),
  );
  const api = new PlatformApi({ baseUrl: "http://localhost/api/v1" });
  await expect(
    api.loadRoundUnitCapDefaults({
      courseId: "course",
      language: "en",
      participants: 2,
      rate: 1,
    }),
  ).resolves.toEqual(defaults);
  const url = new URL((fetch.mock.calls[0][0] as Request).url);
  expect(url.pathname).toBe(
    "/api/v1/courses/course/debate-round-unit-cap-defaults",
  );
  expect(Object.fromEntries(url.searchParams)).toEqual({
    language: "en",
    participants: "2",
    rate: "1",
  });
});

it.each([
  [25, 25, 25],
  [25, 25, 25, 2001],
  [25, 25, 25, 24],
  [25, 25, 25, 25.5],
])("rejects malformed server caps %j", async (...caps) => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(
      JSON.stringify({
        round_unit_caps: caps,
      }),
      { headers: { "Content-Type": "application/json" } },
    ),
  );
  const api = new PlatformApi({ baseUrl: "http://localhost/api/v1" });
  await expect(
    api.loadRoundUnitCapDefaults({
      courseId: "course",
      language: "en",
      participants: 2,
      rate: 1,
    }),
  ).rejects.toMatchObject({ code: "debate_round_unit_caps_invalid" });
});
