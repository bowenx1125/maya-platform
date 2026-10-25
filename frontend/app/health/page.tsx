"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { useT } from "../../lib/i18n";
import {
  classifyBackendFailure,
  classifyBackendResponse,
  publicRuntime,
  type ServiceProbe,
} from "../../lib/runtime";
import type { Translator } from "../../lib/i18n";

export default function HealthPage() {
  const t = useT();
  const checking: ServiceProbe = {
    state: "checking",
    detail: t("checkingApiBoundary"),
  };
  const [backend, setBackend] = useState<ServiceProbe>(checking);

  const requestBackend = useCallback(async (): Promise<ServiceProbe> => {
    try {
      const response = await fetch("/api/v1/auth/me", { cache: "no-store" });
      return classifyBackendResponse(response.status);
    } catch (error) {
      return classifyBackendFailure(error);
    }
  }, []);

  const probeBackend = useCallback(() => {
    setBackend({
      state: "checking",
      detail: t("checkingApiBoundary"),
    });
    void requestBackend().then(setBackend);
  }, [requestBackend, t]);

  useEffect(() => {
    let active = true;
    void requestBackend().then((result) => {
      if (active) {
        setBackend(result);
      }
    });

    return () => {
      active = false;
    };
  }, [requestBackend]);

  return (
    <main className="shell health-shell">
      <header className="page-header">
        <div>
          <div className="eyebrow">{t("runtimeEnvironment")}</div>
          <h1>{t("runtimeHealth")}</h1>
          <p className="lede">{t("runtimeHealthLede")}</p>
        </div>
        <Link className="text-link" href="/">
          {t("backToHome")}
        </Link>
      </header>

      <section className="status-grid" aria-label={t("serviceStatus")}>
        <StatusCard
          label={t("gateway")}
          state="ready"
          detail={t("gatewayDetail")}
        />
        <StatusCard
          label={t("frontend")}
          state="ready"
          detail={t("frontendDetail")}
        />
        <StatusCard
          label={t("backendApi")}
          {...backend}
          detail={localizedProbeDetail(backend, t)}
        />
      </section>

      <section className="environment-card" aria-labelledby="environment-title">
        <div className="card-heading">
          <div>
            <div className="eyebrow">{t("nonSecretBuildContext")}</div>
            <h2 id="environment-title">{t("environment")}</h2>
          </div>
          <button
            className="secondary-action"
            type="button"
            onClick={() => void probeBackend()}
          >
            {t("checkAgain")}
          </button>
        </div>
        <dl className="environment-list">
          <div>
            <dt>{t("runtimeMode")}</dt>
            <dd>{publicRuntime.mode}</dd>
          </div>
          <div>
            <dt>{t("buildMarker")}</dt>
            <dd>{publicRuntime.build}</dd>
          </div>
          <div>
            <dt>{t("browserApiBoundary")}</dt>
            <dd>{t("sameOriginApi")}</dd>
          </div>
          <div>
            <dt>{t("readinessRule")}</dt>
            <dd>{t("readinessRuleDetail")}</dd>
          </div>
        </dl>
      </section>
    </main>
  );
}

function StatusCard({
  label,
  state,
  detail,
}: ServiceProbe & { label: string }) {
  const t = useT();
  return (
    <article className={`status-card status-${state}`}>
      <div className="status-card-topline">
        <span className="status-dot" aria-hidden="true" />
        <span>{label}</span>
      </div>
      <strong>
        {state === "ready"
          ? t("ready")
          : state === "checking"
            ? t("checking")
            : t("unavailable")}
      </strong>
      <p>{detail}</p>
    </article>
  );
}

function localizedProbeDetail(probe: ServiceProbe, t: Translator): string {
  if (probe.state === "checking") return t("checkingApiBoundary");
  if (probe.detail === "Platform API is reachable.") {
    return t("backendReachable");
  }
  if (probe.detail === "The platform API could not be reached.") {
    return t("backendUnreachable");
  }
  const status = probe.detail.match(/^Platform API returned HTTP (\d+)\.$/);
  return status ? t("httpError", { status: status[1] }) : probe.detail;
}
