"use client";

import { AvatarCanvas, type AvatarCanvasProps } from "./avatar-canvas";

export type AvatarPreviewProps = AvatarCanvasProps;

/** Naming alias for pages that want to embed a preview without editor controls. */
export function AvatarPreview(props: AvatarPreviewProps) {
  return <AvatarCanvas {...props} />;
}
