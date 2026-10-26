"use client";

import { cn } from "../../lib/utils";
import { MascotFigure, MASCOT_IDS, type MascotId } from "../academy/mascots";
import { agentMascot } from "./agent-card";

/*
 * Studyform Teams list face stack (teams-page.tsx on ui/teams):
 * G2 overlapping Agent mascot faces + optional "+N" coin.
 * Shared so Chatform create picker matches the Teams page exactly.
 */

/** F1 photo-well colours, in list order (same as Teams polaroids). */
export const TEAM_WELLS = [
  "#FDBA74",
  "#A3E635",
  "#67E8F9",
  "#FFB4C8",
  "#FFE14D",
  "#C4B5FD",
] as const;

export type TeamFaceMember = {
  agent_id: string | null;
  material_theme?: string | null;
  is_leader?: boolean;
};

/** Minimal team shape teamFaces reads (TeamSummaryDto satisfies this). */
export type TeamFacesSource = {
  id: string;
  member_count: number;
  members?: TeamFaceMember[] | null;
};

/**
 * G2 faces, leader first, at most four, from TeamSummary.members. A member
 * whose Agent was deleted (agent_id null) keeps its snapshot theme, or a
 * neutral default face; faces are never links.
 */
export function teamFaces(team: TeamFacesSource): MascotId[] {
  const listed = team.members;
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

const FACE =
  "relative grid shrink-0 place-items-end overflow-hidden rounded-full border-[3px] border-[#111] bg-white shadow-[2px_2px_0_#111]";

/** G2 row: overlapping 50px faces (390: 36px), then a "+N" coin past four. */
export function TeamFaces({
  faces,
  more = 0,
}: {
  faces: MascotId[];
  more?: number;
}) {
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
