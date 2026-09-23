import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { DebateCleanupControls } from "../components/debate/debate-cleanup-controls";
import type { DebateDetail, PlatformApi } from "../lib/api";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
afterEach(cleanup);

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
  const generate = vi.fn().mockRejectedValue(new Error("private details"));
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
