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

/** Step HUD: one pip per step, the current one filled. */
export function GuideHud({
  total,
  index,
  label,
}: {
  total: number;
  index: number;
  label: ReactNode;
}) {
  return (
    <span className="flex items-center gap-2">
      <ol className="m-0 flex list-none gap-1.5 p-0" aria-hidden="true">
        {Array.from({ length: total }, (_, at) => (
          <li
            key={at}
            data-state={at === index ? "now" : at < index ? "done" : "todo"}
            className={cn(
              "h-2.5 w-4 rounded-full border-2 border-border",
              at === index
                ? "w-6 bg-main"
                : at < index
                  ? "bg-ink"
                  : "bg-surface",
            )}
          />
        ))}
      </ol>
      <span className="text-xs font-bold text-arc-muted">{label}</span>
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
        "grid w-[min(560px,calc(100vw-24px))] grid-cols-[168px_1fr] gap-x-5 gap-y-3 rounded-arc border-[3px] border-border bg-surface p-5 font-body text-ink shadow-arc max-[680px]:grid-cols-[96px_1fr] max-[680px]:gap-x-3 max-[680px]:p-4",
        className,
      )}
    >
      {pointer}
      <GuidePortrait className="row-span-2" />
      <h2
        id={titleId}
        className="m-0 self-end font-display text-2xl font-extrabold leading-tight max-[680px]:text-xl"
      >
        {title}
      </h2>
      <p id={bodyId} className="m-0 self-start text-[15px] leading-normal">
        {body}
      </p>
      <div className="col-span-2 flex flex-wrap items-center gap-2.5">
        {hud}
        <span className="ml-auto flex items-center gap-2">{actions}</span>
      </div>
    </div>
  );
});
