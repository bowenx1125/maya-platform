"use client";

import Link from "next/link";
import type { CSSProperties } from "react";

import type { TeamSummaryDto } from "../lib/api";
import { useT } from "../lib/i18n";
import { cn } from "../lib/utils";
import { MascotFigure, MASCOT_IDS, type MascotId } from "./academy/mascots";
import {
  AGENT_PAGE,
  STUDYFORM_BANNER,
  STUDYFORM_BANNER_TITLE,
  STUDYFORM_NEW_CLASS,
} from "./agent-chrome";
import { teamVersionLabel } from "./studyform-layout";
import {
  AGENTS_NEW_CLASS,
  agentMascot,
  DeleteX,
  NewButton,
} from "./ui/agent-card";
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
 * G2 faces, leader first, at most four, from TeamSummary.members. A member
 * whose Agent was deleted (agent_id null) keeps its snapshot theme, or a
 * neutral default face; faces are never links.
 */
export function teamFaces(team: TeamSummaryDto): MascotId[] {
  const listed = (team as { members?: TeamFaceMember[] | null }).members;
  if (Array.isArray(listed) && listed.length)
    return (
      [...listed]
        .sort((left, right) => Number(right.is_leader) - Number(left.is_leader))
        .slice(0, 4)
        // "" hashes to MASCOT_IDS[0], the neutral default face.
        .map((member) =>
          agentMascot(member.agent_id ?? "", member.material_theme),
        )
    );
  let hash = 0;
  for (const char of team.id) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  return Array.from(
    { length: Math.min(Math.max(team.member_count, 0), 4) },
    (_, index) => MASCOT_IDS[(hash + index) % MASCOT_IDS.length],
  );
}
type TeamFaceMember = {
  agent_id: string | null;
  material_theme?: string | null;
  is_leader?: boolean;
};

const FACE =
  "relative grid shrink-0 place-items-end overflow-hidden rounded-full border-[3px] border-[#111] bg-white shadow-[2px_2px_0_#111]";

/** G2 row: overlapping 50px faces (390: 36px), then a "+N" coin past four. */
function Faces({ faces, more = 0 }: { faces: MascotId[]; more?: number }) {
  return (
    <span className="flex items-center" aria-hidden="true">
      {faces.map((face, index) => (
        <span
          key={index}
          style={{ zIndex: 9 - index }}
          className={cn(
            FACE,
            "-ml-4 size-[50px] first:ml-0 max-[767px]:-ml-3.5 max-[767px]:size-9 max-[767px]:first:ml-0",
          )}
        >
          <MascotFigure
            id={face}
            className="h-[120%] w-auto translate-y-[8%]"
          />
        </span>
      ))}
      {more > 0 ? (
        <span className="relative -ml-2.5 grid size-9 shrink-0 place-items-center rounded-full border-[3px] border-[#111] bg-[#FFE14D] font-body text-xs font-extrabold text-[#111] shadow-[2px_2px_0_#111] max-[767px]:size-7 max-[767px]:text-[10px]">
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
  "mt-2.5 flex items-center justify-center border-[3px] border-[#111]";
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
  const faces = teamFaces(team);
  const isPublic = team.visibility === "public";
  return (
    <li
      className={cn(POLAROID, "w-[200px] max-[767px]:w-[calc(50%-10px)]")}
      style={{ "--r": `${TILTS[index % TILTS.length]}deg` } as CSSProperties}
    >
      <Link href={href} className="block text-[#111] no-underline">
        <span
          className={cn(
            TAPE,
            "text-[13px] max-[767px]:max-w-[80%] max-[767px]:text-[11px]",
          )}
        >
          {team.display_name}
        </span>
        <span className="absolute -top-2.5 -left-2.5 z-[3] -rotate-4 rounded-[6px] border-2 border-[#111] bg-white px-2 py-px font-body text-[11px] font-extrabold text-[#111] shadow-[2px_2px_0_#111]">
          {teamVersionLabel(team.current_version_seq)}
        </span>
        <span
          className={cn(PHOTO, "h-[130px] max-[767px]:h-[110px]")}
          style={{ backgroundColor: WELLS[index % WELLS.length] }}
        >
          <Faces faces={faces} more={Math.max(team.member_count - 4, 0)} />
        </span>
        <span className="mt-2.5 flex">
          <span className="inline-flex overflow-hidden rounded-[6px] border-2 max-[767px]:w-full border-[#111] font-body text-[11px] font-extrabold shadow-[2px_2px_0_#111]">
            <span className="bg-white px-2 py-px max-[767px]:min-w-0 max-[767px]:flex-1 max-[767px]:px-1 max-[767px]:leading-tight max-[767px]:tracking-[-0.03em]">
              {t("memberCountShort", { count: team.member_count })}
            </span>
            <span
              className={cn(
                "shrink-0 border-l-2 border-[#111] px-2 py-px max-[767px]:px-1",
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
        "box-border h-[200px] w-[170px] rounded-[4px] border-[3px] border-dashed border-[#1117] bg-[#fff8] opacity-55 max-[767px]:hidden",
        side === "left"
          ? "[transform:rotate(-8deg)_translateX(28px)]"
          : "[transform:rotate(7deg)_translateX(-28px)]",
      )}
    />
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
    <>
      <div className={AGENT_PAGE}>
        <header className={STUDYFORM_BANNER}>
          <h1 id="studyform-teams" className={STUDYFORM_BANNER_TITLE}>
            {t("chatTargetTeams")}
          </h1>
          {teams.length && newHref ? (
            <NewButton
              href={newHref}
              label={newLabel}
              className={STUDYFORM_NEW_CLASS}
            />
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
              <div className="relative z-[2] w-[240px] max-[767px]:w-full">
                <div
                  className={cn(POLAROID, "w-[240px] max-[767px]:w-full")}
                  style={{ "--r": "-1.5deg" } as CSSProperties}
                >
                  <p className={cn(TAPE, "m-0 text-[13px]")}>
                    {t("teamNoneYet")}
                  </p>
                  <div
                    className={cn(
                      PHOTO,
                      SUN,
                      "h-[130px] max-[767px]:h-[100px]",
                    )}
                  >
                    <Faces faces={["scroll", "wreath", "tablet"]} />
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
    </>
  );
}
