// Adapted from neobrutalism.dev (MIT), see ./LICENSE.md.
import { cva, type VariantProps } from "class-variance-authority";
import type { ComponentProps } from "react";

import { cn } from "../../lib/utils";

export const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-[var(--radius-base)] text-sm font-[700] font-[family-name:var(--arc-font-body)] cursor-pointer transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        default:
          "text-[var(--main-foreground)] bg-[var(--main)] border-[3px] border-[var(--border)] shadow-[var(--shadow)] hover:translate-x-[var(--box-shadow-x)] hover:translate-y-[var(--box-shadow-y)] hover:shadow-none",
        noShadow:
          "text-[var(--main-foreground)] bg-[var(--main)] border-[3px] border-[var(--border)]",
        neutral:
          "bg-[var(--secondary-background)] text-[var(--foreground)] border-2 border-[var(--border)] shadow-[3px_3px_0_0_var(--border)] hover:translate-x-[3px] hover:translate-y-[3px] hover:shadow-none",
        reverse:
          "text-[var(--main-foreground)] bg-[var(--main)] border-[3px] border-[var(--border)] hover:translate-x-[var(--reverse-box-shadow-x)] hover:translate-y-[var(--reverse-box-shadow-y)] hover:shadow-[var(--shadow)]",
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
