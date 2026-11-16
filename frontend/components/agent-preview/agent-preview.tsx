"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { Drawing } from "../avatar/drawing";
import { EggCanvas } from "../avatar/egg-canvas";
import { PreviewControls } from "./preview-controls";
import {
  PreviewController,
  type PreviewReply,
  type PreviewState,
} from "./preview-controller";
import styles from "./preview.module.css";

export function AgentPreview({
  onClose,
  drawing,
  request,
}: {
  drawing?: Drawing | null;
  onClose: () => void;
  request: (message: string) => Promise<PreviewReply>;
}) {
  const [state, setState] = useState<PreviewState>({
    question: "",
    answer: "",
    playing: false,
  });
  const controller = useRef<PreviewController | null>(null);
  const dialog = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const oldOverflow = document.body.style.overflow;
    const root = document.documentElement;
    const oldRootOverflow = root.style.overflow;
    const oldGutter = root.style.scrollbarGutter;
    root.style.overflow = "hidden";
    root.style.scrollbarGutter = "auto";
    document.body.style.overflow = "hidden";
    const current = new PreviewController(setState);
    controller.current = current;
    dialog.current?.querySelector<HTMLInputElement>("input")?.focus();
    return () => {
      current.close();
      controller.current = null;
      document.body.style.overflow = oldOverflow;
      root.style.overflow = oldRootOverflow;
      root.style.scrollbarGutter = oldGutter;
      previous?.focus();
    };
  }, []);
  const close = () => {
    controller.current?.close();
    onClose();
  };
  return createPortal(
    <div
      ref={dialog}
      className={styles.preview}
      role="dialog"
      aria-modal="true"
      aria-label="Preview"
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          event.preventDefault();
          close();
        }
        if (event.key === "Tab") {
          const items = dialog.current?.querySelectorAll<HTMLElement>(
            "button:not(:disabled), input",
          );
          if (!items?.length) return;
          const first = items[0],
            last = items[items.length - 1];
          if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last.focus();
          } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first.focus();
          }
        }
      }}
    >
      <div className={styles.courtyard} aria-hidden="true" />
      <div className={styles.stage}>
        <EggCanvas playing={state.playing} drawing={drawing} />
      </div>
      <PreviewControls
        question={state.question}
        answer={state.answer}
        onClose={close}
        onSend={(message) => {
          void controller.current?.ask(message, () => request(message));
        }}
      />
    </div>,
    document.body,
  );
}
