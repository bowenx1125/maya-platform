import {
  cleanup,
  fireEvent,
  render as renderComponent,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { PublishedAgentSummary } from "../lib/api";
import { PlatformApiError } from "../lib/api";
import {
  agentIssuesFromError,
  agentMdIsStandard,
  versionIssues,
} from "../lib/agent-readiness";
import { LocaleProvider } from "../components/locale";

const useSessionMock = vi.hoisted(() => vi.fn());

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  usePathname: () => "/teacher/debates/new",
}));
vi.mock("../components/session-provider", () => ({
  useSession: useSessionMock,
}));

import { TeacherDebateCreate } from "../components/debate/setup/debate-setup";
import { AgentIssueList } from "../components/agent-issue-list";
import { AppShell } from "../components/app-shell";

const courseId = "b1ae79ed-e4a6-5b02-9abd-3a3ae944284b";

afterEach(() => {
  cleanup();
  useSessionMock.mockReset();
});

function candidate(
  id: string,
  name: string,
  voice: string | null = "voice-1",
): PublishedAgentSummary {
  return {
    group_name: `${name} Group`,
    agent: {
      id,
      group_id: `${id}-group`,
      name,
      description: "",
      status: "active",
      current_published_version_id: `${id}-version`,
      current_draft_version_id: null,
    },
    current_version: {
      id: `${id}-version`,
      agent_id: id,
      version_label: "V1.0",
      state: "published",
      revision: 1,
      voice_profile_id: voice,
      agent_md: `# ${name}\n\nText.`,
      knowledge_snapshot_id: `${id}-snapshot`,
    },
  } as PublishedAgentSummary;
}

describe("agent readiness rules", () => {
  it("states the AGENT.md rule as a heading plus text", () => {
    expect(agentMdIsStandard("# 朱熹\n\n格物致知。")).toBe(true);
    expect(agentMdIsStandard("格物致知。")).toBe(false);
    expect(agentMdIsStandard("# 朱熹\n## 只有标题")).toBe(false);
  });

  it("names RAG, Voice None and AGENT.md problems for one Agent", () => {
    const issues = versionIssues(
      { id: "a", name: "朱熹" },
      { agent_md: "只有正文", voice_profile_id: null },
      { ragCount: 0 },
    );
    expect(issues.map((item) => item.issue)).toEqual([
      "rag_missing",
      "voice_missing",
      "agent_md_invalid",
    ]);
  });

  it("reads the structured issues of a refused Debate create", () => {
    const error = new PlatformApiError(422, "not ready", {
      code: "debate_agents_not_ready",
      details: {
        issues: [
          { agent_id: "a", agent_name: "朱熹", issue: "rag_missing" },
          { agent_id: "b", agent_name: "?", issue: "unknown_kind" },
        ],
      },
    });
    expect(agentIssuesFromError(error)).toEqual([
      { agent_id: "a", agent_name: "朱熹", issue: "rag_missing" },
    ]);
    expect(agentIssuesFromError(new Error("plain"))).toBeNull();
  });

  it("renders each issue in Chinese with a pencil to that Agent", () => {
    renderComponent(
      <LocaleProvider initialLocale="zh">
        <AgentIssueList
          issues={[
            { agent_id: "a-1", agent_name: "朱熹", issue: "rag_missing" },
          ]}
          editHref={(id) => `/teacher/agents/${id}`}
        />
      </LocaleProvider>,
    );
    expect(screen.getByText("Agent「朱熹」至少需要一个 RAG。")).toBeTruthy();
    expect(
      screen.getByRole("link", { name: "编辑 Agent「朱熹」" }),
    ).toHaveProperty("pathname", "/teacher/agents/a-1");
  });
});

describe("Debate create names every Agent problem", () => {
  it("lists the refused Agents with an edit pencil each", async () => {
    useSessionMock.mockReturnValue({
      api: {},
      user: { courses: [{ course_id: courseId, role: "teacher" }] },
    });
    const create = vi.fn().mockRejectedValue(
      new PlatformApiError(422, "Some selected Agents are not ready.", {
        code: "debate_agents_not_ready",
        details: {
          issues: [
            { agent_id: "zhuxi", agent_name: "Zhu Xi", issue: "rag_missing" },
            {
              agent_id: "wang",
              agent_name: "Wang",
              issue: "agent_md_invalid",
            },
          ],
        },
      }),
    );
    renderComponent(
      <AppShell role="teacher">
        <TeacherDebateCreate
          controller={{
            loadRuleset: vi
              .fn()
              .mockResolvedValue({ zh: "# 中文", en: "# En" }),
            loadCandidates: vi
              .fn()
              .mockResolvedValue([
                candidate("zhuxi", "Zhu Xi"),
                candidate("wang", "Wang", null),
              ]),
            create,
          }}
        />
      </AppShell>,
    );
    fireEvent.click(await screen.findByRole("button", { name: /Zhu Xi/ }));
    fireEvent.click(screen.getByRole("button", { name: /Wang/ }));
    // Voice None is shown per Agent before submit, with its pencil.
    expect(
      screen.getByText(
        "Agent “Wang” has no Voice (Voice is None). The Debate will use the platform voice or show text only.",
      ),
    ).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Topic"), {
      target: { value: "How should people learn together?" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() => expect(create).toHaveBeenCalled());
    const alert = await screen.findByText(
      "Fix these Agents before the Debate can be created:",
    );
    const notice = alert.closest(".notice") as HTMLElement;
    expect(
      within(notice).getByText("Agent “Zhu Xi” needs at least one RAG file."),
    ).toBeTruthy();
    expect(
      within(notice).getByRole("link", { name: "Edit Agent “Zhu Xi”" }),
    ).toHaveProperty("pathname", "/teacher/agents/zhuxi");
    expect(
      within(notice).getByRole("link", { name: "Edit Agent “Wang”" }),
    ).toHaveProperty("pathname", "/teacher/agents/wang");
  });
});

describe("specific errors with a way to fix them", () => {
  it("names the Agent a Team refused and links to it", async () => {
    const { localizeError } = await import("../lib/i18n");
    const { ErrorNotice } = await import("../components/ui");
    const error = new PlatformApiError(422, "public team", {
      code: "team_member_private",
      details: { agent_id: "agent-zx", agent_name: "朱熹" },
    });
    expect(localizeError(error, "zh")).toBe(
      "Agent「朱熹」是 Private，Public Team 只能放 Public 的 Agent。请把它改成 Public 或移出 Team。",
    );
    renderComponent(
      <LocaleProvider initialLocale="en">
        <ErrorNotice inline error={error} />
      </LocaleProvider>,
    );
    expect(
      screen.getByRole("link", { name: "Edit Agent “朱熹”" }),
    ).toHaveProperty("pathname", "/teacher/agents/agent-zx");
  });

  it("names the reader's own Teams that still hold an Agent", async () => {
    const { localizeError } = await import("../lib/i18n");
    const { ErrorNotice } = await import("../components/ui");
    const error = new PlatformApiError(409, "in team", {
      code: "agent_in_team",
      details: {
        teams: [{ team_id: "t-1", team_name: "伦理圈", group_id: null }],
        other_team_count: 2,
      },
    });
    expect(localizeError(error, "zh")).toBe(
      "这个 Agent 还在 Team「伦理圈」里，请先在 Team 里移除它。 这个 Agent 还在别人的 2 个 Team 里，需要 Team 的创建者先移除它。",
    );
    renderComponent(
      <LocaleProvider initialLocale="zh">
        <ErrorNotice inline error={error} />
      </LocaleProvider>,
    );
    const link = screen.getByRole("link", { name: "编辑 Team「伦理圈」" });
    expect(link.getAttribute("href")).toBe(
      "/teacher/studyform?mode=team-edit&team_id=t-1",
    );
  });

  it("never falls back to a bare request-failed line when a code exists", async () => {
    const { localizeError } = await import("../lib/i18n");
    expect(localizeError({ code: "some_new_code" }, "zh")).toBe(
      "请求没有完成（错误代码：some_new_code）。",
    );
    expect(
      localizeError(
        new PlatformApiError(409, "", { code: "next_not_ready" }),
        "zh",
      ),
    ).toBe("下一段发言还在准备，准备好后就能点 Next。");
  });
});
