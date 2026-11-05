"use client";

import { useEffect } from "react";
import { createPortal } from "react-dom";

import { cn } from "../../../lib/utils";
import {
  KindSticker,
  NOTICE_TAIL_CLASS,
  RoundX,
  useNoticeTray,
  useRevealNotice,
} from "../../ui";
import {
  BETA_END_PROMPT,
  BETA_END_PROMPT_ACTIONS,
  BETA_END_PROMPT_CANCEL,
  BETA_END_PROMPT_END,
  BETA_END_PROMPT_SCRIM,
} from "./beta-chrome";

/**
 * End-that-debate confirm: U3 opaque pink mascot-tray bubble (bell sticker,
 * RoundX, hard shadow) plus neobrutalism Cancel / soft-danger End. A #111 40%
 * scrim keeps the stage blocked while the bubble speaks from the tray.
 * Non-transient — a confirm must stay until Cancel, ×, or End.
 */
export function EndRunningDebatePrompt({
  topic,
  zh,
  busy,
  canEnd,
  onCancel,
  onEnd,
}: {
  topic: string;
  zh: boolean;
  busy: boolean;
  canEnd: boolean;
  onCancel: () => void;
  onEnd: () => void;
}) {
  const tray = useNoticeTray(true);
  useRevealNotice(tray, topic);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape" && !busy) {
        event.preventDefault();
        onCancel();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, onCancel]);

  const message = zh
    ? `「${topic}」正在进行。要结束那场辩论吗？`
    : `“${topic}” is running. End that debate?`;
  const cancelLabel = zh ? "取消" : "Cancel";
  const endLabel = busy ? (zh ? "正在结束…" : "Ending…") : zh ? "结束" : "End";

  const bubble = (
    <div
      className={cn(
        "notice notice-error dismissible-alert-tray pointer-events-auto relative my-0 flex w-full max-w-[440px] flex-none flex-col items-stretch gap-3 rounded-[18px] border-[3px] border-[#111] bg-[#FFE4E4] py-3 pr-[46px] pl-3.5 text-left font-body text-sm leading-[1.45] font-medium text-[#111] shadow-[4px_4px_0_#111]",
        NOTICE_TAIL_CLASS,
      )}
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="end-running-debate"
    >
      <div className="flex items-start gap-2.5">
        <KindSticker kind="bell" />
        <p id="end-running-debate" className="m-0 min-w-0 flex-1">
          {message}
        </p>
      </div>
      <div className={BETA_END_PROMPT_ACTIONS}>
        <button
          className={BETA_END_PROMPT_CANCEL}
          type="button"
          disabled={busy}
          onClick={onCancel}
        >
          {cancelLabel}
        </button>
        <button
          className={BETA_END_PROMPT_END}
          type="button"
          disabled={busy || !canEnd}
          onClick={onEnd}
        >
          {endLabel}
        </button>
      </div>
      <RoundX
        className="notice-close absolute top-[9px] right-[10px]"
        aria-label={zh ? "关闭" : "Dismiss"}
        disabled={busy}
        onClick={onCancel}
      />
    </div>
  );

  // Tray missing (shell-less boot): fall back to a centred neobrutalism card.
  const fallback = (
    <div
      className={BETA_END_PROMPT}
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="end-running-debate"
    >
      <p id="end-running-debate">{message}</p>
      <div className={BETA_END_PROMPT_ACTIONS}>
        <button
          className={BETA_END_PROMPT_CANCEL}
          type="button"
          disabled={busy}
          onClick={onCancel}
        >
          {cancelLabel}
        </button>
        <button
          className={BETA_END_PROMPT_END}
          type="button"
          disabled={busy || !canEnd}
          onClick={onEnd}
        >
          {endLabel}
        </button>
      </div>
    </div>
  );

  return (
    <>
      <div
        className={BETA_END_PROMPT_SCRIM}
        aria-hidden="true"
        onClick={() => {
          if (!busy) onCancel();
        }}
      />
      {tray ? createPortal(bubble, tray) : fallback}
    </>
  );
}
