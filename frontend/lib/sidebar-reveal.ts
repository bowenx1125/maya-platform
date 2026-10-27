/**
 * The phone sidebar is a drawer. The onboarding tour asks the app shell to
 * open it for a step that points into it, and to close it afterwards.
 */
export const SIDEBAR_ID = "workspace-sidebar";
export const SIDEBAR_REVEAL_EVENT = "maya:sidebar-reveal";
export const SIDEBAR_MOBILE_QUERY = "(max-width: 900px)";

export function inSidebar(element: Element | null) {
  return Boolean(element?.closest(`#${SIDEBAR_ID}`));
}

export function sidebarIsDrawer() {
  return Boolean(
    typeof window !== "undefined" &&
    window.matchMedia?.(SIDEBAR_MOBILE_QUERY).matches,
  );
}

export function revealSidebar(open: boolean) {
  window.dispatchEvent(
    new CustomEvent<{ open: boolean }>(SIDEBAR_REVEAL_EVENT, {
      detail: { open },
    }),
  );
}
