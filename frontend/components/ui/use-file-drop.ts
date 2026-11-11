"use client";

import { useState, type DragEvent } from "react";

export function useFileDrop({
  disabled = false,
  busy = false,
  onFile,
}: {
  disabled?: boolean;
  busy?: boolean;
  onFile?: (file: File) => void;
}) {
  const [over, setOver] = useState(false);
  const blocked = disabled || busy;

  function onDragOver(event: DragEvent<HTMLElement>) {
    if (!event.dataTransfer.types.includes("Files")) return;
    event.preventDefault();
    setOver(!blocked);
    event.dataTransfer.dropEffect = blocked ? "none" : "copy";
  }

  function onDragLeave(event: DragEvent<HTMLElement>) {
    if (!event.dataTransfer.types.includes("Files")) return;
    if (
      event.relatedTarget instanceof Node &&
      event.currentTarget.contains(event.relatedTarget)
    )
      return;
    setOver(false);
  }

  function onDrop(event: DragEvent<HTMLElement>) {
    if (!event.dataTransfer.types.includes("Files")) return;
    event.preventDefault();
    setOver(false);
    const file = event.dataTransfer.files[0];
    if (!blocked && file) onFile?.(file);
  }

  return {
    "data-drag": over && !blocked ? ("over" as const) : undefined,
    onDragEnter: onDragOver,
    onDragOver,
    onDragLeave,
    onDrop,
  };
}
