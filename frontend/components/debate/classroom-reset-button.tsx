"use client";

import { useRef, useState } from "react";
import {
  createIdempotencyHandle,
  isAmbiguousMutationFailure,
  type IdempotencyHandle,
} from "../../lib/api";
import { useSession } from "../session-provider";
import { IconRecycle, IconSpinner } from "../quiet-icons";
import { ErrorNotice } from "../ui";
import { Button } from "../ui/button";
import { DEBATE_ROW_BUTTON } from "./debate-chrome";

export function ClassroomResetButton({
  debateId,
  onDone,
  className = DEBATE_ROW_BUTTON,
  disabled = false,
}: {
  debateId: string;
  onDone: () => Promise<void>;
  className?: string;
  disabled?: boolean;
}) {
  const { api } = useSession();
  const [busy, setBusy] = useState(false);
  const [resetCommitted, setResetCommitted] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const active = useRef(false);
  const intent = useRef<{
    body: {
      expected_revision: number;
      expected_control_version: number;
    };
    idempotency: IdempotencyHandle;
  } | null>(null);

  async function reset() {
    if (active.current) return;
    if (
      !resetCommitted &&
      !intent.current &&
      !window.confirm(
        "Keep Preview and reset this classroom? Messages, Report and the final round will be removed.",
      )
    )
      return;
    active.current = true;
    setBusy(true);
    setError(null);
    let committed = resetCommitted;
    try {
      if (!committed) {
        if (!intent.current) {
          const detail = await api.debate(debateId);
          intent.current = {
            body: {
              expected_revision: detail.revision,
              expected_control_version: detail.playback.control_version,
            },
            idempotency: createIdempotencyHandle(),
          };
        }
        await api.rebirthDebate(debateId, intent.current.body, {
          idempotency: intent.current.idempotency,
        });
        committed = true;
        setResetCommitted(true);
        intent.current = null;
      }
      await onDone();
    } catch (cause) {
      if (!isAmbiguousMutationFailure(cause)) intent.current = null;
      setError(committed ? { code: "rebirth_refresh_failed" } : cause);
    } finally {
      active.current = false;
      setBusy(false);
    }
  }

  return (
    <>
      {error ? (
        <ErrorNotice error={error} onRetry={() => void reset()} />
      ) : null}
      <Button
        variant="noShadow"
        className={className}
        disabled={disabled || busy || resetCommitted}
        type="button"
        aria-label="Replay"
        aria-busy={busy || undefined}
        onClick={() => void reset()}
      >
        {busy ? <IconSpinner size={18} /> : <IconRecycle size={18} />}
        <span>Replay</span>
      </Button>
    </>
  );
}
