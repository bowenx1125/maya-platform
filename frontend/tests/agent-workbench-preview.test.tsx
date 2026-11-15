import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AgentWorkbench } from "../components/agent-workspace";
import { AVATAR_TEMPLATE_DEFAULT_CONFIGS as defaults } from "../components/avatar/types";

const state = vi.hoisted(() => ({ api: {}, role: "teacher" }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));
vi.mock("../components/session-provider", () => ({
  useSession: () => ({
    api: state.api,
    user: {
      courses: [{ course_id: "course", role: state.role }],
      groups: [{ group_id: "group", role: "member" }],
    },
  }),
}));
vi.mock("../components/avatar/egg-canvas", () => ({
  EggCanvas: () => <div />,
}));
vi.mock("../components/avatar/avatar-canvas", () => ({
  AvatarCanvas: () => <div />,
}));
afterEach(cleanup);

describe("workbench Preview request", () => {
  it.each(["teacher create", "student create", "saved"])(
    "sends the version and scope for %s",
    async (scope) => {
      state.role = scope === "student create" ? "student" : "teacher";
      const previewAgent = vi.fn(async () => ({ answer: "One sentence." }));
      const create = vi.fn();
      state.api = {
        previewAgent,
        group: vi.fn(async () => ({ course_id: "course" })),
        knowledge: vi.fn(async () => []),
        workspaceDocuments: vi.fn(async () => []),
        avatarTemplates: vi.fn(async () => [
          {
            id: "egg",
            name: "Egg",
            available: true,
            supported_parameters: ["template_id"],
          },
        ]),
        personalVoiceProfiles: vi.fn(async () => []),
        voiceProfiles: vi.fn(async () => []),
        version: vi.fn(async () => ({
          id: "8552ddaf-cd67-46f8-9b1c-c22e1b3b66a1",
          agent_id: "agent",
          state: "draft",
          revision: 0,
          avatar_config: defaults.egg,
          agent_md: "# Saved persona",
          enabled_documents: [],
          publish_blockers: [],
        })),
        agent: vi.fn(async () => ({
          id: "agent",
          name: "Saved",
          course_id: "course",
          group_id: null,
          ownership_scope: "personal",
          visibility: "private",
        })),
        ragPreview: vi.fn(async () => null),
        agentKnowledgeSets: vi.fn(async () => ({ sets: [] })),
      };
      render(
        <AgentWorkbench
          versionId={
            scope === "saved"
              ? "8552ddaf-cd67-46f8-9b1c-c22e1b3b66a1"
              : undefined
          }
          unsavedCreate={
            scope === "saved"
              ? undefined
              : scope === "teacher create"
                ? { courseId: "course", create }
                : { groupId: "group", create }
          }
        />,
      );
      fireEvent.click(await screen.findByRole("button", { name: "Preview" }));
      fireEvent.change(screen.getByPlaceholderText("Type a message..."), {
        target: { value: "Why?" },
      });
      fireEvent.click(screen.getByRole("button", { name: "Send" }));
      await waitFor(() => expect(previewAgent).toHaveBeenCalledOnce());
      expect(previewAgent).toHaveBeenCalledWith(
        expect.objectContaining({
          message: "Why?",
          version_id:
            scope === "saved" ? "8552ddaf-cd67-46f8-9b1c-c22e1b3b66a1" : null,
          course_id: scope === "teacher create" ? "course" : null,
          group_id: scope === "student create" ? "group" : null,
        }),
      );
      expect(create).not.toHaveBeenCalled();
    },
  );
});
