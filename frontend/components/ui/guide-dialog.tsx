"use client";

import { forwardRef, type CSSProperties, type ReactNode } from "react";

import { cn } from "../../lib/utils";
import { MascotFigure, type MascotId } from "../academy/mascots";

/** The 168px gold portrait the guide speaks from (DESIGN option A). */
export function GuidePortrait({
  mascot = "wave",
  className,
}: {
  mascot?: MascotId;
  className?: string;
}) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "grid size-[168px] flex-none place-items-end justify-center overflow-hidden rounded-arc border-[3px] border-border bg-[radial-gradient(circle_at_50%_40%,#FFF3A8_0,#FFE14D_55%,#F5B700_100%)] shadow-arc-s max-[680px]:size-24",
        className,
      )}
    >
      <MascotFigure
        id={mascot}
        className="h-[150px] w-auto max-[680px]:h-[86px]"
      />
    </span>
  );
}

/** Step HUD (guide v3): one bar per step; done and current steps are pink. */
export function GuideHud({
  total,
  index,
  label,
}: {
  total: number;
  index: number;
  label?: ReactNode;
}) {
  return (
    <span className="grid gap-1">
      <ol className="m-0 flex list-none gap-[3px] p-0" aria-hidden="true">
        {Array.from({ length: total }, (_, at) => (
          <li
            key={at}
            data-state={at === index ? "now" : at < index ? "done" : "todo"}
            className={cn(
              "h-2 flex-1 rounded-[2px] border-2 border-border",
              at <= index ? "bg-[#FF4D8D]" : "bg-white",
            )}
          />
        ))}
      </ol>
      {label ? <span className="sr-only">{label}</span> : null}
    </span>
  );
}

/**
 * The guide's speech card: portrait on the left, title and words on the
 * right, the HUD and actions underneath. The tour and the home guide both
 * use it.
 */
export const GuideDialog = forwardRef<
  HTMLDivElement,
  {
    titleId: string;
    bodyId: string;
    title: ReactNode;
    body: ReactNode;
    hud?: ReactNode;
    actions: ReactNode;
    /** A pointer drawn beside the card (the tour's arrow). */
    pointer?: ReactNode;
    modal?: boolean;
    className?: string;
    style?: CSSProperties;
    side?: string;
  }
>(function GuideDialog(
  {
    titleId,
    bodyId,
    title,
    body,
    hud,
    actions,
    pointer,
    modal = true,
    className,
    style,
    side,
  },
  ref,
) {
  return (
    <div
      ref={ref}
      role="dialog"
      aria-modal={modal ? "true" : undefined}
      aria-labelledby={titleId}
      aria-describedby={bodyId}
      data-side={side}
      style={style}
      className={cn(
        "flex w-[min(600px,calc(100vw-24px))] rounded-[10px] border-[3px] border-border bg-white font-body text-ink shadow-[6px_6px_0_#111]",
        className,
      )}
    >
      {pointer}
      {/* Guide v3: a 168px pale-gold panel with the full figure. */}
      <span
        aria-hidden="true"
        className="flex w-[168px] flex-none items-end justify-center rounded-l-[7px] border-r-[3px] border-border bg-[#F3D58A] px-3.5 py-[18px] max-[680px]:w-24 max-[680px]:px-2 max-[680px]:py-3"
      >
        <MascotFigure
          id="wave"
          className="h-auto max-h-[190px] w-full drop-shadow-[3px_3px_0_#111]"
        />
      </span>
      <div className="min-w-0 flex-1 px-4 py-3.5">
        {hud}
        <h2
          id={titleId}
          className="mt-1.5 mb-1 font-display text-xl leading-tight font-extrabold"
        >
          {title}
        </h2>
        <p id={bodyId} className="m-0 mb-3 text-sm leading-normal">
          {body}
        </p>
        <div className="flex flex-wrap items-center gap-2.5">{actions}</div>
      </div>
    </div>
  );
});
