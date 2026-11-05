import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { DebateCleanupControls } from "../components/debate/debate-cleanup-controls";
import {
  PlatformApiError,
  type DebateDetail,
  type PlatformApi,
} from "../lib/api";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
beforeEach(() => localStorage.clear());
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

it.each(["Devocalize", "Delete"])("keeps %s failures quiet", async (label) => {
  vi.spyOn(window, "confirm").mockReturnValue(true);
  const fail = vi.fn().mockRejectedValue(new Error("internal failure details"));
  const detail = {
    id: "debate",
    revision: 1,
    playback: { control_version: 1 },
  } as DebateDetail;
  render(
    <DebateCleanupControls
      detail={detail}
      api={{
        deleteDebateVoice: fail,
        deleteDebateAll: fail,
        regenerateDebateTurnAudio: vi.fn(),
      }}
      onVoiceDeleted={vi.fn()}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: label }));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: label })).toHaveProperty(
      "disabled",
      false,
    ),
  );
  expect(screen.queryByRole("alert")).toBeNull();
  expect(screen.queryByText("internal failure details")).toBeNull();
  vi.restoreAllMocks();
});

it("regenerates only missing saved audio and shows immediate progress", async () => {
  let finish: (value: unknown) => void = () => undefined;
  const generate = vi.fn(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  const refresh = vi.fn();
  const detail = {
    id: "debate-a",
    revision: 3,
    turn_protocol: "segments_v2",
    playback: { control_version: 2 },
    public_turns: [],
    preview_turns: [
      {
        id: "saved",
        speech: "Saved paragraph",
        generation_status: "final_ready",
        audio_ready: false,
      },
      {
        id: "ready",
        speech: "Existing audio",
        generation_status: "final_ready",
        audio_ready: true,
      },
      {
        id: "pending",
        speech: "",
        generation_status: "pending",
        audio_ready: false,
      },
    ],
  } as unknown as DebateDetail;
  const api = {
    deleteDebateVoice: vi.fn(),
    deleteDebateAll: vi.fn(),
    regenerateDebateTurnAudio: generate,
  } as unknown as Pick<
    PlatformApi,
    "deleteDebateVoice" | "deleteDebateAll" | "regenerateDebateTurnAudio"
  >;
  render(
    <DebateCleanupControls
      detail={detail}
      api={api}
      onVoiceDeleted={refresh}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Revocalize" }));
  expect(screen.getByRole("button", { name: "Revocalize..." })).toHaveProperty(
    "disabled",
    true,
  );
  expect(generate).toHaveBeenCalledTimes(1);
  expect(generate.mock.calls[0]?.slice(0, 3)).toEqual([
    "debate-a",
    "saved",
    { expected_revision: 3 },
  ]);
  finish({ status: "completed", audio_ready: true });
  await waitFor(() => expect(refresh).toHaveBeenCalled());
  expect(generate).toHaveBeenCalledTimes(1);
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Devocalize" })).toHaveProperty(
      "disabled",
      false,
    ),
  );
});

it("destroys a list row without depending on a potentially broken detail, even when file cleanup is pending", async () => {
  vi.spyOn(window, "confirm").mockReturnValue(true);
  const loadDetail = vi.fn().mockRejectedValue(new Error("broken detail"));
  const removed = vi.fn();
  const destroy = vi.fn().mockResolvedValue({ cleanup_status: "pending" });
  render(
    <DebateCleanupControls
      debateId="debate"
      loadDetail={loadDetail}
      api={{
        deleteDebateAll: destroy,
        deleteDebateVoice: vi.fn(),
        regenerateDebateTurnAudio: vi.fn(),
      }}
      onAllDeleted={removed}
      onVoiceDeleted={vi.fn()}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Delete" }));
  await waitFor(() => expect(removed).toHaveBeenCalledTimes(1));
  expect(loadDetail).not.toHaveBeenCalled();
  expect(destroy).toHaveBeenCalledTimes(1);
  vi.restoreAllMocks();
});

it("names the in-progress action on the button", async () => {
  vi.spyOn(window, "confirm").mockReturnValue(true);
  let finishVoice: (value: unknown) => void = () => undefined;
  let finishAll: (value: unknown) => void = () => undefined;
  render(
    <DebateCleanupControls
      detail={
        {
          id: "debate",
          revision: 1,
          playback: { control_version: 1 },
        } as unknown as DebateDetail
      }
      api={
        {
          deleteDebateVoice: vi.fn(
            () =>
              new Promise((resolve) => {
                finishVoice = resolve;
              }),
          ),
          deleteDebateAll: vi.fn(
            () =>
              new Promise((resolve) => {
                finishAll = resolve;
              }),
          ),
          regenerateDebateTurnAudio: vi.fn(),
        } as unknown as Pick<
          PlatformApi,
          "deleteDebateVoice" | "deleteDebateAll" | "regenerateDebateTurnAudio"
        >
      }
      onVoiceDeleted={vi.fn()}
      onAllDeleted={vi.fn()}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Devocalize" }));
  expect(screen.getByRole("button", { name: "Devocalizing" })).toHaveProperty(
    "disabled",
    true,
  );
  expect(screen.queryByRole("status")).toBeNull();
  finishVoice({ cleanup_status: "completed" });
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Revocalize" })).toBeTruthy(),
  );
  fireEvent.click(screen.getByRole("button", { name: "Delete" }));
  expect(screen.getByRole("button", { name: "Deleting" })).toHaveProperty(
    "disabled",
    true,
  );
  expect(screen.queryByRole("status")).toBeNull();
  finishAll({ cleanup_status: "completed" });
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Delete" })).toHaveProperty(
      "disabled",
      false,
    ),
  );
  vi.restoreAllMocks();
});

it("switches Devocalize to Revocalize only after successful deletion", async () => {
  vi.spyOn(window, "confirm").mockReturnValue(true);
  const remove = vi.fn().mockResolvedValue({ cleanup_status: "completed" });
  render(
    <DebateCleanupControls
      detail={
        {
          id: "debate",
          revision: 1,
          playback: { control_version: 1 },
        } as unknown as DebateDetail
      }
      api={{
        deleteDebateVoice: remove,
        deleteDebateAll: vi.fn(),
        regenerateDebateTurnAudio: vi.fn(),
      }}
      onVoiceDeleted={vi.fn()}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Devocalize" }));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Revocalize" })).toHaveProperty(
      "disabled",
      false,
    ),
  );
  expect(screen.queryByText("Generate Audio")).toBeNull();
  vi.restoreAllMocks();
});

it("surfaces definitive audio failures without exposing private details", async () => {
  const generate = vi
    .fn()
    .mockRejectedValue(new PlatformApiError(422, "private details"));
  render(
    <DebateCleanupControls
      detail={
        {
          id: "debate",
          revision: 1,
          turn_protocol: "segments_v2",
          playback: { control_version: 1 },
          public_turns: [],
          preview_turns: [
            {
              id: "saved",
              speech: "Kept text",
              generation_status: "final_ready",
              audio_ready: false,
            },
          ],
        } as unknown as DebateDetail
      }
      api={{
        deleteDebateVoice: vi.fn(),
        deleteDebateAll: vi.fn(),
        regenerateDebateTurnAudio: generate,
      }}
      onVoiceDeleted={vi.fn()}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Revocalize" }));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Revocalize" })).toHaveProperty(
      "disabled",
      false,
    ),
  );
  expect(screen.getByRole("alert").textContent).toContain("1 speech turn(s)");
  expect(screen.queryByText("private details")).toBeNull();
});

it("regenerates every missing turn instead of stopping after the first", async () => {
  const generate = vi
    .fn()
    .mockResolvedValueOnce({ status: "completed", audio_ready: true })
    .mockResolvedValueOnce({ status: "completed", audio_ready: true });
  const refresh = vi.fn();
  const detail = {
    id: "debate-multi",
    revision: 4,
    turn_protocol: "segments_v2",
    playback: { control_version: 1 },
    public_turns: [],
    preview_turns: [
      {
        id: "turn-a",
        speech: "First speech",
        generation_status: "final_ready",
        audio_ready: false,
      },
      {
        id: "turn-b",
        speech: "Second speech",
        generation_status: "final_ready",
        audio_ready: false,
      },
      {
        id: "turn-ready",
        speech: "Already has audio",
        generation_status: "final_ready",
        audio_ready: true,
      },
    ],
  } as unknown as DebateDetail;
  render(
    <DebateCleanupControls
      detail={detail}
      api={{
        deleteDebateVoice: vi.fn(),
        deleteDebateAll: vi.fn(),
        regenerateDebateTurnAudio: generate,
      }}
      onVoiceDeleted={refresh}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Revocalize" }));
  await waitFor(() => expect(generate).toHaveBeenCalledTimes(2));
  expect(generate.mock.calls.map((call) => call[1])).toEqual([
    "turn-a",
    "turn-b",
  ]);
  await waitFor(() => expect(refresh).toHaveBeenCalled());
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Devocalize" })).toHaveProperty(
      "disabled",
      false,
    ),
  );
});

it("continues regenerating later turns when an earlier turn is not ready", async () => {
  const generate = vi
    .fn()
    .mockResolvedValueOnce({
      status: "failed",
      audio_ready: false,
      safe_error_code: "voice_unavailable",
    })
    .mockResolvedValueOnce({ status: "completed", audio_ready: true });
  const refresh = vi.fn();
  const detail = {
    id: "debate-partial",
    revision: 5,
    turn_protocol: "segments_v2",
    playback: { control_version: 1 },
    public_turns: [],
    preview_turns: [
      {
        id: "failed-turn",
        speech: "Failed speech",
        generation_status: "final_ready",
        audio_ready: false,
      },
      {
        id: "next-turn",
        speech: "Next speech",
        generation_status: "final_ready",
        audio_ready: false,
      },
    ],
  } as unknown as DebateDetail;
  render(
    <DebateCleanupControls
      detail={detail}
      api={{
        deleteDebateVoice: vi.fn(),
        deleteDebateAll: vi.fn(),
        regenerateDebateTurnAudio: generate,
      }}
      onVoiceDeleted={refresh}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Revocalize" }));
  await waitFor(() => expect(generate).toHaveBeenCalledTimes(2));
  expect(generate.mock.calls.map((call) => call[1])).toEqual([
    "failed-turn",
    "next-turn",
  ]);
  await waitFor(() => expect(refresh).toHaveBeenCalled());
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Revocalize" })).toHaveProperty(
      "disabled",
      false,
    ),
  );
});

it("revocalizes regenerable_turn_ids returned by Devocalize", async () => {
  vi.spyOn(window, "confirm").mockReturnValue(true);
  const generate = vi
    .fn()
    .mockResolvedValue({ status: "completed", audio_ready: true });
  const remove = vi.fn().mockResolvedValue({
    cleanup_status: "completed",
    regenerable_turn_ids: ["regen-a", "regen-b"],
  });
  const detail = {
    id: "debate-regen-ids",
    revision: 2,
    turn_protocol: "segments_v2",
    playback: { control_version: 1 },
    public_turns: [],
    preview_turns: [],
  } as unknown as DebateDetail;
  render(
    <DebateCleanupControls
      detail={detail}
      api={{
        deleteDebateVoice: remove,
        deleteDebateAll: vi.fn(),
        regenerateDebateTurnAudio: generate,
      }}
      onVoiceDeleted={vi.fn()}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Devocalize" }));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Revocalize" })).toHaveProperty(
      "disabled",
      false,
    ),
  );
  fireEvent.click(screen.getByRole("button", { name: "Revocalize" }));
  await waitFor(() => expect(generate).toHaveBeenCalledTimes(2));
  expect(generate.mock.calls.map((call) => call[1])).toEqual([
    "regen-a",
    "regen-b",
  ]);
  vi.restoreAllMocks();
});

type RestorableDetail = DebateDetail & {
  preview_turns: NonNullable<DebateDetail["preview_turns"]>;
};

function restoreDetail(id = "restore-refresh"): RestorableDetail {
  return {
    id,
    revision: 7,
    turn_protocol: "segments_v2",
    playback: { control_version: 2 },
    public_turns: [],
    preview_turns: ["one", "two", "three"].map((id) => ({
      id,
      speech: `Speech ${id}`,
      generation_status: "final_ready",
      audio_ready: false,
    })),
  } as unknown as RestorableDetail;
}

it("dispatches the entire batch before any speech finishes and resumes after refresh with the same keys", async () => {
  const detail = restoreDetail();
  const generate = vi
    .fn()
    .mockResolvedValue({ status: "queued", audio_ready: false });
  const props = {
    detail,
    api: {
      deleteDebateVoice: vi.fn(),
      deleteDebateAll: vi.fn(),
      regenerateDebateTurnAudio: generate,
    },
    onVoiceDeleted: vi.fn(),
  };
  const first = render(<DebateCleanupControls {...props} />);
  fireEvent.click(screen.getByRole("button", { name: "Revocalize" }));
  await waitFor(() => expect(generate).toHaveBeenCalledTimes(3));
  const saved = JSON.parse(
    localStorage.getItem(`maya:revocalize:v1:${detail.id}`)!,
  );
  expect(Object.keys(saved.turns)).toEqual(["one", "two", "three"]);
  const keys = generate.mock.calls.map((call) => call[3].idempotency.key);
  first.unmount();
  generate.mockResolvedValue({ status: "completed", audio_ready: true });
  render(<DebateCleanupControls {...props} />);
  await waitFor(() => expect(generate).toHaveBeenCalledTimes(6));
  expect(
    generate.mock.calls.slice(3).map((call) => call[3].idempotency.key),
  ).toEqual(keys);
  await waitFor(() =>
    expect(localStorage.getItem(`maya:revocalize:v1:${detail.id}`)).toBeNull(),
  );
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Devocalize" })).toHaveProperty(
      "disabled",
      false,
    ),
  );
});

it("keeps polling a queued batch beyond two minutes without creating a new operation", async () => {
  vi.useFakeTimers();
  const detail = restoreDetail("restore-long");
  const generate = vi
    .fn()
    .mockResolvedValue({ status: "queued", audio_ready: false });
  render(
    <DebateCleanupControls
      detail={detail}
      api={{
        deleteDebateVoice: vi.fn(),
        deleteDebateAll: vi.fn(),
        regenerateDebateTurnAudio: generate,
      }}
      onVoiceDeleted={vi.fn()}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Revocalize" }));
  await act(async () => {
    await vi.advanceTimersByTimeAsync(125_000);
  });
  expect(screen.getByRole("button", { name: "Revocalize..." })).toHaveProperty(
    "disabled",
    true,
  );
  for (const id of ["one", "two", "three"]) {
    const requests = generate.mock.calls.filter((call) => call[1] === id);
    expect(requests.length).toBeGreaterThan(120);
    expect(new Set(requests.map((call) => call[3].idempotency.key)).size).toBe(
      1,
    );
  }
  generate.mockResolvedValue({ status: "completed", audio_ready: true });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1_000);
  });
  expect(screen.getByRole("button", { name: "Devocalize" })).toHaveProperty(
    "disabled",
    false,
  );
});

it("retries an ambiguous response using the persisted key, without stopping later turns", async () => {
  vi.useFakeTimers();
  const generate = vi
    .fn()
    .mockRejectedValueOnce(new TypeError("Network lost"))
    .mockResolvedValue({ status: "completed", audio_ready: true });
  render(
    <DebateCleanupControls
      detail={restoreDetail("restore-network")}
      api={{
        deleteDebateVoice: vi.fn(),
        deleteDebateAll: vi.fn(),
        regenerateDebateTurnAudio: generate,
      }}
      onVoiceDeleted={vi.fn()}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Revocalize" }));
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1_000);
  });
  expect(generate).toHaveBeenCalledTimes(4);
  expect(generate.mock.calls[3][3].idempotency.key).toBe(
    generate.mock.calls[0][3].idempotency.key,
  );
  expect(screen.getByRole("button", { name: "Devocalize" })).toHaveProperty(
    "disabled",
    false,
  );
});

it("reconciles a changed revision without reusing stale keys or abandoning missing audio", async () => {
  const detail = restoreDetail("restore-stale");
  localStorage.setItem(
    `maya:revocalize:v1:${detail.id}`,
    JSON.stringify({ revision: 6, turns: { one: { key: "old-key" } } }),
  );
  const generate = vi
    .fn()
    .mockResolvedValue({ status: "completed", audio_ready: true });
  render(
    <DebateCleanupControls
      detail={detail}
      api={{
        deleteDebateVoice: vi.fn(),
        deleteDebateAll: vi.fn(),
        regenerateDebateTurnAudio: generate,
      }}
      onVoiceDeleted={vi.fn()}
    />,
  );
  await waitFor(() =>
    expect(localStorage.getItem(`maya:revocalize:v1:${detail.id}`)).toBeNull(),
  );
  expect(generate).toHaveBeenCalledTimes(3);
  for (const call of generate.mock.calls) {
    expect(call[2]).toEqual({ expected_revision: 7 });
    expect(call[3].idempotency.key).not.toBe("old-key");
  }
});

it("does not automatically create a new billable attempt after a definitive audio failure", async () => {
  const detail = restoreDetail("restore-failed");
  const generate = vi
    .fn()
    .mockResolvedValue({ status: "failed", audio_ready: false });
  const props = {
    detail,
    api: {
      deleteDebateVoice: vi.fn(),
      deleteDebateAll: vi.fn(),
      regenerateDebateTurnAudio: generate,
    },
    onVoiceDeleted: vi.fn(),
  };
  const first = render(<DebateCleanupControls {...props} />);
  fireEvent.click(screen.getByRole("button", { name: "Revocalize" }));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Revocalize" })).toHaveProperty(
      "disabled",
      false,
    ),
  );
  first.unmount();
  render(<DebateCleanupControls {...props} />);
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 30));
  });
  expect(generate).toHaveBeenCalledTimes(3);
  fireEvent.click(screen.getByRole("button", { name: "Revocalize" }));
  await waitFor(() => expect(generate).toHaveBeenCalledTimes(6));
  expect(generate.mock.calls[3][3].idempotency.key).not.toBe(
    generate.mock.calls[0][3].idempotency.key,
  );
});

it("does not resume a previous teacher's authorization after an account switch", async () => {
  const detail = restoreDetail("restore-owner");
  localStorage.setItem(
    `maya:revocalize:v1:${detail.id}`,
    JSON.stringify({
      ownerId: "previous-teacher",
      revision: 7,
      turns: { one: { key: "previous-request" } },
    }),
  );
  const generate = vi.fn();
  render(
    <DebateCleanupControls
      detail={detail}
      restoreOwnerId="current-teacher"
      api={{
        deleteDebateVoice: vi.fn(),
        deleteDebateAll: vi.fn(),
        regenerateDebateTurnAudio: generate,
      }}
      onVoiceDeleted={vi.fn()}
    />,
  );
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 30));
  });
  expect(generate).not.toHaveBeenCalled();
});

function restoreApi(generate: ReturnType<typeof vi.fn>) {
  return {
    deleteDebateVoice: vi.fn(),
    deleteDebateAll: vi.fn(),
    regenerateDebateTurnAudio: generate,
  } as unknown as Pick<
    PlatformApi,
    "deleteDebateVoice" | "deleteDebateAll" | "regenerateDebateTurnAudio"
  >;
}

function markReady(detail: DebateDetail, id: string) {
  for (const turn of detail.preview_turns ?? []) {
    if (turn.id === id) turn.audio_ready = true;
  }
}

it.each(["list", "detail"])(
  "reconciles a partial persisted queue on %s mount",
  async (surface) => {
    const detail = restoreDetail(`partial-${surface}`);
    markReady(detail, "one");
    localStorage.setItem(
      `maya:revocalize:v1:${detail.id}`,
      JSON.stringify({
        ownerId: "teacher",
        revision: 7,
        turns: { one: { key: "done" }, two: { key: "keep-two" } },
      }),
    );
    const generate = vi.fn().mockImplementation(async (_id, turnId) => {
      markReady(detail, turnId);
      return { status: "completed", audio_ready: true };
    });
    render(
      <DebateCleanupControls
        {...(surface === "list"
          ? { debateId: detail.id, audioRestoreNeeded: true }
          : { detail })}
        restoreOwnerId="teacher"
        loadDetail={vi
          .fn()
          .mockImplementation(async () => structuredClone(detail))}
        api={restoreApi(generate)}
        onVoiceDeleted={vi.fn()}
        labelled
      />,
    );
    await waitFor(() => expect(generate).toHaveBeenCalledTimes(2));
    expect(generate.mock.calls.map((call) => call[1])).toEqual([
      "two",
      "three",
    ]);
    expect(generate.mock.calls[0][3].idempotency.key).toBe("keep-two");
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Devocalize" })).toHaveProperty(
        "disabled",
        false,
      ),
    );
    expect(localStorage.getItem(`maya:revocalize:v1:${detail.id}`)).toBeNull();
  },
);

it("preserves intent when Preview navigation unmounts during the first detail GET", async () => {
  const detail = restoreDetail("before-get");
  let finishGet!: (detail: DebateDetail) => void;
  const loadDetail = vi
    .fn()
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finishGet = resolve;
        }),
    )
    .mockImplementation(async () => structuredClone(detail));
  const generate = vi.fn().mockImplementation(async (_id, turnId) => {
    markReady(detail, turnId);
    return { status: "completed", audio_ready: true };
  });
  const props = {
    debateId: detail.id,
    restoreOwnerId: "teacher",
    audioRestoreNeeded: true,
    loadDetail,
    api: restoreApi(generate),
    onVoiceDeleted: vi.fn(),
  };
  const first = render(<DebateCleanupControls {...props} />);
  fireEvent.click(screen.getByRole("button", { name: "Revocalize" }));
  expect(
    JSON.parse(localStorage.getItem(`maya:revocalize:v1:${detail.id}`)!).turns,
  ).toEqual({});
  first.unmount(); // Open Preview, then the old request completes off-page.
  await act(async () => finishGet(detail));
  expect(generate).not.toHaveBeenCalled();
  render(<DebateCleanupControls {...props} />); // Back to list.
  await waitFor(() => expect(generate).toHaveBeenCalledTimes(3));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Devocalize" })).toHaveProperty(
      "disabled",
      false,
    ),
  );
});

it("resumes after Preview and Back, retaining pending keys and discovering newly eligible speech", async () => {
  const detail = restoreDetail("preview-back");
  const generate = vi.fn().mockImplementation(async (_id, turnId) => {
    if (turnId === "one") {
      markReady(detail, turnId);
      return { status: "completed", audio_ready: true };
    }
    return { status: "queued", audio_ready: false };
  });
  const props = {
    debateId: detail.id,
    audioRestoreNeeded: true,
    restoreOwnerId: "teacher",
    loadDetail: vi.fn().mockImplementation(async () => structuredClone(detail)),
    api: restoreApi(generate),
    onVoiceDeleted: vi.fn(),
  };
  const first = render(<DebateCleanupControls {...props} />);
  fireEvent.click(screen.getByRole("button", { name: "Revocalize" }));
  await waitFor(() => expect(generate).toHaveBeenCalledTimes(3));
  const pending = JSON.parse(
    localStorage.getItem(`maya:revocalize:v1:${detail.id}`)!,
  ).turns;
  expect(Object.keys(pending)).toEqual(["two", "three"]);
  first.unmount();
  detail.preview_turns.push({ ...detail.preview_turns[1], id: "four" });
  generate.mockImplementation(async (_id, turnId) => {
    markReady(detail, turnId);
    return { status: "completed", audio_ready: true };
  });
  render(<DebateCleanupControls {...props} />);
  await waitFor(() => expect(generate).toHaveBeenCalledTimes(6));
  expect(generate.mock.calls.slice(3).map((call) => call[1])).toEqual([
    "two",
    "three",
    "four",
  ]);
  expect(generate.mock.calls[3][3].idempotency.key).toBe(pending.two.key);
  expect(generate.mock.calls[4][3].idempotency.key).toBe(pending.three.key);
  await waitFor(() =>
    expect(localStorage.getItem(`maya:revocalize:v1:${detail.id}`)).toBeNull(),
  );
});

it("automatically retries a pre-provider admission refusal, including across refresh", async () => {
  const detail = restoreDetail("admission-refused");
  detail.preview_turns = detail.preview_turns.slice(0, 1);
  const generate = vi.fn().mockResolvedValue({
    status: "failed",
    audio_ready: false,
    safe_error_code: "tts_provider_unavailable",
  });
  const props = {
    detail,
    restoreOwnerId: "teacher",
    api: restoreApi(generate),
    onVoiceDeleted: vi.fn(),
  };
  const first = render(<DebateCleanupControls {...props} />);
  fireEvent.click(screen.getByRole("button", { name: "Revocalize" }));
  await waitFor(() => expect(generate).toHaveBeenCalledTimes(1));
  const saved = JSON.parse(
    localStorage.getItem(`maya:revocalize:v1:${detail.id}`)!,
  );
  expect(saved.turns.one.failed).not.toBe(true);
  expect(saved.turns.one.key).not.toBe(
    generate.mock.calls[0][3].idempotency.key,
  );
  expect(screen.getByRole("button", { name: "Revocalize..." })).toHaveProperty(
    "disabled",
    true,
  );
  first.unmount();
  generate.mockResolvedValue({ status: "completed", audio_ready: true });
  render(<DebateCleanupControls {...props} />);
  await waitFor(() => expect(generate).toHaveBeenCalledTimes(2));
  expect(generate.mock.calls[1][3].idempotency.key).toBe(saved.turns.one.key);
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Devocalize" })).toHaveProperty(
      "disabled",
      false,
    ),
  );
});

it.each([408, 425, 429, 503])(
  "keeps HTTP %s transient without minting a new attempt",
  async (status) => {
    vi.useFakeTimers();
    const detail = restoreDetail(`http-${status}`);
    detail.preview_turns = detail.preview_turns.slice(0, 1);
    const generate = vi
      .fn()
      .mockRejectedValueOnce(new PlatformApiError(status, "private details"))
      .mockResolvedValue({ status: "completed", audio_ready: true });
    render(
      <DebateCleanupControls
        detail={detail}
        api={restoreApi(generate)}
        onVoiceDeleted={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Revocalize" }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_000);
    });
    expect(generate).toHaveBeenCalledTimes(2);
    expect(generate.mock.calls[1][3].idempotency.key).toBe(
      generate.mock.calls[0][3].idempotency.key,
    );
    expect(screen.getByRole("button", { name: "Devocalize" })).toHaveProperty(
      "disabled",
      false,
    );
  },
);

it("reconciles a stale response against the new revision without losing remaining work", async () => {
  vi.useFakeTimers();
  const detail = restoreDetail("revision-in-flight");
  detail.preview_turns = detail.preview_turns.slice(0, 1);
  const generate = vi
    .fn()
    .mockImplementationOnce(async () => {
      detail.revision = 8;
      return {
        status: "stale",
        audio_ready: false,
        safe_error_code: "stale_revision",
      };
    })
    .mockImplementation(async (_id, turnId) => {
      markReady(detail, turnId);
      return { status: "completed", audio_ready: true };
    });
  render(
    <DebateCleanupControls
      debateId={detail.id}
      audioRestoreNeeded
      loadDetail={vi
        .fn()
        .mockImplementation(async () => structuredClone(detail))}
      api={restoreApi(generate)}
      onVoiceDeleted={vi.fn()}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Revocalize" }));
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1_000);
  });
  expect(generate).toHaveBeenCalledTimes(2);
  expect(generate.mock.calls.map((call) => call[2].expected_revision)).toEqual([
    7, 8,
  ]);
  expect(generate.mock.calls[1][3].idempotency.key).not.toBe(
    generate.mock.calls[0][3].idempotency.key,
  );
  expect(localStorage.getItem(`maya:revocalize:v1:${detail.id}`)).toBeNull();
});

it("keeps an empty durable marker until the final detail verification finishes", async () => {
  const detail = restoreDetail("verify-last");
  detail.preview_turns = detail.preview_turns.slice(0, 1);
  let finishVerification!: (detail: DebateDetail) => void;
  const loadDetail = vi
    .fn()
    .mockResolvedValueOnce(structuredClone(detail))
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finishVerification = resolve;
        }),
    )
    .mockImplementation(async () => structuredClone(detail));
  const generate = vi.fn().mockImplementation(async (_id, turnId) => {
    markReady(detail, turnId);
    return { status: "completed", audio_ready: true };
  });
  const props = {
    debateId: detail.id,
    audioRestoreNeeded: true,
    loadDetail,
    api: restoreApi(generate),
    onVoiceDeleted: vi.fn(),
  };
  const first = render(<DebateCleanupControls {...props} />);
  fireEvent.click(screen.getByRole("button", { name: "Revocalize" }));
  await waitFor(() => expect(loadDetail).toHaveBeenCalledTimes(2));
  expect(
    JSON.parse(localStorage.getItem(`maya:revocalize:v1:${detail.id}`)!).turns,
  ).toEqual({});
  first.unmount();
  await act(async () => finishVerification(detail));
  expect(
    localStorage.getItem(`maya:revocalize:v1:${detail.id}`),
  ).not.toBeNull();
  render(<DebateCleanupControls {...props} />);
  await waitFor(() =>
    expect(localStorage.getItem(`maya:revocalize:v1:${detail.id}`)).toBeNull(),
  );
  expect(generate).toHaveBeenCalledTimes(1);
});

it("bounds dispatch concurrency but persists all unsent turns for the next mount", async () => {
  const detail = restoreDetail("bounded-queue");
  detail.preview_turns = Array.from({ length: 10 }, (_, index) => ({
    ...detail.preview_turns[0],
    id: `speech-${index}`,
  }));
  const generate = vi.fn().mockImplementation(() => new Promise(() => {}));
  const props = { detail, api: restoreApi(generate), onVoiceDeleted: vi.fn() };
  const first = render(<DebateCleanupControls {...props} />);
  fireEvent.click(screen.getByRole("button", { name: "Revocalize" }));
  await waitFor(() => expect(generate).toHaveBeenCalledTimes(3));
  const saved = JSON.parse(
    localStorage.getItem(`maya:revocalize:v1:${detail.id}`)!,
  );
  expect(Object.keys(saved.turns)).toHaveLength(10);
  first.unmount();
  generate.mockResolvedValue({ status: "completed", audio_ready: true });
  render(<DebateCleanupControls {...props} />);
  await waitFor(() => expect(generate).toHaveBeenCalledTimes(13));
  await waitFor(() =>
    expect(localStorage.getItem(`maya:revocalize:v1:${detail.id}`)).toBeNull(),
  );
});

it("keeps backing off admission refusals beyond two minutes, then finishes without a manual click", async () => {
  vi.useFakeTimers();
  const detail = restoreDetail("admission-long");
  detail.preview_turns = detail.preview_turns.slice(0, 1);
  const generate = vi.fn().mockResolvedValue({
    status: "failed",
    audio_ready: false,
    safe_error_code: "tts_provider_unavailable",
  });
  render(
    <DebateCleanupControls
      detail={detail}
      api={restoreApi(generate)}
      onVoiceDeleted={vi.fn()}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Revocalize" }));
  await act(async () => {
    await vi.advanceTimersByTimeAsync(125_000);
  });
  expect(screen.getByRole("button", { name: "Revocalize..." })).toHaveProperty(
    "disabled",
    true,
  );
  expect(screen.queryByRole("alert")).toBeNull();
  expect(generate.mock.calls.length).toBeGreaterThan(5);
  expect(generate.mock.calls.length).toBeLessThan(20);
  generate.mockResolvedValue({ status: "completed", audio_ready: true });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(15_000);
  });
  expect(screen.getByRole("button", { name: "Devocalize" })).toHaveProperty(
    "disabled",
    false,
  );
});

it("surfaces definitive per-turn failures after refresh but still seeds and completes unrecorded turns", async () => {
  const detail = restoreDetail("failed-partial");
  localStorage.setItem(
    `maya:revocalize:v1:${detail.id}`,
    JSON.stringify({
      revision: 7,
      turns: { one: { key: "failed-once", failed: true } },
    }),
  );
  const generate = vi.fn().mockImplementation(async (_id, turnId) => {
    markReady(detail, turnId);
    return { status: "completed", audio_ready: true };
  });
  const props = {
    debateId: detail.id,
    audioRestoreNeeded: true,
    loadDetail: vi.fn().mockImplementation(async () => structuredClone(detail)),
    api: restoreApi(generate),
    onVoiceDeleted: vi.fn(),
  };
  const first = render(<DebateCleanupControls {...props} />);
  await waitFor(() => expect(generate).toHaveBeenCalledTimes(2));
  expect(generate.mock.calls.map((call) => call[1])).toEqual(["two", "three"]);
  await waitFor(() =>
    expect(screen.getByRole("alert").textContent).toContain("1 speech turn(s)"),
  );
  first.unmount();
  render(<DebateCleanupControls {...props} />);
  await waitFor(() =>
    expect(screen.getByRole("alert").textContent).toContain("1 speech turn(s)"),
  );
  expect(generate).toHaveBeenCalledTimes(2);
  fireEvent.click(screen.getByRole("button", { name: "Revocalize" }));
  await waitFor(() => expect(generate).toHaveBeenCalledTimes(3));
  expect(generate.mock.calls[2][1]).toBe("one");
  expect(generate.mock.calls[2][3].idempotency.key).not.toBe("failed-once");
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Devocalize" })).toHaveProperty(
      "disabled",
      false,
    ),
  );
});

it("keeps the persisted queue when detail loading is temporarily unavailable on mount", async () => {
  vi.useFakeTimers();
  const detail = restoreDetail("detail-unavailable");
  localStorage.setItem(
    `maya:revocalize:v1:${detail.id}`,
    JSON.stringify({
      revision: 7,
      turns: { one: { key: "retained" } },
    }),
  );
  const loadDetail = vi
    .fn()
    .mockRejectedValueOnce(new PlatformApiError(503, "Unavailable"))
    .mockImplementation(async () => structuredClone(detail));
  const generate = vi.fn().mockImplementation(async (_id, turnId) => {
    markReady(detail, turnId);
    return { status: "completed", audio_ready: true };
  });
  render(
    <DebateCleanupControls
      debateId={detail.id}
      loadDetail={loadDetail}
      api={restoreApi(generate)}
      onVoiceDeleted={vi.fn()}
    />,
  );
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1_000);
  });
  expect(generate).toHaveBeenCalledTimes(3);
  expect(generate.mock.calls[0][3].idempotency.key).toBe("retained");
  expect(localStorage.getItem(`maya:revocalize:v1:${detail.id}`)).toBeNull();
});

it("retries a claim-admission race with the original key", async () => {
  vi.useFakeTimers();
  const detail = restoreDetail("claim-race");
  detail.preview_turns = detail.preview_turns.slice(0, 1);
  const generate = vi
    .fn()
    .mockResolvedValueOnce({
      status: "failed",
      audio_ready: false,
      safe_error_code: "claim_unavailable",
    })
    .mockResolvedValue({ status: "completed", audio_ready: true });
  render(
    <DebateCleanupControls
      detail={detail}
      api={restoreApi(generate)}
      onVoiceDeleted={vi.fn()}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Revocalize" }));
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1_000);
  });
  expect(generate).toHaveBeenCalledTimes(2);
  expect(generate.mock.calls[1][3].idempotency.key).toBe(
    generate.mock.calls[0][3].idempotency.key,
  );
  expect(screen.getByRole("button", { name: "Devocalize" })).toHaveProperty(
    "disabled",
    false,
  );
});

it.each([
  "tts_timeout",
  "audio_regeneration_interrupted",
  "acceptance_unknown",
])("never silently sends a new provider attempt after %s", async (code) => {
  const detail = restoreDetail(`terminal-${code}`);
  detail.preview_turns = detail.preview_turns.slice(0, 1);
  const generate = vi.fn().mockResolvedValue({
    status: "failed",
    audio_ready: false,
    safe_error_code: code,
  });
  const props = { detail, api: restoreApi(generate), onVoiceDeleted: vi.fn() };
  const first = render(<DebateCleanupControls {...props} />);
  fireEvent.click(screen.getByRole("button", { name: "Revocalize" }));
  await screen.findByRole("alert");
  first.unmount();
  render(<DebateCleanupControls {...props} />);
  await screen.findByRole("alert");
  expect(generate).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("alert").textContent).toContain("one");
});
