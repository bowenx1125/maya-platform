export type PreviewRetryTurn = {
  id: string;
  generation_status: string;
  speech?: string | null;
  audio_ready?: boolean;
  safe_error_code?: string | null;
};

export type PreviewRetrySnapshot = {
  playback: { control_version: number };
  preview_turns?: readonly PreviewRetryTurn[] | null;
};

const IN_FLIGHT_STATUSES = new Set([
  "pending",
  "generating",
  "not_started",
  "running",
  "queued",
  "preparing",
]);

export const PREVIEW_RETRY_POLL_MS = 2000;
export const PREVIEW_RETRY_TIMEOUT_MS = 8 * 60 * 1000;

export function previewTurnReady(turn: PreviewRetryTurn): boolean {
  return (
    ["final_ready", "ready", "completed"].includes(turn.generation_status) &&
    Boolean((turn.speech ?? "").trim())
  );
}

export function previewTurnInFlight(turn: PreviewRetryTurn): boolean {
  if (previewTurnReady(turn)) return false;
  if (IN_FLIGHT_STATUSES.has(turn.generation_status)) return true;
  return turn.generation_status !== "failed" && !turn.safe_error_code;
}

function defaultDelay(ms: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

export async function retryPreviewTurnsInOrder(options: {
  turnIds: readonly string[];
  controlVersion: number;
  retry: (turnId: string, controlVersion: number) => Promise<void>;
  refresh: () => Promise<PreviewRetrySnapshot>;
  delay?: (ms: number) => Promise<void>;
  pollMs?: number;
  timeoutMs?: number;
  now?: () => number;
  onTurnStart?: (turnId: string) => void;
  isCancelled?: () => boolean;
}): Promise<{
  controlVersion: number;
  failedTurnId?: string;
  timedOutTurnId?: string;
  cancelled?: boolean;
}> {
  const delay = options.delay ?? defaultDelay;
  const pollMs = options.pollMs ?? PREVIEW_RETRY_POLL_MS;
  const timeoutMs = options.timeoutMs ?? PREVIEW_RETRY_TIMEOUT_MS;
  const now = options.now ?? Date.now;
  let controlVersion = options.controlVersion;

  for (const turnId of options.turnIds) {
    if (options.isCancelled?.()) {
      return { controlVersion, cancelled: true };
    }
    options.onTurnStart?.(turnId);
    await options.retry(turnId, controlVersion);
    const startedAt = now();
    let seenInFlight = false;
    let snapshot = await options.refresh();
    controlVersion = snapshot.playback.control_version;

    while (true) {
      const turn = snapshot.preview_turns?.find((item) => item.id === turnId);
      if (!turn) {
        return { controlVersion, failedTurnId: turnId };
      }
      if (previewTurnReady(turn)) {
        break;
      }
      if (previewTurnInFlight(turn)) {
        seenInFlight = true;
      } else if (seenInFlight) {
        return { controlVersion, failedTurnId: turnId };
      }
      if (now() - startedAt >= timeoutMs) {
        return { controlVersion, timedOutTurnId: turnId };
      }
      await delay(pollMs);
      if (options.isCancelled?.()) {
        return { controlVersion, cancelled: true };
      }
      snapshot = await options.refresh();
      controlVersion = snapshot.playback.control_version;
    }
  }

  return { controlVersion };
}
