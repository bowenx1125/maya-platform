import Link from "next/link";

import { cn } from "../lib/utils";
import { MascotFigure, type MascotId } from "./academy/mascots";
import type { AcademyMood } from "./academy/mood";

/*
 * A whole-page stop (sign in first, no access, no such page) in the sign-in
 * page's look (proposal 38 v3): the sunburst and lime stage, one scholar
 * whose face matches the news, and the taped card with the heading as its
 * speech bubble.
 */
export function StatusScreen({
  eyebrow,
  title,
  body,
  action,
  href,
  primary = true,
  mascot,
  mood,
  alert = false,
}: {
  eyebrow: string;
  title: string;
  body?: string;
  action: string;
  href: string;
  /** Pink key for the way forward; white for a way back. */
  primary?: boolean;
  mascot: MascotId;
  mood: AcademyMood;
  alert?: boolean;
}) {
  return (
    <main className="relative grid min-h-screen place-items-center overflow-hidden bg-[#FFF7CC] bg-[repeating-conic-gradient(from_0deg_at_30%_78%,#FFE14D_0_7deg,#FFF7CC_7deg_14deg)] px-6 py-16 text-[#111] max-[767px]:px-4 max-[767px]:pt-10 max-[767px]:pb-[140px]">
      <div
        aria-hidden="true"
        className="absolute right-0 bottom-0 left-0 h-[110px] border-t-[8px] border-[#111] bg-[#A3E635] bg-[repeating-linear-gradient(90deg,#0000_0_40px,#0001_40px_80px)] max-[767px]:h-[72px]"
      />
      <MascotFigure
        id={mascot}
        mood={mood}
        className="absolute bottom-[86px] left-[max(24px,calc(50%-560px))] h-[260px] w-auto -rotate-3 drop-shadow-[6px_6px_0_#1113] max-[767px]:bottom-[52px] max-[767px]:left-4 max-[767px]:h-[140px]"
      />
      <section
        role={alert ? "alert" : undefined}
        className="relative w-full max-w-[560px] rotate-[1.5deg] rounded-[24px] border-[5px] border-[#111] bg-white px-9 pt-[88px] pb-9 shadow-[14px_14px_0_#111] max-[767px]:rotate-0 max-[767px]:px-5 max-[767px]:pt-20"
      >
        <span
          aria-hidden="true"
          className="absolute -top-4 right-10 h-8 w-28 rotate-6 border-[3px] border-[#111] bg-[#67E8F9cc]"
        />
        <div className="absolute -top-12 -left-10 max-[767px]:-top-10 max-[767px]:-left-1">
          <p className="m-0 mb-2 ml-3 w-max -rotate-3 border-[3px] border-[#111] bg-white bg-[linear-gradient(90deg,#A3E635_0_10px,transparent_10px_calc(100%-10px),#A3E635_calc(100%-10px))] px-4 py-0.5 font-body text-xs font-extrabold tracking-[.16em] uppercase">
            {eyebrow}
          </p>
          <h1 className="relative m-0 -rotate-[4deg] rounded-[26px] border-[5px] border-[#111] bg-[#FFE14D] px-6 py-3 font-display text-[40px] leading-none font-extrabold shadow-[8px_8px_0_#111] after:absolute after:-bottom-[24px] after:left-10 after:h-0 after:w-0 after:border-t-[24px] after:border-r-[24px] after:border-t-[#111] after:border-r-transparent after:content-[''] max-[767px]:text-[28px]">
            {title}
          </h1>
        </div>
        {body ? (
          <p className="m-0 mb-6 font-body text-base leading-relaxed font-bold text-[#333]">
            {body}
          </p>
        ) : null}
        <Link
          href={href}
          className={cn(
            "inline-flex min-h-[56px] items-center justify-center rounded-[16px] border-[4px] border-[#111] px-8 font-display text-[22px] font-extrabold text-[#111] no-underline transition-[translate,box-shadow] duration-150 hover:-translate-y-0.5 focus-visible:outline-[3px] focus-visible:outline-offset-4 focus-visible:outline-[#FF4D8D] active:translate-y-1.5 active:shadow-none motion-reduce:transition-none motion-reduce:hover:translate-y-0 motion-reduce:active:translate-y-0",
            primary
              ? "bg-[#FF4D8D] shadow-[0_8px_0_#111]"
              : "bg-white shadow-[0_6px_0_#111]",
          )}
        >
          {action}
        </Link>
      </section>
    </main>
  );
}
