import { PRESS_MOTION } from "./ui/button";
import { cn } from "../lib/utils";

/*
 * Agent Create/Edit chrome, ported 1:1 from the approved mockup
 * (proposals/12-agents/final-create-edit/src/fin.mjs: WB + OPT.A + R2 + CMP,
 * layout O2, Voices V2). Option A "Sticker Board": solid colour cards with a
 * tilted tab label sitting on the top edge.
 */

/** Card colours, option A. */
export const AGENT_CARD_COLOR = {
  name: "bg-[#A3E635]",
  markdown: "bg-white",
  brainform: "bg-[#67E8F9]",
  avatar: "bg-[#FDBA74]",
  voices: "bg-[#FF4D8D]",
} as const;

const CARD =
  "relative m-0 min-w-0 rounded-[12px] border-[3px] border-[#111] text-[#111] " +
  // header: no rule, tab label absolutely positioned on the card's top edge
  "[&>.section-card-header]:m-0 [&>.section-card-header]:flex [&>.section-card-header]:min-h-[10px] [&>.section-card-header]:flex-row [&>.section-card-header]:flex-nowrap [&>.section-card-header]:items-center [&>.section-card-header]:justify-between [&>.section-card-header]:gap-[18px] [&>.section-card-header]:border-0 [&>.section-card-header]:p-0 " +
  "[&>.section-card-header>div:last-child]:flex [&>.section-card-header>div:last-child]:items-center [&>.section-card-header>div:last-child]:gap-2.5 " +
  "[&>.section-card-header_h2]:absolute [&>.section-card-header_h2]:-top-5 [&>.section-card-header_h2]:left-[18px] [&>.section-card-header_h2]:m-0 [&>.section-card-header_h2]:inline-block [&>.section-card-header_h2]:-rotate-1 [&>.section-card-header_h2]:border-[3px] [&>.section-card-header_h2]:border-[#111] [&>.section-card-header_h2]:bg-white [&>.section-card-header_h2]:px-4 [&>.section-card-header_h2]:py-0.5 [&>.section-card-header_h2]:font-display [&>.section-card-header_h2]:text-[22px] [&>.section-card-header_h2]:leading-[1.35] [&>.section-card-header_h2]:font-extrabold [&>.section-card-header_h2]:tracking-normal [&>.section-card-header_h2]:text-[#111] [&>.section-card-header_h2]:[background-image:linear-gradient(90deg,#FFE14D_0_8px,transparent_8px_calc(100%-8px),#FFE14D_calc(100%-8px))]";

/** A Create/Edit card. compact: the auto-shrunk empty Brainform / Voices. */
export function agentCard(
  color: keyof typeof AGENT_CARD_COLOR,
  compact = false,
) {
  return cn(
    CARD,
    AGENT_CARD_COLOR[color],
    compact
      ? "px-[18px] pt-[26px] pb-4 shadow-[5px_5px_0_#111] [&>.section-card-header]:mb-2"
      : "px-[22px] pt-[30px] pb-[22px] shadow-[8px_8px_0_#111] [&>.section-card-header]:mb-3.5",
  );
}

/** Shared "+ New" (Button default, R2). */
export const AGENT_NEW_BUTTON = `m-0 inline-flex h-10 w-auto shrink-0 cursor-pointer items-center gap-1.5 rounded-[10px] border-[3px] border-[#111] bg-[#FF4D8D] px-3.5 py-0 font-body text-sm leading-none font-bold whitespace-nowrap text-[#111] disabled:pointer-events-none disabled:opacity-50 [&_svg]:size-4 [&_svg]:stroke-3 ${PRESS_MOTION}`;

/** Shared 40px icon button (Button neutral size=icon, R2). */
export const AGENT_ICON_BUTTON =
  "m-0 inline-grid size-10 min-h-0 shrink-0 cursor-pointer place-items-center rounded-[10px] border-2 border-[#111] bg-white p-0 text-[#111] shadow-[3px_3px_0_#111] hover:translate-x-[3px] hover:translate-y-[3px] hover:shadow-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 [&_svg]:size-[18px] [&_svg]:stroke-[2.25]";

/** Page body (.pg) and banner (.ph). */
export const AGENT_PAGE =
  "box-border w-full max-w-[1180px] px-14 pt-11 pb-[120px] font-body text-[#111] max-[767px]:px-4 max-[767px]:pt-6 max-[767px]:pb-[140px]";
export const AGENT_BANNER =
  "mb-9 flex items-center gap-4 rounded-[16px] border-[3px] border-[#111] bg-[#FFF7CC] px-7 py-[26px] shadow-[0_0_0_3px_#FDBA74,8px_8px_0_3px_#111] [background-image:repeating-conic-gradient(from_0deg_at_92%_100%,#FFE14D55_0_8deg,transparent_8deg_16deg)] max-[767px]:mb-6 max-[767px]:flex-wrap max-[767px]:gap-2.5 max-[767px]:p-[18px]";
export const AGENT_BANNER_TITLE =
  "m-0 min-w-0 flex-1 font-display text-[52px] leading-[1.1] font-extrabold tracking-normal text-[#111] max-[767px]:order-[-1] max-[767px]:basis-full max-[767px]:text-[34px]";
/** List-card hover lift (DESIGN-RULES: -2px, --dur-ui 150ms, --ease); keeps the --r tilt; none under reduced motion. */
export const LIST_CARD_LIFT =
  "[transform:translateY(var(--card-lift,0px))_rotate(var(--r,0deg))] transition-transform duration-150 ease-[cubic-bezier(.2,.8,.2,1)] hover:[--card-lift:-2px] motion-reduce:hover:[--card-lift:0px]";
