import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({
    children,
    href,
  }: {
    children: React.ReactNode;
    href: string;
  }) => <a href={href}>{children}</a>,
}));

const session = vi.hoisted(() => ({
  api: { groupOverview: vi.fn() },
}));

vi.mock("../components/session-provider", () => ({
  useSession: () => session,
}));

import { GroupOverview } from "../components/group-overview";
import { LocaleProvider } from "../components/locale";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const overview = {
  group_id: "group-1",
  members: [
    {
      user_id: "ada",
      display_name: "Ada",
      avatar: null,
      agents: [{ id: "agent-1", name: "Quiet voice", visibility: "private" }],
      teams: [{ id: "team-1", name: "Study circle", visibility: "public" }],
      rag_count: 2,
      voice_count: 0,
    },
  ],
  results: [
    {
      attempt_id: "attempt-1",
      user_id: "ada",
      student_name: "Ada",
      test_name: "Keynotes · Formal diagnostic questions · V1.0",
      team_name: "Keynotes",
      status: "completed",
      phase: "completed",
      conversation_id: "4afc794f-1111-4111-8111-111111111111",
      started_at: "2026-10-13T08:00:00Z",
      ended_at: "2026-10-13T08:20:00Z",
      points_awarded: 3,
      points_total: 4,
      questions: [
        {
          number: 1,
          prompt: "What is ren?",
          answers: ["Humaneness"],
          skipped: false,
          points_awarded: 1,
          points_total: 1,
          feedback: "Right.",
        },
      ],
      report_download_path: "/api/v1/learning/reports/r/download?revision_id=v",
    },
  ],
  activity: [
    {
      kind: "agent_published",
      at: "2026-10-13T09:00:00Z",
      user_id: "ada",
      display_name: "Ada",
      title: "Quiet voice V1.1",
    },
  ],
};

describe("group overview", () => {
  it("shows members' work and recent activity, without test results", async () => {
    session.api.groupOverview.mockResolvedValue(overview);
    render(
      <LocaleProvider initialLocale="en">
        <GroupOverview groupId="group-1" />
      </LocaleProvider>,
    );

    const ada = await screen.findByRole("button", {
      name: /Ada.*Agents 1 · Teams 1 · RAG 2/,
    });
    expect(session.api.groupOverview).toHaveBeenCalledWith("group-1");
    fireEvent.click(ada);
    expect(
      screen.getByRole("link", { name: "Quiet voice" }).getAttribute("href"),
    ).toBe("/student/agents/agent-1");
    expect(
      screen.getByRole("link", { name: "Study circle" }).getAttribute("href"),
    ).toBe("/student/groups/group-1?mode=team-edit&team_id=team-1");

    // Results moved to the teacher's Brainform Record.
    expect(screen.queryByText(/Keynotes/)).toBeNull();
    expect(screen.queryByRole("link", { name: "Report" })).toBeNull();

    expect(screen.getByText("published Quiet voice V1.1")).toBeTruthy();
  });

  it("says when there is nothing to show yet", async () => {
    session.api.groupOverview.mockResolvedValue({
      group_id: "group-1",
      members: [],
      results: [],
      activity: [],
    });
    render(
      <LocaleProvider initialLocale="zh">
        <GroupOverview groupId="group-1" />
      </LocaleProvider>,
    );
    expect(await screen.findByText("这个组还没有学生。")).toBeTruthy();
    expect(screen.queryByText("还没有测试成绩。")).toBeNull();
    expect(screen.getByText("还没有动态。")).toBeTruthy();
  });
});
