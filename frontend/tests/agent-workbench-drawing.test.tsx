import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AgentWorkbench } from "../components/agent-workspace";
import {
  AVATAR_TEMPLATE_DEFAULT_CONFIGS as defaults,
  type AvatarConfig,
} from "../components/avatar/types";
import type { AgentVersion } from "../lib/api/platform";
const state = vi.hoisted(() => ({ api: {} }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));
vi.mock("../components/session-provider", () => ({
  useSession: () => ({
    api: state.api,
    user: {
      id: "teacher",
      courses: [{ course_id: "course", role: "teacher" }],
      groups: [],
    },
  }),
}));
vi.mock("../components/avatar/egg-canvas", () => ({
  EggCanvas: () => <div />,
}));
vi.mock("../components/avatar/avatar-canvas", () => ({
  AvatarCanvas: ({ config }: { config: AvatarConfig }) => (
    <div data-testid="card-avatar">{JSON.stringify(config)}</div>
  ),
}));
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
describe("Option A drawing entry", () => {
  it("waits for Avatar Save confirmation and preserves unrelated unsaved persona", async () => {
    vi.stubGlobal(
      "ResizeObserver",
      class {
        observe() {}
        disconnect() {}
      },
    );
    const baseline = {
      id: "published-base",
      agent_id: "agent",
      version_label: "V1.0",
      state: "published",
      revision: 7,
      avatar_config: defaults.egg,
      agent_md: "# Published persona",
      voice_profile_id: null,
      enabled_documents: [],
      publish_blockers: [],
    } as unknown as AgentVersion;
    let resolve!: (v: AgentVersion) => void;
    const reply = new Promise<AgentVersion>((r) => {
      resolve = r;
    });
    const saveAgentAvatar = vi.fn(() => reply);
    state.api = {
      saveAgentAvatar,
      avatarTemplates: vi.fn(async () => [
        {
          id: "egg",
          name: "Egg",
          available: true,
          supported_parameters: ["template_id"],
        },
      ]),
      version: vi.fn(async () => baseline),
      agent: vi.fn(async () => ({
        id: "agent",
        name: "Saved",
        can_edit: true,
        course_id: "course",
        group_id: null,
        ownership_scope: "personal",
        visibility: "private",
        current_published_version_id: baseline.id,
      })),
      workspaceDocuments: vi.fn(async () => []),
      agentKnowledgeSets: vi.fn(async () => ({ sets: [] })),
      personalVoiceProfiles: vi.fn(async () => []),
    };
    render(<AgentWorkbench versionId={baseline.id} publishOnDone />);
    const editor = await screen.findByRole("textbox", {
      name: "AGENT.md editor",
    });
    fireEvent.change(editor, { target: { value: "# Unsaved local persona" } });
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    const board = screen.getByRole("dialog", { name: "Avatar" });
    fireEvent.click(within(board).getByRole("button", { name: "Save" }));
    expect(saveAgentAvatar).toHaveBeenCalledWith(
      baseline.id,
      expect.objectContaining({
        expected_revision: 7,
        expected_published_version_id: baseline.id,
        avatar_config: expect.objectContaining({
          template_id: "egg",
          drawing: expect.objectContaining({ strokes: [] }),
        }),
      }),
      expect.any(String),
    );
    expect(screen.getByRole("dialog", { name: "Avatar" })).toBeTruthy();
    expect(JSON.parse(screen.getByTestId("card-avatar").textContent!)).toEqual(
      defaults.egg,
    );
    const confirmed = {
      ...baseline,
      id: "published-next",
      avatar_config: {
        ...defaults.egg,
        drawing: {
          version: 1 as const,
          strokes: [],
          mouth: { x: 0.55, y: 0.435 },
        },
      },
    };
    resolve(confirmed);
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Avatar" })).toBeNull(),
    );
    expect(JSON.parse(screen.getByTestId("card-avatar").textContent!)).toEqual(
      confirmed.avatar_config,
    );
    expect(
      (
        screen.getByRole("textbox", {
          name: "AGENT.md editor",
        }) as HTMLTextAreaElement
      ).value,
    ).toBe("# Unsaved local persona");
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    fireEvent.click(
      within(screen.getByRole("dialog", { name: "Avatar" })).getByRole(
        "button",
        { name: "Back" },
      ),
    );
    expect(JSON.parse(screen.getByTestId("card-avatar").textContent!)).toEqual(
      confirmed.avatar_config,
    );
  });
});
