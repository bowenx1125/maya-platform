"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import {
  classifyBackendFailure,
  classifyBackendResponse,
  publicRuntime,
  type ServiceProbe,
} from "../../lib/runtime";

const checking: ServiceProbe = {
  state: "checking",
  detail: "Checking the same-origin API boundary…",
};

export default function HealthPage() {
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
    setBackend(checking);
    void requestBackend().then(setBackend);
  }, [requestBackend]);

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
          <div className="eyebrow">MAYA · ENVIRONMENT</div>
          <h1>Runtime health</h1>
          <p className="lede">
            A small, honest view of the local platform boundary.
          </p>
        </div>
        <Link className="text-link" href="/">
          Back to home
        </Link>
      </header>

      <section className="status-grid" aria-label="Service status">
        <StatusCard
          label="Gateway"
          state="ready"
          detail="Single origin is configured on port 8080."
        />
        <StatusCard
          label="Frontend"
          state="ready"
          detail="Next.js shell is serving this page."
        />
        <StatusCard label="Backend API" {...backend} />
      </section>

      <section className="environment-card" aria-labelledby="environment-title">
        <div className="card-heading">
          <div>
            <div className="eyebrow">NON-SECRET BUILD CONTEXT</div>
            <h2 id="environment-title">Environment</h2>
          </div>
          <button
            className="secondary-action"
            type="button"
            onClick={() => void probeBackend()}
          >
            Check again
          </button>
        </div>
        <dl className="environment-list">
          <div>
            <dt>Runtime mode</dt>
            <dd>{publicRuntime.mode}</dd>
          </div>
          <div>
            <dt>Build marker</dt>
            <dd>{publicRuntime.build}</dd>
          </div>
          <div>
            <dt>Browser API boundary</dt>
            <dd>/api/v1 · same origin</dd>
          </div>
          <div>
            <dt>Readiness rule</dt>
            <dd>HTTP 200, 2xx, 401, or 403 from the platform API</dd>
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
  return (
    <article className={`status-card status-${state}`}>
      <div className="status-card-topline">
        <span className="status-dot" aria-hidden="true" />
        <span>{label}</span>
      </div>
      <strong>
        {state === "ready"
          ? "Ready"
          : state === "checking"
            ? "Checking"
            : "Unavailable"}
      </strong>
      <p>{detail}</p>
    </article>
  );
}
