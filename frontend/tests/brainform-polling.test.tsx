import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({
  api: {} as Record<string, ReturnType<typeof vi.fn>>,
  user: {
    id: "teacher-one",
    courses: [{ course_id: "course-1", role: "teacher" }],
    groups: [],
  },
}));

vi.mock("../components/session-provider", () => ({
  useSession: () => ({
    api: state.api,
    user: state.user,
    identityGeneration: 1,
  }),
}));
vi.mock("next/navigation", () => ({
  usePathname: () => "/teacher/knowledge",
  useRouter: () => ({ push: vi.fn() }),
}));

import { BrainformWorkspace } from "../components/knowledge/brainform-workspace";
import { LocaleProvider } from "../components/locale";
import { PlatformApi, PlatformApiError } from "../lib/api/platform";

const knowledge = {
  agent_id: "agent-1",
  canonical_set_id: "set-1",
  source_agent_display_name: "Socrates",
  knowledge_display_name: "Question bank",
  can_read: true,
  can_edit: true,
  version_seq: 1,
  content_hash: "b".repeat(64),
  generation_job_id: null,
  generation_state: "completed",
  safe_error_code: null,
};
const reads = [
  "courses",
  "workspaceDocuments",
  "brainformKnowledge",
  "chatAgents",
  "groups",
];

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

function workspace() {
  return (
    <LocaleProvider initialLocale="en">
      <BrainformWorkspace role="teacher" />
    </LocaleProvider>
  );
}

beforeEach(() => {
  vi.useFakeTimers();
  state.user = {
    id: "teacher-one",
    courses: [{ course_id: "course-1", role: "teacher" }],
    groups: [],
  };
  state.api = {
    courses: vi
      .fn()
      .mockResolvedValue([{ id: "course-1", name: "Course One" }]),
    groups: vi.fn().mockResolvedValue([]),
    workspaceDocuments: vi.fn().mockResolvedValue([]),
    brainformKnowledge: vi.fn().mockResolvedValue([knowledge]),
    chatAgents: vi.fn().mockResolvedValue([]),
    courseAssessmentAttempts: vi.fn().mockResolvedValue([]),
    knowledgeSet: vi
      .fn()
      .mockResolvedValue({ metadata_revision: 0, content_revision: 0 }),
    deleteKnowledgeSet: vi.fn().mockResolvedValue(undefined),
  };
  sessionStorage.clear();
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("Brainform polling", () => {
  it("does not start background reads while the initial workspace is pending", async () => {
    const initial = deferred<(typeof knowledge)[]>();
    state.api.brainformKnowledge.mockReturnValue(initial.promise);
    render(workspace());
    await advance(30_001);

    for (const name of reads) expect(state.api[name]).toHaveBeenCalledTimes(1);
    await act(async () => initial.resolve([knowledge]));
    expect(
      screen.getByRole("button", { name: "Download Question bank" }),
    ).toBeTruthy();
  });

  it("waits for a slow generation poll before scheduling another workspace read", async () => {
    const pending = deferred<(typeof knowledge)[]>();
    state.api.brainformKnowledge
      .mockResolvedValueOnce([{ ...knowledge, generation_state: "running" }])
      .mockReturnValueOnce(pending.promise);
    render(workspace());
    await advance(1);
    expect(
      screen.getByRole("button", { name: "Generating Question bank" }),
    ).toBeTruthy();
    await advance(30_000);

    for (const name of reads) expect(state.api[name]).toHaveBeenCalledTimes(2);
    await act(async () => pending.resolve([knowledge]));
    expect(
      screen.getByRole("button", { name: "Download Question bank" }),
    ).toBeTruthy();
    await advance(9_999);
    expect(state.api.brainformKnowledge).toHaveBeenCalledTimes(2);
    await advance(1);
    expect(state.api.brainformKnowledge).toHaveBeenCalledTimes(3);
  });

  it("does not duplicate pending siblings when another list fails promptly", async () => {
    const pending = deferred<(typeof knowledge)[]>();
    state.api.brainformKnowledge
      .mockResolvedValueOnce([{ ...knowledge, generation_state: "running" }])
      .mockReturnValueOnce(pending.promise);
    state.api.workspaceDocuments
      .mockResolvedValueOnce([])
      .mockRejectedValueOnce(new TypeError("Network request failed"));
    render(workspace());
    await advance(1);
    await advance(30_000);

    for (const name of reads) expect(state.api[name]).toHaveBeenCalledTimes(2);
    await act(async () => pending.resolve([knowledge]));
    await advance(1_500);
    expect(state.api.brainformKnowledge).toHaveBeenCalledTimes(3);
    expect(
      screen.getByRole("button", { name: "Download Question bank" }),
    ).toBeTruthy();
  });

  it.each(["refused", "wrong-course"])(
    "shows a %s group error promptly without repeating its pending files read",
    async (failure) => {
      const pending = deferred<never[]>();
      state.api.knowledge = vi.fn().mockReturnValue(pending.promise);
      state.api.group = vi
        .fn()
        .mockResolvedValueOnce({ id: "group-1", course_id: "course-1" });
      if (failure === "refused")
        state.api.group.mockRejectedValue(
          new PlatformApiError(404, "Group unavailable"),
        );
      else
        state.api.group.mockResolvedValue({
          id: "group-1",
          course_id: "course-other",
        });
      render(
        <LocaleProvider initialLocale="en">
          <BrainformWorkspace role="teacher" initialGroupId="group-1" />
        </LocaleProvider>,
      );
      await advance(1);
      await advance(1);
      expect(screen.getByRole("alert")).toBeTruthy();
      expect(state.api.group).toHaveBeenCalledTimes(2);
      expect(state.api.knowledge).toHaveBeenCalledTimes(1);
      await advance(30_000);
      expect(state.api.group).toHaveBeenCalledTimes(2);
      expect(state.api.knowledge).toHaveBeenCalledTimes(1);
      await act(async () => pending.resolve([]));
      await advance(10_000);
      expect(state.api.knowledge).toHaveBeenCalledTimes(2);
    },
  );

  it("refreshes immediately after a mutation and ignores the older pending poll", async () => {
    const pending = deferred<(typeof knowledge)[]>();
    state.api.brainformKnowledge
      .mockResolvedValueOnce([knowledge])
      .mockReturnValueOnce(pending.promise)
      .mockResolvedValue([]);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(workspace());
    await advance(10_001);
    expect(state.api.brainformKnowledge).toHaveBeenCalledTimes(2);

    await act(async () => {
      fireEvent.click(
        screen.getByRole("button", { name: "Delete Question bank" }),
      );
    });
    expect(state.api.deleteKnowledgeSet).toHaveBeenCalledTimes(1);
    expect(state.api.brainformKnowledge).toHaveBeenCalledTimes(3);
    expect(
      screen.queryByRole("button", { name: "Download Question bank" }),
    ).toBeNull();
    await advance(10_000);
    expect(state.api.brainformKnowledge).toHaveBeenCalledTimes(4);
    await act(async () => pending.resolve([knowledge]));
    expect(
      screen.queryByRole("button", { name: "Download Question bank" }),
    ).toBeNull();
  });

  it("loads a new identity without waiting for the old read or restoring its rows", async () => {
    const pending = deferred<(typeof knowledge)[]>();
    state.api.brainformKnowledge
      .mockResolvedValueOnce([knowledge])
      .mockReturnValueOnce(pending.promise)
      .mockResolvedValue([]);
    const view = render(workspace());
    await advance(10_001);
    expect(state.api.brainformKnowledge).toHaveBeenCalledTimes(2);

    state.user = { ...state.user, id: "teacher-two" };
    view.rerender(workspace());
    await advance(1);
    expect(state.api.brainformKnowledge).toHaveBeenCalledTimes(3);
    expect(
      screen.queryByRole("button", { name: "Download Question bank" }),
    ).toBeNull();
    await act(async () => pending.resolve([knowledge]));
    expect(
      screen.queryByRole("button", { name: "Download Question bank" }),
    ).toBeNull();
  });

  it("aborts a hung poll before recovering automatically without overlapping fetches", async () => {
    const api = new PlatformApi({ baseUrl: "http://maya.test/api/v1" });
    let stalledSignal!: AbortSignal;
    let pendingFetches = 0;
    let peak = 0;
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation((input, init) => {
        pendingFetches += 1;
        peak = Math.max(peak, pendingFetches);
        if (fetchMock.mock.calls.length === 1) {
          stalledSignal = new Request(input, init).signal;
          return new Promise((_resolve, reject) => {
            stalledSignal.addEventListener(
              "abort",
              () => {
                pendingFetches -= 1;
                reject(stalledSignal.reason);
              },
              { once: true },
            );
          });
        }
        pendingFetches -= 1;
        return Promise.resolve(new Response(JSON.stringify([knowledge])));
      });
    state.api.brainformKnowledge
      .mockResolvedValueOnce([{ ...knowledge, generation_state: "running" }])
      .mockImplementation(() => api.brainformKnowledge("course-1"));
    render(workspace());
    await advance(1);
    await advance(1_500);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await advance(59_999);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await advance(1_501);
    expect(stalledSignal.aborted).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(pendingFetches).toBe(0);
    expect(peak).toBe(1);
    expect(
      screen.getByRole("button", { name: "Download Question bank" }),
    ).toBeTruthy();
  });
});
