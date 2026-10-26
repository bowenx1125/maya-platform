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

export const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-[var(--radius-base)] text-sm font-[700] font-[family-name:var(--arc-font-body)] cursor-pointer transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        default: `text-[var(--main-foreground)] bg-[var(--main)] border-[3px] border-[var(--border)] ${PRESS_MOTION}`,
        noShadow:
          "text-[var(--main-foreground)] bg-[var(--main)] border-[3px] border-[var(--border)]",
        neutral:
          `bg-[var(--secondary-background)] text-[var(--foreground)] border-2 border-[var(--border)] ${PRESS_MOTION}`,
        reverse:
          `text-[var(--main-foreground)] bg-[var(--main)] border-[3px] border-[var(--border)] ${PRESS_MOTION}`,
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
  ...props
}: ComponentProps<"button"> & VariantProps<typeof buttonVariants>) {
  return (
    <button
      type={type}
      data-slot="button"
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  );
}
