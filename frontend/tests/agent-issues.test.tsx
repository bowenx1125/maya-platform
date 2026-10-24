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
  debateFieldProblems,
  mergeIssues,
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

import {
  TeacherDebateCreate,
  type DebateCreateController,
} from "../components/debate/setup/debate-setup";
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
  issues: string[] = [],
): PublishedAgentSummary {
  return {
    readiness_issues: issues.map((issue) => ({
      agent_id: id,
      agent_name: name,
      issue,
      blocking: issue !== "voice_missing",
      message: issue,
    })),
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
      voice_profile_id: issues.includes("voice_missing") ? null : "voice-1",
      agent_md: `# ${name}\n\nText.`,
      knowledge_snapshot_id: `${id}-snapshot`,
    },
  } as PublishedAgentSummary;
}

describe("agent readiness rules", () => {
  it("reads the structured issues of a refused Debate create", () => {
    const error = new PlatformApiError(422, "not ready", {
      code: "debate_agents_not_ready",
      details: {
        issues: [
          { agent_id: "a", agent_name: "朱熹", issue: "rag_missing" },
          { agent_id: "c", agent_name: "", issue: "agent_not_found" },
          { agent_id: "b", agent_name: "?", issue: "unknown_kind" },
        ],
      },
    });
    expect(agentIssuesFromError(error)).toEqual([
      {
        agent_id: "a",
        agent_name: "朱熹",
        issue: "rag_missing",
        blocking: true,
      },
      {
        agent_id: "c",
        agent_name: "",
        issue: "agent_not_found",
        blocking: true,
      },
    ]);
    expect(agentIssuesFromError(new Error("plain"))).toBeNull();
  });

  it("merges the server's and the form's issues once, filling unknown names", () => {
    const merged = mergeIssues(
      [
        [{ agent_id: "c", agent_name: "", issue: "agent_not_found" }],
        [
          { agent_id: "c", agent_name: "", issue: "agent_not_found" },
          { agent_id: "a", agent_name: "朱熹", issue: "voice_missing" },
        ],
      ],
      { c: "王阳明" },
    );
    expect(merged.map((item) => [item.agent_name, item.issue])).toEqual([
      ["王阳明", "agent_not_found"],
      ["朱熹", "voice_missing"],
    ]);
  });

  it("turns a malformed request into one sentence per field", () => {
    const error = new PlatformApiError(400, "bad", {
      code: "malformed_request",
      details: {
        fields: [],
        errors: [
          { field: "topic", type: "topic_blank" },
          { field: "participants", type: "participants_duplicate" },
          { field: "participants.1", type: "assigned_stance_missing" },
          { field: "teaching_prompts.zh", type: "string_type" },
        ],
      },
    });
    expect(
      debateFieldProblems(error, (index) => ["朱熹", "王阳明"][index])?.map(
        (item) => [item.key, item.params?.name ?? ""],
      ),
    ).toEqual([
      ["debateFieldTopicBlank", ""],
      ["debateFieldDuplicateAgent", ""],
      ["debateFieldStanceMissing", "王阳明"],
      ["debateFieldTeachingPrompts", ""],
    ]);
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

function renderCreate(
  candidates: PublishedAgentSummary[],
  create: DebateCreateController["create"],
) {
  useSessionMock.mockReturnValue({
    api: {},
    user: { courses: [{ course_id: courseId, role: "teacher" }] },
  });
  const loadCandidates = vi.fn().mockResolvedValue(candidates);
  const view = renderComponent(
    <AppShell role="teacher">
      <TeacherDebateCreate
        controller={{
          loadRuleset: vi.fn().mockResolvedValue({ zh: "# 中文", en: "# En" }),
          loadCandidates,
          create,
        }}
      />
    </AppShell>,
  );
  return { ...view, loadCandidates };
}

async function pickAndSubmit(names: string[], topic = "How should we learn?") {
  for (const name of names) {
    fireEvent.click(await screen.findByRole("button", { name }));
  }
  fireEvent.change(screen.getByLabelText("Topic"), {
    target: { value: topic },
  });
  fireEvent.click(screen.getByRole("button", { name: "Done" }));
}

function hintBar(): HTMLElement {
  const bar = document.querySelector(".agent-hint-bar") as HTMLElement | null;
  expect(bar).not.toBeNull();
  return bar as HTMLElement;
}

describe("Debate create names every Agent problem", () => {
  it("checks each Agent as it is picked, in one bar above the form, and sends nothing", async () => {
    const create = vi.fn();
    const { container } = renderCreate(
      [
        candidate("zhuxi", "Zhu Xi", ["rag_missing", "avatar_missing"]),
        candidate("wang", "Wang", ["voice_missing"]),
      ],
      create,
    );
    fireEvent.click(await screen.findByRole("button", { name: "Zhu Xi" }));
    fireEvent.click(screen.getByRole("button", { name: "Wang" }));
    const bar = hintBar();
    expect(bar.textContent).toContain("Fix these before creating the Debate:");
    // Blocking and Voice None lines share the bar and its look.
    for (const line of [
      "Agent “Zhu Xi” needs at least one RAG file.",
      "Agent “Zhu Xi” has no usable Avatar.",
      "Agent “Wang” has no Voice",
    ]) {
      expect(bar.textContent).toContain(line);
    }
    expect(
      within(bar).getByRole("link", { name: "Edit Agent “Wang”" }),
    ).toHaveProperty("pathname", "/teacher/agents/wang");
    expect(
      within(bar).getAllByRole("link", { name: "Edit Agent “Zhu Xi”" }),
    ).toHaveLength(2);
    const form = container.querySelector("form");
    expect(
      form &&
        bar.compareDocumentPosition(form) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Topic"), {
      target: { value: "How should we learn?" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(create).not.toHaveBeenCalled();
  });

  it("shows a refusal in the same bar, names the Agent, and reads the list again", async () => {
    const create = vi.fn().mockRejectedValue(
      new PlatformApiError(422, "Some selected Agents are not ready.", {
        code: "debate_agents_not_ready",
        details: {
          issues: [
            {
              agent_id: "zhuxi",
              agent_name: "Zhu Xi",
              issue: "agent_not_current",
            },
            { agent_id: "wang", agent_name: "", issue: "agent_not_found" },
          ],
        },
      }),
    );
    const { loadCandidates } = renderCreate(
      [
        candidate("zhuxi", "Zhu Xi"),
        candidate("wang", "Wang", ["voice_missing"]),
      ],
      create,
    );
    await pickAndSubmit(["Zhu Xi", "Wang"]);
    await waitFor(() => expect(create).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(loadCandidates).toHaveBeenCalledTimes(2));
    const bar = hintBar();
    expect(bar.textContent).toContain(
      "Agent “Zhu Xi” changed while the Debate was being created.",
    );
    expect(bar.textContent).toContain(
      "Agent “Wang” is no longer available in this course.",
    );
    expect(document.querySelectorAll(".agent-hint-bar")).toHaveLength(1);
    expect(
      screen.queryByText(/Please check the submitted information/),
    ).toBeNull();
  });

  it("names each wrong field instead of a generic line", async () => {
    const create = vi.fn().mockRejectedValue(
      new PlatformApiError(400, "bad", {
        code: "malformed_request",
        details: {
          fields: ["('body', 'participants')"],
          errors: [{ field: "participants", type: "participants_duplicate" }],
        },
      }),
    );
    renderCreate(
      [candidate("zhuxi", "Zhu Xi"), candidate("wang", "Wang")],
      create,
    );
    await pickAndSubmit(["Zhu Xi", "Wang"]);
    await waitFor(() =>
      expect(hintBar().textContent).toContain(
        "The same Agent is selected twice.",
      ),
    );
    expect(
      screen.queryByText(/Please check the submitted information/),
    ).toBeNull();
  });

  it("asks for a topic in any language, in the bar at the top", async () => {
    const create = vi.fn();
    renderCreate(
      [candidate("zhuxi", "Zhu Xi"), candidate("wang", "Wang")],
      create,
    );
    await pickAndSubmit(["Zhu Xi", "Wang"], "   ");
    expect(hintBar().textContent).toContain("Enter a topic.");
    expect(create).not.toHaveBeenCalled();
  });

  it("retries an unrelated failure by sending the form again", async () => {
    const create = vi
      .fn()
      .mockRejectedValueOnce(
        new PlatformApiError(503, "busy", { code: "provider_unavailable" }),
      )
      .mockResolvedValueOnce({ id: "debate-1" });
    const { loadCandidates } = renderCreate(
      [candidate("zhuxi", "Zhu Xi"), candidate("wang", "Wang")],
      create,
    );
    await pickAndSubmit(["Zhu Xi", "Wang"]);
    fireEvent.click(await screen.findByRole("button", { name: /Retry/ }));
    await waitFor(() => expect(create).toHaveBeenCalledTimes(2));
    expect(loadCandidates).toHaveBeenCalledTimes(1);
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
