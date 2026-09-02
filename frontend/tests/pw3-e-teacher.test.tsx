import { readFileSync } from "node:fs";

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  AgentDetail,
  AgentVersion,
  GroupDetail,
  KnowledgeSnapshot,
} from "../lib/api";
import { LocaleProvider } from "../components/locale";

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

  it.each([
    {
      locale: "en" as const,
      boundary: "Student drafts cannot be viewed or edited here.",
    },
    {
      locale: "zh" as const,
      boundary: "教师视图不能查看或编辑学生草稿。",
    },
  ])(
    "states the student-draft boundary once and loads the course ($locale)",
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

      // The boundary is stated in the page lede. It used to be repeated in a
      // capabilities section and again in five explainer cards; exactly one
      // statement is the contract now.
      await waitFor(() =>
        expect(
          screen.getAllByText((content) => content.includes(caseData.boundary)),
        ).toHaveLength(1),
      );
      expect(api.courses).toHaveBeenCalledTimes(1);
      expect(api.publishedAgents).toHaveBeenCalledWith(courseId);
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
    expect(screen.getByText("Platform voice fallback")).toBeTruthy();
    expect(screen.getByText(/custom voice is optional/i)).toBeTruthy();
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
