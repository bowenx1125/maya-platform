// Adapted from neobrutalism.dev (MIT), see ./LICENSE.md.
import { cva, type VariantProps } from "class-variance-authority";
import type { ComponentProps } from "react";

import { cn } from "../../lib/utils";

/**
 * DESIGN-RULES L28/L44-49 press motion for every pressable button: rest
 * shadow 0 6px 0, hover lifts 2px, press sinks 6px and the shadow goes to 0
 * (80ms press, 150ms ui, --ease). Reduced motion keeps only colour changes.
 */
export const PRESS_MOTION =
  "shadow-[0_6px_0_#111] transition-[translate,box-shadow,background-color,color] duration-150 ease-[cubic-bezier(.2,.8,.2,1)] hover:-translate-y-0.5 active:translate-y-1.5 active:shadow-none active:duration-[80ms] motion-reduce:transition-colors motion-reduce:hover:translate-y-0 motion-reduce:active:translate-y-0 motion-reduce:active:shadow-[0_6px_0_#111]";

/**
 * DESIGN-RULES L44-49 for icon and ghost buttons: no shadow and no lift;
 * a 2px #111 border shows on hover (rest colour is the button's own). Reduced motion keeps the colour change only.
 */
export const ICON_MOTION =
  "shadow-none border-2 transition-[border-color,background-color,color] duration-150 ease-[cubic-bezier(.2,.8,.2,1)] hover:border-[#111] motion-reduce:transition-colors";

/**
 * Debates final mock F `.bt.ld`: while aria-busy the control sinks
 * (translate 3px 4px), hard shadow goes to 0, and a yellow L→R fill runs.
 * Neutral / white buttons use this. Pair with a spinner beside the existing
 * label; no hover/press motion while busy. Reduced motion: no fill/spinner.
 */
export const BUSY_MOTION =
  "aria-busy:cursor-progress aria-busy:translate-x-[3px] aria-busy:translate-y-1 aria-busy:border-[#111] aria-busy:text-[#111] aria-busy:shadow-[0_0_0_#111] aria-busy:bg-[linear-gradient(90deg,#FFE14D_var(--p,0%),#fff_0)] aria-busy:animate-debate-fill aria-busy:opacity-100 aria-busy:hover:translate-x-[3px] aria-busy:hover:translate-y-1 aria-busy:active:translate-x-[3px] aria-busy:active:translate-y-1 aria-busy:active:shadow-[0_0_0_#111] disabled:aria-busy:opacity-100 motion-reduce:aria-busy:animate-none motion-reduce:aria-busy:[&_.spinner]:animate-none motion-reduce:aria-busy:[&_svg.animate-spin]:animate-none";

/**
 * F `.bt.pri.ld`: same sunk + fill treatment for pink primary buttons
 * (#FF4D8D → #FFD1E1).
 */
export const BUSY_MOTION_PRIMARY =
  "aria-busy:cursor-progress aria-busy:translate-x-[3px] aria-busy:translate-y-1 aria-busy:border-[#111] aria-busy:text-[#111] aria-busy:shadow-[0_0_0_#111] aria-busy:bg-[linear-gradient(90deg,#FF4D8D_var(--p,0%),#FFD1E1_0)] aria-busy:animate-debate-fill aria-busy:opacity-100 aria-busy:hover:translate-x-[3px] aria-busy:hover:translate-y-1 aria-busy:active:translate-x-[3px] aria-busy:active:translate-y-1 aria-busy:active:shadow-[0_0_0_#111] disabled:aria-busy:opacity-100 motion-reduce:aria-busy:animate-none motion-reduce:aria-busy:[&_.spinner]:animate-none motion-reduce:aria-busy:[&_svg.animate-spin]:animate-none";

export const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-[var(--radius-base)] text-sm font-[700] font-[family-name:var(--arc-font-body)] cursor-pointer transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        default: `text-[var(--main-foreground)] bg-[var(--main)] border-[3px] border-[var(--border)] ${PRESS_MOTION} ${BUSY_MOTION_PRIMARY}`,
        noShadow: `text-[var(--main-foreground)] bg-[var(--main)] border-[3px] border-[var(--border)] ${BUSY_MOTION_PRIMARY}`,
        neutral: `bg-[var(--secondary-background)] text-[var(--foreground)] border-2 border-[var(--border)] ${PRESS_MOTION} ${BUSY_MOTION}`,
        reverse: `text-[var(--main-foreground)] bg-[var(--main)] border-[3px] border-[var(--border)] ${PRESS_MOTION} ${BUSY_MOTION_PRIMARY}`,
        ghost: `bg-transparent text-[var(--foreground)] border-transparent ${ICON_MOTION}`,
      },
      size: {
        default: "h-10 px-4 py-2",
        sm: "h-9 px-3",
        lg: "h-11 px-8",
        icon: "size-10",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  },
);

export function Button({
  className,
  variant,
  size,
  type = "button",
  busy,
  disabled,
  "aria-busy": ariaBusyProp,
  ...props
}: ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & {
    /** F busy: sinks, fills, and sets aria-busy. Callers keep their own spinner/label. */
    busy?: boolean;
  }) {
  const ariaBusy = busy || ariaBusyProp || undefined;
  return (
    <button
      type={type}
      data-slot="button"
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
      disabled={Boolean(disabled || busy) || undefined}
      aria-busy={ariaBusy || undefined}
    />
  );
}
