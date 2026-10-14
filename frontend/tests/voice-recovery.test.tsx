import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppShell } from "../components/app-shell";
import { VoiceLibrary } from "../components/voice/voice-library";
import { PlatformApiError } from "../lib/api/platform";

vi.mock("next/navigation", () => ({
  useRouter: () => ({}),
  usePathname: () => "/student/groups/group-a/voices",
}));

const api = {
  voiceProfiles: vi.fn(),
  personalVoiceProfiles: vi.fn(),
  enrollVoice: vi.fn(),
  enrollPersonalVoice: vi.fn(),
  voiceProfile: vi.fn(),
  createVoicePreview: vi.fn(),
  confirmVoiceProfile: vi.fn(),
  renameVoiceProfile: vi.fn(),
};

vi.mock("../components/session-provider", () => ({
  useSession: () => ({ api }),
}));

const unfinished = {
  id: "voice-1",
  scope: "group" as const,
  group_id: "group-a",
  status: "preview_ready" as const,
  source_filename: "sample.wav",
  safe_error_code: null,
  can_manage: true,
  created_at: "2026-01-01T00:00:00Z",
};

function previewResource(seconds = 60) {
  return {
    playback_url: "/api/v1/voice-previews/preview-1/media",
    expires_at: new Date(Date.now() + seconds * 1000).toISOString(),
  };
}

beforeEach(() => {
  vi.resetAllMocks();
  api.voiceProfiles.mockResolvedValue([unfinished]);
  api.personalVoiceProfiles.mockResolvedValue([
    { ...unfinished, scope: "personal", group_id: null },
  ]);
  api.createVoicePreview.mockImplementation(async () => previewResource());
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("Voice recovery", () => {
  it.each([false, true])(
    "retries a failed preview without another enrollment (personal=%s)",
    async (personal) => {
      api.createVoicePreview.mockRejectedValueOnce(
        new PlatformApiError(503, "Unavailable", {
          code: "provider_unavailable",
        }),
      );
      const onSelect = vi.fn();
      const onProfilesChange = vi.fn();
      const profile = {
        ...unfinished,
        scope: personal ? "personal" : "group",
        group_id: personal ? null : "group-a",
      };
      const list = personal ? api.personalVoiceProfiles : api.voiceProfiles;
      list.mockResolvedValue([profile]);
      api.confirmVoiceProfile.mockImplementation(async () => {
        const ready = { ...profile, status: "ready" };
        list.mockResolvedValue([ready]);
        return ready;
      });
      render(
        <VoiceLibrary
          groupId={personal ? null : "group-a"}
          courseId={personal ? "course-a" : null}
          onSelect={onSelect}
          onProfilesChange={onProfilesChange}
        />,
      );
      fireEvent.click(await screen.findByRole("button", { name: "Preview" }));
      expect(await screen.findByRole("alert")).toBeTruthy();
      expect(screen.getByRole("button", { name: "Confirm" })).toHaveProperty(
        "disabled",
        true,
      );
      fireEvent.focus(window);
      await waitFor(() => expect(list).toHaveBeenCalledTimes(2));
      expect(screen.getByRole("alert")).toBeTruthy();
      expect(api.createVoicePreview).toHaveBeenCalledTimes(1);
      fireEvent.click(screen.getByRole("button", { name: "Retry" }));
      await waitFor(() => expect(document.querySelector("audio")).toBeTruthy());
      expect(api.createVoicePreview.mock.calls).toEqual([
        [unfinished.id],
        [unfinished.id],
      ]);
      fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
      const choice = screen.getByRole("button", { name: "sample.wav" });
      await waitFor(() => expect(choice).toHaveProperty("disabled", false));
      fireEvent.click(choice);
      expect(onSelect).toHaveBeenCalledWith(unfinished.id);
      expect(onProfilesChange).toHaveBeenLastCalledWith([
        expect.objectContaining({ status: "ready" }),
      ]);
      expect(api.enrollVoice).not.toHaveBeenCalled();
      expect(api.enrollPersonalVoice).not.toHaveBeenCalled();
    },
  );

  it.each([false, true])(
    "retries the same upload with its original idempotency handle (personal=%s)",
    async (personal) => {
      const list = personal ? api.personalVoiceProfiles : api.voiceProfiles;
      const enroll = personal ? api.enrollPersonalVoice : api.enrollVoice;
      list.mockResolvedValue([]);
      enroll
        .mockRejectedValueOnce(new TypeError("Network interrupted"))
        .mockResolvedValueOnce(unfinished);
      render(
        <AppShell role={personal ? "teacher" : "student"}>
          <VoiceLibrary
            groupId={personal ? null : "group-a"}
            courseId={personal ? "course-a" : null}
          />
        </AppShell>,
      );
      const newButton = await screen.findByRole("button", { name: "New" });
      await waitFor(() => expect(newButton).toHaveProperty("disabled", false));
      fireEvent.click(newButton);
      const file = new File([new Uint8Array([1, 2, 3])], "sample.wav", {
        type: "audio/wav",
      });
      fireEvent.change(screen.getByLabelText(/10–15-second/), {
        target: { files: [file] },
      });
      fireEvent.click(screen.getByRole("checkbox"));
      fireEvent.click(screen.getByRole("button", { name: "Done" }));
      expect(await screen.findByRole("alert")).toBeTruthy();
      const initial = enroll.mock.calls[0];
      fireEvent.click(screen.getByRole("button", { name: "Retry" }));
      await waitFor(() => expect(enroll).toHaveBeenCalledTimes(2));
      expect(enroll.mock.calls[1][0]).toBe(personal ? "course-a" : "group-a");
      expect(enroll.mock.calls[1][1]).toBe(file);
      expect(enroll.mock.calls[1][3].idempotency).toBe(initial[3].idempotency);
      expect(api.createVoicePreview).not.toHaveBeenCalled();
    },
  );

  it("expires a preview without making an automatic provider request", async () => {
    api.createVoicePreview.mockImplementation(async () => previewResource(1));
    render(<VoiceLibrary groupId="group-a" />);
    const preview = await screen.findByRole("button", { name: "Preview" });
    vi.useFakeTimers();
    await act(async () => fireEvent.click(preview));
    expect(screen.getByRole("button", { name: "Confirm" })).toHaveProperty(
      "disabled",
      false,
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1001);
    });
    expect(
      screen.getByText(
        "This preview has expired. Preview the voice again before confirming.",
      ),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "Confirm" })).toHaveProperty(
      "disabled",
      true,
    );
    expect(document.querySelector("audio")).toBeNull();
    expect(api.createVoicePreview).toHaveBeenCalledTimes(1);
    expect(api.confirmVoiceProfile).not.toHaveBeenCalled();
    await act(async () =>
      fireEvent.click(screen.getByRole("button", { name: "Retry" })),
    );
    expect(api.createVoicePreview).toHaveBeenCalledTimes(2);
  });

  it("invalidates failed media and requires an explicit preview retry", async () => {
    render(<VoiceLibrary groupId="group-a" />);
    fireEvent.click(await screen.findByRole("button", { name: "Preview" }));
    await waitFor(() => expect(document.querySelector("audio")).toBeTruthy());
    fireEvent.error(document.querySelector("audio")!);
    expect(
      screen.getByText(
        "The preview could not be played. Retry the preview before confirming.",
      ),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "Confirm" })).toHaveProperty(
      "disabled",
      true,
    );
    expect(api.createVoicePreview).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() =>
      expect(api.createVoicePreview).toHaveBeenCalledTimes(2),
    );
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Confirm" })).toHaveProperty(
        "disabled",
        false,
      ),
    );
  });

  it("recovers a lost confirmation response without confirming or synthesizing again", async () => {
    const ready = { ...unfinished, status: "ready" };
    api.confirmVoiceProfile.mockRejectedValueOnce(
      new TypeError("Network interrupted"),
    );
    api.voiceProfile.mockResolvedValue(ready);
    render(<VoiceLibrary groupId="group-a" />);
    fireEvent.click(await screen.findByRole("button", { name: "Preview" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Confirm" })).toHaveProperty(
        "disabled",
        false,
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    expect(await screen.findByRole("alert")).toBeTruthy();
    api.voiceProfiles.mockResolvedValue([ready]);
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Confirm" })).toBeNull(),
    );
    expect(api.voiceProfile).toHaveBeenCalledWith(unfinished.id);
    expect(api.confirmVoiceProfile).toHaveBeenCalledTimes(1);
    expect(api.createVoicePreview).toHaveBeenCalledTimes(1);
    expect(document.querySelector("audio")).toBeNull();
  });

  it.each([false, true])(
    "clears a preview expiry after delayed confirmation reaches ready (conflict=%s)",
    async (conflict) => {
      const ready = { ...unfinished, status: "ready" };
      let resolveConfirmation!: (profile: typeof ready) => void;
      let rejectConfirmation!: (cause: Error) => void;
      api.confirmVoiceProfile.mockImplementation(
        () =>
          new Promise<typeof ready>((resolve, reject) => {
            resolveConfirmation = resolve;
            rejectConfirmation = reject;
          }),
      );
      api.createVoicePreview.mockImplementation(async () => previewResource(1));
      api.voiceProfile.mockResolvedValue(ready);
      render(<VoiceLibrary groupId="group-a" onSelect={vi.fn()} />);
      const preview = await screen.findByRole("button", { name: "Preview" });
      vi.useFakeTimers();
      await act(async () => fireEvent.click(preview));
      await act(async () =>
        fireEvent.click(screen.getByRole("button", { name: "Confirm" })),
      );
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1001);
      });
      expect(screen.getByRole("alert")).toBeTruthy();
      api.voiceProfiles.mockResolvedValue([ready]);
      await act(async () => {
        if (conflict) {
          rejectConfirmation(
            new PlatformApiError(409, "Invalid state", {
              code: "invalid_state",
            }),
          );
        } else {
          resolveConfirmation(ready);
        }
      });
      expect(screen.queryByRole("alert")).toBeNull();
      expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
      expect(screen.getByRole("button", { name: "sample.wav" })).toHaveProperty(
        "disabled",
        false,
      );
      expect(api.confirmVoiceProfile).toHaveBeenCalledTimes(1);
      expect(api.createVoicePreview).toHaveBeenCalledTimes(1);
    },
  );

  it.each([false, true])(
    "preserves another Voice's expiry after delayed confirmation reaches ready (conflict=%s)",
    async (conflict) => {
      const other = {
        ...unfinished,
        id: "voice-2",
        source_filename: "other.wav",
      };
      const ready = { ...unfinished, status: "ready" };
      let resolveConfirmation!: (profile: typeof ready) => void;
      let rejectConfirmation!: (cause: Error) => void;
      api.voiceProfiles.mockResolvedValue([unfinished, other]);
      api.confirmVoiceProfile.mockImplementation(
        () =>
          new Promise<typeof ready>((resolve, reject) => {
            resolveConfirmation = resolve;
            rejectConfirmation = reject;
          }),
      );
      api.createVoicePreview.mockImplementation(async (profileId: string) =>
        previewResource(profileId === other.id ? 1 : 60),
      );
      api.voiceProfile.mockResolvedValue(ready);
      render(<VoiceLibrary groupId="group-a" onSelect={vi.fn()} />);
      await screen.findByRole("button", { name: "sample.wav" });
      const previews = screen.getAllByRole("button", { name: "Preview" });
      vi.useFakeTimers();
      await act(async () => fireEvent.click(previews[0]));
      await act(async () => fireEvent.click(previews[1]));
      await act(async () =>
        fireEvent.click(screen.getAllByRole("button", { name: "Confirm" })[0]),
      );
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1001);
      });
      expect(screen.getByRole("alert")).toBeTruthy();
      api.voiceProfiles.mockResolvedValue([ready, other]);
      await act(async () => {
        if (conflict) {
          rejectConfirmation(
            new PlatformApiError(409, "Invalid state", {
              code: "invalid_state",
            }),
          );
        } else {
          resolveConfirmation(ready);
        }
      });
      expect(screen.getByRole("alert")).toBeTruthy();
      expect(screen.getByRole("button", { name: "sample.wav" })).toHaveProperty(
        "disabled",
        false,
      );
      await act(async () =>
        fireEvent.click(screen.getByRole("button", { name: "Retry" })),
      );
      expect(api.createVoicePreview).toHaveBeenCalledTimes(3);
      expect(api.createVoicePreview).toHaveBeenLastCalledWith(other.id);
      expect(api.confirmVoiceProfile).toHaveBeenCalledTimes(1);
    },
  );

  it.each(["ready", "preview_ready"])(
    "reconciles an invalid confirmation against the current %s status",
    async (status) => {
      api.confirmVoiceProfile.mockRejectedValueOnce(
        new PlatformApiError(409, "Invalid state", { code: "invalid_state" }),
      );
      api.voiceProfile.mockResolvedValue({ ...unfinished, status });
      render(<VoiceLibrary groupId="group-a" />);
      fireEvent.click(await screen.findByRole("button", { name: "Preview" }));
      await waitFor(() =>
        expect(screen.getByRole("button", { name: "Confirm" })).toHaveProperty(
          "disabled",
          false,
        ),
      );
      api.voiceProfiles.mockResolvedValue([{ ...unfinished, status }]);
      fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
      await waitFor(() =>
        expect(api.voiceProfile).toHaveBeenCalledWith(unfinished.id),
      );
      if (status === "ready") {
        await waitFor(() =>
          expect(screen.queryByRole("button", { name: "Confirm" })).toBeNull(),
        );
        expect(screen.queryByRole("alert")).toBeNull();
      } else {
        expect(
          await screen.findByText(
            "This preview has expired. Preview the voice again before confirming.",
          ),
        ).toBeTruthy();
        expect(screen.getByRole("button", { name: "Confirm" })).toHaveProperty(
          "disabled",
          true,
        );
      }
      expect(api.createVoicePreview).toHaveBeenCalledTimes(1);
      expect(api.confirmVoiceProfile).toHaveBeenCalledTimes(1);
    },
  );

  it("retries a failed rename with the edited name", async () => {
    api.renameVoiceProfile
      .mockRejectedValueOnce(new TypeError("Network interrupted"))
      .mockResolvedValueOnce({ ...unfinished, source_filename: "My voice" });
    render(<VoiceLibrary groupId="group-a" />);
    fireEvent.click(await screen.findByRole("button", { name: "sample.wav" }));
    const name = screen.getByRole("textbox", { name: "Voice name" });
    fireEvent.change(name, { target: { value: "My voice" } });
    fireEvent.blur(name);
    expect(await screen.findByRole("alert")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(
      await screen.findByRole("button", { name: "My voice" }),
    ).toBeTruthy();
    expect(api.renameVoiceProfile.mock.calls).toEqual([
      [unfinished.id, "My voice"],
      [unfinished.id, "My voice"],
    ]);
  });

  it("shows readable fallback guidance when the voice provider is unavailable", async () => {
    api.createVoicePreview.mockRejectedValueOnce(
      new PlatformApiError(503, "Unavailable", {
        code: "provider_unavailable",
      }),
    );
    render(<VoiceLibrary groupId="group-a" />);
    fireEvent.click(await screen.findByRole("button", { name: "Preview" }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toMatch(/platform fallback voice/i);
    expect(alert.textContent).toMatch(/not a successful custom voice/i);
    expect(screen.queryByText(/Voice profile created/i)).toBeNull();
  });

  it("clears the enroll error after a successful Retry", async () => {
    api.voiceProfiles.mockResolvedValue([]);
    api.enrollVoice
      .mockRejectedValueOnce(
        new PlatformApiError(503, "Unavailable", {
          code: "provider_unavailable",
        }),
      )
      .mockResolvedValueOnce(unfinished);
    render(
      <AppShell role="student">
        <VoiceLibrary groupId="group-a" />
      </AppShell>,
    );
    const newButton = await screen.findByRole("button", { name: "New" });
    await waitFor(() => expect(newButton).toHaveProperty("disabled", false));
    fireEvent.click(newButton);
    const file = new File([new Uint8Array([1, 2, 3])], "sample.wav", {
      type: "audio/wav",
    });
    fireEvent.change(screen.getByLabelText(/10–15-second/), {
      target: { files: [file] },
    });
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toMatch(
      /platform fallback voice/i,
    );
    api.voiceProfiles.mockResolvedValue([unfinished]);
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
    expect(api.enrollVoice).toHaveBeenCalledTimes(2);
  });
});
