/**
 * Sampled timings for a few key moments, sent to POST /client-metrics.
 *
 * One page load in SAMPLE_RATE is sampled; the rest record nothing, so most
 * browsers never send a request. Sampled metrics are batched and sent every
 * FLUSH_MS, at MAX_BATCH, or when the page is hidden. A failed send is
 * dropped: timings must never cost the page a retry or an error.
 */

export type ClientMetricName =
  "debate_next_to_play" | "page_first_render" | "assessment_submit";

export type ClientMetric = {
  name: ClientMetricName;
  ms: number;
  page?: string | null;
};

type Transport = (metrics: ClientMetric[]) => Promise<unknown>;

export const SAMPLE_RATE = 0.25;
const FLUSH_MS = 30_000;
const MAX_BATCH = 20;
const MAX_MS = 600_000;
const NEXT_TO_PLAY_MAX_MS = 120_000;
const ID_SEGMENT = /^(?:[0-9a-fA-F-]{8,}|[0-9]+)$/;

let sampled: boolean | null = null;
let transport: Transport | null = null;
let queue: ClientMetric[] = [];
let timer: ReturnType<typeof setTimeout> | null = null;
let hideListener = false;
let nextClickedAt: number | null = null;

function isSampled(): boolean {
  if (sampled === null) sampled = Math.random() < SAMPLE_RATE;
  return sampled;
}

/** The current page as a route template: record ids become "{id}". */
export function pageTemplate(pathname?: string): string | null {
  const path =
    pathname ??
    (typeof window === "undefined" ? undefined : window.location.pathname);
  if (!path || !path.startsWith("/")) return null;
  const template = path
    .split("/")
    .map((part) => (ID_SEGMENT.test(part) ? "{id}" : part))
    .join("/")
    .replace(/[^A-Za-z0-9/_{}[\]-]/g, "")
    .slice(0, 120);
  return template || "/";
}

export function recordClientMetric(name: ClientMetricName, ms: number): void {
  if (!isSampled() || !Number.isFinite(ms) || ms < 0) return;
  queue.push({
    name,
    ms: Math.min(Math.round(ms), MAX_MS),
    page: pageTemplate(),
  });
  if (queue.length >= MAX_BATCH) {
    flushClientMetrics();
    return;
  }
  if (timer === null) timer = setTimeout(flushClientMetrics, FLUSH_MS);
  if (!hideListener && typeof document !== "undefined") {
    hideListener = true;
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "hidden") flushClientMetrics();
    });
  }
}

export function flushClientMetrics(): void {
  if (timer !== null) {
    clearTimeout(timer);
    timer = null;
  }
  // Without a signed-in transport the batch waits; it is sent once one exists.
  if (!transport || queue.length === 0) return;
  const batch = queue.slice(0, MAX_BATCH);
  queue = queue.slice(MAX_BATCH);
  try {
    void transport(batch).catch(() => undefined);
  } catch {
    // A transport that throws before returning a promise is dropped too.
  }
  if (queue.length > 0) timer = setTimeout(flushClientMetrics, FLUSH_MS);
}

/** Set by the signed-in session; null on sign-out drops what is queued. */
export function setClientMetricsTransport(next: Transport | null): void {
  transport = next;
  if (next === null) {
    queue = [];
    return;
  }
  if (queue.length > 0) flushClientMetrics();
}

/** The controller pressed Next; the clock stops when the next speech plays. */
export function markDebateNextClicked(): void {
  nextClickedAt = performance.now();
}

export function noteDebateSpeechPlaying(): void {
  if (nextClickedAt === null) return;
  const ms = performance.now() - nextClickedAt;
  nextClickedAt = null;
  // A Next that led to a text-only turn leaves the clock running; the next
  // speech minutes later is not what this metric measures.
  if (ms <= NEXT_TO_PLAY_MAX_MS) recordClientMetric("debate_next_to_play", ms);
}

/** First contentful paint of this page load, recorded once. */
export function observeFirstRender(): void {
  if (!isSampled() || typeof PerformanceObserver === "undefined") return;
  try {
    const observer = new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        if (entry.name === "first-contentful-paint") {
          recordClientMetric("page_first_render", entry.startTime);
          observer.disconnect();
          return;
        }
      }
    });
    observer.observe({ type: "paint", buffered: true });
  } catch {
    // Browsers without paint timing simply record nothing.
  }
}

/** Tests only. */
export function resetClientMetricsForTests(sample: boolean | null): void {
  sampled = sample;
  transport = null;
  queue = [];
  nextClickedAt = null;
  if (timer !== null) clearTimeout(timer);
  timer = null;
}
