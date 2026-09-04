"use client";

import { useState } from "react";

import { useSession } from "../session-provider";
import { useT } from "../locale";
import { ErrorNotice } from "../ui";
import styles from "./release-button.module.css";

/**
 * Recover one stuck classroom playback, with a confirmation step.
 *
 * Two presses, not a dialog: the first press says what will happen, the second
 * does it. That is the browser's equivalent of the `--confirm RESET` token the
 * CLI required, and it keeps an accidental click from ending a live lesson.
 */
export function ReleaseButton({
  debateId,
  onReleased,
  label,
}: {
  debateId: string;
  onReleased: () => void;
  label?: string;
}) {
  const t = useT();
  const { api } = useSession();
  const [armed, setArmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<unknown>(null);

  const release = async () => {
    setBusy(true);
    setFailure(null);
    try {
      await api.releaseDebate(debateId);
      setArmed(false);
      onReleased();
    } catch (cause) {
      setFailure(cause);
    } finally {
      setBusy(false);
    }
  };

  return (
    <span className={styles.releaseSlot}>
      <button
        className="secondary-action"
        disabled={busy}
        onClick={(event) => {
          event.preventDefault();
          if (armed) void release();
          else setArmed(true);
        }}
        type="button"
      >
        {armed ? t("debateReleaseConfirm") : (label ?? t("debateRelease"))}
      </button>
      {failure ? <ErrorNotice error={failure} /> : null}
    </span>
  );
}
