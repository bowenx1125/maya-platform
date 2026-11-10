"use client";

import { LIST_CARD_LIFT } from "../agent-chrome";
import { FitTitle } from "../fit-title";
import type { ChatAgent } from "../../lib/api";
import { useT } from "../../lib/i18n";
import { IconCheck } from "../quiet-icons";
import { MascotFigure } from "../academy/mascots";
import { agentMascot, agentTone } from "../ui/agent-card";
import { TEAM_WELLS, TeamFaces, teamFaces } from "../ui/team-faces";
import type { TeamFaceMember } from "../ui/team-faces";
import { teamVersionLabel } from "../studyform-layout";
import { cn } from "../../lib/utils";
import styles from "../agent-chat.module.css";

/**
 * Catalog row plus the two labels chat-agents does not send yet.
 * Absent or blank values are left off the card; nothing is invented.
 */
export type ChatTargetAgent = ChatAgent & {
  group_name?: string | null;
  last_edited_by_name?: string | null;
};

function shown(value: string | null | undefined): string | null {
  const text = value?.trim();
  return text ? text : null;
}

export type ChatTargetTeam = {
  id: string;
  display_name: string;
  current_version_seq?: number;
  visibility?: "private" | "public";
  /** Used by Studyform teamFaces when members are absent. */
  member_count?: number;
  /** Prefer member Agent mascots (Studyform Teams list). */
  members?: TeamFaceMember[] | null;
  leaderName?: string | null;
  memberNames?: string[];
};

/**
 * The New page: Scheme A sticker cards for Agents and Teams.
 * Agents = Studyform agentMascot/agentTone. Teams = Studyform TeamFaces stack.
 */
export function ChatTargetPicker({
  teams,
  agents,
  value,
  disabled,
  onPick,
  surface = "both",
}: {
  teams: ChatTargetTeam[];
  agents: ChatTargetAgent[];
  value: string;
  disabled: boolean;
  onPick: (value: string) => void;
  /** Agent and Team Chats each open only their own column. */
  surface?: "agent" | "team" | "both";
}) {
  const t = useT();

  const agentTile = (agent: ChatTargetAgent, index: number) => {
    const key = `agent:${agent.version_id}`;
    const picked = value === key;
    const unavailable = agent.available === false;
    const tone = agentTone(agent.agent_id, index);
    const mascot = agentMascot(
      agent.agent_id,
      agent.avatar_config?.material_theme,
    );
    const group = shown(agent.group_name);
    const version = shown(agent.version_label);
    const editor = shown(agent.last_edited_by_name);
    const fact = (label: string, text: string) => (
      <span className={styles.pickFact}>
        <span className={styles.pickFactLabel}>{label}</span>
        <span className={styles.pickFactValue}>{text}</span>
      </span>
    );
    return (
      <li key={key} className={cn(styles.pickCardWrap, LIST_CARD_LIFT)}>
        <button
          type="button"
          className={cn(
            styles.pickCard,
            styles.pickAgentCard,
            picked && styles.pickCardPicked,
          )}
          aria-pressed={picked}
          disabled={disabled || unavailable}
          onClick={() => onPick(picked ? "" : key)}
        >
          <span
            className={styles.pickArt}
            style={{
              backgroundColor: tone,
              // Same sunburst formula as Studyform AgentCard art.
              backgroundImage:
                "radial-gradient(circle at 50% 60%,#fff8 0 30%,transparent 31%),repeating-conic-gradient(from 0deg at 50% 60%,#fff6 0 10deg,transparent 10deg 20deg)",
            }}
          >
            <MascotFigure id={mascot} className="h-24 w-auto" />
          </span>
          <span className={styles.pickAgentName}>
            <FitTitle text={agent.name} />
          </span>
          <span className={styles.pickFacts}>
            {group ? fact(t("groupNameLabel"), group) : null}
            {version ? fact(t("chatPickVersion"), version) : null}
            {editor ? (
              <span className={styles.pickFactLine}>
                {t("agentLastEditedBy", { name: editor })}
              </span>
            ) : null}
            {/* "Available" said nothing; only a card that cannot be picked
                is labelled (2026-11-03). */}
            {unavailable ? (
              <span className={cn(styles.pickBadge, styles.pickBadgeMuted)}>
                {t("unavailable")}
              </span>
            ) : null}
          </span>
          {picked ? (
            <span className={styles.pickMark} aria-hidden="true">
              <IconCheck size={14} />
            </span>
          ) : null}
        </button>
      </li>
    );
  };

  const teamTile = (team: ChatTargetTeam, index: number) => {
    const key = `team:${team.id}`;
    const picked = value === key;
    const label = team.current_version_seq
      ? teamVersionLabel(team.current_version_seq)
      : null;
    const memberCount = team.member_count ?? team.members?.length ?? 0;
    const faces = teamFaces({
      id: team.id,
      member_count: memberCount,
      members: team.members,
    });
    return (
      <li key={key} className={cn(styles.pickCardWrap, LIST_CARD_LIFT)}>
        <button
          type="button"
          className={cn(styles.pickCard, picked && styles.pickCardPicked)}
          style={{
            transform: `rotate(${index % 2 ? 1.2 : -1.2}deg)`,
          }}
          aria-pressed={picked}
          disabled={disabled}
          onClick={() => onPick(picked ? "" : key)}
        >
          {label ? <span className={styles.pickVersion}>{label}</span> : null}
          <span className={styles.pickName}>
            <FitTitle text={team.display_name} />
          </span>
          <span
            className={cn(styles.pickArt, styles.pickTeamArt)}
            style={{ backgroundColor: TEAM_WELLS[index % TEAM_WELLS.length] }}
          >
            <TeamFaces faces={faces} more={Math.max(memberCount - 4, 0)} />
          </span>
          <span className={styles.pickMeta}>
            {team.visibility ? (
              <span
                className={cn(
                  styles.pickBadge,
                  team.visibility === "private" && styles.pickBadgeMuted,
                )}
              >
                {team.visibility === "private"
                  ? t("privateOption")
                  : t("publicOption")}
              </span>
            ) : null}
            <span className={cn(styles.pickBadge, styles.pickBadgeMuted)}>
              {memberCount} members
            </span>
          </span>
          {team.leaderName || team.memberNames?.length ? (
            <span className={styles.pickRoster}>
              {team.leaderName ? (
                <span>
                  <b>Leader</b> {team.leaderName}
                </span>
              ) : null}
              {team.memberNames?.length ? (
                <span>{team.memberNames.join(", ")}</span>
              ) : null}
            </span>
          ) : null}
          {picked ? (
            <span className={styles.pickMark} aria-hidden="true">
              <IconCheck size={14} />
            </span>
          ) : null}
        </button>
      </li>
    );
  };

  return (
    <div
      className={cn(
        styles.pickLayout,
        surface !== "both" && styles.pickLayoutSingle,
      )}
    >
      {surface === "team" ? null : (
        <section className={styles.pickCol} aria-labelledby="chat-pick-agents">
          <h2 id="chat-pick-agents" className={styles.pickColTitle}>
            {t("agents")}
          </h2>
          {agents.length ? (
            <ul className={cn(styles.pickGrid, styles.pickGridAgents)}>
              {agents.map(agentTile)}
            </ul>
          ) : (
            <p className={styles.pickEmpty}>{t("noAgents")}</p>
          )}
        </section>
      )}
      {surface === "agent" ? null : (
        <section className={styles.pickCol} aria-labelledby="chat-pick-teams">
          <h2 id="chat-pick-teams" className={styles.pickColTitle}>
            {t("chatTargetTeams")}
          </h2>
          {teams.length ? (
            <ul
              className={cn(
                styles.pickGrid,
                surface === "team" && styles.pickGridWide,
              )}
            >
              {teams.map(teamTile)}
            </ul>
          ) : (
            <p className={styles.pickEmpty}>{t("teamNoneYet")}</p>
          )}
        </section>
      )}
    </div>
  );
}
