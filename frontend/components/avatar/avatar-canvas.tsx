"use client";

import { useEffect, useRef, useState } from "react";

import { useT } from "../locale";
import type { AvatarConfig, AvatarState } from "./types";
import { avatarAssetUrlForTemplate } from "./types";
import styles from "./avatar.module.css";

export type AvatarCanvasProps = {
  config: AvatarConfig;
  state?: AvatarState;
  assetUrl?: string;
  framing?: "head" | "full-body";
  fallbackLabel?: string;
  className?: string;
  onLoad?: () => void;
  onError?: (error: Error) => void;
};

type CanvasStatus = "loading" | "ready" | "failed";

function initials(label: string): string {
  const words = label.trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return "?";
  return words
    .slice(0, 2)
    .map((word) => word[0]?.toUpperCase() ?? "")
    .join("");
}

export function AvatarCanvas({
  config,
  state = "idle",
  assetUrl,
  fallbackLabel,
  framing = "head",
  className,
  onLoad,
  onError,
}: AvatarCanvasProps) {
  const t = useT();
  const fallback = fallbackLabel ?? t("avatar");
  // A missing config is not a guessable character. Leave the mesh unloaded
  // so the static initials stay up until a real AvatarConfig arrives.
  const templateId =
    config && typeof config.template_id === "string" ? config.template_id : "";
  const resolvedAssetUrl =
    assetUrl ?? (templateId ? avatarAssetUrlForTemplate(templateId) : "");
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rendererRef = useRef<import("./avatar-renderer").AvatarRenderer | null>(
    null,
  );
  const configRef = useRef(config);
  const stateRef = useRef(state);
  const onLoadRef = useRef(onLoad);
  const onErrorRef = useRef(onError);
  const tRef = useRef(t);
  const assetUrlRef = useRef(resolvedAssetUrl);
  const hasAsset = Boolean(resolvedAssetUrl);
  const [status, setStatus] = useState<CanvasStatus>("loading");
  const [failure, setFailure] = useState<Error | null>(null);
  const previewKey = `${framing}:${resolvedAssetUrl}`;
  const [previousPreviewKey, setPreviousPreviewKey] = useState(previewKey);

  if (previousPreviewKey !== previewKey) {
    setPreviousPreviewKey(previewKey);
    setStatus("loading");
    setFailure(null);
  }

  useEffect(() => {
    configRef.current = config;
  }, [config]);

  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  useEffect(() => {
    onLoadRef.current = onLoad;
    onErrorRef.current = onError;
  }, [onError, onLoad]);

  useEffect(() => {
    tRef.current = t;
  }, [t]);

  useEffect(() => {
    assetUrlRef.current = resolvedAssetUrl;
  }, [resolvedAssetUrl]);

  useEffect(() => {
    let active = true;
    const canvas = canvasRef.current;
    if (!hasAsset || !assetUrlRef.current) return undefined;
    if (!canvas) return undefined;
    void import("./avatar-renderer")
      .then(({ AvatarRenderer }) => {
        if (!active || !canvas) return;
        try {
          const renderer = new AvatarRenderer({
            canvas,
            assetUrl: assetUrlRef.current,
            framing,
            onReady: () => {
              if (!active) return;
              setFailure(null);
              setStatus("ready");
              onLoadRef.current?.();
            },
            onError: (error) => {
              if (!active) return;
              setFailure(error);
              setStatus("failed");
              onErrorRef.current?.(error);
            },
          });
          if (
            configRef.current &&
            typeof configRef.current.template_id === "string"
          ) {
            renderer.setConfig(configRef.current);
          }
          renderer.setState(stateRef.current);
          rendererRef.current = renderer;
        } catch (cause) {
          const error =
            cause instanceof Error
              ? cause
              : new Error(tRef.current("avatarPreviewUnavailable"));
          setFailure(error);
          setStatus("failed");
          onErrorRef.current?.(error);
        }
      })
      .catch((cause: unknown) => {
        if (!active) return;
        const error =
          cause instanceof Error
            ? cause
            : new Error(tRef.current("avatarPreviewUnavailable"));
        setFailure(error);
        setStatus("failed");
        onErrorRef.current?.(error);
      });

    return () => {
      active = false;
      rendererRef.current?.dispose();
      rendererRef.current = null;
    };
  }, [framing, hasAsset]);

  useEffect(() => {
    if (!resolvedAssetUrl) return;
    rendererRef.current?.setAsset(resolvedAssetUrl);
  }, [resolvedAssetUrl]);

  useEffect(() => {
    if (!config || typeof config.template_id !== "string") return;
    rendererRef.current?.setConfig(config);
  }, [config]);

  useEffect(() => {
    rendererRef.current?.setState(state);
  }, [state]);

  return (
    <div
      className={`${styles.canvasFrame}${className ? ` ${className}` : ""}`}
      role="img"
      aria-label={`${fallback} ${t("avatarPreview")}`}
      data-avatar-status={resolvedAssetUrl ? status : "failed"}
      data-avatar-state={state}
      data-avatar-template={templateId}
      data-avatar-material={config?.material_theme ?? ""}
      data-avatar-eye={config?.eye_color ?? ""}
      data-avatar-expression={config?.default_expression ?? ""}
      data-avatar-strength={config?.expression_strength ?? ""}
      data-avatar-motion={config?.motion_style ?? ""}
    >
      <canvas
        ref={canvasRef}
        className={styles.canvas}
        hidden={!resolvedAssetUrl || status !== "ready"}
      />
      {resolvedAssetUrl && status === "loading" ? (
        <span className={styles.loading}>{t("avatarPreviewLoading")}</span>
      ) : null}
      <div
        className={styles.fallback}
        hidden={Boolean(resolvedAssetUrl) && status !== "failed"}
        aria-hidden="true"
      >
        {initials(fallback)}
      </div>
      {!resolvedAssetUrl || (status === "failed" && failure) ? (
        <span className={styles.previewLabel}>
          {fallback} · {t("avatarStaticPreview")}
        </span>
      ) : null}
    </div>
  );
}
