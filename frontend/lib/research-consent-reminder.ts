/**
 * Device-local reminder for the login research-consent checkbox.
 *
 * After a successful authenticated consent, this browser may restore the
 * checkbox when the same username is typed again. It is not server truth,
 * never queried over the network, and never copies between accounts.
 */

export const RESEARCH_CONSENT_REMINDER_KEY =
  "maya.learningResearchConsentReminder.v1";

export const RESEARCH_CONSENT_COPY_VERSION = "learning-data-consent-v1";

export const RESEARCH_CONSENT_PDF_HREF = `/legal/${RESEARCH_CONSENT_COPY_VERSION}.pdf`;

type ReminderMap = Record<string, string>;

function storage(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

/** Match backend ``username_key``: NFKC, strip, casefold. */
export function normalizeUsernameKey(raw: string): string {
  return raw.normalize("NFKC").trim().toLowerCase();
}

export async function hashUsernameKey(raw: string): Promise<string> {
  const key = normalizeUsernameKey(raw);
  if (!key || typeof crypto === "undefined" || !crypto.subtle) {
    return "";
  }
  const bytes = new TextEncoder().encode(key);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest))
    .map((value) => value.toString(16).padStart(2, "0"))
    .join("");
}

function readMap(): ReminderMap {
  const store = storage();
  const raw = store?.getItem(RESEARCH_CONSENT_REMINDER_KEY);
  if (!raw) return {};
  try {
    const value = JSON.parse(raw) as unknown;
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      store?.removeItem(RESEARCH_CONSENT_REMINDER_KEY);
      return {};
    }
    const next: ReminderMap = {};
    for (const [hash, version] of Object.entries(value as ReminderMap)) {
      if (
        typeof hash === "string" &&
        /^[0-9a-f]{64}$/i.test(hash) &&
        typeof version === "string" &&
        version.length > 0 &&
        version.length <= 80
      ) {
        next[hash.toLowerCase()] = version;
      }
    }
    return next;
  } catch {
    store?.removeItem(RESEARCH_CONSENT_REMINDER_KEY);
    return {};
  }
}

function writeMap(map: ReminderMap): void {
  const store = storage();
  if (!store) return;
  if (Object.keys(map).length === 0) {
    store.removeItem(RESEARCH_CONSENT_REMINDER_KEY);
    return;
  }
  store.setItem(RESEARCH_CONSENT_REMINDER_KEY, JSON.stringify(map));
}

export async function shouldRestoreResearchConsent(
  username: string,
): Promise<boolean> {
  const hash = await hashUsernameKey(username);
  if (!hash) return false;
  return readMap()[hash] === RESEARCH_CONSENT_COPY_VERSION;
}

export async function rememberResearchConsent(username: string): Promise<void> {
  const hash = await hashUsernameKey(username);
  if (!hash) return;
  const map = readMap();
  map[hash] = RESEARCH_CONSENT_COPY_VERSION;
  writeMap(map);
}

export async function forgetResearchConsent(username: string): Promise<void> {
  const hash = await hashUsernameKey(username);
  if (!hash) return;
  const map = readMap();
  if (!(hash in map)) return;
  delete map[hash];
  writeMap(map);
}
