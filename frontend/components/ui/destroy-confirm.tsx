"use client";

import { useEffect } from "react";
import { createPortal } from "react-dom";

import { useT } from "../../lib/i18n";
import { cn } from "../../lib/utils";
import { NOTICE_TAIL_CLASS, useNoticeTray } from "../notice-tray";
import { KindSticker, RoundX, useRevealNotice } from "./error-kit";

const SCRIM = "fixed inset-0 z-[60] bg-[#111]/40";
const ACTIONS = "flex flex-wrap justify-end gap-2";
const CANCEL =
  "inline-flex min-h-10 cursor-pointer items-center justify-center rounded-[10px] border-2 border-[#111] bg-white px-4 py-2 font-body text-sm font-bold text-[#111] shadow-[0_6px_0_#111] transition-[translate,box-shadow] duration-150 hover:-translate-y-0.5 active:translate-y-1.5 active:shadow-none disabled:cursor-default disabled:opacity-50 motion-reduce:transition-colors motion-reduce:hover:translate-y-0 motion-reduce:active:translate-y-0 motion-reduce:active:shadow-[0_6px_0_#111]";
/** Red Delete (Scheme B), not immerse soft-danger End. */
const DELETE =
  "inline-flex min-h-10 cursor-pointer items-center justify-center rounded-[10px] border-[3px] border-[#111] bg-[#ef4444] px-4 py-2 font-body text-sm font-bold text-white shadow-[0_3px_0_#111] transition-[translate,box-shadow,background-color] duration-150 hover:-translate-y-0.5 hover:bg-[#dc2626] active:translate-y-1 active:shadow-none disabled:cursor-default disabled:opacity-50 motion-reduce:transition-colors motion-reduce:hover:translate-y-0 motion-reduce:active:translate-y-0 motion-reduce:active:shadow-[0_3px_0_#111]";
const FALLBACK =
  "fixed z-[61] top-1/2 left-1/2 grid gap-4 w-[min(420px,calc(100%_-_48px))] p-5 border-[3px] border-solid border-[#111] rounded-[10px] bg-white shadow-[6px_6px_0_#111] [transform:translate(-50%,-50%)] [&_p]:m-0 [&_p]:whitespace-pre-line [&_p]:text-[16px] [&_p]:leading-[1.5] [&_p]:font-medium [&_p]:text-[#111]";

/**
 * Destroy/hide confirm: U3 opaque pink mascot-tray bubble (bell sticker,
 * RoundX, hard shadow) plus Cancel / red Delete. Same set as debate End, with
 * a red Delete action. A #111 40% scrim blocks the page until Cancel, ×, or
 * Delete. Non-transient — stays until one of those.
 */
export function DestroyConfirmPrompt({
  message,
  busy = false,
  onCancel,
  onConfirm,
}: {
  message: string;
  busy?: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const t = useT();
  const tray = useNoticeTray(true);
  useRevealNotice(tray, message);

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

  const bubble = (
    <div
      className={cn(
        "notice notice-error dismissible-alert-tray pointer-events-auto relative my-0 flex w-full max-w-[440px] flex-none flex-col items-stretch gap-3 rounded-[18px] border-[3px] border-[#111] bg-[#FFE4E4] py-3 pr-[46px] pl-3.5 text-left font-body text-sm leading-[1.45] font-medium text-[#111] shadow-[4px_4px_0_#111]",
        NOTICE_TAIL_CLASS,
      )}
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="destroy-confirm-message"
    >
      <div className="flex items-start gap-2.5">
        <KindSticker kind="bell" />
        <p
          id="destroy-confirm-message"
          className="m-0 min-w-0 flex-1 whitespace-pre-line"
        >
          {message}
        </p>
      </div>
      <div className={ACTIONS}>
        <button
          className={CANCEL}
          type="button"
          disabled={busy}
          onClick={onCancel}
        >
          {t("cancel")}
        </button>
        <button
          className={DELETE}
          type="button"
          disabled={busy}
          onClick={onConfirm}
        >
          {t("delete")}
        </button>
      </div>
      <RoundX
        className="notice-close absolute top-[9px] right-[10px]"
        aria-label={t("knowledgeCheckClose")}
        disabled={busy}
        onClick={onCancel}
      />
    </div>
  );

  const fallback = (
    <div
      className={FALLBACK}
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="destroy-confirm-message"
    >
      <p id="destroy-confirm-message">{message}</p>
      <div className={ACTIONS}>
        <button
          className={CANCEL}
          type="button"
          disabled={busy}
          onClick={onCancel}
        >
          {t("cancel")}
        </button>
        <button
          className={DELETE}
          type="button"
          disabled={busy}
          onClick={onConfirm}
        >
          {t("delete")}
        </button>
      </div>
    </div>
  );

  return (
    <>
      <div
        className={SCRIM}
        aria-hidden="true"
        onClick={() => {
          if (!busy) onCancel();
        }}
      />
      {tray ? createPortal(bubble, tray) : fallback}
    </>
  );
}
