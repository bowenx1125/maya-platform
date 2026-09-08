import { readFileSync } from "node:fs";

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  AgentDetail,
  AgentVersion,
  GroupDetail,
  KnowledgeSnapshot,
} from "../lib/api";
import { LocaleProvider } from "../components/locale";
import { TeacherDebateList } from "../components/debate/setup/debate-setup";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("../components/session-provider", () => ({
  useSession: vi.fn(),
}));

vi.mock("../components/avatar/avatar-preview", () => ({
  AvatarPreview: ({ fallbackLabel }: { fallbackLabel?: string }) => (
    <div
      role="img"
      aria-label={`${fallbackLabel ?? "avatar"} avatar preview`}
      data-readonly-avatar-preview="true"
    />
  ),
}));

import { useSession } from "../components/session-provider";
import {
  TeacherAgentDetail,
  TeacherDashboard,
} from "../components/teacher-workspace";

const mockedUseSession = vi.mocked(useSession);
const courseId = "course-id";
const groupId = "group-id";
const agentId = "agent-id";
const versionId = "version-id";
const snapshotId = "snapshot-id";

function version(): AgentVersion {
  return {
    id: versionId,
    agent_id: agentId,
    version_label: "V1.0",
    state: "published",
    revision: 1,
    agent_md: "# Published Agent",
    avatar_config: {
      template_id: "wave1-default-head",
      material_theme: "demo",
      eye_color: null,
      default_expression: "neutral",
      expression_strength: "medium",
      motion_style: "calm",
    },
    voice_profile_id: null,
    effective_voice_profile_id: null,
    voice_fallback_active: true,
    persona_confirmed: false,
    knowledge_snapshot_id: snapshotId,
    enabled_documents: [],
    publish_blockers: [],
  } as AgentVersion;
}

function agent(): AgentDetail {
  return {
    id: agentId,
    group_id: groupId,
    name: "Published Agent",
    description: "A released classroom perspective.",
    metadata_revision: 0,
    status: "active",
    current_published_version_id: versionId,
    current_draft_version_id: null,
    versions: [],
  } as AgentDetail;
}

function snapshot(): KnowledgeSnapshot {
  return {
    id: snapshotId,
    agent_version_id: versionId,
    content_hash: "hash",
    total_char_count: 24,
    documents: [],
    created_at: "2026-08-28T00:00:00Z",
  } as KnowledgeSnapshot;
}

function apiForTeacher() {
  const currentVersion = version();
  return {
    courses: vi.fn().mockResolvedValue([
      {
        id: courseId,
        code: "MAYA-101",
        name: "Cultural exchange",
        current_audio_debate_id: null,
      },
    ]),
    publishedAgents: vi.fn().mockResolvedValue([]),
    agent: vi.fn().mockResolvedValue(agent()),
    versions: vi.fn().mockResolvedValue([currentVersion]),
    group: vi.fn().mockResolvedValue({
      id: groupId,
      course_id: courseId,
      name: "Bowen group",
      members: [],
    } as GroupDetail),
    snapshot: vi.fn().mockResolvedValue(snapshot()),
    downloadSnapshot: vi.fn(),
    downloadSnapshotDocument: vi.fn(),
    downloadAgentMd: vi.fn(),
  };
}

describe("PW3-E teacher shell and responsive contract", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("keeps the stalled row unchanged when Remake fails", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const api = {
      debates: vi.fn().mockResolvedValue([
        {
          id: "debate-resume",
          topic: "A stalled classroom",
          status: "draft",
          created_at: "2026-09-08T00:00:00Z",
          round_count: 2,
          preview: { prepared_turns: 1, expected_turns: 2, ready: false },
          stall: {
            turn_id: "turn-resume",
            round_no: 1,
            safe_error_code: "invalid_state",
          },
        },
      ]),
      debate: vi
        .fn()
        .mockResolvedValue({ revision: 1, playback: { control_version: 4 } }),
      remakeDebate: vi
        .fn()
        .mockRejectedValue(
          new Error("That action is not available in the current state."),
        ),
    };
    mockedUseSession.mockReturnValue({
      api,
      user: { courses: [{ course_id: courseId, role: "teacher" }] },
    } as never);
    render(
      <LocaleProvider initialLocale="en">
        <TeacherDebateList />
      </LocaleProvider>,
    );
    const resume = await screen.findByRole("button", { name: "Remake" });
    fireEvent.click(resume);
    await waitFor(() => expect(api.remakeDebate).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(resume).toHaveProperty("disabled", false));
    expect(resume.textContent).toBe("Remake");
    expect(screen.getByText("A stalled classroom")).toBeTruthy();
    expect(screen.getByText("Stalled")).toBeTruthy();
    expect(
      screen.queryByText("That action is not available in the current state."),
    ).toBeNull();
    expect(api.debates).toHaveBeenCalledTimes(1);
  });

  it.each([{ locale: "en" as const }, { locale: "zh" as const }])(
    "loads the course without explaining itself ($locale)",
    async (caseData) => {
      const api = apiForTeacher();
      mockedUseSession.mockReturnValue({
        api,
        user: { courses: [{ course_id: courseId, role: "teacher" }] },
      } as never);
      render(
        <LocaleProvider initialLocale={caseData.locale}>
          <TeacherDashboard />
        </LocaleProvider>,
      );

      // The student-draft boundary used to be stated in a page lede, then in a
      // capabilities section, then again in five explainer cards. It is a rule
      // the screen enforces, not a sentence the screen has to say, so the last
      // statement of it is gone too.
      await waitFor(() => expect(api.courses).toHaveBeenCalledTimes(1));
      expect(api.publishedAgents).toHaveBeenCalledWith(courseId);
      for (const boundary of [
        "Student drafts cannot be viewed or edited here.",
        "教师视图不能查看或编辑学生草稿。",
      ]) {
        expect(
          screen.queryAllByText((content) => content.includes(boundary)),
        ).toHaveLength(0);
      }
    },
  );

  it("shows producing group, read-only avatar, and effective platform fallback voice", async () => {
    const api = apiForTeacher();
    mockedUseSession.mockReturnValue({ api } as never);
    render(
      <LocaleProvider initialLocale="en">
        <TeacherAgentDetail agentId={agentId} />
      </LocaleProvider>,
    );

    await waitFor(() => expect(screen.getByText("Bowen group")).toBeTruthy());
    expect(api.group).toHaveBeenCalledWith(groupId);
    expect(
      screen.getByRole("img", { name: "Published Agent avatar preview" }),
    ).toBeTruthy();
    // The state is a badge, not a paragraph explaining what the badge means.
    expect(screen.getByText("Platform voice fallback")).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: /edit description/i }),
    ).toBeNull();
  });

  it("keeps shared navigation, text, summary, and file actions on 44px targets", () => {
    const frontendRoot = process.cwd().endsWith("/frontend")
      ? process.cwd()
      : `${process.cwd()}/frontend`;
    const css = readFileSync(`${frontendRoot}/app/globals.css`, "utf8");
    expect(css).toMatch(/\.brand-mark\s*\{[^}]*min-height:\s*44px/s);
    expect(css).toMatch(/\.text-link\s*\{[^}]*min-height:\s*44px/s);
    expect(css).toMatch(/details > summary\s*\{[^}]*min-height:\s*44px/s);
    expect(css).toMatch(
      /\.primary-action,\s*\.secondary-action\s*\{[^}]*min-height:\s*44px/s,
    );
    expect(css).toMatch(
      /\.inline-button,\s*\.nav-logout,\s*\.chip-button\s*\{[^}]*min-height:\s*44px/s,
    );
    expect(css).toMatch(/\.file-button\s*\{[^}]*min-height:\s*44px/s);
    expect(css).toContain(".teacher-agent-context-grid");
    expect(css).toMatch(
      /@media \(max-width: 900px\)[\s\S]*teacher-agent-context-grid/,
    );
    expect(css).toMatch(/@media \(max-width: 620px\)[\s\S]*\.text-link/);
  });
});
