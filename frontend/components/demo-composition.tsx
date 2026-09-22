"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  type DemoComponent,
  type DemoComponentKey,
  type DemoRuntimeStatus,
  type ProviderSettings,
} from "../lib/api";
import { type MessageKey } from "../lib/i18n";
import { useLocale, useT } from "./locale";
import { useSession } from "./session-provider";
import { ErrorNotice } from "./ui";
import styles from "./demo-composition.module.css";

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
  const { locale } = useLocale();
  const { api, user } = useSession();
  const [status, setStatus] = useState<DemoRuntimeStatus | null>(null);
  const courseId = user?.courses?.find(
    (course) => course.role === "teacher",
  )?.course_id;
  const [settings, setSettings] = useState<ProviderSettings | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [key, setKey] = useState("");
  const [pendingComponent, setPendingComponent] =
    useState<DemoComponentKey | null>(null);
  const dialog = useRef<HTMLDialogElement>(null);

  const loadStatus =
    useCallback(async (): Promise<DemoRuntimeStatus | null> => {
      if (!api) return null;
      if (typeof api.demoStatus !== "function") return null;
      try {
        const next = await api.demoStatus();
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

  useEffect(() => {
    if (!courseId || typeof api.providerSettings !== "function") return;
    let active = true;
    void api
      .providerSettings(courseId)
      .then((value) => {
        if (active) setSettings(value);
      })
      .catch(() => {
        if (active) setSettings(null);
      });
    return () => {
      active = false;
    };
  }, [api, courseId]);

  async function change(
    component: DemoComponentKey | null,
    mode?: "real" | "mock",
    apiKey?: string,
  ) {
    if (!courseId || !settings) return;
    if (mode === "real" && !settings.credential_ready && !apiKey) {
      setPendingComponent(component);
      dialog.current?.showModal();
      return;
    }
    setBusy(true);
    setError(null);
    try {
      setSettings(
        await api.updateProviderSettings(courseId, {
          expected_revision: settings.revision,
          component,
          mode: mode ?? null,
          ...(apiKey ? { api_key: apiKey } : {}),
        }),
      );
      setStatus(await loadStatus());
      setKey("");
      dialog.current?.close();
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(false);
    }
  }

  async function check() {
    if (!courseId || busy) return;
    setBusy(true);
    setError(null);
    try {
      let current = await api.providerSettings(courseId);
      setSettings(current);
      const pending = current.components.filter(
        (item) => item.switchable && item.status !== "ready",
      );
      const realCount = pending.filter((item) => item.mode === "real").length;
      if (
        realCount &&
        !window.confirm(
          locale === "zh"
            ? `Check 将发送最多 ${realCount} 次公开测试请求，可能计费。继续？`
            : `Check sends up to ${realCount} public test requests and may incur charges. Continue?`,
        )
      )
        return;
      for (const item of pending) {
        current = await api.checkProvider(courseId, item.key, {
          expected_revision: current.revision,
          request_id: crypto.randomUUID(),
          confirm_real_call: item.mode === "real",
        });
        setSettings(current);
        const result = current.components.find(
          (value) => value.key === item.key,
        );
        if (result?.status === "failed") {
          if (
            ["provider_key_required", "provider_auth_failed"].includes(
              result.safe_error_code ?? "",
            )
          ) {
            setPendingComponent(null);
            dialog.current?.showModal();
          }
          break;
        }
      }
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(false);
    }
  }

  if (!status) return null;

  return (
    <section
      aria-labelledby="demo-composition-title"
      className={`section-card ${styles.panel}`}
      data-testid="demo-composition"
    >
      <div className="section-card-header">
        <h2 id="demo-composition-title">Components</h2>
        {settings ? (
          <button
            className="text-link"
            disabled={busy}
            onClick={() => void check()}
          >
            Check
          </button>
        ) : null}
      </div>
      {error ? <ErrorNotice error={error} /> : null}
      <div aria-label={t("demoComposition")} className={styles.rows}>
        {status.composition.components.map((component) => {
          const control = settings?.components.find(
            (item) => item.key === component.key,
          );
          return (
            <div
              className={styles.row}
              data-demo-component={component.key}
              key={component.key}
            >
              <label htmlFor={`mode-${component.key}`}>
                {t(componentLabelKeys[component.key])}
              </label>
              {control ? (
                <select
                  id={`mode-${component.key}`}
                  className={styles.mode}
                  aria-label={`${t(componentLabelKeys[component.key])} mode`}
                  value={control.mode}
                  disabled={busy || !control.switchable}
                  onChange={(event) =>
                    void change(
                      component.key,
                      event.target.value as "real" | "mock",
                    )
                  }
                >
                  <option value="mock">{t("demoMock")}</option>
                  <option value="real">{t("demoReal")}</option>
                </select>
              ) : (
                <strong
                  className={`demo-mode demo-mode-${component.mode}`}
                  data-demo-mode={component.mode}
                >
                  {component.mode === "real" ? t("demoReal") : t("demoMock")}
                </strong>
              )}
              {control ? (
                <>
                  <span
                    className={styles.status}
                    role="status"
                    title={
                      control.safe_error_code ?? control.checked_at ?? undefined
                    }
                    data-check-status={control.status}
                  >
                    {control.status === "unchecked"
                      ? "—"
                      : control.status === "ready"
                        ? "Ready"
                        : control.status === "failed"
                          ? "Failed"
                          : "Deferred"}
                  </span>
                </>
              ) : null}
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
          );
        })}
      </div>
      <dialog
        ref={dialog}
        aria-labelledby="provider-key-title"
        className={styles.dialog}
        onClose={() => setKey("")}
      >
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void change(
              pendingComponent,
              pendingComponent ? "real" : undefined,
              key,
            );
          }}
        >
          <h2 id="provider-key-title">API Key</h2>
          <input
            aria-label="API Key"
            type="password"
            autoComplete="new-password"
            value={key}
            onChange={(event) => setKey(event.target.value)}
            maxLength={1024}
            required
          />
          {error ? <ErrorNotice error={error} /> : null}
          <div className={styles.actions}>
            <button
              type="button"
              className="secondary-action"
              disabled={busy}
              onClick={() => dialog.current?.close()}
            >
              {t("cancel")}
            </button>
            <button
              type="submit"
              className="primary-action"
              disabled={busy || !key.trim()}
            >
              {t("save")}
            </button>
          </div>
        </form>
      </dialog>
    </section>
  );
}
