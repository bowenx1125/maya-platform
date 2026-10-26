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

/*
 * Unified Studyform banner, approved H2 (proposals/15-studyform-banner):
 * one fixed-height box for the Agents and Teams list, create and edit pages
 * (132px, 390: 92px; 32px sides). The list carries the title and "+ New" at
 * the far right; create/edit carry Back, the title and Done.
 */
export const STUDYFORM_BANNER =
  "mb-9 box-border flex h-[132px] min-h-0 flex-nowrap items-center gap-4 rounded-[16px] border-[3px] border-[#111] bg-[#FFF7CC] px-8 py-0 shadow-[0_0_0_3px_#FDBA74,8px_8px_0_3px_#111] [background-image:repeating-conic-gradient(from_0deg_at_92%_100%,#FFE14D55_0_8deg,transparent_8deg_16deg)] max-[767px]:mb-6 max-[767px]:h-[92px] max-[767px]:gap-2.5 max-[767px]:px-[18px]";
/** Create/Edit banner: Back · title · Done in one row; at 390 (13-teams-final)
 * the title takes its own row and Back · Done sit on the next. */
export const STUDYFORM_BANNER_FORM =
  "max-[767px]:h-auto max-[767px]:flex-wrap max-[767px]:gap-2.5 max-[767px]:p-[18px]";
export const STUDYFORM_BANNER_TITLE =
  "m-0 min-w-0 flex-1 overflow-hidden font-display text-[52px] leading-[1.1] font-extrabold tracking-normal text-ellipsis whitespace-nowrap text-[#111] max-[767px]:text-[34px]";
/** Create/Edit title at 390: first row, full width, 34px. */
export const STUDYFORM_BANNER_FORM_TITLE =
  "max-[767px]:order-first max-[767px]:basis-full max-[767px]:text-[34px]";
/** H2 list "+ New": 52px tall, 22px sides, 17px label, 22px icon (3.5). */
export const STUDYFORM_NEW_CLASS =
  "m-0 ml-auto box-border inline-flex h-[52px] min-h-[52px] shrink-0 items-center gap-2.5 rounded-[10px] border-[3px] border-[#111] bg-[#FF4D8D] px-[22px] py-0 font-body text-[17px] leading-none font-extrabold text-[#111] no-underline shadow-[0_6px_0_#111] hover:translate-x-0 hover:translate-y-0 hover:shadow-[0_6px_0_#111] [&_svg]:size-[22px] [&_svg]:stroke-[3.5]";
