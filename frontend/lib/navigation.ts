const DEFAULT_PLATFORM_ORIGIN = "http://localhost:8080";
const HTTP_PROTOCOLS = new Set(["http:", "https:"]);
const CONTROL_CHARACTERS = /[\u0000-\u001f\u007f-\u009f]/u;
const BACKSLASH_OR_ENCODED_BACKSLASH = /\\|%5c/i;
const ABSOLUTE_SCHEME = /^[a-z][a-z\d+.-]*:/i;
const PLATFORM_ORIGIN =
  typeof window !== "undefined"
    ? window.location.origin
    : DEFAULT_PLATFORM_ORIGIN;

/**
 * Return the origin that owns the platform navigation surface.
 *
 * The browser origin is captured as the trusted base, never from the value
 * supplied in the `next` query parameter. The fallback only applies during
 * server rendering and tests, where no browser location exists.
 */
function platformOrigin(): URL | null {
  try {
    const parsed = new URL(PLATFORM_ORIGIN);
    return HTTP_PROTOCOLS.has(parsed.protocol) &&
      !parsed.username &&
      !parsed.password
      ? parsed
      : null;
  } catch {
    return null;
  }
}

function containsUnsafeNavigationCharacters(value: string): boolean {
  return (
    CONTROL_CHARACTERS.test(value) || BACKSLASH_OR_ENCODED_BACKSLASH.test(value)
  );
}

/**
 * Convert a requested post-login target to a same-origin path.
 *
 * URL parsing is deliberately performed against a fixed, trusted platform
 * origin. The returned value contains only pathname, search and hash, so a
 * caller cannot accidentally forward credentials, host, or URL protocol.
 */
export function sanitizeNextPath(
  requested: string | null | undefined,
): string | null {
  if (!requested || containsUnsafeNavigationCharacters(requested)) return null;

  let decoded: string;
  try {
    // URLSearchParams normally performs one decode already. Decoding once more
    // lets this boundary reject encoded controls/backslashes when called by a
    // different router or directly in a test.
    decoded = decodeURIComponent(requested);
  } catch {
    return null;
  }
  if (containsUnsafeNavigationCharacters(decoded)) return null;

  const base = platformOrigin();
  if (!base) return null;

  // A protocol-relative target must never be allowed to select another host.
  // Backslashes are rejected above because WHATWG URL normalizes them as `/`.
  if (decoded.startsWith("//")) return null;

  const isAbsolute = ABSOLUTE_SCHEME.test(decoded);
  if (!isAbsolute && !decoded.startsWith("/")) return null;

  let parsed: URL;
  try {
    parsed = new URL(decoded, base);
  } catch {
    return null;
  }

  if (
    !HTTP_PROTOCOLS.has(parsed.protocol) ||
    parsed.origin !== base.origin ||
    parsed.username ||
    parsed.password
  ) {
    return null;
  }

  return `${parsed.pathname}${parsed.search}${parsed.hash}` || "/";
}
