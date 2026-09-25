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
};

vi.mock("../components/session-provider", () => ({
  useSession: () => ({ api }),
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("M08 voice library", () => {
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
    fireEvent.click(screen.getByRole("button", { name: "New" }));
    expect(screen.queryByRole("button", { name: "Done" })).toBeNull();
    expect(
      (screen.getByRole("button", { name: "New" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);

    const input = screen.getByLabelText(
      "Voice sample file",
    ) as HTMLInputElement;
    const file = new File([new Uint8Array([1, 2, 3])], "sample.wav", {
      type: "audio/wav",
    });
    fireEvent.change(input, { target: { files: [file] } });
    expect(screen.queryByRole("button", { name: "Done" })).toBeNull();
    fireEvent.click(screen.getByRole("checkbox"));
    expect(await screen.findByRole("button", { name: "Done" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.queryByRole("button", { name: "Done" })).toBeNull();
    expect(screen.queryByLabelText("Voice sample file")).toBeNull();
    expect(await screen.findByRole("button", { name: "New" })).toBeTruthy();
    expect(api.enrollVoice).not.toHaveBeenCalled();
  });

  it("enrolls with the selected sample language and shows the voice id", async () => {
    const created = {
      id: "voice-new",
      scope: "group",
      group_id: "group-a",
      status: "enrolling",
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
    const input = screen.getByLabelText(
      "Voice sample file",
    ) as HTMLInputElement;
    fireEvent.change(input, {
      target: {
        files: [
          new File([new Uint8Array([1, 2, 3])], "sample.wav", {
            type: "audio/wav",
          }),
        ],
      },
    });
    fireEvent.change(screen.getByLabelText("Sample language"), {
      target: { value: "zh-CN" },
    });
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(await screen.findByRole("button", { name: "Done" }));
    await waitFor(() =>
      expect(api.enrollVoice).toHaveBeenCalledWith(
        "group-a",
        expect.any(File),
        "voice-consent-v1",
        expect.objectContaining({ language: "zh-CN" }),
      ),
    );
    expect(await screen.findByText("voice-new")).toBeTruthy();
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
      expires_at: "2026-01-01T00:10:00Z",
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
    expect(screen.getByText("voice-1")).toBeTruthy();
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
