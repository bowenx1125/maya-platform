import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AgentChat } from "../components/agent-chat";
import type { AvatarConfig } from "../components/avatar";
import { TeacherAgentDetail } from "../components/teacher-workspace";
import { SidebarActions } from "./sidebar-actions";

const publishedAvatar: AvatarConfig = {
  template_id: "maya-warm-scholar",
  material_theme: "warm_sand",
  eye_color: "hazel",
  default_expression: "attentive",
  expression_strength: "low",
  motion_style: "calm",
};

const state = vi.hoisted(() => ({
  role: "student" as "student" | "teacher",
}));

vi.mock("next/navigation", () => ({
  usePathname: () => `/${state.role}/chat`,
  useSearchParams: () => new URLSearchParams(window.location.search),
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
}));

vi.mock("../components/session-provider", () => ({
  useSession: () => ({
    api: {
      chatAgents: vi.fn(async () => [
        {
          agent_id: "agent",
          version_id: "version",
          course_id: "course",
          name: "Socrates",
          version_label: "V1.2",
          avatar_config: publishedAvatar,
          available: true,
        },
      ]),
      conversations: vi.fn(async () => []),
      createConversation: vi.fn(async () => ({
        id: "chat",
        entry_kind: "agent",
        chat_visibility: "private",
        origin: "single_agent",
        read_only: false,
        can_send: true,
        agent: {
          agent_id: "agent",
          version_id: "version",
          course_id: "course",
          name: "Socrates",
          version_label: "V1.2",
          avatar_config: publishedAvatar,
          available: true,
        },
        revision: 0,
        turns: [],
        created_at: "2026-10-11T00:00:00Z",
      })),
      agent: vi.fn(async () => ({
        id: "agent",
        group_id: "group",
        name: "Socrates",
        description: "",
        status: "active",
        current_published_version_id: "version",
        current_draft_version_id: null,
        versions: [],
      })),
      versions: vi.fn(async () => [
        {
          id: "version",
          agent_id: "agent",
          version_label: "V1.2",
          state: "published",
          revision: 4,
          agent_md: "# Published",
          avatar_config: publishedAvatar,
          voice_fallback_active: true,
          enabled_documents: [],
          publish_blockers: [],
        },
      ]),
    },
    user: {
      courses: [{ course_id: "course", role: state.role }],
      groups: [],
    },
    logout: vi.fn(),
  }),
}));

vi.mock("../components/avatar/avatar-renderer", () => ({
  AvatarRenderer: class {
    constructor(options: { onReady?: () => void }) {
      queueMicrotask(() => options.onReady?.());
    }

    setConfig(): void {
      return;
    }

    setState(): void {
      return;
    }

    dispose(): void {
      return;
    }
  },
}));

const APPEARANCE_FIELDS = [
  ["template_id", "data-avatar-template"],
  ["material_theme", "data-avatar-material"],
  ["eye_color", "data-avatar-eye"],
  ["default_expression", "data-avatar-expression"],
  ["expression_strength", "data-avatar-strength"],
  ["motion_style", "data-avatar-motion"],
] as const;

function readAvatarFields() {
  const node = screen.getByRole("img", { name: /Socrates avatar preview/i });
  return Object.fromEntries(
    APPEARANCE_FIELDS.map(([field, attribute]) => [
      field,
      node.getAttribute(attribute),
    ]),
  );
}

function expectedFields() {
  return {
    template_id: publishedAvatar.template_id,
    material_theme: publishedAvatar.material_theme,
    eye_color: publishedAvatar.eye_color,
    default_expression: publishedAvatar.default_expression,
    expression_strength: publishedAvatar.expression_strength,
    motion_style: publishedAvatar.motion_style,
  };
}

describe("published avatar field parity", () => {
  afterEach(() => {
    cleanup();
    window.history.replaceState(null, "", "/");
    state.role = "student";
  });

  it.each(["student", "teacher"] as const)(
    "keeps the published avatar out of %s Chats",
    async (role) => {
      state.role = role;
      window.history.replaceState(null, "", `/${role}/chat?mode=new`);
      render(
        <>
          <SidebarActions>
            <AgentChat />
          </SidebarActions>
        </>,
      );
      fireEvent.click(await screen.findByRole("button", { name: /Socrates/ }));
      expect(screen.queryByRole("img", { name: /Socrates/i })).toBeNull();
      fireEvent.click(
        within(screen.getByRole("navigation")).getByRole("button", {
          name: "Done",
        }),
      );
      await screen.findByRole("heading", { level: 2, name: "Socrates" });
      expect(screen.queryByRole("img", { name: /Socrates/i })).toBeNull();
      expect(screen.queryByRole("combobox", { name: "3D model" })).toBeNull();
    },
  );

  // TODO(ui-release): teacher preview read-only Agent view deleted (approved step 2)
  it.skip("preserves every published avatar field in teacher preview", async () => {
    state.role = "teacher";
    const teacherPreview = render(
      <>
        <TeacherAgentDetail agentId="agent" />
      </>,
    );
    expect(await screen.findByRole("img", { name: /Socrates/i })).toBeTruthy();
    const teacherPreviewFields = readAvatarFields();
    teacherPreview.unmount();

    expect(teacherPreviewFields).toEqual(expectedFields());
  });
});
