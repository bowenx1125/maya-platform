export type ServiceProbeState = "checking" | "ready" | "unavailable";

export type ServiceProbe = {
  state: ServiceProbeState;
  detail: string;
};

export function classifyBackendResponse(status: number): ServiceProbe {
  if (status === 401 || status === 403 || (status >= 200 && status < 300)) {
    return { state: "ready", detail: "Platform API is reachable." };
  }

  return {
    state: "unavailable",
    detail: `Platform API returned HTTP ${status}.`,
  };
}

export function classifyBackendFailure(error: unknown): ServiceProbe {
  const detail =
    error instanceof Error
      ? error.message
      : "The platform API could not be reached.";
  return { state: "unavailable", detail };
}

export const publicRuntime = {
  mode: process.env.NEXT_PUBLIC_RUNTIME_MODE ?? "unknown",
  build: process.env.NEXT_PUBLIC_BUILD_SHA ?? "unreported",
  // Built "false" where the backend turns quick login off (production), so
  // the login page does not ask /auth/demo-identities for a 404 every time.
  demoQuickLogin: process.env.NEXT_PUBLIC_DEMO_QUICK_LOGIN !== "false",
};
