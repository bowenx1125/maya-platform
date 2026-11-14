"use client";

import { usePathname } from "next/navigation";
import { useLayoutEffect, useRef, type ReactNode, type RefObject } from "react";

export function usePageTransition(ref: RefObject<HTMLElement | null>) {
  const pathname = usePathname();
  const previousPathname = useRef(pathname);
  useLayoutEffect(() => {
    if (previousPathname.current === pathname) return;
    previousPathname.current = pathname;
    const animations = ref.current?.getAnimations?.({ subtree: true }) ?? [];
    // Restart only the existing entrance, without remounting content or focus.
    for (const animation of animations) {
      if ((animation as CSSAnimation).animationName === "page-rise") {
        animation.cancel();
        animation.play();
      }
    }
  }, [pathname, ref]);
  return pathname;
}

export function PageTransition({ children }: { children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const pathname = usePageTransition(ref);
  // Workspace shells own their content boundary; Immerse owns its stage motion.
  const workspace = /^\/(teacher|student)(\/|$)/.test(pathname);
  return workspace ? (
    children
  ) : (
    <div
      ref={ref}
      className="page-transition"
      style={{ display: "contents" }}
      data-page-transition={pathname}
    >
      {children}
    </div>
  );
}
