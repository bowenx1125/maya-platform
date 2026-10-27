"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { cn } from "../../lib/utils";

function prefersReducedMotion() {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

/**
 * The home's Agents as one row that scrolls sideways (native swipe, trackpad
 * or Shift+wheel; snapped per card). While more cards wait to the right, the
 * row fades out on its right edge over a peek of the next card; at the end,
 * or when everything fits, the fade is gone. Tabbing to a card scrolls it in.
 * Children are the cards' `<li>`s.
 */
export function HomeAgentRow({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  const row = useRef<HTMLUListElement>(null);
  const [more, setMore] = useState(false);
  const measure = useCallback(() => {
    const node = row.current;
    if (!node) return;
    setMore(node.scrollLeft + node.clientWidth < node.scrollWidth - 2);
  }, []);
  useEffect(() => {
    measure();
    const node = row.current;
    if (!node || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, [measure, children]);

  return (
    <div
      className={cn(
        "relative min-w-0 after:pointer-events-none after:absolute after:top-0 after:right-0 after:bottom-[18px] after:w-[72px] after:bg-[linear-gradient(90deg,#DCEBFF00,#DCEBFF)] after:transition-opacity after:duration-[160ms] after:content-[''] max-[767px]:after:w-10 motion-reduce:after:transition-none",
        more ? "after:opacity-100" : "after:opacity-0",
        className,
      )}
      data-more={more ? "true" : "false"}
    >
      <ul
        ref={row}
        onScroll={measure}
        onFocus={(event) => {
          const card = (event.target as HTMLElement).closest("li");
          card?.scrollIntoView?.({
            inline: "nearest",
            block: "nearest",
            behavior: prefersReducedMotion() ? "auto" : "smooth",
          });
        }}
        className="m-0 flex list-none snap-x snap-mandatory scroll-px-1 flex-nowrap gap-[22px] overflow-x-auto overscroll-x-contain p-0 pt-[14px] pr-1 pb-[18px] pl-1 [scrollbar-color:#111_transparent] [scrollbar-width:thin] [&>li]:w-[150px] [&>li]:flex-none [&>li]:snap-start"
      >
        {children}
      </ul>
    </div>
  );
}
