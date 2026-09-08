"use client";

import { useState } from "react";

import { useSession } from "../session-provider";
import { useT } from "../locale";
import { createIdempotencyHandle } from "../../lib/api";

import styles from "./release-button.module.css";

/** Explicit current-turn recovery; saved text is reused whenever available. */
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

  const release = async () => {
    setBusy(true);

    try {
      const detail = await api.debate(debateId);
      await api.remakeDebate(
        debateId,
        {
          expected_revision: detail.revision,
          expected_control_version: detail.playback.control_version,
        },
        { idempotency: createIdempotencyHandle() },
      );
      setArmed(false);
      onReleased();
    } catch {
      setArmed(false);
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
    </span>
  );
}
