import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AgentWorkbench } from "../components/agent-workspace";
import type { AgentDetail } from "../lib/api";
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
      const previewAgent = vi.fn(async (_payload: unknown) => ({
        answer: "One sentence.",
      }));
      const create = vi.fn();
      state.api = {
        previewAgent,
        checkAgentDebateCard: vi.fn(async () => ({
          card_status: "ready",
          card: {
            identity: "Stored nurse persona",
            position: "A stored position",
            reasoning: [],
            speaking_style: "Warm",
            voice_style: null,
            dropped: [{ excerpt: "Speak forever", reason: "length_limit" }],
          },
        })),
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
      if (scope === "saved") {
        fireEvent.click(await screen.findByText("Check card"));
        expect(await screen.findByText("Stored nurse persona")).toBeTruthy();
        expect(screen.getByText("A stored position")).toBeTruthy();
        expect(screen.getByText("Speak forever")).toBeTruthy();
        expect(screen.queryByText("Nothing was dropped.")).toBeNull();
        expect(state.api).toHaveProperty("checkAgentDebateCard");
      }
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
      expect(previewAgent.mock.calls[0][0]).not.toHaveProperty("document_ids");
      expect(create).not.toHaveBeenCalled();
    },
  );

  it("shows a stored Ready tag while collapsed and does not compile", async () => {
    const checkAgentDebateCard = vi.fn();
    state.api = {
      checkAgentDebateCard,
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
        stored_card_status: "ready",
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
    render(<AgentWorkbench versionId="8552ddaf-cd67-46f8-9b1c-c22e1b3b66a1" />);
    expect((await screen.findByTestId("debate-card-status")).textContent).toBe(
      "Ready",
    );
    fireEvent.change(screen.getByLabelText("AGENT.md editor"), {
      target: { value: "# Saved persona\nOne more line" },
    });
    expect(screen.getByTestId("debate-card-status").textContent).toBe("Ready");
    expect(screen.queryByText(/could not be prepared/)).toBeNull();
    expect(checkAgentDebateCard).not.toHaveBeenCalled();
  });

  it("compiles a new Agent from the editor text instead of failing", async () => {
    const text = "A brand new philosopher";
    const create = vi.fn(async (): Promise<AgentDetail> => ({
      id: "agent-new",
      name: "Ada",
      description: "",
      course_id: "course",
      group_id: null,
      ownership_scope: "personal",
      visibility: "private",
      can_edit: true,
      can_manage_visibility: true,
      metadata_revision: 0,
      status: "active",
      current_draft_version_id: "version-new",
      current_published_version_id: null,
      versions: [],
    }));
    const updateDraft = vi.fn(async () => ({
      id: "version-new",
      agent_id: "agent-new",
      version_label: "V1.0",
      state: "draft",
      revision: 1,
      agent_md: text,
      avatar_config: defaults.egg,
      voice_profile_id: null,
      voice_fallback_active: true,
      enabled_documents: [],
      publish_blockers: [],
    }));
    const checkAgentDebateCard = vi.fn(async () => ({
      card_status: "ready",
      card: {
        identity: "From the editor",
        position: "A stored position",
        reasoning: [],
        speaking_style: "Warm",
        voice_style: null,
        dropped: [],
      },
    }));
    state.api = {
      checkAgentDebateCard,
      updateDraft,
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
      ragPreview: vi.fn(async () => null),
      agentKnowledgeSets: vi.fn(async () => ({ sets: [] })),
    };
    render(
      <AgentWorkbench
        publishOnDone
        unsavedCreate={{ courseId: "course", create }}
      />,
    );
    fireEvent.change(await screen.findByLabelText("Name"), {
      target: { value: "Ada" },
    });
    fireEvent.change(screen.getByLabelText("AGENT.md editor"), {
      target: { value: text },
    });
    fireEvent.click(screen.getByText("Check card"));
    await waitFor(() =>
      expect(checkAgentDebateCard).toHaveBeenCalledWith("version-new", text),
    );
    expect(create).toHaveBeenCalled();
    expect(updateDraft).toHaveBeenCalledWith(
      "version-new",
      expect.objectContaining({ agent_md: text }),
    );
    expect(await screen.findByText("From the editor")).toBeTruthy();
    expect(screen.queryByText(/could not be prepared/)).toBeNull();
  });

  it("shows Compiling when a new Agent still has no version", async () => {
    const create = vi.fn(async () => {
      throw new Error("name required");
    });
    const checkAgentDebateCard = vi.fn();
    state.api = {
      checkAgentDebateCard,
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
      ragPreview: vi.fn(async () => null),
      agentKnowledgeSets: vi.fn(async () => ({ sets: [] })),
    };
    render(
      <AgentWorkbench
        publishOnDone
        unsavedCreate={{ courseId: "course", create }}
      />,
    );
    fireEvent.change(await screen.findByLabelText("Name"), {
      target: { value: "Ada" },
    });
    fireEvent.change(screen.getByLabelText("AGENT.md editor"), {
      target: { value: "Unsaved philosopher" },
    });
    fireEvent.click(screen.getByText("Check card"));
    expect((await screen.findByTestId("debate-card-status")).textContent).toBe(
      "Compiling",
    );
    expect(screen.queryByText(/could not be prepared/)).toBeNull();
    expect(checkAgentDebateCard).not.toHaveBeenCalled();
  });
});
