import { cn } from "../../lib/utils";

/*
 * Debates chrome, ported from the approved final mockup
 * (proposals/03-debates-final: option F "Ribbon Index", list merged with E's
 * dashed tear lines). Flat outline pill buttons; pink only on the primary.
 */

/** F `.bt`: flat outline pill, icon + text. */
export const DEBATE_BUTTON =
  "m-0 inline-flex h-auto w-auto shrink-0 cursor-pointer items-center gap-[7px] rounded-full border-2 border-[#111] bg-white py-[7px] pr-[15px] pl-[11px] font-body text-sm leading-[normal] font-bold whitespace-nowrap text-[#111] no-underline shadow-none transition-transform duration-[80ms] hover:bg-[#F1F7FF] disabled:cursor-default disabled:border-[#D6D3D1] disabled:bg-[#FAFAF9] disabled:text-[#A8A29E] disabled:opacity-100 [&_svg]:flex-none";

/**
 * F `.bt.pri`: the single pink primary action. Applied on top of the shared
 * Button's default variant, so the site-wide shadow and hover/press motion
 * come from the shared Button (not the mock's `0 4px 0`).
 */
export const DEBATE_PRIMARY =
  "h-auto w-auto shrink-0 gap-[7px] rounded-full border-2 border-[#111] bg-[#FF4D8D] py-[7px] pr-[15px] pl-[11px] font-body text-sm leading-[normal] font-bold text-[#111] no-underline [&_svg]:flex-none";

/** F `.bt.ld`: a busy button keeps its label, sinks and fills. */
export const DEBATE_BUSY =
  "aria-busy:cursor-progress aria-busy:translate-y-[2px] aria-busy:border-[#111] aria-busy:text-[#111] aria-busy:shadow-none aria-busy:bg-[linear-gradient(90deg,#FFE14D_var(--p,0%),#fff_0)] aria-busy:animate-debate-fill motion-reduce:aria-busy:animate-none";

/** List row action (`.ticket .acts .bt`). */
export const DEBATE_ROW_BUTTON = cn(
  DEBATE_BUTTON,
  DEBATE_BUSY,
  "py-1 pr-3 pl-[9px] text-[13px] leading-[normal] disabled:pointer-events-none",
);

/** F status pills (`.tag`). */
export const DEBATE_TAG =
  "inline-flex items-center gap-1.5 rounded-full border-2 border-[#111] bg-white px-3 py-[3px] font-body text-xs leading-[normal] font-extrabold whitespace-nowrap text-[#111] [&>span[aria-hidden]]:hidden";
export const DEBATE_TAG_TONE = {
  completed: "bg-white",
  running: "bg-[#22C55E]",
  thinking: "bg-[#FACC15]",
  ready: "bg-[#A7F3D0]",
  stalled: "bg-[#EF4444] text-white",
} as const;

/** Ribbon colours, cycled down the list. */
export const RIBBON_COLORS = [
  "#A3E635",
  "#67E8F9",
  "#FDBA74",
  "#FFE14D",
  "#FF8FB5",
] as const;

/** Page body (`.wrap .in`). */
export const DEBATE_PAGE =
  "mx-auto box-border w-full max-w-[1100px] font-body text-[#111]";

/** `.lh h1`: the white pill title with the cyan offset. */
export const DEBATE_TITLE =
  "m-0 rounded-full border-[2.5px] border-[#111] bg-white px-[22px] py-1 font-display text-[34px] leading-[normal] font-extrabold tracking-normal text-[#111] shadow-[4px_5px_0_#67E8F9] max-[600px]:text-2xl";
