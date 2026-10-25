"use client";

import Link from "next/link";

import { useT } from "../lib/i18n";

export type GuideStep = {
  label: string;
  complete: boolean;
  href: string;
  optional?: boolean;
};

const STICKER =
  "inline-block rounded border-2 border-ink px-2 py-px font-body text-[11px] font-extrabold text-ink uppercase not-italic shadow-[2px_2px_0_#111] max-[640px]:hidden";

/**
 * The home's steps as a level map: a segmented progress bar, then one row per
 * step with a round level badge. Only the step that comes next wears the Next
 * sticker and points onward; the others show the way on hover.
 */
export function HomeGuide({ steps }: { steps: GuideStep[] }) {
  const t = useT();
  const next = steps.findIndex((step) => !step.complete);
  return (
    <>
      <div
        className="hud my-3 flex gap-1 rounded-md border-[3px] border-ink bg-white p-1"
        aria-hidden="true"
      >
        {steps.map((step, index) => (
          <i
            key={step.label}
            className="relative block h-3.5 flex-1 -skew-x-[20deg] overflow-hidden rounded-xs bg-[#E5E7EB]"
          >
            {step.complete ? (
              <span
                className="absolute inset-0 origin-left animate-hud-fill bg-[#A3E635] shadow-[0_0_8px_#A3E635,0_0_2px_#65A30D] motion-reduce:animate-none"
                style={{
                  animationDelay: `${60 * steps.slice(0, index).filter((item) => item.complete).length}ms`,
                }}
              />
            ) : null}
          </i>
        ))}
      </div>
      <ol className="home-guide-list m-0 grid list-none p-0">
        {steps.map((step, index) => {
          const state = step.complete
            ? "done"
            : index === next
              ? "next"
              : "todo";
          return (
            <li key={step.label}>
              <Link
                className="home-guide-row group flex min-h-[52px] items-center gap-3 rounded-lg border-0 border-b-2 border-dashed border-[#11111133] px-3 py-2.5 font-body text-sm font-bold text-ink no-underline transition-colors duration-200 hover:bg-[#FFF7CC] focus-visible:bg-[#FFF7CC] data-[state=next]:bg-[#FFF7CC] motion-reduce:transition-none"
                href={step.href}
                data-state={state}
                aria-current={state === "next" ? "step" : undefined}
              >
                <span
                  className="home-guide-marker grid size-[34px] flex-none place-items-center rounded-full border-[3px] border-ink bg-white font-display text-sm font-extrabold shadow-[0_0_0_3px_#fff,0_0_0_5px_#FFE14D] group-data-[state=done]:bg-[#A3E635] group-data-[state=done]:shadow-[0_0_0_3px_#fff,0_0_0_5px_#A3E635]"
                  aria-hidden="true"
                >
                  {state === "next" ? "●" : state === "done" ? "✓" : index + 1}
                </span>
                <strong className="min-w-0 flex-1 font-bold group-data-[state=done]:font-semibold group-data-[state=done]:text-[#555]">
                  {step.label}
                </strong>
                {step.optional ? (
                  <small className={`${STICKER} -rotate-[4deg] bg-[#FDBA74]`}>
                    {t("guideOptional")}
                  </small>
                ) : null}
                <span
                  className={
                    state === "next"
                      ? `home-guide-state ${STICKER} bg-[#FF4D8D]`
                      : "sr-only"
                  }
                >
                  {step.complete ? t("guideDone") : t("guideNext")}
                </span>
                <span
                  className="home-guide-arrow -translate-x-1 text-ink opacity-0 transition-[opacity,translate] duration-200 ease-[cubic-bezier(0.34,1.4,0.64,1)] group-hover:translate-x-0 group-hover:opacity-100 group-focus-visible:translate-x-0 group-focus-visible:opacity-100 group-data-[state=next]:translate-x-0 group-data-[state=next]:opacity-100 motion-reduce:transition-none"
                  aria-hidden="true"
                >
                  →
                </span>
              </Link>
            </li>
          );
        })}
      </ol>
    </>
  );
}
