"use client";

import Link from "next/link";
import type { CSSProperties } from "react";

import type { TeamSummaryDto } from "../lib/api";
import { useT } from "../lib/i18n";
import { cn } from "../lib/utils";
import { MascotFigure, MASCOT_IDS, type MascotId } from "./academy/mascots";
import { AGENT_PAGE, LIST_CARD_LIFT } from "./agent-chrome";
import { PageAction } from "./page-action";
import { PageBanner } from "./page-banner";
import { teamVersionLabel } from "./studyform-layout";
import { AgentsEmpty, agentMascot, DeleteX } from "./ui/agent-card";

/*
 * Teams page, approved fusion F1 (proposals/13-teams-fusion/src/gen.mjs
 * listF / emptyF): the Agents sunburst banner over a grid of C polaroids
 * (tilted tape name, coloured photo well with Agent faces, "member(s) |
 * visibility" footer) three to a row, or, when empty, the Agents page's
 * own empty card so both sit in the same place (proposals/37 final-v2).
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
      className={cn(POLAROID, LIST_CARD_LIFT, "min-w-0")}
      style={{ "--r": `${TILTS[index % TILTS.length]}deg` } as CSSProperties}
    >
      <Link
        href={href}
        aria-label={team.display_name}
        className="absolute inset-0 z-0 rounded-[inherit] focus-visible:outline-[3px] focus-visible:outline-offset-2 focus-visible:outline-main"
      />
      <span className="pointer-events-none relative z-[1] block text-[#111]">
        <span
          className={cn(
            TAPE,
            "text-sm max-[767px]:max-w-[80%] max-[767px]:text-[11px]",
          )}
        >
          {team.display_name}
        </span>
        <span className="absolute -top-2.5 -left-2.5 z-[3] -rotate-4 rounded-[6px] border-2 border-[#111] bg-white px-2 py-px font-body text-[11px] font-extrabold text-[#111] shadow-[2px_2px_0_#111]">
          {teamVersionLabel(team.current_version_seq)}
        </span>
        <span
          className={cn(PHOTO, "h-[150px] max-[767px]:h-[110px]")}
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
      </span>
      {onDelete ? (
        <DeleteX label={deleteLabel} disabled={deleting} onClick={onDelete} />
      ) : null}
    </li>
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
        <PageBanner
          title={t("chatTargetTeams")}
          titleId="studyform-teams"
          className="max-[767px]:shadow-[8px_8px_0_#111]"
        >
          {teams.length && newHref ? (
            <PageAction
              name="new"
              placement="page"
              href={newHref}
              guide="workspace.new"
            />
          ) : null}
        </PageBanner>
        <section aria-labelledby="studyform-teams">
          {teams.length ? (
            <ul className="m-0 grid w-full list-none grid-cols-3 gap-x-[26px] gap-y-[44px] p-0 pt-[18px] max-[767px]:grid-cols-2 max-[767px]:gap-x-5 max-[767px]:gap-y-7 max-[767px]:pt-6">
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
            <AgentsEmpty
              title={t("teamNoneYet")}
              newHref={newHref}
              newLabel={newLabel}
            >
              <Faces faces={["scroll", "wreath", "tablet"]} />
            </AgentsEmpty>
          )}
        </section>
      </div>
    </>
  );
}
