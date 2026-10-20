import { afterEach, describe, expect, it, vi } from "vitest";
import { isConflict, PlatformApi } from "../lib/api";

/**
 * After a 409 stale_revision, "refresh" (re-reading the version) must return
 * the latest revision -- no client cache may serve the old one -- and the
 * save that follows with that revision must succeed.
 */
describe("stale save -> refresh -> save", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("re-reads the latest Agent draft revision and the next save succeeds", async () => {
    let revision = 1; // a groupmate already saved once
    let agentMd = "# A\nGroupmate";
    const json = (status: number, body: unknown) =>
      new Response(JSON.stringify(body), {
        status,
        headers: { "content-type": "application/json" },
      });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const request =
          input instanceof Request ? input : new Request(input, init);
        const version = () => ({
          id: "v1",
          revision,
          agent_md: agentMd,
          state: "draft",
        });
        if (request.method === "GET") return json(200, version());
        const body = (await request.json()) as {
          expected_revision: number;
          agent_md: string;
        };
        if (body.expected_revision !== revision)
          return json(409, {
            code: "stale_revision",
            message: "stale",
            details: { current_revision: revision },
          });
        revision += 1;
        agentMd = body.agent_md;
        return json(200, version());
      }),
    );
    const api = new PlatformApi({
      baseUrl: "http://test/api/v1",
      csrfToken: "c",
    });
    await api.version("v1");
    const stale = await api
      .updateDraft("v1", { expected_revision: 0, agent_md: "# A\nMine" })
      .catch((cause: unknown) => cause);
    expect(isConflict(stale)).toBe(true);
    const fresh = await api.version("v1");
    expect(fresh.revision).toBe(1);
    expect(fresh.agent_md).toContain("Groupmate");
    const saved = await api.updateDraft("v1", {
      expected_revision: fresh.revision,
      agent_md: "# A\nMine",
    });
    expect(saved.revision).toBe(2);
  });
});
