"use client";

import Link from "next/link";
import type { CSSProperties } from "react";

import type { TeamSummaryDto } from "../lib/api";
import { useT } from "../lib/i18n";
import { cn } from "../lib/utils";
import { MascotFigure, MASCOT_IDS, type MascotId } from "./academy/mascots";
import { AGENT_BANNER, AGENT_BANNER_TITLE, AGENT_PAGE } from "./agent-chrome";
import { AGENTS_NEW_CLASS, DeleteX, NewButton } from "./ui/agent-card";
import { IconPlus } from "./quiet-icons";

/*
 * Teams page, approved fusion F1 (proposals/13-teams-fusion/src/gen.mjs
 * listF / emptyF): the Agents sunburst banner over a grid of C polaroids
 * (tilted tape name, coloured photo well with Agent faces, "member(s) |
 * visibility" footer), or the Spotlight starter polaroid when empty.
 */

/** F1 tilt cycle (≤1.5°, card walls only). */
const TILTS = [-1.2, 0.8, -0.6, 1.2, -0.9, 0.6] as const;
/** F1 photo-well colours, in list order. */
const WELLS = [
  "#FDBA74",
  "#A3E635",
  "#67E8F9",
  "#FFB4C8",
  "#FFE14D",
  "#C4B5FD",
] as const;

/**
 * TeamSummary carries only member_count, not who the members are, so the
 * faces are picked from the team id (same hash as agentMascot).
 */
function teamFaces(id: string, count: number): MascotId[] {
  let hash = 0;
  for (const char of id) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  return Array.from(
    { length: Math.min(Math.max(count, 0), 3) },
    (_, index) => MASCOT_IDS[(hash + index) % MASCOT_IDS.length],
  );
}

function Faces({
  faces,
  more = 0,
  size,
}: {
  faces: MascotId[];
  more?: number;
  size: "card" | "starter";
}) {
  return (
    <span className="relative flex items-end justify-center" aria-hidden="true">
      {faces.map((face, index) => (
        <span
          key={index}
          style={{ zIndex: 10 - index }}
          className={cn(
            "-ml-[18px] grid shrink-0 place-items-end overflow-hidden rounded-full border-[3px] border-[#111] bg-white shadow-[2px_2px_0_#111] first:ml-0",
            size === "card"
              ? "size-[58px] max-[767px]:-ml-3 max-[767px]:size-10 max-[767px]:first:ml-0"
              : "size-[52px]",
          )}
        >
          <MascotFigure id={face} className="h-[120%] w-auto translate-y-[8%]" />
        </span>
      ))}
      {more > 0 ? (
        <span className="-ml-3.5 grid size-10 place-items-center rounded-full border-[3px] border-[#111] bg-[#FFE14D] font-body text-xs font-extrabold text-[#111] shadow-[2px_2px_0_#111] max-[767px]:size-[30px]">
          +{more}
        </span>
      ) : null}
    </span>
  );
}

const POLAROID =
  "relative box-border list-none rounded-[4px] border-[3px] border-[#111] bg-white px-3 pt-3.5 pb-3 text-[#111] shadow-[5px_5px_0_#111] [transform:rotate(var(--r,0deg))]";
const TAPE =
  "absolute -top-3 left-1/2 w-max max-w-[88%] -translate-x-1/2 -rotate-2 border-2 border-[#111] bg-[#FFE14D] px-3.5 py-0.5 text-center font-display leading-[1.15] font-extrabold text-[#111] shadow-[2px_2px_0_#111]";
const PHOTO =
  "mt-2.5 flex items-end justify-center border-[3px] border-[#111] pb-2.5";
const SUN =
  "[background:radial-gradient(circle_at_50%_50%,#FFE14D_0_24%,transparent_25%),repeating-conic-gradient(from_0deg_at_50%_50%,#FFF7CC_0_9deg,#fff_9deg_18deg)]";

function TeamPolaroid({
  team,
  index,
  href,
  deleting,
  deleteLabel,
  onDelete,
}: {
  team: TeamSummaryDto;
  index: number;
  href: string;
  deleting: boolean;
  deleteLabel: string;
  onDelete?: () => void;
}) {
  const t = useT();
  const faces = teamFaces(team.id, team.member_count);
  const isPublic = team.visibility === "public";
  return (
    <li
      className={cn(POLAROID, "w-[200px] max-[767px]:w-[calc(50%-10px)]")}
      style={{ "--r": `${TILTS[index % TILTS.length]}deg` } as CSSProperties}
    >
      <Link href={href} className="block text-[#111] no-underline">
        <span className={cn(TAPE, "text-[13px]")}>{team.display_name}</span>
        <span
          className={cn(PHOTO, "h-[130px] max-[767px]:h-[100px]")}
          style={{ backgroundColor: WELLS[index % WELLS.length] }}
        >
          <Faces
            faces={faces}
            more={Math.max(team.member_count - 3, 0)}
            size="card"
          />
        </span>
        <span className="mt-2.5 flex">
          <span className="inline-flex overflow-hidden rounded-[6px] border-2 border-[#111] font-body text-[11px] font-extrabold shadow-[2px_2px_0_#111]">
            <span className="bg-white px-2 py-px">
              {t("memberCountShort", { count: team.member_count })}
            </span>
            <span
              className={cn(
                "border-l-2 border-[#111] px-2 py-px",
                isPublic ? "bg-[#22C55E]" : "bg-[#E5E7EB]",
              )}
            >
              {t(isPublic ? "publicOption" : "privateOption")}
            </span>
          </span>
        </span>
      </Link>
      {onDelete ? (
        <DeleteX label={deleteLabel} disabled={deleting} onClick={onDelete} />
      ) : null}
    </li>
  );
}

function GhostPolaroid({ side }: { side: "left" | "right" }) {
  return (
    <div
      aria-hidden="true"
      className={cn(
        "box-border w-[170px] rounded-[4px] border-[3px] border-dashed border-[#1117] bg-[#fff8] p-3 opacity-55 max-[767px]:hidden",
        side === "left"
          ? "[transform:rotate(-8deg)_translateX(28px)]"
          : "[transform:rotate(8deg)_translateX(-28px)]",
      )}
    >
      <div className="mx-auto mt-[-22px] mb-2 h-[18px] w-3/5 border-2 border-dashed border-[#1115] bg-[#FFE14D55]" />
      <div className="h-[110px] border-[3px] border-dashed border-[#1113] bg-[#1111]" />
      <div className="mt-2 h-[26px] w-[70%] border-2 border-dashed border-[#1113]" />
    </div>
  );
}

export type TeamsPageTeam = {
  team: TeamSummaryDto;
  href: string;
  onDelete?: () => void;
};

export function TeamsPage({
  teams,
  newHref,
  deleting,
}: {
  teams: TeamsPageTeam[];
  /** Absent when this viewer cannot start a Team (read-only visit). */
  newHref?: string;
  deleting: boolean;
}) {
  const t = useT();
  const newLabel = t("newAgent");
  return (
    <div className={AGENT_PAGE}>
      <header
        className={cn(
          AGENT_BANNER,
          "py-[45px] max-[767px]:flex-nowrap max-[767px]:py-[18px]",
        )}
      >
        <h1
          id="studyform-teams"
          className={cn(
            AGENT_BANNER_TITLE,
            "max-[767px]:order-none max-[767px]:mt-[18px] max-[767px]:mb-5 max-[767px]:basis-auto",
          )}
        >
          {t("chatTargetTeams")}
        </h1>
        {teams.length && newHref ? (
          <NewButton href={newHref} label={newLabel} className={AGENTS_NEW_CLASS} />
        ) : null}
      </header>
      <section aria-labelledby="studyform-teams">
        {teams.length ? (
          <ul className="m-0 flex list-none flex-wrap gap-x-7 gap-y-[34px] p-0 pt-[30px] max-[767px]:gap-x-5 max-[767px]:gap-y-7">
            {teams.map(({ team, href, onDelete }, index) => (
              <TeamPolaroid
                key={team.id}
                team={team}
                index={index}
                href={href}
                deleting={deleting}
                deleteLabel={t("deleteAgent")}
                onDelete={onDelete}
              />
            ))}
          </ul>
        ) : (
          <div className="relative flex min-h-[360px] items-center justify-center pt-10 pb-5">
            <GhostPolaroid side="left" />
            <div className="relative z-[2] w-[240px] scale-[1.12] max-[767px]:w-full max-[767px]:scale-100">
              <div
                className={cn(POLAROID, "w-[240px] max-[767px]:w-full")}
                style={{ "--r": "-1.5deg" } as CSSProperties}
              >
                <p className={cn(TAPE, "m-0 text-base")}>{t("teamNoneYet")}</p>
                <div className={cn(PHOTO, SUN, "h-[130px] max-[767px]:h-[100px]")}>
                  <Faces faces={["wave", "wreath", "scroll"]} size="starter" />
                </div>
                <div className="mt-2.5 flex justify-center">
                  {newHref ? (
                    <Link
                      href={newHref}
                      aria-label={newLabel}
                      data-tour="new"
                      data-tour-empty="true"
                      className={AGENTS_NEW_CLASS}
                    >
                      <IconPlus size={16} />
                      {newLabel}
                    </Link>
                  ) : null}
                </div>
              </div>
            </div>
            <GhostPolaroid side="right" />
          </div>
        )}
      </section>
    </div>
  );
}
