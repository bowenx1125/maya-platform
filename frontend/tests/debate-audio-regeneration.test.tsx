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

it("returns to quiet Revocalize when audio restoration fails", async () => {
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
  expect(screen.queryByRole("alert")).toBeNull();
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

function restoreDetail(id = "restore-refresh"): DebateDetail {
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
  } as unknown as DebateDetail;
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

it("keeps polling a queued batch beyond 45 seconds without creating a new operation", async () => {
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
    await vi.advanceTimersByTimeAsync(46_000);
  });
  expect(screen.getByRole("button", { name: "Revocalize..." })).toHaveProperty(
    "disabled",
    true,
  );
  for (const id of ["one", "two", "three"]) {
    const requests = generate.mock.calls.filter((call) => call[1] === id);
    expect(requests.length).toBeGreaterThan(45);
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

it("does not reuse an old batch after Rebirth changes the revision", async () => {
  const detail = restoreDetail("restore-stale");
  localStorage.setItem(
    `maya:revocalize:v1:${detail.id}`,
    JSON.stringify({ revision: 6, turns: { one: { key: "old-key" } } }),
  );
  const generate = vi.fn();
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
  expect(generate).not.toHaveBeenCalled();
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
