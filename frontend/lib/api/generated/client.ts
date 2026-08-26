import createClient, { type Client, type Middleware } from "openapi-fetch";

import type { paths } from "./schema";

/** The generated OpenAPI client shape used by all platform API callers. */
export type PlatformClient = Client<paths>;

export interface PlatformClientOptions {
  /** Same-origin API root; the default is the frozen platform server path. */
  baseUrl?: string;
  /** CSRF token returned by /auth/login or /auth/me. */
  csrfToken?: string;
}

export interface PlatformClientHandle extends PlatformClient {
  /** Replace the in-memory token after login, refresh, or session rotation. */
  setCsrfToken(token: string | undefined): void;
}

/**
 * Create the one platform-owned HTTP client.
 *
 * Cookies are same-origin credentials and the CSRF token is attached by
 * middleware. Request and response DTOs stay generated from the frozen
 * OpenAPI document; no supplier-specific fields are introduced here.
 */
export function createPlatformClient({
  baseUrl = "/api/v1",
  csrfToken,
}: PlatformClientOptions = {}): PlatformClientHandle {
  let currentCsrfToken = csrfToken;

  const csrfMiddleware: Middleware = {
    onRequest({ request }) {
      const isLogin = new URL(request.url).pathname.endsWith("/auth/login");
      if (
        currentCsrfToken &&
        !isLogin &&
        !request.headers.has("X-CSRF-Token")
      ) {
        request.headers.set("X-CSRF-Token", currentCsrfToken);
      }
    },
  };

  const client = createClient<paths>({ baseUrl, credentials: "include" });
  client.use(csrfMiddleware);

  return Object.assign(client, {
    setCsrfToken(token: string | undefined) {
      currentCsrfToken = token;
    },
  });
}
