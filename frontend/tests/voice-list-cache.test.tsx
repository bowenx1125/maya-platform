import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { VoiceLibrary } from "../components/voice/voice-library";
import { PlatformApiError } from "../lib/api/platform";
import {
  cachedVoiceList,
  fetchVoiceList,
  prefetchVoiceList,
  VOICE_LIST_FRESH_MS,
  voiceListIdentity,
} from "../lib/voice-list-cache";
import { invalidateRequestCache } from "../lib/request-cache";

vi.mock("next/navigation", () => ({
  useRouter: () => ({}),
  usePathname: () => "/student/groups/group-a",
}));

const session: {
  api: Record<string, ReturnType<typeof vi.fn>>;
  user: { id: string } | null;
  identityGeneration: number;
} = { api: {}, user: { id: "student-a" }, identityGeneration: 1 };

vi.mock("../components/session-provider", () => ({
  useSession: () => session,
}));

function voice(id: string, name: string, status = "ready") {
  return {
    id,
    scope: "group",
    group_id: "group-a",
    status,
    source_filename: name,
    created_at: "2026-10-12T00:00:00Z",
    can_manage: true,
  };
}

function freshApi() {
  const api = {
    voiceProfiles: vi.fn(),
    personalVoiceProfiles: vi.fn(),
    enrollVoice: vi.fn(),
    createVoicePreview: vi.fn(),
    deleteVoiceProfile: vi.fn(),
    renameVoiceProfile: vi.fn(),
  };
  session.api = api;
  session.user = { id: "student-a" };
  session.identityGeneration = 1;
  return api;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

// Leave the freshness window, as a later Studyform visit would.
function laterVisit() {
  const now = Date.now() + VOICE_LIST_FRESH_MS + 1_000;
  vi.spyOn(Date, "now").mockReturnValue(now);
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.restoreAllMocks();
});

describe("Studyform voice list cache", () => {
  it("shows the last list at once on a return visit and refreshes it quietly", async () => {
    const api = freshApi();
    api.voiceProfiles.mockResolvedValueOnce([voice("v1", "first.wav")]);
    const first = render(<VoiceLibrary groupId="group-a" moduleCard />);
    expect(screen.getByRole("status")).toBeTruthy();
    expect(await screen.findByText("first.wav")).toBeTruthy();
    first.unmount();
    laterVisit();

    const refresh = deferred<unknown[]>();
    api.voiceProfiles.mockReturnValueOnce(refresh.promise);
    render(<VoiceLibrary groupId="group-a" moduleCard />);
    // No loading card: the cached list is on screen in the first render.
    expect(screen.getByText("first.wav")).toBeTruthy();
    expect(screen.queryByRole("status")).toBeNull();
    await waitFor(() => expect(api.voiceProfiles).toHaveBeenCalledTimes(2));

    refresh.resolve([voice("v1", "first.wav"), voice("v2", "second.wav")]);
    expect(await screen.findByText("second.wav")).toBeTruthy();
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("never shows one person's cached list to another identity", async () => {
    const api = freshApi();
    api.voiceProfiles.mockResolvedValueOnce([voice("v1", "mine.wav")]);
    const first = render(<VoiceLibrary groupId="group-a" moduleCard />);
    expect(await screen.findByText("mine.wav")).toBeTruthy();
    first.unmount();

    session.user = { id: "student-b" };
    const pending = deferred<unknown[]>();
    api.voiceProfiles.mockReturnValueOnce(pending.promise);
    render(<VoiceLibrary groupId="group-a" moduleCard />);
    expect(screen.queryByText("mine.wav")).toBeNull();
    expect(screen.getByRole("status")).toBeTruthy();
    pending.resolve([]);
    await waitFor(() => expect(screen.queryByRole("status")).toBeNull());
    // The other identity's entries are gone, not just hidden.
    expect(
      cachedVoiceList(
        api,
        voiceListIdentity("student-a", 1),
        "group",
        "group-a",
      ),
    ).toBeUndefined();
  });

  it("drops the cached list when the server now refuses the group", async () => {
    const api = freshApi();
    api.voiceProfiles.mockResolvedValueOnce([voice("v1", "old.wav")]);
    const first = render(<VoiceLibrary groupId="group-a" moduleCard />);
    expect(await screen.findByText("old.wav")).toBeTruthy();
    first.unmount();
    laterVisit();

    api.voiceProfiles.mockRejectedValueOnce(
      new PlatformApiError(404, "Group not found.", { code: "not_found" }),
    );
    render(<VoiceLibrary groupId="group-a" moduleCard />);
    await waitFor(() => expect(screen.queryByText("old.wav")).toBeNull());
    expect(
      cachedVoiceList(
        api,
        voiceListIdentity("student-a", 1),
        "group",
        "group-a",
      ),
    ).toBeUndefined();
  });

  it("joins a Studyform prefetch instead of asking again", async () => {
    const api = freshApi();
    const pending = deferred<unknown[]>();
    api.voiceProfiles.mockReturnValueOnce(pending.promise);
    prefetchVoiceList(
      api,
      voiceListIdentity("student-a", 1),
      "group",
      "group-a",
    );
    render(<VoiceLibrary groupId="group-a" moduleCard />);
    pending.resolve([voice("v1", "early.wav")]);
    expect(await screen.findByText("early.wav")).toBeTruthy();
    expect(api.voiceProfiles).toHaveBeenCalledTimes(1);
  });

  it("shows a prefetch that already landed with no loading card and no second request", async () => {
    const api = freshApi();
    api.voiceProfiles.mockResolvedValueOnce([voice("v1", "landed.wav")]);
    const identity = voiceListIdentity("student-a", 1);
    prefetchVoiceList(api, identity, "group", "group-a");
    await waitFor(() =>
      expect(cachedVoiceList(api, identity, "group", "group-a")).toBeTruthy(),
    );
    render(<VoiceLibrary groupId="group-a" moduleCard />);
    expect(screen.getByText("landed.wav")).toBeTruthy();
    expect(screen.queryByRole("status")).toBeNull();
    await new Promise((done) => setTimeout(done, 10));
    expect(api.voiceProfiles).toHaveBeenCalledTimes(1);
  });

  it("reloads from the server after a delete even inside the freshness window", async () => {
    const api = freshApi();
    api.voiceProfiles
      .mockResolvedValueOnce([voice("v1", "doomed.wav")])
      .mockResolvedValueOnce([]);
    api.deleteVoiceProfile.mockResolvedValue(undefined);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<VoiceLibrary groupId="group-a" moduleCard />);
    expect(await screen.findByText("doomed.wav")).toBeTruthy();
    screen.getByRole("button", { name: "Delete doomed.wav" }).click();
    await waitFor(() => expect(screen.queryByText("doomed.wav")).toBeNull());
    expect(api.voiceProfiles).toHaveBeenCalledTimes(2);
    expect(
      cachedVoiceList(
        api,
        voiceListIdentity("student-a", 1),
        "group",
        "group-a",
      ),
    ).toEqual([]);
  });

  it("caches nothing without a signed-in user", async () => {
    const api = freshApi();
    session.user = null;
    api.voiceProfiles.mockResolvedValue([voice("v1", "anon.wav")]);
    const first = render(<VoiceLibrary groupId="group-a" moduleCard />);
    expect(await screen.findByText("anon.wav")).toBeTruthy();
    first.unmount();
    render(<VoiceLibrary groupId="group-a" moduleCard />);
    expect(screen.getByRole("status")).toBeTruthy();
    expect(await screen.findByText("anon.wav")).toBeTruthy();
  });

  it("a reload after a change never adopts an answer that started before it", async () => {
    const api = freshApi();
    const identity = voiceListIdentity("student-a", 1);
    const stale = deferred<unknown[]>();
    api.voiceProfiles
      .mockReturnValueOnce(stale.promise)
      .mockResolvedValueOnce([]);
    const early = fetchVoiceList(api, identity, "group", "group-a", {
      reuse: true,
    });
    const fresh = await fetchVoiceList(api, identity, "group", "group-a");
    expect(fresh).toEqual([]);
    stale.resolve([voice("gone", "deleted-meanwhile.wav")]);
    await early;
    expect(api.voiceProfiles).toHaveBeenCalledTimes(2);
    expect(cachedVoiceList(api, identity, "group", "group-a")).toEqual([]);
  });

  it("lives in the shared page-load cache, so any change empties it", async () => {
    const api = freshApi();
    const identity = voiceListIdentity("student-a", 1);
    api.voiceProfiles.mockResolvedValueOnce([voice("v1", "kept.wav")]);
    await fetchVoiceList(api, identity, "group", "group-a");
    expect(cachedVoiceList(api, identity, "group", "group-a")).toHaveLength(1);
    // What PlatformApi does on every non-GET request.
    invalidateRequestCache(api);
    expect(cachedVoiceList(api, identity, "group", "group-a")).toBeUndefined();
  });

  it("keeps a teacher's personal list apart from a group list", async () => {
    const api = freshApi();
    session.user = { id: "teacher-a" };
    api.personalVoiceProfiles.mockResolvedValueOnce([
      { ...voice("p1", "teacher.wav"), scope: "personal", group_id: null },
    ]);
    const first = render(<VoiceLibrary groupId={null} courseId="course-a" />);
    expect(await screen.findByText("teacher.wav")).toBeTruthy();
    first.unmount();
    laterVisit();
    api.personalVoiceProfiles.mockResolvedValueOnce([]);
    render(<VoiceLibrary groupId={null} courseId="course-a" />);
    expect(screen.getByText("teacher.wav")).toBeTruthy();
    await waitFor(() =>
      expect(api.personalVoiceProfiles).toHaveBeenCalledTimes(2),
    );
    await waitFor(() => expect(screen.queryByText("teacher.wav")).toBeNull());
    expect(api.voiceProfiles).not.toHaveBeenCalled();
  });

  it("does not bring back an old name after a rename", async () => {
    const api = freshApi();
    api.voiceProfiles
      .mockResolvedValueOnce([voice("v1", "old-name.wav")])
      .mockResolvedValueOnce([voice("v1", "new-name.wav")]);
    api.renameVoiceProfile.mockResolvedValue({
      ...voice("v1", "new-name.wav"),
    });
    const first = render(<VoiceLibrary groupId="group-a" moduleCard />);
    screen.getByRole("status");
    (await screen.findByRole("button", { name: "old-name.wav" })).click();
    const input = await screen.findByRole("textbox");
    fireEvent.change(input, { target: { value: "new-name.wav" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(
      await screen.findByRole("button", { name: "new-name.wav" }),
    ).toBeTruthy();
    first.unmount();
    // Inside the freshness window: the stale list must not be shown.
    render(<VoiceLibrary groupId="group-a" moduleCard />);
    expect(screen.queryByText("old-name.wav")).toBeNull();
    expect(await screen.findByText("new-name.wav")).toBeTruthy();
  });
});
