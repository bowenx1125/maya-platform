"use client";

import { useEffect, useRef, useState } from "react";

import { useT } from "../locale";
import type { AvatarConfig, AvatarState } from "./types";
import { AVATAR_ASSET_URL } from "./types";
import styles from "./avatar.module.css";

export type AvatarCanvasProps = {
  config: AvatarConfig;
  state?: AvatarState;
  assetUrl?: string;
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
  assetUrl = AVATAR_ASSET_URL,
  fallbackLabel,
  className,
  onLoad,
  onError,
}: AvatarCanvasProps) {
  const t = useT();
  const fallback = fallbackLabel ?? t("avatar");
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rendererRef = useRef<import("./avatar-renderer").AvatarRenderer | null>(
    null,
  );
  const configRef = useRef(config);
  const stateRef = useRef(state);
  const onLoadRef = useRef(onLoad);
  const onErrorRef = useRef(onError);
  const tRef = useRef(t);
  const [status, setStatus] = useState<CanvasStatus>("loading");
  const [failure, setFailure] = useState<Error | null>(null);

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
    let active = true;
    const canvas = canvasRef.current;
    if (!canvas) return undefined;
    setStatus("loading");
    setFailure(null);
    void import("./avatar-renderer")
      .then(({ AvatarRenderer }) => {
        if (!active || !canvas) return;
        try {
          const renderer = new AvatarRenderer({
            canvas,
            assetUrl,
            onReady: () => {
              if (!active) return;
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
          renderer.setConfig(configRef.current);
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
  }, [assetUrl]);

  useEffect(() => {
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
      data-avatar-status={status}
      data-avatar-state={state}
    >
      <canvas
        ref={canvasRef}
        className={styles.canvas}
        hidden={status === "failed"}
      />
      {status === "loading" ? (
        <span className={styles.loading}>{t("avatarPreviewLoading")}</span>
      ) : null}
      <div
        className={styles.fallback}
        hidden={status !== "failed"}
        aria-hidden="true"
      >
        {initials(fallback)}
      </div>
      {status === "failed" && failure ? (
        <span className={styles.previewLabel}>
          {fallback} · {t("avatarStaticPreview")}
        </span>
      ) : null}
    </div>
  );
}
