import { cn } from "../../lib/utils";
import { BUSY_MOTION, PRESS_MOTION } from "../ui/button";

/*
 * Debates chrome, ported from the approved final mockup
 * (proposals/03-debates-final: option F "Ribbon Index", list merged with E's
 * dashed tear lines). Flat outline pill buttons; pink only on the primary.
 */

/** F `.bt`: flat outline pill, icon + text. */
export const DEBATE_BUTTON = `m-0 inline-flex h-auto w-auto shrink-0 cursor-pointer items-center gap-[7px] rounded-full border-2 border-[#111] bg-white py-[7px] pr-[15px] pl-[11px] font-body text-sm leading-[normal] font-bold whitespace-nowrap text-[#111] no-underline hover:bg-[#F1F7FF] disabled:cursor-default disabled:border-[#D6D3D1] disabled:bg-[#FAFAF9] disabled:text-[#A8A29E] disabled:opacity-100 disabled:shadow-none [&_svg]:flex-none ${PRESS_MOTION} ${BUSY_MOTION}`;

/**
 * F `.bt.pri`: the single pink primary action. Applied on top of the shared
 * Button's default variant, so the site-wide shadow and hover/press motion
 * come from the shared Button (not the mock's `0 4px 0`).
 */
export const DEBATE_PRIMARY =
  "h-auto w-auto shrink-0 gap-[7px] rounded-full border-2 border-[#111] bg-[#FF4D8D] py-[7px] pr-[15px] pl-[11px] font-body text-sm leading-[normal] font-bold text-[#111] no-underline [&_svg]:flex-none";

/** F `.bt.ld`: a busy button keeps its label, sinks and fills. */
export const DEBATE_BUSY = BUSY_MOTION;

/** List row action (`.ticket .acts .bt`). */
export const DEBATE_ROW_BUTTON = cn(
  DEBATE_BUTTON,
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
  "mx-auto box-border w-full min-w-0 max-w-[1100px] font-body text-[#111]";

/** `.lh h1`: the white pill title with the cyan offset. */
export const DEBATE_TITLE =
  "m-0 rounded-full border-[2.5px] border-[#111] bg-white px-[22px] py-1 font-display text-[34px] leading-[normal] font-extrabold tracking-normal text-[#111] shadow-[4px_5px_0_#67E8F9] max-[600px]:text-2xl";

/* ---- Create page (F "create D" + F overrides) ---- */

/** `.create .card`: white rounded card, flat black drop; `--sh` tints the dot. */
export const CREATE_CARD =
  "relative mb-[22px] box-border min-w-0 rounded-[24px] border-2 border-[#111] bg-white px-[18px] pt-4 pb-[18px] text-[#111] shadow-[0_5px_0_#111] [--sh:#FFE14D]";

/** `.create .ch` with its tinted dot. */
export const CREATE_CARD_TITLE =
  "m-0 flex pb-0.5 w-fit items-center gap-2 font-display text-[17px] leading-[normal] font-bold tracking-normal text-[#111] outline-none before:size-3 before:shrink-0 before:rounded-full before:border-2 before:border-[#111] before:bg-[var(--sh)] before:content-['']";

/** `.create .ta`. */
export const CREATE_TEXTAREA =
  "mt-3 box-border block min-h-20 w-full resize-y rounded-2xl border-[2.5px] border-[#111] bg-[#F8FBFF] px-3 py-2.5 font-body text-sm leading-normal text-[#111] shadow-none outline-none placeholder:text-[#757575] focus:shadow-[4px_4px_0_#FF4D8D]";

/** `.create .seg`: the 中文/English switch with its globe. */
export const CREATE_SEG =
  "inline-flex flex-none items-center overflow-hidden rounded-full border-[2.5px] border-[#111] bg-white text-[#111] [&>svg]:mx-1.5 [&>svg]:flex-none";
export const CREATE_SEG_BUTTON =
  "m-0 h-auto min-h-0 cursor-pointer rounded-none border-0 border-l-2 border-[#111] bg-white px-2.5 py-1.5 font-body text-xs leading-[normal] font-bold whitespace-nowrap text-[#111] shadow-none aria-pressed:bg-[#FF4D8D] disabled:cursor-default disabled:opacity-60";

/** `.bt.sm2`: the small Edit / Back / Save pill on a card. */
export const CREATE_SMALL_BUTTON = cn(
  DEBATE_BUTTON,
  "py-1 pr-2.5 pl-2 text-xs leading-[normal]",
);

/** Parameter sub-card tints. */
export const CREATE_SUB_DEBATE = "[--sh:#FF8FB5]";
export const CREATE_SUB_VOICE = "[--sh:#67E8F9]";

/* ---- Preview page (F "preview D" + F overrides) ---- */

/** `.tape`: the white tale-of-the-tape card. */
export const PREVIEW_TAPE =
  "box-border min-w-0 rounded-[26px] border-2 border-[#111] bg-white p-[18px] text-[#111] shadow-[0_5px_0_#111]";

/** `.tc`: one saved turn; `--tone` is the speaker's colour. */
export const PREVIEW_TURN =
  "min-w-0 overflow-hidden rounded-[20px] border-[2.5px] border-[#111] bg-white px-3.5 py-2.5 shadow-[3px_4px_0_var(--tone)]";

/** `.tape:not(.ready) .tc:has(.say.pend)`: dashed, shimmering placeholder. */
export const PREVIEW_TURN_PENDING =
  "border-dashed shadow-none bg-[repeating-linear-gradient(110deg,#fff_0_40%,#EEF5FF_50%,#fff_60%)] bg-size-[300%_100%] animate-debate-shim motion-reduce:animate-none";

/** Speaker colours (`--tone`), by participant order. */
export const PREVIEW_TONES = ["#FFE14D", "#67E8F9", "#A3E635"] as const;
