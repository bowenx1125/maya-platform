import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  usePathname: () => "/student/chat",
  useSearchParams: () => new URLSearchParams("kind=agent&mode=new"),
}));

const pending = () => new Promise(() => undefined);

vi.mock("../components/session-provider", () => ({
  useSession: () => ({
    api: new Proxy(
      {},
      {
        get: () => pending,
      },
    ),
    user: {
      id: "student-id",
      courses: [{ course_id: "course-id", role: "student" }],
      groups: [{ group_id: "group-id", role: "member" }],
    },
    identityGeneration: 1,
    status: "authenticated",
  }),
}));

import { AgentChat } from "../components/agent-chat";
import { AgentOverview, AgentWorkbench } from "../components/agent-workspace";

afterEach(cleanup);

function expectPageLoader() {
  const card = document.querySelector(".loading-card");
  expect(card).toBeTruthy();
  expect(card?.className).toContain("loading-card--lg");
  expect(card?.className).not.toContain("loading-card--sm");
  expect((card as HTMLElement).dataset.size).toBe("lg");
}

describe("page-level loading cards", () => {
  it("uses the large loader while the agent editor is loading", () => {
    render(<AgentWorkbench versionId="version-id" publishOnDone />);
    expectPageLoader();
  });

  it("uses the large loader while an agent overview is loading", () => {
    render(<AgentOverview agentId="agent-id" />);
    expectPageLoader();
  });

  it("uses the large loader on New Agent chat before the catalog arrives", () => {
    render(<AgentChat />);
    expectPageLoader();
  });
});
