// Adapted from neobrutalism.dev (MIT), see ./LICENSE.md.
import { cva, type VariantProps } from "class-variance-authority";
import type { ComponentProps } from "react";

import { cn } from "../../lib/utils";

export const badgeVariants = cva(
  "inline-flex items-center justify-center rounded-[var(--radius-pill,999px)] border-2 border-[var(--border)] px-2.5 py-0.5 text-xs font-[700] w-fit whitespace-nowrap shrink-0 gap-1 font-[family-name:var(--arc-font-body)]",
  {
    variants: {
      variant: {
        default: "bg-[var(--main)] text-[var(--main-foreground)]",
        neutral: "bg-[var(--secondary-background)] text-[var(--foreground)]",
      },
    },
    defaultVariants: { variant: "default" },
  },
);

export function Badge({
  className,
  variant,
  ...props
}: ComponentProps<"span"> & VariantProps<typeof badgeVariants>) {
  return (
    <span
      data-slot="badge"
      className={cn(badgeVariants({ variant }), className)}
      {...props}
    />
  );
}
