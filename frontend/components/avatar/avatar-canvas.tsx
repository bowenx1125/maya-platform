"use client";

import { useEffect, useRef, useState } from "react";

import { EggCanvas } from "./egg-canvas";
import { useT } from "../../lib/i18n";
import { LoadingCard } from "../ui";
import type { AvatarConfig, AvatarState } from "./types";
import { avatarAssetUrlForTemplate } from "./types";

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

export function AvatarCanvas(props: AvatarCanvasProps) {
  if (props.config?.template_id === "egg")
    return (
      <div className={`w-full ${props.className ?? "aspect-square"}`}>
        <EggCanvas />
      </div>
    );
  return <LegacyAvatarCanvas {...props} />;
}

function LegacyAvatarCanvas({
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
      className={`relative grid aspect-square min-h-[260px] w-full place-items-center overflow-hidden max-[620px]:min-h-[230px]${className ? ` ${className}` : ""}`}
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
        className="block size-full"
        hidden={!resolvedAssetUrl || status !== "ready"}
      />
      {resolvedAssetUrl && status === "loading" ? (
        <span className="absolute inset-0 grid place-items-center">
          <LoadingCard size="sm" label={t("avatarPreviewLoading")} />
        </span>
      ) : null}
      <div
        className="grid aspect-square w-[min(58%,12rem)] place-items-center rounded-full border border-[rgba(35,57,72,0.14)] bg-(--accent-soft,#f6ecd3) text-[clamp(2rem,8vw,4rem)] font-[720] tracking-[0.03em] text-(--accent,#76591f) shadow-[0_1rem_2rem_rgba(74,71,65,0.16)]"
        hidden={Boolean(resolvedAssetUrl) && status !== "failed"}
        aria-hidden="true"
      >
        {initials(fallback)}
      </div>
      {!resolvedAssetUrl || (status === "failed" && failure) ? (
        <span className="absolute right-[0.8rem] bottom-[0.8rem] max-w-[calc(100%-1.6rem)] overflow-hidden text-right text-[0.77rem] leading-[1.25] font-[650] text-(--ink,#1d1d1f) [overflow-wrap:anywhere] whitespace-normal line-clamp-2">
          {fallback} · {t("avatarStaticPreview")}
        </span>
      ) : null}
    </div>
  );
}
