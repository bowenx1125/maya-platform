import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { VoiceLibrary } from "../components/voice/voice-library";

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
    render(<VoiceLibrary groupId="group-a" />);
    await waitFor(() =>
      expect(api.voiceProfiles).toHaveBeenCalledWith("group-a"),
    );
    const button = screen.getByRole("button", {
      name: /^upload$/i,
    });
    expect((button as HTMLButtonElement).disabled).toBe(true);

    const input = screen.getByLabelText(
      "Voice sample file",
    ) as HTMLInputElement;
    const file = new File([new Uint8Array([1, 2, 3])], "sample.wav", {
      type: "audio/wav",
    });
    fireEvent.change(input, { target: { files: [file] } });
    expect((button as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("checkbox"));
    expect((button as HTMLButtonElement).disabled).toBe(false);
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
