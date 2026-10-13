import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ComponentProps } from "react";

import { AgentWorkbench } from "../components/agent-workspace";
import { AppShell } from "../components/app-shell";
import type { AvatarConfig } from "../components/avatar";
import { LocaleProvider } from "../components/locale";
import { SessionProvider } from "../components/session-provider";
import { PlatformApiError } from "../lib/api";
import type {
  AgentDetail,
  AgentVersion,
  AuthSession,
  PlatformApi,
  VoiceProfile,
} from "../lib/api";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/student/agent-versions/version-id/edit",
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

const initialAvatar: AvatarConfig = {
  template_id: "wave1-default-head",
  material_theme: "demo",
  eye_color: null,
  default_expression: "neutral",
  expression_strength: "medium",
  motion_style: "calm",
};

function makeVersion(overrides: Partial<AgentVersion> = {}): AgentVersion {
  return {
    id: "version-id",
    agent_id: "agent-id",
    version_label: "V1.0",
    state: "draft",
    revision: 0,
    agent_md: "# Server Agent",
    avatar_config: initialAvatar,
    voice_profile_id: null,
    effective_voice_profile_id: null,
    voice_fallback_active: true,
    knowledge_snapshot_id: null,
    enabled_documents: [],
    publish_blockers: [],
    ...overrides,
  } as AgentVersion;
}

function makeApi(version: AgentVersion) {
  const api = {
    me: vi.fn(async () => makeSession()),
    getCsrfToken: vi.fn(() => "csrf-1"),
    version: vi.fn(async () => version),
    agent: vi.fn(
      async () =>
        ({
          id: "agent-id",
          group_id: "group-id",
          course_id: "course-id",
          ownership_scope: "group",
          visibility: "public",
          can_edit: true,
          name: "Agent",
          description: "A stable Agent description",
          metadata_revision: 0,
          status: "active",
          current_draft_version_id: "version-id",
          current_published_version_id: null,
          versions: [],
        }) as AgentDetail,
    ),
    knowledge: vi.fn(async () => []),
    knowledgeSets: vi.fn(async () => []),
    agentKnowledgeSets: vi.fn(async () => ({
      agent_id: "agent-id",
      agent_metadata_revision: 0,
      sets: [],
    })),
    replaceAgentKnowledgeSets: vi.fn(
      async (
        _agentId: string,
        body: { expected_agent_metadata_revision: number },
      ) => ({
        agent_id: "agent-id",
        agent_metadata_revision: body.expected_agent_metadata_revision + 1,
        sets: [],
      }),
    ),
    ragPreview: vi.fn(async () => ({
      version_id: "version-id",
      total_char_count: 0,
      limit: null,
      document_count: 0,
      index_status: "ready",
      combined_markdown: "",
    })),
    avatarTemplates: vi.fn(async () => [
      {
        id: "wave1-default-head",
        name: "Wave 1 Default Head",
        available: true,
        supported_parameters: ["template_id", "material_theme", "eye_color"],
      },
      {
        id: "maya-warm-scholar",
        name: "Maya Warm Scholar",
        available: true,
        supported_parameters: ["template_id", "material_theme", "eye_color"],
      },
    ]),
    voiceProfiles: vi.fn(async (): Promise<VoiceProfile[]> => []),
    updateDraft: vi.fn(
      async (_id: string, _body: { avatar_config?: AvatarConfig }) => version,
    ),
    publish: vi.fn(),
  };
  return api;
}

function makeSession(): AuthSession {
  return {
    csrf_token: "csrf-1",
    expires_at: "2026-08-27T12:00:00Z",
    user: {
      id: "student-id",
      username: "student",
      display_name: "Student",
      courses: [{ course_id: "course-id", role: "student" }],
      groups: [{ group_id: "group-id", role: "member" }],
    },
  } as AuthSession;
}

function renderWorkbench(
  api: PlatformApi,
  publishOnDone = false,
  unsavedCreate?: ComponentProps<typeof AgentWorkbench>["unsavedCreate"],
) {
  return render(
    <LocaleProvider initialLocale="en">
      <SessionProvider api={api}>
        <AppShell role="student">
          <AgentWorkbench
            versionId={unsavedCreate ? undefined : "version-id"}
            publishOnDone={publishOnDone}
            unsavedCreate={unsavedCreate}
          />
        </AppShell>
      </SessionProvider>
    </LocaleProvider>,
  );
}

describe("AvatarEditor draft persistence", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("saves appearance through UpdateAgentDraft and shows it after refresh", async () => {
    let stored = makeVersion();
    const api = makeApi(stored);
    api.updateDraft.mockImplementation(
      async (_id: string, body: { avatar_config?: AvatarConfig }) => {
        stored = makeVersion({
          revision: stored.revision + 1,
          avatar_config: body.avatar_config ?? stored.avatar_config,
        });
        return stored;
      },
    );
    api.publish.mockImplementation(async () => ({
      ...stored,
      state: "published",
    }));
    api.version.mockImplementation(async () => stored);

    const view = renderWorkbench(api as unknown as PlatformApi);
    const theme = await screen.findByLabelText("Material theme");
    expect((theme as HTMLSelectElement).value).toBe("demo");
    fireEvent.change(theme, { target: { value: "warm_sand" } });
    fireEvent.change(screen.getByLabelText("Eye color"), {
      target: { value: "blue" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Done" }));

    await waitFor(() => expect(api.updateDraft).toHaveBeenCalledTimes(1));
    expect(api.updateDraft).toHaveBeenCalledWith(
      "version-id",
      expect.objectContaining({
        expected_revision: 0,
        avatar_config: {
          ...initialAvatar,
          material_theme: "warm_sand",
          eye_color: "blue",
        },
      }),
    );

    view.unmount();
    renderWorkbench(api as unknown as PlatformApi);
    const refreshed = await screen.findByLabelText("Material theme");
    expect((refreshed as HTMLSelectElement).value).toBe("warm_sand");
    expect(
      (screen.getByLabelText("Eye color") as HTMLSelectElement).value,
    ).toBe("blue");
  });

  it("renders a load failure before constructing the Agent Knowledge link", async () => {
    const api = makeApi(makeVersion());
    api.version.mockRejectedValue(new Error("Draft unavailable"));

    renderWorkbench(api as unknown as PlatformApi);

    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Retry" })).toBeTruthy();
  });
});

const availableVoice: VoiceProfile = {
  id: "voice-old",
  scope: "group",
  group_id: "group-id",
  status: "ready",
  source_filename: "Saved voice.wav",
  safe_error_code: null,
  can_manage: true,
  created_at: "2026-01-01T00:00:00Z",
};

describe("Agent optional media resilience", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it.each(["avatarTemplates", "voiceProfiles"] as const)(
    "keeps the Agent and saved choices usable when %s is unavailable",
    async (resource) => {
      const stored = makeVersion({
        avatar_config: {
          ...initialAvatar,
          material_theme: "warm_sand",
          eye_color: "blue",
        },
        voice_profile_id: availableVoice.id,
      });
      const api = makeApi(stored);
      api[resource].mockRejectedValue(
        new PlatformApiError(503, "Media catalog unavailable"),
      );
      api.publish.mockResolvedValue({ ...stored, state: "published" });
      renderWorkbench(api as unknown as PlatformApi);

      const editor = await screen.findByRole("textbox", {
        name: "AGENT.md editor",
      });
      expect((editor as HTMLTextAreaElement).value).toBe(stored.agent_md);
      expect(await screen.findByRole("alert")).toBeTruthy();
      expect(
        (screen.getByLabelText("Material theme") as HTMLSelectElement).value,
      ).toBe("warm_sand");
      expect(
        screen.getByRole("button", { name: "Current voice" }),
      ).toBeTruthy();
      if (resource === "voiceProfiles")
        expect(screen.queryByText("No voices yet.")).toBeNull();
      fireEvent.change(editor, { target: { value: "# Unsaved local text" } });

      if (resource === "avatarTemplates") {
        api.avatarTemplates.mockResolvedValue([
          {
            id: "wave1-default-head",
            name: "Wave 1 Default Head",
            available: true,
            supported_parameters: [
              "template_id",
              "material_theme",
              "eye_color",
            ],
          },
        ]);
      } else {
        api.voiceProfiles.mockResolvedValue([availableVoice]);
      }
      fireEvent.click(screen.getByRole("button", { name: "Retry" }));
      await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
      expect(
        (
          screen.getByRole("textbox", {
            name: "AGENT.md editor",
          }) as HTMLTextAreaElement
        ).value,
      ).toBe("# Unsaved local text");
      expect(api.version).toHaveBeenCalledTimes(1);
      if (resource === "voiceProfiles") {
        expect(
          screen
            .getByRole("button", { name: "Saved voice.wav" })
            .getAttribute("aria-pressed"),
        ).toBe("true");
        expect(
          screen.queryByRole("button", { name: "Current voice" }),
        ).toBeNull();
      }
      fireEvent.click(screen.getByRole("button", { name: "Done" }));
      await waitFor(() => expect(api.updateDraft).toHaveBeenCalledTimes(1));
      const body = api.updateDraft.mock.calls[0][1];
      expect(body).toEqual(
        expect.objectContaining({ avatar_config: stored.avatar_config }),
      );
      expect(body).not.toHaveProperty("voice_profile_id");
    },
  );

  it("locks Voice selection while Done is saving the selected binding", async () => {
    const api = makeApi(makeVersion());
    api.voiceProfiles.mockResolvedValue([
      availableVoice,
      {
        ...availableVoice,
        id: "voice-next",
        source_filename: "Other voice.wav",
      },
    ]);
    let finishSave!: (version: AgentVersion) => void;
    api.updateDraft.mockImplementation(
      () =>
        new Promise((resolve) => {
          finishSave = resolve;
        }),
    );
    const saved = makeVersion({
      revision: 1,
      voice_profile_id: availableVoice.id,
    });
    api.publish.mockResolvedValue({ ...saved, state: "published" });
    renderWorkbench(api as unknown as PlatformApi);
    fireEvent.click(
      await screen.findByRole("button", { name: "Saved voice.wav" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() => expect(api.updateDraft).toHaveBeenCalledTimes(1));
    const other = screen.getByRole("button", { name: "Other voice.wav" });
    expect((other as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(other);
    expect(
      screen
        .getByRole("button", { name: "Saved voice.wav" })
        .getAttribute("aria-pressed"),
    ).toBe("true");
    await act(async () => finishSave(saved));
    await waitFor(() => expect(api.publish).toHaveBeenCalledTimes(1));
  });
});

describe("Published Agent media submission", () => {
  afterEach(cleanup);

  it("locks Voice selection before creating the next published Agent draft", async () => {
    const stored = makeVersion({
      state: "published",
      voice_profile_id: availableVoice.id,
    });
    const api = { ...makeApi(stored), nextVersion: vi.fn() };
    api.voiceProfiles.mockResolvedValue([
      availableVoice,
      {
        ...availableVoice,
        id: "voice-next",
        source_filename: "Other voice.wav",
      },
    ]);
    let finishNext!: (version: AgentVersion) => void;
    api.nextVersion.mockImplementation(
      () =>
        new Promise((resolve) => {
          finishNext = resolve;
        }),
    );
    const saved = makeVersion({ revision: 1, voice_profile_id: "voice-next" });
    api.updateDraft.mockResolvedValue(saved);
    api.publish.mockResolvedValue({ ...saved, state: "published" });
    renderWorkbench(api as unknown as PlatformApi, true);
    fireEvent.click(
      await screen.findByRole("button", { name: "Other voice.wav" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() => expect(api.nextVersion).toHaveBeenCalledTimes(1));
    expect(
      (screen.getByRole("button", { name: "Done" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    expect(
      (
        screen.getByRole("button", {
          name: "Saved voice.wav",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(api.nextVersion).toHaveBeenCalledTimes(1);
    await act(async () => finishNext(saved));
    await waitFor(() => expect(api.publish).toHaveBeenCalledTimes(1));
  });
});

describe("New Agent optional media", () => {
  afterEach(cleanup);

  it.each(["avatarTemplates", "voiceProfiles"] as const)(
    "keeps a new Agent form open when %s fails",
    async (resource) => {
      const api = {
        ...makeApi(makeVersion()),
        group: vi.fn(async () => ({ id: "group-id", course_id: "course-id" })),
      };
      api[resource].mockRejectedValue(
        new PlatformApiError(503, "Catalog unavailable"),
      );
      const create = vi.fn();
      renderWorkbench(api as unknown as PlatformApi, true, {
        groupId: "group-id",
        create,
      });
      const editor = await screen.findByRole("textbox", {
        name: "AGENT.md editor",
      });
      expect(await screen.findByRole("alert")).toBeTruthy();
      expect(screen.getByRole("textbox", { name: "Name" })).toBeTruthy();
      fireEvent.change(editor, { target: { value: "# New local Agent" } });
      expect((editor as HTMLTextAreaElement).value).toBe("# New local Agent");
      expect(create).not.toHaveBeenCalled();
      expect(api.updateDraft).not.toHaveBeenCalled();
    },
  );

  it("restores voice controls and reports a failed published-draft write", async () => {
    const stored = makeVersion({
      state: "published",
      voice_profile_id: availableVoice.id,
    });
    const api = {
      ...makeApi(stored),
      nextVersion: vi.fn(async () => makeVersion()),
    };
    api.voiceProfiles.mockResolvedValue([
      availableVoice,
      {
        ...availableVoice,
        id: "voice-next",
        source_filename: "Other voice.wav",
      },
    ]);
    api.updateDraft.mockRejectedValue(
      new PlatformApiError(503, "Draft write unavailable"),
    );
    renderWorkbench(api as unknown as PlatformApi, true);
    fireEvent.click(
      await screen.findByRole("button", { name: "Other voice.wav" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(
      (
        screen.getByRole("button", {
          name: "Other voice.wav",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(false);
    expect(
      screen
        .getByRole("button", { name: "Other voice.wav" })
        .getAttribute("aria-pressed"),
    ).toBe("true");
    expect(api.publish).not.toHaveBeenCalled();
  });
});

describe("Agent publish scope ownership", () => {
  afterEach(cleanup);

  function scopeUi(api: PlatformApi, versionId: string) {
    return (
      <LocaleProvider initialLocale="en">
        <SessionProvider api={api}>
          <AppShell role="student">
            <AgentWorkbench versionId={versionId} publishOnDone />
          </AppShell>
        </SessionProvider>
      </LocaleProvider>
    );
  }

  it.each(["published", "draft"] as const)(
    "does not carry a pending %s save into the next version scope",
    async (state) => {
      const old = makeVersion({ state });
      const fresh = makeVersion({ id: "version-b", agent_md: "# New scope" });
      const api = { ...makeApi(old), nextVersion: vi.fn() };
      api.version.mockImplementation(async () => old);
      let finishOld!: (version: AgentVersion) => void;
      const pending = () =>
        new Promise<AgentVersion>((resolve) => {
          finishOld = resolve;
        });
      if (state === "published") api.nextVersion.mockImplementation(pending);
      else api.updateDraft.mockImplementation(pending);
      const view = render(scopeUi(api as unknown as PlatformApi, "version-id"));
      fireEvent.change(await screen.findByLabelText("Material theme"), {
        target: { value: "warm_sand" },
      });
      fireEvent.click(screen.getByRole("button", { name: "Done" }));
      await waitFor(() =>
        expect(
          state === "published" ? api.nextVersion : api.updateDraft,
        ).toHaveBeenCalledTimes(1),
      );
      api.version.mockResolvedValue(fresh);
      view.rerender(scopeUi(api as unknown as PlatformApi, "version-b"));
      await waitFor(() =>
        expect(
          (
            screen.getByRole("textbox", {
              name: "AGENT.md editor",
            }) as HTMLTextAreaElement
          ).value,
        ).toBe("# New scope"),
      );
      expect(
        (
          screen.getByRole("textbox", {
            name: "AGENT.md editor",
          }) as HTMLTextAreaElement
        ).disabled,
      ).toBe(false);
      await act(async () => finishOld(makeVersion({ id: "old-draft" })));
      expect(
        (
          screen.getByRole("textbox", {
            name: "AGENT.md editor",
          }) as HTMLTextAreaElement
        ).disabled,
      ).toBe(false);
      expect(api.updateDraft).toHaveBeenCalledTimes(
        state === "published" ? 0 : 1,
      );
      expect(api.publish).not.toHaveBeenCalled();
    },
  );

  it("keeps the new scope locked when an older request finishes", async () => {
    const old = makeVersion({ state: "published" });
    const fresh = makeVersion({
      id: "version-b",
      state: "published",
      agent_md: "# New scope",
    });
    const api = { ...makeApi(old), nextVersion: vi.fn() };
    const rejects: ((error: Error) => void)[] = [];
    api.nextVersion.mockImplementation(
      () =>
        new Promise((_resolve, reject) => {
          rejects.push(reject);
        }),
    );
    const view = render(scopeUi(api as unknown as PlatformApi, "version-id"));
    fireEvent.change(await screen.findByLabelText("Material theme"), {
      target: { value: "warm_sand" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() => expect(api.nextVersion).toHaveBeenCalledTimes(1));
    api.version.mockResolvedValue(fresh);
    view.rerender(scopeUi(api as unknown as PlatformApi, "version-b"));
    await waitFor(() =>
      expect(
        (
          screen.getByRole("textbox", {
            name: "AGENT.md editor",
          }) as HTMLTextAreaElement
        ).value,
      ).toBe("# New scope"),
    );
    fireEvent.change(screen.getByLabelText("Material theme"), {
      target: { value: "cool_ink" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() => expect(api.nextVersion).toHaveBeenCalledTimes(2));
    await act(async () =>
      rejects[0](new PlatformApiError(503, "Old pending scope failed")),
    );
    expect(
      (screen.getByRole("button", { name: "Done" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    expect(
      (
        screen.getByRole("textbox", {
          name: "AGENT.md editor",
        }) as HTMLTextAreaElement
      ).disabled,
    ).toBe(true);
    expect(screen.queryByRole("alert")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(api.nextVersion).toHaveBeenCalledTimes(2);
    await act(async () =>
      rejects[1](new PlatformApiError(503, "Current pending scope failed")),
    );
    await waitFor(() =>
      expect(
        (screen.getByRole("button", { name: "Done" }) as HTMLButtonElement)
          .disabled,
      ).toBe(false),
    );
    expect(await screen.findByRole("alert")).toBeTruthy();
  });
});

describe("Agent Voice binding scope", () => {
  afterEach(cleanup);

  async function makePersonalApi(version: AgentVersion) {
    const api = {
      ...makeApi(version),
      workspaceDocuments: vi.fn(async () => []),
      createVoicePreview: vi.fn(async () => ({
        playback_url: "/api/v1/voice-previews/fixture/media",
        expires_at: "2026-10-12T12:00:00Z",
      })),
      renameVoiceProfile: vi.fn(async (_id: string, name: string) => ({
        ...availableVoice,
        source_filename: name,
      })),
    };
    api.agent.mockResolvedValue({
      ...(await api.agent()),
      group_id: null,
      ownership_scope: "personal",
    });
    api.voiceProfiles.mockResolvedValue([availableVoice]);
    api.publish.mockResolvedValue({ ...version, state: "published" });
    return api;
  }

  it("keeps personal Voice management and preview without offering a binding", async () => {
    const api = await makePersonalApi(makeVersion());
    renderWorkbench(api as unknown as PlatformApi);
    const voice = await screen.findByRole("button", {
      name: "Saved voice.wav",
    });
    expect(voice.getAttribute("aria-pressed")).toBeNull();
    expect((voice as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(voice);
    const name = screen.getByRole("textbox", { name: "Voice name" });
    fireEvent.change(name, { target: { value: "Renamed voice.wav" } });
    fireEvent.keyDown(name, { key: "Enter" });
    await screen.findByRole("button", { name: "Renamed voice.wav" });
    expect(api.renameVoiceProfile).toHaveBeenCalledWith(
      availableVoice.id,
      "Renamed voice.wav",
    );
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    await waitFor(() =>
      expect(api.createVoicePreview).toHaveBeenCalledWith(availableVoice.id),
    );
    await waitFor(() =>
      expect(
        (screen.getByRole("button", { name: "Preview" }) as HTMLButtonElement)
          .disabled,
      ).toBe(false),
    );
    fireEvent.change(screen.getByRole("textbox", { name: "AGENT.md editor" }), {
      target: { value: "# Personal saved text" },
    });
    fireEvent.change(screen.getByLabelText("Material theme"), {
      target: { value: "warm_sand" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() => expect(api.updateDraft).toHaveBeenCalledTimes(1));
    const body = api.updateDraft.mock.calls[0][1];
    expect(body).toEqual(
      expect.objectContaining({
        agent_md: "# Personal saved text",
        avatar_config: expect.objectContaining({ material_theme: "warm_sand" }),
      }),
    );
    expect(body).not.toHaveProperty("voice_profile_id");
  });

  it("can explicitly clear a personal binding even when its Voice is listed", async () => {
    const api = await makePersonalApi(
      makeVersion({ voice_profile_id: availableVoice.id }),
    );
    renderWorkbench(api as unknown as PlatformApi);
    await screen.findByRole("button", { name: "Saved voice.wav" });
    fireEvent.click(screen.getByRole("button", { name: "Current voice" }));
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() => expect(api.updateDraft).toHaveBeenCalledTimes(1));
    expect(api.updateDraft.mock.calls[0][1]).toEqual(
      expect.objectContaining({ voice_profile_id: null }),
    );
  });

  it.each(["bind", "clear"] as const)(
    "keeps same-group Voice %s available",
    async (action) => {
      const stored = makeVersion({
        voice_profile_id: action === "clear" ? availableVoice.id : null,
      });
      const api = makeApi(stored);
      api.voiceProfiles.mockResolvedValue([availableVoice]);
      api.publish.mockResolvedValue({ ...stored, state: "published" });
      renderWorkbench(api as unknown as PlatformApi);
      const voice = await screen.findByRole("button", {
        name: "Saved voice.wav",
      });
      expect(voice.getAttribute("aria-pressed")).toBe(
        action === "clear" ? "true" : "false",
      );
      fireEvent.click(voice);
      fireEvent.click(screen.getByRole("button", { name: "Done" }));
      await waitFor(() => expect(api.updateDraft).toHaveBeenCalledTimes(1));
      expect(api.updateDraft.mock.calls[0][1]).toEqual(
        expect.objectContaining({
          voice_profile_id: action === "clear" ? null : availableVoice.id,
        }),
      );
    },
  );
});
