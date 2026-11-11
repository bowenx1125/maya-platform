import type { components } from "./generated/schema";
import { PlatformApiError, readErrorPayload } from "./platform";
import { tm } from "../i18n";

export type DebateDiagnostics = components["schemas"]["DebateDiagnostics"];
export type AgentDiagnostic = components["schemas"]["AgentDiagnostic"];
export type RoundDiagnostic = components["schemas"]["RoundDiagnostic"];
export type ParagraphDiagnostic = components["schemas"]["ParagraphDiagnostic"];

/** The teacher-only per-Agent diagnostics read (getDebateDiagnostics). */
export async function fetchDebateDiagnostics(
  debateId: string,
  baseUrl = "/api/v1",
): Promise<DebateDiagnostics> {
  const response = await fetch(
    `${baseUrl}/debates/${encodeURIComponent(debateId)}/diagnostics`,
    { credentials: "include" },
  );
  const text = await response.text();
  let body: unknown;
  try {
    body = text ? JSON.parse(text) : undefined;
  } catch {
    body = undefined;
  }
  if (!response.ok) {
    const payload = readErrorPayload(body);
    throw new PlatformApiError(
      response.status,
      payload?.message ?? tm("httpError", { status: response.status }),
      payload,
    );
  }
  return body as DebateDiagnostics;
}
