import "@testing-library/jest-dom/vitest";

import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { VoiceLibrary } from "../components/voice/voice-library";
import { AppShell } from "../components/app-shell";
import { PlatformApi, PlatformApiError } from "../lib/api/platform";

vi.mock("next/navigation", () => ({
  useRouter: () => ({}),
  usePathname: () => "/student/voices",
}));

const api = {
  voiceProfiles: vi.fn(),
  personalVoiceProfiles: vi.fn(),
  voiceAffectedAgents: vi.fn().mockResolvedValue([]),
  enrollVoice: vi.fn(),
  createVoicePreview: vi.fn(),
  deleteVoiceProfile: vi.fn(),
  renameVoiceProfile: vi.fn(),
};

vi.mock("../components/session-provider", () => ({
  useSession: () => ({ api }),
}));

const CONSENT =
  "I confirm this is my voice and authorize this course to create a reusable profile.";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  api.voiceAffectedAgents.mockReset().mockResolvedValue([]);
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
  // Confirming consent is the create step; there is no sidebar Done.
  return screen.findByRole("button", { name: CONSENT });
}

describe("M08 voice library", () => {
  it.each([
    { role: "teacher", visiting: false },
    { role: "teacher", visiting: true },
    { role: "student", visiting: false },
  ] as const)(
    "shows the API creator and visible Agent usage in the $role album (visiting=$visiting)",
    async ({ role, visiting }) => {
      const profile = {
        id: "album-voice",
        scope: role === "teacher" && !visiting ? "personal" : "group",
        status: "ready",
        source_filename: "sample.wav",
        created_at: "2026-10-12T00:00:00Z",
        owner_username: "voicecreator",
        can_manage: role === "teacher",
      };
      api.voiceProfiles.mockResolvedValue([profile]);
      api.personalVoiceProfiles.mockResolvedValue([profile]);
      api.voiceAffectedAgents.mockResolvedValue([
        { agent_id: "visible-agent", name: "Socrates" },
      ]);
      render(
        <AppShell role={role}>
          <VoiceLibrary
            album
            groupId={role === "student" || visiting ? "group-a" : null}
            courseId={role === "teacher" && !visiting ? "course-a" : null}
            listenOnly={visiting}
          />
        </AppShell>,
      );
      expect(await screen.findByText("@voicecreator")).toBeVisible();
      expect(await screen.findByText("Socrates")).toBeVisible();
      expect(screen.queryByText("No Agents yet")).toBeNull();
      expect(api.voiceAffectedAgents).toHaveBeenCalledWith("album-voice");
    },
  );

  it("reports a failed usage lookup and retries it when the list reloads", async () => {
    api.voiceProfiles.mockResolvedValue([
      {
        id: "album-voice",
        scope: "group",
        status: "ready",
        source_filename: "sample.wav",
        created_at: "2026-10-12T00:00:00Z",
        owner_username: "voicecreator",
      },
    ]);
    api.voiceAffectedAgents
      .mockRejectedValueOnce(new PlatformApiError(503, "Usage unavailable."))
      .mockResolvedValue([{ agent_id: "visible-agent", name: "Socrates" }]);
    render(
      <AppShell role="student">
        <VoiceLibrary album groupId="group-a" />
      </AppShell>,
    );
    expect(
      await screen.findByText(
        "A platform capability is temporarily unavailable.",
      ),
    ).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("Socrates")).toBeVisible();
    expect(
      screen.queryByText("A platform capability is temporarily unavailable."),
    ).toBeNull();
  });

  it.each([
    { embedded: true, moduleCard: false, picker: true },
    { embedded: true, moduleCard: false, picker: false },
    { embedded: true, moduleCard: true, picker: true },
    { embedded: false, moduleCard: false, picker: true },
  ])(
    "places New below the embedded Agent body only ($embedded/$moduleCard/$picker)",
    async ({ embedded, moduleCard, picker }) => {
      api.voiceProfiles.mockResolvedValue([]);
      render(
        <VoiceLibrary
          groupId="group-a"
          embedded={embedded}
          moduleCard={moduleCard}
          onSelect={picker ? vi.fn() : undefined}
        />,
      );
      const create = screen.getByRole("button", { name: "New" });
      await waitFor(() => expect(create).toBeEnabled());
      expect(within(create).getByText("New")).toBeVisible();
      expect(create.querySelector("svg")).toBeTruthy();
      const heading = screen
        .getAllByRole("heading", { name: "Voices" })
        .at(-1)!;
      if (embedded && !moduleCard) {
        const body = picker
          ? screen.getByRole("radiogroup", { name: "Voices" })
          : screen.getByText("No voices yet.");
        expect(create.closest(".section-card-header")).toBeNull();
        expect(create.closest("section")).toBe(body.closest("section"));
        expect(
          body.compareDocumentPosition(create) &
            Node.DOCUMENT_POSITION_FOLLOWING,
        ).toBeTruthy();
        if (picker) {
          expect(screen.getByRole("radio", { name: "None" })).toBeChecked();
        } else {
          expect(body).toHaveClass("muted-copy");
          expect(body.tagName).toBe("P");
        }
      } else {
        expect(heading.parentElement).toContainElement(create);
      }
    },
  );

  it("lets a groupmate choose and hear a ready voice but not rename or delete it", async () => {
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
    fireEvent.click(await screen.findByRole("radio", { name: "peer.wav" }));
    expect(onSelect).toHaveBeenCalledWith("peer-voice");
    expect(screen.queryByRole("button", { name: "peer.wav" })).toBeNull();
    expect(screen.getByRole("button", { name: "Preview" })).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: "Delete peer.wav" }),
    ).toBeNull();
  });

  it("shows a groupmate's voice as a plain, playable name outside a picker", async () => {
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
    // Owner decision (2026-10-18): groupmates hear each other's voices.
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    await waitFor(() =>
      expect(api.createVoicePreview).toHaveBeenCalledWith("peer-voice"),
    );
    expect(
      screen.queryByRole("button", { name: "Delete peer.wav" }),
    ).toBeNull();
  });

  it("lets a visiting course teacher rename and delete what the server says they manage", async () => {
    // Owner decision (2026-10-26): a course teacher manages a student's voice.
    api.voiceProfiles.mockResolvedValue([
      {
        id: "student-voice",
        scope: "group",
        group_id: "group-a",
        status: "ready",
        source_filename: "student.wav",
        created_at: "2026-10-12T00:00:00Z",
        can_manage: true,
      },
      {
        id: "other-voice",
        scope: "group",
        group_id: "group-a",
        status: "ready",
        source_filename: "other.wav",
        created_at: "2026-10-12T00:00:00Z",
        can_manage: false,
      },
    ]);
    render(
      <AppShell role="teacher">
        <VoiceLibrary groupId="group-a" listenOnly />
      </AppShell>,
    );
    expect(
      await screen.findByRole("button", { name: "student.wav" }),
    ).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Delete student.wav" }),
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: "other.wav" })).toBeNull();
    expect(
      screen.queryByRole("button", { name: "Delete other.wav" }),
    ).toBeNull();
    // Visiting a group still creates no voice there.
    expect(screen.queryByRole("button", { name: "New" })).toBeNull();
  });

  it("deletes the owner's voice after confirming and drops it from the list", async () => {
    const own = {
      id: "own-voice",
      scope: "group",
      group_id: "group-a",
      status: "ready",
      source_filename: "mine.wav",
      created_at: "2026-10-12T00:00:00Z",
      can_manage: true,
    };
    api.voiceProfiles
      .mockResolvedValueOnce([own])
      .mockResolvedValue([{ ...own, status: "deleted" }]);
    api.deleteVoiceProfile.mockResolvedValue({ ...own, status: "deleted" });
    const confirm = vi.fn(() => true);
    vi.stubGlobal("confirm", confirm);
    render(
      <AppShell role="student">
        <VoiceLibrary groupId="group-a" />
      </AppShell>,
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Delete mine.wav" }),
    );
    await waitFor(() =>
      expect(confirm).toHaveBeenCalledWith(
        "Delete this custom voice? Debates already created keep their voice.",
      ),
    );
    await waitFor(() =>
      expect(api.deleteVoiceProfile).toHaveBeenCalledWith(
        "own-voice",
        expect.objectContaining({ idempotency: expect.anything() }),
      ),
    );
    await waitFor(() => expect(screen.queryByText("mine.wav")).toBeNull());
  });

  it("keeps the voice when the delete is cancelled, and offers delete only to the owner, in a picker too", async () => {
    vi.stubGlobal(
      "confirm",
      vi.fn(() => false),
    );
    api.voiceProfiles.mockResolvedValue([
      {
        id: "own-voice",
        scope: "group",
        group_id: "group-a",
        status: "ready",
        source_filename: "mine.wav",
        created_at: "2026-10-12T00:00:00Z",
        can_manage: true,
      },
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
    const view = render(
      <AppShell role="student">
        <VoiceLibrary groupId="group-a" />
      </AppShell>,
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Delete mine.wav" }),
    );
    expect(api.deleteVoiceProfile).not.toHaveBeenCalled();
    expect(
      screen.queryByRole("button", { name: "Delete peer.wav" }),
    ).toBeNull();
    view.unmount();

    render(
      <AppShell role="student">
        <VoiceLibrary groupId="group-a" onSelect={vi.fn()} />
      </AppShell>,
    );
    expect(await screen.findByRole("radio", { name: "mine.wav" })).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Delete mine.wav" }),
    ).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: "Delete peer.wav" }),
    ).toBeNull();
  });

  it("shows × on every voice status and keeps it visible, disabled, while that delete runs", async () => {
    const statuses = [
      "enrolling",
      "preview_ready",
      "ready",
      "failed",
      "deleting",
      "outcome_unknown",
    ];
    const rows = statuses.map((status) => ({
      id: `voice-${status}`,
      scope: "group",
      group_id: "group-a",
      status,
      source_filename: `${status}.wav`,
      created_at: "2026-10-12T00:00:00Z",
      can_manage: true,
    }));
    api.voiceProfiles.mockResolvedValue(rows);
    let finishDelete: (value: unknown) => void = () => undefined;
    api.deleteVoiceProfile.mockImplementation(
      () =>
        new Promise((resolve) => {
          finishDelete = resolve;
        }),
    );
    vi.stubGlobal(
      "confirm",
      vi.fn(() => true),
    );
    render(
      <AppShell role="student">
        <VoiceLibrary groupId="group-a" moduleCard />
      </AppShell>,
    );
    for (const status of statuses) {
      const button = await screen.findByRole("button", {
        name: `Delete ${status}.wav`,
      });
      expect(button).toHaveProperty("disabled", false);
    }

    const unknown = screen.getByRole("button", {
      name: "Delete outcome_unknown.wav",
    });
    fireEvent.click(unknown);
    await waitFor(() =>
      expect(api.deleteVoiceProfile).toHaveBeenCalledWith(
        "voice-outcome_unknown",
        expect.objectContaining({ idempotency: expect.anything() }),
      ),
    );
    // Mid-delete the × is still there: disabled, busy, with a spinner.
    const busy = screen.getByRole("button", {
      name: "Delete outcome_unknown.wav",
    });
    expect(busy).toHaveProperty("disabled", true);
    expect(busy.getAttribute("aria-busy")).toBe("true");
    expect(busy.querySelector(".spinner")).toBeTruthy();
    for (const status of statuses) {
      expect(
        screen.getByRole("button", { name: `Delete ${status}.wav` }),
      ).toBeTruthy();
    }
    api.voiceProfiles.mockResolvedValue(
      rows.filter((row) => row.status !== "outcome_unknown"),
    );
    await act(async () => {
      finishDelete({ ...rows[5], status: "deleted" });
    });
    await waitFor(() =>
      expect(screen.queryByText("outcome_unknown.wav")).toBeNull(),
    );
    expect(
      screen.getByRole("button", { name: "Delete deleting.wav" }),
    ).toHaveProperty("disabled", false);
  });

  it("lays out each voice as one row with only Preview and Delete, and deletes a failed voice", async () => {
    const failed = {
      id: "failed-voice",
      scope: "group",
      group_id: "group-a",
      status: "failed",
      source_filename: "refused.m4a",
      created_at: "2026-10-12T00:00:00Z",
      can_manage: true,
    };
    const unconfirmed = {
      ...failed,
      id: "preview-voice",
      status: "preview_ready",
      source_filename: "sample.m4a",
    };
    api.voiceProfiles
      .mockResolvedValueOnce([unconfirmed, failed])
      .mockResolvedValue([unconfirmed]);
    api.deleteVoiceProfile.mockResolvedValue({ ...failed, status: "deleted" });
    vi.stubGlobal(
      "confirm",
      vi.fn(() => true),
    );
    render(
      <AppShell role="student">
        <VoiceLibrary groupId="group-a" moduleCard />
      </AppShell>,
    );
    const failedRow = (await screen.findByText("refused.m4a")).closest("li")!;
    const readyRow = screen.getByText("sample.m4a").closest("li")!;
    // No status pill and no separate check button on any row.
    expect(screen.queryByText(/preview ready/i)).toBeNull();
    expect(screen.queryByText(/^failed$/i)).toBeNull();
    expect(screen.queryByRole("button", { name: /^confirm$/i })).toBeNull();
    // Hover tips removed sitewide; status stays out of a pill (aria/status elsewhere).
    expect(failedRow.getAttribute("title")).toBeNull();
    expect(readyRow.getAttribute("title")).toBeNull();
    // Exactly Preview and Delete per row; a failed voice cannot be played.
    expect(
      within(readyRow)
        .getAllByRole("button")
        .map(
          (button) => button.getAttribute("aria-label") ?? button.textContent,
        ),
    ).toEqual(["sample.m4a", "Preview", "Delete sample.m4a"]);
    expect(
      within(failedRow).getByRole("button", { name: "Preview" }),
    ).toHaveProperty("disabled", true);
    fireEvent.click(
      within(failedRow).getByRole("button", { name: "Delete refused.m4a" }),
    );
    await waitFor(() =>
      expect(api.deleteVoiceProfile).toHaveBeenCalledWith(
        "failed-voice",
        expect.objectContaining({ idempotency: expect.anything() }),
      ),
    );
    await waitFor(() => expect(screen.queryByText("refused.m4a")).toBeNull());
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
    const confirm = screen.getByRole("button", {
      name: consentCopy,
    }) as HTMLButtonElement;
    expect(confirm.closest("[data-ui-guide]")).toBeNull();
    expect(confirm.disabled).toBe(true);
    expect(screen.queryByRole("checkbox")).toBeNull();
    // Creating a voice never borrows the sidebar's Back or Done: the only
    // Back is the create panel's own (icon and word, 2026-11-03).
    expect(screen.queryByRole("button", { name: "Done" })).toBeNull();
    expect(
      screen
        .getAllByRole("button", { name: "Back" })
        .map((button) => button.getAttribute("data-ui-guide")),
    ).toEqual(["voice.cancelCreate"]);
    expect(screen.queryByRole("button", { name: "New" })).toBeNull();

    const sampleHint =
      "Upload a 10–20 second clip of yourself reading aloud (16-bit WAV, MP3, or M4A; max 10 MB).";
    const input = screen.getByLabelText(sampleHint) as HTMLInputElement;
    // The create panel is the Voices album's (2026-11-02): it shows the
    // sample rules on its card, and labels the file input with them too.
    expect(screen.getByText(sampleHint)).toBeTruthy();
    const file = new File([new Uint8Array([1, 2, 3])], "sample.wav", {
      type: "audio/wav",
    });
    fireEvent.change(input, { target: { files: [file] } });
    await waitFor(() => expect(confirm.disabled).toBe(false));
    // The top-right Back (arrow and word) cancels: nothing is uploaded.
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.queryByRole("button", { name: consentCopy })).toBeNull();
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
    expect(screen.getByText(sampleHint)).toBeTruthy();
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
    fireEvent.click(await screen.findByRole("button", { name: CONSENT }));
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
    fireEvent.click(await openEnrollForm());
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.queryByText("Created")).toBeNull();
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
  });

  it("does not list a refused or deleted voice card", async () => {
    api.voiceProfiles.mockResolvedValue([
      {
        id: "voice-ready",
        scope: "group",
        group_id: "group-a",
        status: "ready",
        source_filename: "ready.wav",
        created_at: "2026-01-01T00:00:00Z",
      },
      {
        id: "voice-refused",
        scope: "group",
        group_id: "group-a",
        status: "failed",
        source_filename: "refused.wav",
        safe_error_code: "voice_clone_refused",
        created_at: "2026-01-01T00:00:00Z",
      },
      {
        id: "voice-deleted",
        scope: "group",
        group_id: "group-a",
        status: "deleted",
        source_filename: "deleted.wav",
        safe_error_code: "voice_clone_refused",
        created_at: "2026-01-01T00:00:00Z",
      },
    ]);
    render(
      <AppShell role="student">
        <VoiceLibrary groupId="group-a" />
      </AppShell>,
    );
    expect(
      await screen.findByRole("button", { name: "ready.wav" }),
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: "refused.wav" })).toBeNull();
    expect(screen.queryByRole("button", { name: "deleted.wav" })).toBeNull();
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
    fireEvent.click(await openEnrollForm());
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
    fireEvent.click(await openEnrollForm());
    expect(await screen.findByRole("button", { name: "Retry" })).toBeTruthy();
    expect(screen.queryByText("Created")).toBeNull();
  });

  it("re-uploads a fixed file with the same name after a rejected sample", async () => {
    api.voiceProfiles.mockResolvedValue([]);
    api.enrollVoice
      .mockRejectedValueOnce(
        new PlatformApiError(422, "bad", { code: "audio_invalid" }),
      )
      .mockResolvedValueOnce({
        id: "voice-ok",
        scope: "group",
        group_id: "group-a",
        status: "preview_ready",
        source_filename: "me.wav",
        safe_error_code: null,
        created_at: "2026-01-01T00:00:00Z",
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
      "Upload a 10–20 second clip of yourself reading aloud (16-bit WAV, MP3, or M4A; max 10 MB).",
    ) as HTMLInputElement;
    const bad = new File([new Uint8Array([1])], "me.wav", {
      type: "audio/wav",
    });
    fireEvent.change(input, { target: { files: [bad] } });
    fireEvent.click(screen.getByRole("button", { name: CONSENT }));
    expect(
      await screen.findByText(/The audio file could not be used\./),
    ).toBeTruthy();
    // A rejected file is final: no Retry of the same bytes, and the stale
    // selection is cleared so consent cannot resend it.
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
    expect(
      screen.getByRole("button", { name: CONSENT }).hasAttribute("disabled"),
    ).toBe(true);
    // The input was reset, so the browser fires change for the same name.
    expect(input.value).toBe("");
    const good = new File([new Uint8Array([1, 2, 3, 4])], "me.wav", {
      type: "audio/wav",
    });
    fireEvent.change(input, { target: { files: [good] } });
    expect(screen.queryByText(/The audio file could not be used\./)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: CONSENT }));
    await waitFor(() => expect(api.enrollVoice).toHaveBeenCalledTimes(2));
    expect(api.enrollVoice.mock.calls[1][1]).toBe(good);
    expect(api.enrollVoice.mock.calls[1][3].idempotency).not.toBe(
      api.enrollVoice.mock.calls[0][3].idempotency,
    );
    expect(await screen.findByText("Created")).toBeTruthy();
  });

  it("shows a platform preview URL and plays it without any confirm step", async () => {
    api.voiceProfiles.mockResolvedValue([
      {
        id: "voice-1",
        scope: "group",
        group_id: "group-a",
        status: "ready",
        source_filename: "sample.wav",
        safe_error_code: null,
        created_at: "2026-01-01T00:00:00Z",
      },
    ]);
    api.createVoicePreview.mockResolvedValue({
      playback_url: "/api/v1/voice-previews/preview-1/media",
      expires_at: new Date(Date.now() + 60_000).toISOString(),
    });
    render(<VoiceLibrary groupId="group-a" />);
    await waitFor(() => expect(screen.getByText("sample.wav")).toBeTruthy());
    expect(screen.queryByText("voice-1")).toBeNull();
    // No check button and no status pill on the row.
    expect(screen.queryByRole("button", { name: /^confirm$/i })).toBeNull();
    expect(screen.queryByText(/preview ready/i)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /^preview$/i }));
    await waitFor(() => expect(document.querySelector("audio")).toBeTruthy());
    expect((document.querySelector("audio") as HTMLAudioElement).src).toContain(
      "/api/v1/voice-previews/preview-1/media",
    );
    fireEvent.ended(document.querySelector("audio")!);
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
      expect(screen.queryByRole("radio", { name: "sample.wav" })).toBeNull();
      // The saved binding stays the one checked row while the list is down.
      expect(
        (
          screen.getByRole("radio", {
            name: "Current voice",
          }) as HTMLInputElement
        ).checked,
      ).toBe(true);
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
    const choice = await screen.findByRole("radio", { name: "sample.wav" });
    expect((choice as HTMLInputElement).disabled).toBe(true);
    expect((choice as HTMLInputElement).checked).toBe(true);
    expect(
      (screen.getByRole("radio", { name: "None" }) as HTMLInputElement)
        .disabled,
    ).toBe(true);
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
    fireEvent.click(screen.getByRole("radio", { name: "None" }));
    expect(onSelect).toHaveBeenCalledWith(null);
  });
});

describe("Agent voice picker", () => {
  const mine = {
    id: "own-voice",
    scope: "group",
    group_id: "group-a",
    status: "ready",
    source_filename: "mine.wav",
    created_at: "2026-10-12T00:00:00Z",
    can_manage: true,
  };
  const peer = {
    ...mine,
    id: "peer-voice",
    source_filename: "peer.wav",
    can_manage: false,
  };

  function checked() {
    return screen
      .getAllByRole("radio")
      .filter((radio) => (radio as HTMLInputElement).checked)
      .map((radio) => {
        const label = radio.closest("label")?.cloneNode(true) as HTMLElement;
        label
          .querySelectorAll('[aria-hidden="true"]')
          .forEach((node) => node.remove());
        return label.textContent;
      });
  }

  it("always checks exactly one row, None by default", async () => {
    api.voiceProfiles.mockResolvedValue([mine, peer]);
    const onSelect = vi.fn();
    const view = render(
      <VoiceLibrary
        groupId="group-a"
        embedded
        selectedId={null}
        onSelect={onSelect}
      />,
    );
    await screen.findByRole("radio", { name: "peer.wav" });
    expect(screen.getByRole("radiogroup", { name: "Voices" })).toBeTruthy();
    expect(checked()).toEqual(["None"]);
    fireEvent.click(screen.getByRole("radio", { name: "peer.wav" }));
    expect(onSelect).toHaveBeenLastCalledWith("peer-voice");
    view.rerender(
      <VoiceLibrary
        groupId="group-a"
        embedded
        selectedId="peer-voice"
        onSelect={onSelect}
      />,
    );
    expect(checked()).toEqual(["peer.wav"]);
    const chosen = screen.getByRole("radio", { name: "peer.wav" });
    const label = chosen.closest("label")!;
    expect(within(label).getByText("Selected")).toBeTruthy();
    expect(label.querySelector('svg path[d="m5 12 4 4L19 6"]')).toBeTruthy();
    expect(chosen.hasAttribute("aria-selected")).toBe(false);
    expect(chosen.hasAttribute("aria-pressed")).toBe(false);
    expect(label.querySelector('[class*="animate-"]')).toBeNull();
    fireEvent.click(screen.getByRole("radio", { name: "None" }));
    expect(onSelect).toHaveBeenLastCalledWith(null);
  });

  it("selects a voice just uploaded from an Agent, and only that one", async () => {
    const created = {
      id: "voice-new",
      scope: "group",
      group_id: "group-a",
      status: "ready",
      source_filename: "fresh.wav",
      safe_error_code: null,
      created_at: "2026-01-01T00:00:00Z",
    };
    let enrolled = false;
    api.voiceProfiles.mockImplementation(async () =>
      enrolled ? [mine, peer, created] : [mine, peer],
    );
    api.enrollVoice.mockImplementation(async () => {
      enrolled = true;
      return created;
    });
    const onSelect = vi.fn();
    render(
      <AppShell role="student">
        <VoiceLibrary
          groupId="group-a"
          embedded
          selectedId={null}
          onSelect={onSelect}
        />
      </AppShell>,
    );
    await screen.findByRole("radio", { name: "peer.wav" });
    // Voices exist but none was uploaded here: the choice stays None.
    expect(checked()).toEqual(["None"]);
    expect(onSelect).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "New" }));
    const input = screen.getByLabelText(
      "Upload a 10–20 second clip of yourself reading aloud (16-bit WAV, MP3, or M4A; max 10 MB).",
    ) as HTMLInputElement;
    fireEvent.change(input, {
      target: {
        files: [
          new File([new Uint8Array([1, 2, 3])], "fresh.wav", {
            type: "audio/wav",
          }),
        ],
      },
    });
    fireEvent.click(await screen.findByRole("button", { name: CONSENT }));
    await waitFor(() => expect(onSelect).toHaveBeenCalledWith("voice-new"));
    expect(onSelect).toHaveBeenCalledTimes(1);
  });

  it("falls back to None when the chosen voice is deleted", async () => {
    vi.stubGlobal(
      "confirm",
      vi.fn(() => true),
    );
    api.voiceProfiles
      .mockResolvedValueOnce([mine])
      .mockResolvedValue([{ ...mine, status: "deleted" }]);
    api.deleteVoiceProfile.mockResolvedValue({ ...mine, status: "deleted" });
    const onSelect = vi.fn();
    render(
      <VoiceLibrary
        groupId="group-a"
        embedded
        selectedId="own-voice"
        onSelect={onSelect}
      />,
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Delete mine.wav" }),
    );
    await waitFor(() => expect(onSelect).toHaveBeenCalledWith(null));
  });

  it("cancels embedded voice creation from the footer Back without touching the sidebar", async () => {
    api.voiceProfiles.mockResolvedValue([mine]);
    const onSelect = vi.fn();
    render(
      <AppShell role="student">
        <VoiceLibrary
          groupId="group-a"
          embedded
          selectedId={null}
          onSelect={onSelect}
        />
      </AppShell>,
    );
    await screen.findByRole("radio", { name: "mine.wav" });
    const sidebarButtons = () =>
      within(screen.getByRole("banner"))
        .queryAllByRole("button")
        .map((button) => button.textContent);
    const before = sidebarButtons();
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "New" }).hasAttribute("disabled"),
      ).toBe(false),
    );
    fireEvent.click(screen.getByRole("button", { name: "New" }));
    expect(screen.queryByRole("radio")).toBeNull();
    fireEvent.change(screen.getByLabelText(/10–20 second/), {
      target: {
        files: [
          new File([new Uint8Array([1])], "x.wav", { type: "audio/wav" }),
        ],
      },
    });
    expect(sidebarButtons()).toEqual(before);
    expect(screen.queryByRole("button", { name: "Done" })).toBeNull();
    const cancel = screen.getByRole("button", { name: "Back" });
    // The app's back arrow and the word (2026-11-03), not a ×.
    expect(cancel.querySelector("path")?.getAttribute("d")).toBe(
      "M19 12H5m7-7-7 7 7 7",
    );
    fireEvent.click(cancel);
    expect(await screen.findByRole("radio", { name: "mine.wav" })).toBeTruthy();
    expect(checked()).toEqual(["None"]);
    expect(api.enrollVoice).not.toHaveBeenCalled();
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("creates the voice as soon as consent is confirmed", async () => {
    api.voiceProfiles.mockResolvedValue([]);
    api.enrollVoice.mockResolvedValue({
      ...mine,
      id: "voice-new",
      status: "preview_ready",
      safe_error_code: null,
    });
    render(
      <AppShell role="student">
        <VoiceLibrary groupId="group-a" embedded onSelect={vi.fn()} />
      </AppShell>,
    );
    fireEvent.click(await openEnrollForm());
    await waitFor(() => expect(api.enrollVoice).toHaveBeenCalledTimes(1));
    expect(await screen.findByText("Created")).toBeTruthy();
  });
});

describe("Voices album create (p2-tab)", () => {
  it.each([false, true])(
    "uses the same picked/dropped file and busy state (album=%s)",
    async (album) => {
      api.voiceProfiles.mockResolvedValue([]);
      let finish!: (value: unknown) => void;
      api.enrollVoice.mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            finish = resolve;
          }),
      );
      render(
        <VoiceLibrary groupId="group-a" album={album} embedded={!album} />,
      );
      await waitFor(() =>
        expect(
          (screen.getByRole("button", { name: "New" }) as HTMLButtonElement)
            .disabled,
        ).toBe(false),
      );
      fireEvent.click(screen.getByRole("button", { name: "New" }));
      const input = screen.getByLabelText(/10–20 second/) as HTMLInputElement;
      const tile = input.closest("label")!;
      const picked = new File(["sample"], "picked.wav", { type: "audio/wav" });
      fireEvent.change(input, { target: { files: [picked] } });
      expect(within(tile).getByText("picked.wav")).toBeTruthy();
      const dropped = new File(["sample"], "dropped.wav");
      const dataTransfer = {
        types: ["Files"],
        files: [dropped],
        dropEffect: "none",
      };
      fireEvent.dragEnter(tile, { dataTransfer });
      expect(tile.getAttribute("data-drag")).toBe("over");
      fireEvent.dragLeave(tile, { dataTransfer, relatedTarget: document.body });
      expect(tile.hasAttribute("data-drag")).toBe(false);
      fireEvent.dragOver(tile, { dataTransfer });
      expect(tile.getAttribute("data-drag")).toBe("over");
      fireEvent.drop(tile, { dataTransfer });
      expect(tile.hasAttribute("data-drag")).toBe(false);
      expect(within(tile).getByText("dropped.wav")).toBeTruthy();
      expect(within(tile).queryByText("picked.wav")).toBeNull();
      fireEvent.click(
        screen.getByRole("button", { name: album ? "Done" : CONSENT }),
      );
      expect(tile.getAttribute("aria-busy")).toBe("true");
      expect(tile.getAttribute("data-has-file")).toBe("true");
      expect(within(tile).queryByText("dropped.wav")).toBeNull();
      expect(tile.querySelector(".upload-tile-disc > svg")).toBeTruthy();
      expect(input.disabled).toBe(true);
      expect(api.enrollVoice.mock.calls.at(-1)?.[1]).toBe(dropped);
      expect(
        fireEvent.drop(tile, {
          dataTransfer: { types: ["Files"], files: [picked] },
        }),
      ).toBe(false);
      expect(within(tile).queryByText("picked.wav")).toBeNull();
      expect(within(tile).queryByText("dropped.wav")).toBeNull();
      expect(api.enrollVoice).toHaveBeenCalledTimes(1);
      expect(api.enrollVoice.mock.calls.at(-1)?.[1]).toBe(dropped);
      await act(async () => {
        finish({
          id: "new-voice",
          status: "ready",
          source_filename: dropped.name,
        });
      });
      expect(await screen.findByText("Created")).toBeTruthy();
    },
  );

  it.each([false, true])(
    "rejects invalid audio picks and drops without replacing the file (album=%s)",
    async (album) => {
      api.voiceProfiles.mockResolvedValue([]);
      render(
        <VoiceLibrary
          groupId="group-a"
          album={album}
          embedded={!album}
          initialCreate
        />,
      );
      const input = (await screen.findByLabelText(
        /10–20 second/,
      )) as HTMLInputElement;
      const tile = input.closest("label")!;
      const submit = () =>
        screen.getByRole("button", { name: album ? "Done" : CONSENT });
      const picked = new File(["sample"], "picked.wav", { type: "audio/wav" });
      const invalid = new File(["wrong"], "wrong.pdf", {
        type: "application/pdf",
      });
      for (const method of ["pick", "drop"]) {
        const reject = () => {
          if (method === "pick")
            fireEvent.change(input, { target: { files: [invalid] } });
          else
            fireEvent.drop(tile, {
              dataTransfer: { types: ["Files"], files: [invalid] },
            });
        };
        reject();
        expect(
          screen.getByText("Choose a .wav, .mp3, or .m4a audio file."),
        ).toBeTruthy();
        expect(within(tile).queryByText("wrong.pdf")).toBeNull();
        expect((submit() as HTMLButtonElement).disabled).toBe(true);
        fireEvent.click(submit());
        expect(api.enrollVoice).not.toHaveBeenCalled();

        fireEvent.change(input, { target: { files: [picked] } });
        expect(
          screen.queryByText("Choose a .wav, .mp3, or .m4a audio file."),
        ).toBeNull();
        reject();
        expect(
          screen.getByText("Choose a .wav, .mp3, or .m4a audio file."),
        ).toBeTruthy();
        expect(within(tile).getByText("picked.wav")).toBeTruthy();
        expect(within(tile).queryByText("wrong.pdf")).toBeNull();
        expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
        expect(api.enrollVoice).not.toHaveBeenCalled();
        fireEvent.change(input, { target: { files: [] } });
        expect(within(tile).queryByText("picked.wav")).toBeNull();
      }
    },
  );

  it.each(["pick", "drop"])(
    "accepts audio extensions or browser MIME aliases on %s",
    async (method) => {
      api.voiceProfiles.mockResolvedValue([]);
      render(<VoiceLibrary groupId="group-a" album initialCreate />);
      const input = await screen.findByLabelText(/10–20 second/);
      const tile = input.closest("label")!;
      for (const [name, type] of [
        ["sample.WAV", ""],
        ["sample.MP3", "application/octet-stream"],
        ["sample.M4A", ""],
        ...[
          "audio/wav",
          "audio/x-wav",
          "audio/wave",
          "audio/mpeg",
          "audio/mp3",
          "audio/mp4",
          "audio/x-m4a",
          "audio/m4a",
        ].map((type) => ["sample.unknown", type]),
      ]) {
        const file = new File(["sample"], name, { type });
        if (method === "pick")
          fireEvent.change(input, { target: { files: [file] } });
        else
          fireEvent.drop(tile, {
            dataTransfer: { types: ["Files"], files: [file] },
          });
        expect(within(tile).getByText(name)).toBeTruthy();
        expect(
          screen.queryByText("Choose a .wav, .mp3, or .m4a audio file."),
        ).toBeNull();
        expect(
          (screen.getByRole("button", { name: "Done" }) as HTMLButtonElement)
            .disabled,
        ).toBe(false);
      }
      expect(api.enrollVoice).not.toHaveBeenCalled();
    },
  );

  it("ignores drops when the parent disables the Voices create tile", async () => {
    api.voiceProfiles.mockResolvedValue([]);
    render(<VoiceLibrary groupId="group-a" album initialCreate disabled />);
    const input = (await screen.findByLabelText(
      /10–20 second/,
    )) as HTMLInputElement;
    const tile = input.closest("label")!;
    const dataTransfer = {
      types: ["Files"],
      files: [new File(["sample"], "ignored.wav")],
    };
    expect(input.disabled).toBe(true);
    expect(fireEvent.dragOver(tile, { dataTransfer })).toBe(false);
    expect(tile.hasAttribute("data-drag")).toBe(false);
    expect(fireEvent.drop(tile, { dataTransfer })).toBe(false);
    expect(within(tile).queryByText("ignored.wav")).toBeNull();
    expect(api.enrollVoice).not.toHaveBeenCalled();
  });

  it.each([false, true])(
    "omits the idle hint and describes the disabled action with existing requirements (album=%s)",
    async (album) => {
      api.voiceProfiles.mockResolvedValue([]);
      render(
        <AppShell role="student">
          <VoiceLibrary
            groupId="group-a"
            album={album}
            embedded={!album}
            onSelect={album ? undefined : vi.fn()}
          />
        </AppShell>,
      );
      await waitFor(() =>
        expect(
          screen.getByRole("button", { name: "New" }).hasAttribute("disabled"),
        ).toBe(false),
      );
      fireEvent.click(screen.getByRole("button", { name: "New" }));
      const req =
        "Upload a 10–20 second clip of yourself reading aloud (16-bit WAV, MP3, or M4A; max 10 MB).";
      const reqEl = document.getElementById("voice-sample-req");
      expect(reqEl?.textContent).toBe(req);
      const input = screen.getByLabelText(req) as HTMLInputElement;
      expect(input.getAttribute("aria-describedby")).toBe("voice-sample-req");
      if (album)
        expect(
          input.closest('[data-ui-guide="voice.uploadSample"]'),
        ).toBeNull();
      expect(document.getElementById("voice-consent-text")?.textContent).toBe(
        CONSENT,
      );
      expect(screen.queryByText(/Select an audio file/)).toBeNull();
      expect(
        document.querySelector('[title*="Select an audio file"]'),
      ).toBeNull();
      expect(document.getElementById("voice-consent-hint")).toBeNull();
      const done = screen.getByRole("button", {
        name: album ? "Done" : CONSENT,
      });
      expect(
        (done.getAttribute("aria-describedby") ?? "").split(" ").sort(),
      ).toEqual(
        album
          ? ["voice-consent-text", "voice-sample-req"]
          : ["voice-sample-req"],
      );
      for (const id of done.getAttribute("aria-describedby")!.split(" ")) {
        expect(document.getElementById(id)).not.toBeNull();
      }
      expect(done.hasAttribute("disabled")).toBe(true);
      fireEvent.click(done);
      expect(api.enrollVoice).not.toHaveBeenCalled();
      expect(screen.getByRole("button", { name: "Back" })).toBeTruthy();
      fireEvent.change(input, {
        target: {
          files: [
            new File([new Uint8Array([1])], "s.wav", { type: "audio/wav" }),
          ],
        },
      });
      await waitFor(() =>
        expect(
          screen
            .getByRole("button", { name: album ? "Done" : CONSENT })
            .hasAttribute("disabled"),
        ).toBe(false),
      );
    },
  );
});
