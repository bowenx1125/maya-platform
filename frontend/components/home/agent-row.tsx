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
        className="m-0 flex list-none snap-x snap-mandatory scroll-px-1 flex-nowrap gap-[22px] overflow-x-auto overscroll-x-contain p-0 pt-[14px] pr-1 pb-[18px] pl-1 [scrollbar-color:#111_transparent] [scrollbar-width:thin] [&>li]:w-[150px] [&>li]:min-h-0 [&>li]:flex-none [&>li]:snap-start [&>li]:rounded-[12px] [&>li]:border-0 [&>li]:bg-transparent [&>li]:p-0 [&>li]:shadow-none [&>li]:transition-none [&>li:hover]:translate-y-0 [&>li:focus-within]:translate-y-0 [&>li>a]:rounded-[12px] [&>li>a]:shadow-[5px_5px_0_#111] [&>li>a]:transition-transform [&>li>a]:duration-100 [&>li:hover>a]:-translate-y-[3px] [&>li:focus-within>a]:-translate-y-[3px] [&_[data-card-band]]:h-auto [&_[data-card-band]]:min-h-[61px] [&_[data-card-band]]:justify-center [&_[data-card-band]]:px-[9px] [&_[data-card-band]]:py-[7px] [&_[data-card-band]]:text-center [&_[data-card-band]_*]:text-center [&_[data-card-band]_*]:text-[16px] [&_[data-card-art]]:h-[96px] [&_[data-card-art]]:items-center [&_[data-card-art]]:border-b-0 [&_[data-card-art]>*]:h-[100px] [&_[data-card-art]]:overflow-hidden [&_[data-card-art]]:![background-image:repeating-conic-gradient(from_0deg,#fff6_0_10deg,transparent_10deg_20deg)] [&_[data-card-strip]]:gap-[5px] [&_[data-card-strip]]:px-[9px] [&_[data-card-strip]]:py-[7px] [&_[data-card-footer]]:hidden motion-reduce:[&>li>a]:transition-none motion-reduce:[&>li:hover>a]:translate-y-0 motion-reduce:[&>li:focus-within>a]:translate-y-0"
      >
        {children}
      </ul>
    </div>
  );
}
