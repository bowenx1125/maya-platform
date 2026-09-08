"use client";

import { useCallback, useEffect, useState } from "react";

import {
  type DemoComponent,
  type DemoComponentKey,
  type DemoRuntimeStatus,
  type PlatformApi,
} from "../lib/api";
import { type MessageKey } from "../lib/i18n";
import { useT } from "./locale";
import { useSession } from "./session-provider";

const componentLabelKeys: Record<DemoComponentKey, MessageKey> = {
  embedding: "demoEmbedding",
  llm: "demoLlm",
  tts: "demoTts",
  voice: "demoVoice",
  report: "demoReport",
};

function isDemoComponentKey(value: unknown): value is DemoComponentKey {
  return typeof value === "string" && value in componentLabelKeys;
}

function isDemoComponent(value: unknown): value is DemoComponent {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<DemoComponent>;
  return (
    isDemoComponentKey(candidate.key) &&
    (candidate.mode === "real" || candidate.mode === "mock")
  );
}

function safeStatus(value: DemoRuntimeStatus): DemoRuntimeStatus | null {
  if (
    !value ||
    !value.baseline ||
    value.baseline.system_baseline !== true ||
    value.baseline.immutable !== true ||
    !value.composition ||
    !Array.isArray(value.composition.components)
  ) {
    return null;
  }
  const components = value.composition.components.filter(isDemoComponent);
  if (components.length === 0) return null;
  return {
    ...value,
    composition: { components },
  };
}

/**
 * Small, server-truthful status strip for the local Demo. It is deliberately
 * tolerant of older test/session doubles that predate the status method.
 */
export function DemoCompositionBadge() {
  const t = useT();
  const { api } = useSession();
  const [status, setStatus] = useState<DemoRuntimeStatus | null>(null);

  const loadStatus =
    useCallback(async (): Promise<DemoRuntimeStatus | null> => {
      if (!api) return null;
      const candidate = api as PlatformApi & {
        demoStatus?: () => Promise<DemoRuntimeStatus>;
      };
      if (typeof candidate.demoStatus !== "function") return null;
      try {
        const next = await candidate.demoStatus();
        return safeStatus(next);
      } catch {
        return null;
      }
    }, [api]);

  useEffect(() => {
    let active = true;
    void loadStatus().then((next) => {
      if (active) setStatus(next);
    });
    return () => {
      active = false;
    };
  }, [loadStatus]);

  if (!status) return null;

  return (
    <section
      aria-labelledby="demo-composition-title"
      className="demo-composition-strip"
      data-testid="demo-composition"
    >
      <div className="demo-composition-heading">
        <h2 id="demo-composition-title">
          {t("demoBaseline")} {t("demoComposition")}
        </h2>
      </div>
      <div aria-label={t("demoComposition")} className="demo-composition-grid">
        {status.composition.components.map((component) => (
          <div
            className="demo-composition-item"
            data-demo-component={component.key}
            key={component.key}
          >
            <span>{t(componentLabelKeys[component.key])}</span>
            <strong
              className={`demo-mode demo-mode-${component.mode}`}
              data-demo-mode={component.mode}
            >
              {component.mode === "real" ? t("demoReal") : t("demoMock")}
            </strong>
            {component.policy_unreviewed ? (
              // A real component whose provider policy was derived locally
              // rather than reviewed. Never let it read as audited.
              <span
                className="demo-mode-unreviewed"
                data-demo-policy="unreviewed"
                title={t("demoPolicyUnreviewedHint")}
              >
                {t("demoPolicyUnreviewed")}
              </span>
            ) : null}
          </div>
        ))}
      </div>
      <div className="demo-composition-footer">
        <span
          className={`status-badge ${status.baseline.usable ? "status-good" : "status-bad"}`}
        >
          <span aria-hidden="true" />
          {status.baseline.usable
            ? t("demoBaselineReady")
            : t("demoBaselineUnavailable")}
        </span>
      </div>
    </section>
  );
}
