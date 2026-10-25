// Adapted from neobrutalism.dev (MIT), see ./LICENSE.md.
import type { ComponentProps } from "react";

import { cn } from "../../lib/utils";

export function Input({ className, type, ...props }: ComponentProps<"input">) {
  return (
    <input
      type={type}
      data-slot="input"
      className={cn(
        "flex h-10 w-full rounded-[var(--radius-base)] border-[3px] border-[var(--border)] bg-[var(--secondary-background)] px-3 py-2 text-sm font-[500] text-[var(--foreground)] font-[family-name:var(--arc-font-body)] placeholder:text-[var(--arc-muted)] focus-visible:outline-none focus-visible:shadow-[3px_3px_0_0_var(--main)] disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
      {...props}
    />
  );
}
