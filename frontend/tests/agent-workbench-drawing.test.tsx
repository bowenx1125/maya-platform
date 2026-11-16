import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AgentWorkbench } from "../components/agent-workspace";
import {
  AVATAR_TEMPLATE_DEFAULT_CONFIGS as defaults,
  type AvatarConfig,
} from "../components/avatar/types";
import {
  BLANK_DRAWING,
  boardPosition,
  type Drawing,
} from "../components/avatar/drawing";
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
  EggCanvas: ({ drawing }: { drawing: Drawing }) => (
    <div data-testid="egg-ink">{JSON.stringify(drawing)}</div>
  ),
}));
vi.mock("../components/avatar/avatar-canvas", () => ({
  AvatarCanvas: ({ config }: { config: AvatarConfig }) => (
    <div data-testid="card-avatar">{JSON.stringify(config)}</div>
  ),
}));
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
beforeEach(() => {
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      disconnect() {}
    },
  );
  vi.stubGlobal(
    "PointerEvent",
    class extends MouseEvent {
      pointerId = 1;
      isPrimary = true;
      pointerType = "mouse";
    },
  );
  HTMLElement.prototype.setPointerCapture = vi.fn();
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({
    x: 0,
    y: 0,
    left: 0,
    top: 0,
    width: 600,
    height: 600,
    right: 600,
    bottom: 600,
    toJSON() {
      return {};
    },
  });
});
function setup(drawing?: Drawing, saveAgentAvatar = vi.fn()) {
  const baseline = {
    id: "published-base",
    agent_id: "agent",
    version_label: "V1.0",
    state: "published",
    revision: 7,
    avatar_config: drawing ? { ...defaults.egg, drawing } : defaults.egg,
    agent_md: "# Published persona",
    voice_profile_id: null,
    enabled_documents: [],
    publish_blockers: [],
  } as unknown as AgentVersion;
  state.api = {
    saveAgentAvatar,
    previewAgent: vi.fn(async () => ({ answer: "Hello." })),
    avatarTemplates: vi.fn(async () => [
      {
        id: "egg",
        name: "Egg",
        available: true,
        supported_parameters: ["template_id"],
      },
      {
        id: "maya-warm-scholar",
        name: "Scholar",
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
  return baseline;
}
function drawLine(release = true) {
  const surface = screen.getByLabelText("Avatar drawing canvas");
  const sample = (x: number) => {
    const p = boardPosition({ x, y: 0.2 }, 600, 600);
    return { clientX: p.x, clientY: p.y, pointerId: 1 };
  };
  fireEvent.pointerDown(surface, sample(0.4));
  fireEvent.pointerMove(surface, sample(0.6));
  if (release) fireEvent.pointerUp(surface, sample(0.6));
}
function boardInk() {
  return JSON.parse(
    within(screen.getByRole("dialog", { name: "Avatar" })).getByTestId(
      "egg-ink",
    ).textContent!,
  ) as Drawing;
}
function cardConfig() {
  return JSON.parse(
    screen.getByTestId("card-avatar").textContent!,
  ) as AvatarConfig;
}

describe("Option A drawing entry", () => {
  it("waits for Avatar Save confirmation and preserves unrelated unsaved persona", async () => {
    let resolve!: (v: AgentVersion) => void;
    const reply = new Promise<AgentVersion>((r) => {
      resolve = r;
    });
    const saveAgentAvatar = vi.fn(() => reply);
    const baseline = setup(undefined, saveAgentAvatar);
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
  it.each([
    ["Close", true],
    ["Escape", true],
    ["Close", false],
    ["Escape", false],
  ] as const)(
    "Edit → Preview → %s → Save persists the edited strokes immediately (pointer released: %s)",
    async (close, release) => {
      const save = vi.fn();
      const baseline = setup(undefined, save);
      save.mockImplementation(
        async (_id: string, body: { avatar_config: AvatarConfig }) => ({
          ...baseline,
          id: "published-next",
          avatar_config: body.avatar_config,
        }),
      );
      render(<AgentWorkbench versionId={baseline.id} publishOnDone />);
      fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
      drawLine(release);
      const edited = boardInk();
      expect(edited.strokes).toHaveLength(1);
      const board = screen.getByRole("dialog", { name: "Avatar" });
      fireEvent.click(within(board).getByRole("button", { name: "Preview" }));
      const preview = screen.getByRole("dialog", { name: "Preview" });
      expect(
        JSON.parse(within(preview).getByTestId("egg-ink").textContent!),
      ).toEqual(edited);
      expect(save).not.toHaveBeenCalled();
      if (close === "Close")
        fireEvent.click(within(preview).getByRole("button", { name: "Close" }));
      else fireEvent.keyDown(preview, { key: "Escape" });
      expect(screen.getByRole("dialog", { name: "Avatar" })).toBe(board);
      expect(boardInk()).toEqual(edited);
      drawLine();
      const saved = boardInk();
      expect(saved.strokes).toHaveLength(2);
      fireEvent.click(within(board).getByRole("button", { name: "Save" }));
      await waitFor(() =>
        expect(screen.queryByRole("dialog", { name: "Avatar" })).toBeNull(),
      );
      expect(save).toHaveBeenCalledWith(
        baseline.id,
        {
          expected_revision: 7,
          expected_published_version_id: baseline.id,
          avatar_config: { ...defaults.egg, drawing: saved },
        },
        expect.any(String),
      );
      expect(cardConfig().drawing).toEqual(saved);
    },
  );
  it.each(["Back", "Escape"])(
    "%s stays when cancelled and discards unsaved ink when confirmed",
    async (action) => {
      const save = vi.fn();
      const baseline = setup(undefined, save);
      const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
      render(<AgentWorkbench versionId={baseline.id} publishOnDone />);
      fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
      drawLine();
      const edited = boardInk();
      const board = screen.getByRole("dialog", { name: "Avatar" });
      const leave = () =>
        action === "Back"
          ? fireEvent.click(within(board).getByRole("button", { name: "Back" }))
          : fireEvent.keyDown(board, { key: "Escape" });
      leave();
      expect(confirm).toHaveBeenCalledWith(
        "Leave without saving your drawing?",
      );
      expect(screen.getByRole("dialog", { name: "Avatar" })).toBe(board);
      expect(boardInk()).toEqual(edited);
      confirm.mockReturnValue(true);
      leave();
      expect(screen.queryByRole("dialog", { name: "Avatar" })).toBeNull();
      expect(save).not.toHaveBeenCalled();
      expect(cardConfig()).toEqual(defaults.egg);
      fireEvent.click(screen.getByRole("button", { name: "Edit" }));
      expect(boardInk()).toEqual(BLANK_DRAWING);
    },
  );
  it.each(["edit", "create"])(
    "retains the saved egg drawing across template switches on the %s page",
    async (page) => {
      const save = vi.fn();
      const baseline = setup(undefined, save);
      save.mockImplementation(
        async (_id: string, body: { avatar_config: AvatarConfig }) => ({
          ...baseline,
          id: "published-next",
          avatar_config: body.avatar_config,
        }),
      );
      const create = vi.fn();
      render(
        page === "edit" ? (
          <AgentWorkbench versionId={baseline.id} publishOnDone />
        ) : (
          <AgentWorkbench
            unsavedCreate={{ courseId: "course", create }}
            publishOnDone
          />
        ),
      );
      fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
      drawLine();
      const saved = boardInk();
      expect(saved.strokes).toHaveLength(1);
      fireEvent.click(
        within(screen.getByRole("dialog", { name: "Avatar" })).getByRole(
          "button",
          { name: "Save" },
        ),
      );
      await waitFor(() =>
        expect(screen.queryByRole("dialog", { name: "Avatar" })).toBeNull(),
      );
      expect(cardConfig().drawing).toEqual(saved);
      fireEvent.click(screen.getByRole("radio", { name: "Scholar" }));
      expect(cardConfig().template_id).toBe("maya-warm-scholar");
      fireEvent.click(screen.getByRole("radio", { name: "Egg" }));
      expect(cardConfig().drawing).toEqual(saved);
      fireEvent.click(screen.getByRole("button", { name: "Edit" }));
      expect(boardInk()).toEqual(saved);
      expect(save).toHaveBeenCalledTimes(page === "edit" ? 1 : 0);
      expect(create).not.toHaveBeenCalled();
    },
  );
  it("restores an egg drawing loaded from the server after switching away and back", async () => {
    const saved = {
      ...BLANK_DRAWING,
      strokes: [
        {
          id: "saved",
          color: "#111111",
          width: 0.01,
          opacity: 1,
          points: [{ x: 0.4, y: 0.2 }],
        },
      ],
    };
    const baseline = setup(saved);
    render(<AgentWorkbench versionId={baseline.id} publishOnDone />);
    await screen.findByRole("button", { name: "Edit" });
    fireEvent.click(screen.getByRole("radio", { name: "Scholar" }));
    fireEvent.click(screen.getByRole("radio", { name: "Egg" }));
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    expect(boardInk()).toEqual(saved);
  });
});
