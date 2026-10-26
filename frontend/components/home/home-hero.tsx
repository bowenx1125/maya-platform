"use client";

import type { ReactNode } from "react";

import { useT } from "../../lib/i18n";
import { AcademyMascots } from "../academy/mascots";

/**
 * The home's banner: "Welcome" with the name on a pink sticker, the four
 * scholars on their lime ground, and the Holdem felt chip peeking from behind
 * the rightmost one. The heading's text is still `homeWelcomeTitle`; the name
 * is only wrapped so it can wear the sticker. Nothing in the banner is a
 * control except the scholars (SecretDoor listens on
 * `.home-hero .academy-scholar`).
 */
export function HomeHero({
  name,
  children,
}: {
  name: string;
  /** Under the heading, in the copy column (the teacher's two counts). */
  children?: ReactNode;
}) {
  const t = useT();
  const [before, after = ""] = t("homeWelcomeTitle").split("{name}");
  return (
    <section className="home-hero relative grid min-h-[290px] grid-cols-2 items-end gap-5 rounded-[16px] border-[3px] border-ink bg-[#FFF7CC] bg-[repeating-conic-gradient(from_0deg_at_75%_100%,#FFE14D8C_0deg_8deg,transparent_8deg_16deg)] px-10 pt-10 shadow-[0_0_0_3px_#FDBA74,8px_8px_0_3px_#111] max-[880px]:min-h-0 max-[880px]:grid-cols-1 max-[880px]:px-5 max-[880px]:py-6">
      <div className="home-hero-copy min-w-0 self-center pb-10 max-[880px]:pb-0">
        <h1 className="m-0 cursor-default font-display text-[68px] leading-[1.1] font-extrabold text-ink max-[767px]:text-[40px]">
          {before}
          {/* O3's sticker: pink, inked, hard shadow, a black pointer on its
              right edge. A label, not a button: no hover, press or focus. */}
          <span className="relative mt-3.5 block w-fit max-w-full -rotate-[1.5deg] rounded-[10px] border-[3px] border-ink bg-[#FF4D8D] px-3 pb-1 text-[66px] break-words text-ink shadow-[6px_6px_0_#111] after:absolute after:top-1/2 after:-right-[13px] after:-translate-y-1/2 after:border-y-[9px] after:border-l-[11px] after:border-y-transparent after:border-l-ink after:content-[''] max-[767px]:text-[42px] max-[767px]:shadow-[4px_4px_0_#111]">
            {name}
          </span>
          {after}
        </h1>
        {children}
      </div>
      <div className="home-hero-art relative isolate self-end w-full max-w-[490px] min-w-0 justify-self-center border-b-[8px] border-ink bg-[linear-gradient(transparent_82%,#A3E635_82%)] px-5 max-[880px]:hidden [&_.academy-mascots]:relative [&_.academy-mascots]:inset-auto [&_.academy-mascots]:z-[1] [&_.academy-mascots]:m-0 [&_.academy-mascots]:block [&_.academy-mascots]:h-auto [&_.academy-mascots]:max-h-[220px] [&_.academy-mascots]:w-full">
        <span
          aria-hidden="true"
          className="pointer-events-none absolute top-[25%] right-[4%] z-0 grid aspect-square w-[16%] max-w-[76px] rotate-[10deg] place-items-center rounded-full border-[3px] border-ink bg-[repeating-conic-gradient(#16A34A_0_15deg,#15803D_15deg_30deg)] font-display text-[13px] font-extrabold whitespace-nowrap max-[1180px]:text-[10px] text-white shadow-[inset_0_0_0_6px_#fff,inset_0_0_0_9px_#FF4D8D,4px_4px_0_#111] select-none [text-shadow:1px_1px_0_#111]"
        >
          Holdem
        </span>
        <AcademyMascots label={t("academyMascotsLabel")} />
      </div>
    </section>
  );
}

/** One of the teacher's counts: a tilted colour block in the banner. */
export function HomeStat({
  value,
  label,
  tone,
}: {
  value: ReactNode;
  label: string;
  tone: "lime" | "cyan";
}) {
  return (
    <div
      className={
        "home-stat flex min-w-[120px] flex-col gap-0.5 rounded-[12px] border-[3px] border-ink px-5 py-3 text-ink shadow-[4px_4px_0_#111] max-[767px]:min-w-0 max-[767px]:flex-1 max-[767px]:px-3 max-[767px]:py-2 " +
        (tone === "lime" ? "-rotate-2 bg-[#A3E635]" : "rotate-2 bg-[#67E8F9]")
      }
    >
      <b className="font-body text-[40px] leading-none font-black max-[767px]:text-[28px]">
        {value}
      </b>
      <span className="font-body text-[13px] font-extrabold">{label}</span>
    </div>
  );
}

/** Module heading as a strip of tape: white, inked, yellow ends. */
export const HOME_TAPE_TITLE =
  "m-0 inline-block w-max -rotate-1 border-[3px] border-ink bg-white bg-[linear-gradient(90deg,#FFE14D_0_8px,transparent_8px_calc(100%-8px),#FFE14D_calc(100%-8px))] px-4 py-0.5 font-display text-[22px] leading-tight font-extrabold text-ink";

/** The home page: a column of modules on the page's blue. */
export const HOME_CLASS =
  "mayaform-home mx-auto grid w-full max-w-[1180px] gap-10 px-6 pt-6 pb-16 max-[640px]:gap-8 max-[640px]:px-3";

/** A home module: white card, neon ring, hard ink shadow, tape title on top. */
export const HOME_CARD_CLASS =
  "relative grid min-w-0 gap-3 rounded-xl border-[3px] border-ink bg-white px-5 pt-[30px] pb-5 font-body text-ink";

/** The tape title riding a module's top edge. */
export const HOME_CARD_TITLE = `${HOME_TAPE_TITLE} absolute -top-5 left-4`;
