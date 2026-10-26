"use client";

import Link from "next/link";

import { useT } from "../lib/i18n";
import { IconArrowRight, IconCheck } from "./quiet-icons";

export type GuideStep = {
  label: string;
  complete: boolean;
  href: string;
};

const STICKER =
  "inline-block rounded border-2 border-ink px-2 py-px font-body text-[11px] font-extrabold text-ink uppercase not-italic shadow-[2px_2px_0_#111]";

/**
 * The home's steps as a quest map: a segmented XP bar, then one level node
 * (a keycap) per step on a track. Done nodes are stamped lime, the next one
 * is the pink keycap with the Next sticker, the rest wait in white.
 */
export function HomeGuide({ steps }: { steps: GuideStep[] }) {
  const t = useT();
  const next = steps.findIndex((step) => !step.complete);
  const done = steps.filter((step) => step.complete).length;
  return (
    <>
      <div className="hud mt-1 mb-4 flex items-center gap-2" aria-hidden="true">
        <div className="flex flex-1 gap-1 rounded-md border-[3px] border-ink bg-white p-1 shadow-[3px_3px_0_#111]">
          {steps.map((step, index) => (
            <i
              key={step.label}
              className="relative block h-3 flex-1 -skew-x-[20deg] overflow-hidden rounded-xs bg-[#E5E7EB]"
            >
              {step.complete ? (
                <span
                  className="absolute inset-0 origin-left animate-hud-fill bg-[#A3E635] motion-reduce:animate-none"
                  style={{
                    animationDelay: `${60 * steps.slice(0, index).filter((item) => item.complete).length}ms`,
                  }}
                />
              ) : null}
            </i>
          ))}
        </div>
        <span className="rounded-md border-[3px] border-ink bg-[#FFE14D] px-1.5 font-display text-xs leading-5 font-extrabold tabular-nums shadow-[2px_2px_0_#111]">
          {done}/{steps.length}
        </span>
      </div>
      <ol className="home-guide-list relative m-0 grid list-none gap-2.5 p-0">
        {steps.map((step, index) => {
          const state = step.complete
            ? "done"
            : index === next
              ? "next"
              : "todo";
          const last = index === steps.length - 1;
          return (
            <li key={step.label} className="relative">
              {last ? null : (
                <span
                  aria-hidden="true"
                  className={`absolute top-[38px] bottom-[-14px] left-[21px] w-[4px] rounded-full ${
                    step.complete
                      ? "bg-ink"
                      : "bg-[repeating-linear-gradient(#111_0_5px,transparent_5px_10px)] opacity-40"
                  }`}
                />
              )}
              <Link
                className="home-guide-row group relative flex min-h-[48px] items-center gap-3 rounded-lg border-[3px] border-transparent py-1 pr-2 pl-0.5 font-body text-sm font-bold text-ink no-underline transition-[background-color,border-color,translate,box-shadow] duration-200 hover:border-ink hover:bg-white focus-visible:border-ink focus-visible:bg-white data-[state=next]:border-ink data-[state=next]:bg-[#FFF7CC] data-[state=next]:shadow-[4px_4px_0_#111] motion-reduce:transition-none"
                href={step.href}
                data-state={state}
                aria-current={state === "next" ? "step" : undefined}
              >
                <span
                  className="home-guide-marker relative grid size-[40px] flex-none place-items-center rounded-lg border-[3px] border-ink bg-white font-display text-base font-extrabold text-[#9CA3AF] shadow-[0_4px_0_#111] group-data-[state=done]:-rotate-6 group-data-[state=done]:bg-[#A3E635] group-data-[state=done]:text-ink group-data-[state=next]:bg-[#FF4D8D] group-data-[state=next]:text-ink"
                  aria-hidden="true"
                >
                  {state === "done" ? <IconCheck size={20} /> : index + 1}
                </span>
                <strong className="min-w-0 flex-1 font-bold group-data-[state=done]:text-[#555] group-data-[state=done]:line-through group-data-[state=done]:decoration-2 group-data-[state=todo]:text-[#555]">
                  {step.label}
                </strong>
                <span
                  className={
                    state === "next"
                      ? `home-guide-state ${STICKER} rotate-[-4deg] bg-[#FF4D8D]`
                      : "sr-only"
                  }
                >
                  {step.complete ? t("guideDone") : t("guideNext")}
                </span>
                <span
                  className="home-guide-arrow hidden -translate-x-1 text-ink transition-transform duration-200 group-hover:inline-flex group-hover:translate-x-0 group-focus-visible:inline-flex group-data-[state=next]:inline-flex max-[680px]:!hidden motion-reduce:transition-none"
                  aria-hidden="true"
                >
                  <IconArrowRight size={16} />
                </span>
              </Link>
            </li>
          );
        })}
      </ol>
    </>
  );
}
