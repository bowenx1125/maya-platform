import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { VoiceLibrary } from "../components/voice/voice-library";
import { AppShell } from "../components/app-shell";
import { PlatformApi, PlatformApiError } from "../lib/api/platform";

vi.mock("next/navigation", () => ({
  useRouter: () => ({}),
  usePathname: () => "/student/groups/group-a/voices",
}));

const api = {
  voiceProfiles: vi.fn(),
  enrollVoice: vi.fn(),
  createVoicePreview: vi.fn(),
  confirmVoiceProfile: vi.fn(),
  deleteVoiceProfile: vi.fn(),
  renameVoiceProfile: vi.fn(),
};

vi.mock("../components/session-provider", () => ({
  useSession: () => ({ api }),
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.unstubAllGlobals();
});

async function openEnrollForm() {
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "New" }).hasAttribute("disabled"),
    ).toBe(false),
  );
  fireEvent.click(screen.getByRole("button", { name: "New" }));
  const sampleHint =
    "Upload a 10–20 second clip of yourself reading aloud (16-bit WAV, MP3, or M4A; max 10 MB).";
  const input = screen.getByLabelText(sampleHint) as HTMLInputElement;
  fireEvent.change(input, {
    target: {
      files: [
        new File([new Uint8Array([1, 2, 3])], "sample.wav", {
          type: "audio/wav",
        }),
      ],
    },
  });
  fireEvent.click(screen.getByRole("checkbox"));
  return screen.findByRole("button", { name: "Done" });
}

describe("M08 voice library", () => {
  it("lets a groupmate choose a ready voice but not rename or preview it", async () => {
    api.voiceProfiles.mockResolvedValue([
      {
        id: "peer-voice",
        scope: "group",
        group_id: "group-a",
        status: "ready",
        source_filename: "peer.wav",
        created_at: "2026-10-12T00:00:00Z",
        can_manage: false,
      },
    ]);
    const onSelect = vi.fn();
    render(
      <AppShell role="student">
        <VoiceLibrary groupId="group-a" onSelect={onSelect} />
      </AppShell>,
    );
    fireEvent.click(await screen.findByRole("button", { name: "peer.wav" }));
    expect(onSelect).toHaveBeenCalledWith("peer-voice");
    expect(screen.queryByRole("button", { name: "Preview" })).toBeNull();
  });

  it("shows a groupmate's voice as a plain name outside a picker", async () => {
    api.voiceProfiles.mockResolvedValue([
      {
        id: "peer-voice",
        scope: "group",
        group_id: "group-a",
        status: "ready",
        source_filename: "peer.wav",
        created_at: "2026-10-12T00:00:00Z",
        can_manage: false,
      },
    ]);
    render(
      <AppShell role="student">
        <VoiceLibrary groupId="group-a" />
      </AppShell>,
    );
    expect(await screen.findByText("peer.wav")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "peer.wav" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Preview" })).toBeNull();
  });

  it("requires consent and a local file before enrollment", async () => {
    api.voiceProfiles.mockResolvedValue([]);
    render(
      <AppShell role="student">
        <VoiceLibrary groupId="group-a" />
      </AppShell>,
    );
    await waitFor(() =>
      expect(api.voiceProfiles).toHaveBeenCalledWith("group-a"),
    );
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "New" }).hasAttribute("disabled"),
      ).toBe(false),
    );
    expect(screen.getByText("No voices yet.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "New" }));
    const consentCopy =
      "I confirm this is my voice and authorize this course to create a reusable profile.";
    expect(screen.getByText(consentCopy)).toBeTruthy();
    expect(screen.queryByText("Consent")).toBeNull();
    expect(
      screen
        .getByRole("checkbox", { name: consentCopy })
        .closest("[data-ui-guide]"),
    ).toBeNull();
    const done = screen.getByRole("button", {
      name: "Done",
    }) as HTMLButtonElement;
    expect(done.disabled).toBe(true);
    expect(screen.queryByRole("button", { name: "New" })).toBeNull();

    const sampleHint =
      "Upload a 10–20 second clip of yourself reading aloud (16-bit WAV, MP3, or M4A; max 10 MB).";
    const input = screen.getByLabelText(sampleHint) as HTMLInputElement;
    expect(screen.queryByText(sampleHint)).toBeNull();
    const file = new File([new Uint8Array([1, 2, 3])], "sample.wav", {
      type: "audio/wav",
    });
    fireEvent.change(input, { target: { files: [file] } });
    expect(done.disabled).toBe(true);
    fireEvent.click(screen.getByRole("checkbox"));
    await waitFor(() => expect(done.disabled).toBe(false));
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.queryByRole("button", { name: "Done" })).toBeNull();
    expect(screen.queryByLabelText(sampleHint)).toBeNull();
    expect(await screen.findByRole("button", { name: "New" })).toBeTruthy();
    expect(api.enrollVoice).not.toHaveBeenCalled();
  });

  it("enrolls without a language selector and shows the filename without an id", async () => {
    const created = {
      id: "voice-new",
      scope: "group",
      group_id: "group-a",
      status: "preview_ready",
      source_filename: "sample.wav",
      safe_error_code: null,
      created_at: "2026-01-01T00:00:00Z",
    };
    let enrolled = false;
    api.voiceProfiles.mockImplementation(async () =>
      enrolled ? [created] : [],
    );
    api.enrollVoice.mockImplementation(async () => {
      enrolled = true;
      return created;
    });
    render(
      <AppShell role="student">
        <VoiceLibrary groupId="group-a" />
      </AppShell>,
    );
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "New" }).hasAttribute("disabled"),
      ).toBe(false),
    );
    fireEvent.click(screen.getByRole("button", { name: "New" }));
    const sampleHint =
      "Upload a 10–20 second clip of yourself reading aloud (16-bit WAV, MP3, or M4A; max 10 MB).";
    expect(screen.queryByText(sampleHint)).toBeNull();
    const input = screen.getByLabelText(sampleHint) as HTMLInputElement;
    fireEvent.change(input, {
      target: {
        files: [
          new File([new Uint8Array([1, 2, 3])], "sample.wav", {
            type: "audio/wav",
          }),
        ],
      },
    });
    expect(screen.queryByLabelText("Sample language")).toBeNull();
    expect(screen.queryByRole("combobox")).toBeNull();
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(await screen.findByRole("button", { name: "Done" }));
    await waitFor(() =>
      expect(api.enrollVoice).toHaveBeenCalledWith(
        "group-a",
        expect.any(File),
        "voice-consent-v1",
        expect.objectContaining({ idempotency: expect.any(Object) }),
      ),
    );
    expect(api.enrollVoice.mock.calls[0][3]).not.toHaveProperty("language");
    expect(
      await screen.findByRole("button", { name: "sample.wav" }),
    ).toBeTruthy();
    expect(screen.queryByText("voice-new")).toBeNull();
    expect(await screen.findByText("Created")).toBeTruthy();
  });

  it("does not show Created when enroll returns a failed profile", async () => {
    api.voiceProfiles.mockResolvedValue([]);
    api.enrollVoice.mockResolvedValue({
      id: "voice-failed",
      scope: "group",
      group_id: "group-a",
      status: "failed",
      source_filename: "sample.wav",
      safe_error_code: "voice_enrollment_failed",
      created_at: "2026-01-01T00:00:00Z",
    });
    render(
      <AppShell role="student">
        <VoiceLibrary groupId="group-a" />
      </AppShell>,
    );
    await openEnrollForm();
    fireEvent.click(await screen.findByRole("button", { name: "Done" }));
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.queryByText("Created")).toBeNull();
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
  });

  it("shows refuse-clone error without Retry and without Created", async () => {
    api.voiceProfiles.mockResolvedValue([]);
    api.enrollVoice.mockRejectedValue(
      new PlatformApiError(422, "refused", { code: "voice_clone_refused" }),
    );
    render(
      <AppShell role="student">
        <VoiceLibrary groupId="group-a" />
      </AppShell>,
    );
    await openEnrollForm();
    fireEvent.click(await screen.findByRole("button", { name: "Done" }));
    expect(
      await screen.findByText(
        "This voice path does not support cloning. The sample was not saved as a custom voice.",
      ),
    ).toBeTruthy();
    expect(screen.queryByText("Created")).toBeNull();
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
    expect(screen.queryByText(/temporarily unavailable/i)).toBeNull();
  });

  it("keeps Retry for a provider outage during enroll", async () => {
    api.voiceProfiles.mockResolvedValue([]);
    api.enrollVoice.mockRejectedValue(
      new PlatformApiError(503, "down", { code: "provider_unavailable" }),
    );
    render(
      <AppShell role="student">
        <VoiceLibrary groupId="group-a" />
      </AppShell>,
    );
    await openEnrollForm();
    fireEvent.click(await screen.findByRole("button", { name: "Done" }));
    expect(await screen.findByRole("button", { name: "Retry" })).toBeTruthy();
    expect(screen.queryByText("Created")).toBeNull();
  });

  it("shows a platform preview URL and only confirms after preview", async () => {
    api.voiceProfiles.mockResolvedValue([
      {
        id: "voice-1",
        scope: "group",
        group_id: "group-a",
        status: "preview_ready",
        source_filename: "sample.wav",
        safe_error_code: null,
        created_at: "2026-01-01T00:00:00Z",
      },
    ]);
    api.createVoicePreview.mockResolvedValue({
      playback_url: "/api/v1/voice-previews/preview-1/media",
      expires_at: new Date(Date.now() + 60_000).toISOString(),
    });
    api.confirmVoiceProfile.mockResolvedValue({
      id: "voice-1",
      scope: "group",
      group_id: "group-a",
      status: "ready",
      source_filename: "sample.wav",
      safe_error_code: null,
      created_at: "2026-01-01T00:00:00Z",
    });
    render(<VoiceLibrary groupId="group-a" />);
    await waitFor(() => expect(screen.getByText("sample.wav")).toBeTruthy());
    expect(screen.queryByText("voice-1")).toBeNull();
    const confirm = screen.getByRole("button", { name: /^confirm$/i });
    expect((confirm as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: /^preview$/i }));
    await waitFor(() => expect(document.querySelector("audio")).toBeTruthy());
    expect((document.querySelector("audio") as HTMLAudioElement).src).toContain(
      "/api/v1/voice-previews/preview-1/media",
    );
    expect((confirm as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(confirm);
    await waitFor(() =>
      expect(api.confirmVoiceProfile).toHaveBeenCalledWith("voice-1"),
    );
  });
});

const profile = {
  id: "voice-edit",
  scope: "group",
  group_id: "group-a",
  status: "ready",
  source_filename: "sample.wav",
  safe_error_code: null,
  created_at: "2026-01-01T00:00:00Z",
};

describe("voice filename editing", () => {
  it("saves once for Enter followed by blur and loads the persisted name", async () => {
    let saved = profile;
    let finish!: (value: typeof profile) => void;
    api.voiceProfiles.mockImplementation(async () => [saved]);
    api.renameVoiceProfile.mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    const view = render(<VoiceLibrary groupId="group-a" />);
    fireEvent.click(await screen.findByRole("button", { name: "sample.wav" }));
    const input = screen.getByRole("textbox", { name: "Voice name" });
    fireEvent.change(input, { target: { value: "古典哲学" } });
    fireEvent.keyDown(input, { key: "Enter" });
    fireEvent.blur(input);
    expect(api.renameVoiceProfile).toHaveBeenCalledTimes(1);
    expect(api.renameVoiceProfile).toHaveBeenCalledWith(
      "voice-edit",
      "古典哲学",
    );
    saved = { ...profile, source_filename: "古典哲学" };
    finish(saved);
    expect(
      await screen.findByRole("button", { name: "古典哲学" }),
    ).toBeTruthy();
    expect(screen.queryByText("voice-edit")).toBeNull();
    expect(screen.queryByText(/Voice ID/)).toBeNull();
    view.unmount();
    render(<VoiceLibrary groupId="group-a" />);
    expect(
      await screen.findByRole("button", { name: "古典哲学" }),
    ).toBeTruthy();
  });

  it("cancels with Escape and skips unchanged names", async () => {
    api.voiceProfiles.mockResolvedValue([profile]);
    render(<VoiceLibrary groupId="group-a" />);
    fireEvent.click(await screen.findByRole("button", { name: "sample.wav" }));
    const input = screen.getByRole("textbox", { name: "Voice name" });
    fireEvent.change(input, { target: { value: "Unwanted change" } });
    fireEvent.keyDown(input, { key: "Escape" });
    const name = screen.getByRole("button", { name: "sample.wav" });
    expect(document.activeElement).toBe(name);
    fireEvent.click(name);
    fireEvent.blur(screen.getByRole("textbox", { name: "Voice name" }));
    expect(screen.queryByRole("textbox", { name: "Voice name" })).toBeNull();
    expect(api.renameVoiceProfile).not.toHaveBeenCalled();
  });

  it("keeps a failed edit and saves it on a later blur", async () => {
    api.voiceProfiles.mockResolvedValue([profile]);
    api.renameVoiceProfile
      .mockRejectedValueOnce(new Error("Rename unavailable"))
      .mockResolvedValueOnce({ ...profile, source_filename: "New name" });
    render(<VoiceLibrary groupId="group-a" />);
    fireEvent.click(await screen.findByRole("button", { name: "sample.wav" }));
    const input = screen.getByRole("textbox", { name: "Voice name" });
    fireEvent.change(input, { target: { value: "New name" } });
    fireEvent.blur(input);
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.getByRole("textbox", { name: "Voice name" })).toHaveProperty(
      "value",
      "New name",
    );
    fireEvent.focus(input);
    fireEvent.blur(input);
    expect(
      await screen.findByRole("button", { name: "New name" }),
    ).toBeTruthy();
    expect(api.renameVoiceProfile).toHaveBeenCalledTimes(2);
  });
});

describe("voice rename API", () => {
  it("persists the name through the profile PATCH endpoint with CSRF", async () => {
    const renamed = { ...profile, source_filename: "我的声音" };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(renamed), {
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const client = new PlatformApi({
      baseUrl: "http://maya.test/api/v1",
      csrfToken: "test-csrf",
    });
    expect(
      await client.renameVoiceProfile(profile.id, renamed.source_filename),
    ).toEqual(renamed);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const request = fetchMock.mock.calls[0][0] as Request;
    expect(request.method).toBe("PATCH");
    expect(request.url).toBe(
      "http://maya.test/api/v1/voice-profiles/voice-edit",
    );
    expect(request.headers.get("X-CSRF-Token")).toBe("test-csrf");
    expect(await request.json()).toEqual({ source_filename: "我的声音" });
  });
});

describe("Voice catalog failure boundaries", () => {
  it.each([503, 403, 404, 0])(
    "shows a local error rather than an empty library for status %s",
    async (status) => {
      api.voiceProfiles.mockRejectedValue(
        status
          ? new PlatformApiError(status, "Unavailable")
          : new Error("Unclassified network failure"),
      );
      const onSelect = vi.fn();
      render(
        <VoiceLibrary
          groupId="group-a"
          selectedId={profile.id}
          onSelect={onSelect}
        />,
      );
      expect(await screen.findByRole("alert")).toBeTruthy();
      expect(screen.queryByText("No voices yet.")).toBeNull();
      expect(screen.queryByRole("button", { name: "sample.wav" })).toBeNull();
      expect(onSelect).not.toHaveBeenCalled();
      expect(api.enrollVoice).not.toHaveBeenCalled();
      if (status === 403 || status === 404) {
        expect(
          (screen.getByRole("button", { name: "New" }) as HTMLButtonElement)
            .disabled,
        ).toBe(true);
      }
    },
  );

  it("locks all voice mutations when the parent is saving", async () => {
    api.voiceProfiles.mockResolvedValue([profile]);
    const onSelect = vi.fn();
    const view = render(
      <VoiceLibrary
        groupId="group-a"
        disabled
        selectedId={profile.id}
        onSelect={onSelect}
      />,
    );
    const choice = await screen.findByRole("button", { name: "sample.wav" });
    expect((choice as HTMLButtonElement).disabled).toBe(true);
    expect(
      (screen.getByRole("button", { name: "Preview" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    expect(
      (screen.getByRole("button", { name: "New" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    fireEvent.click(choice);
    expect(onSelect).not.toHaveBeenCalled();
    view.rerender(
      <VoiceLibrary
        groupId="group-a"
        selectedId={profile.id}
        onSelect={onSelect}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "sample.wav" }));
    expect(onSelect).toHaveBeenCalledWith(profile.id);
  });
});
