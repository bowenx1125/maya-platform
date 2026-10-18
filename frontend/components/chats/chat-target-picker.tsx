"use client";

import type { ChatAgent } from "../../lib/api";
import { useT } from "../locale";
import { IconCheck } from "../quiet-icons";
import { ModuleCard, ModuleGrid, teamVersionLabel } from "../studyform-layout";
import styles from "../agent-chat.module.css";

export type ChatTargetTeam = {
  id: string;
  display_name: string;
  current_version_seq?: number;
  visibility?: "private" | "public";
};

/**
 * The New page: one Studyform-style list of Agents and Teams to chat with.
 * Agents come first (the left column on wide screens, the top card when the
 * grid stacks), Teams second.
 */
export function ChatTargetPicker({
  teams,
  agents,
  value,
  disabled,
  onPick,
}: {
  teams: ChatTargetTeam[];
  agents: ChatAgent[];
  value: string;
  disabled: boolean;
  onPick: (value: string) => void;
}) {
  const t = useT();
  const tile = (
    key: string,
    name: string,
    label: string | null,
    visibility?: "private" | "public",
    unavailable = false,
  ) => {
    const picked = value === key;
    return (
      <li key={key}>
        <button
          type="button"
          className={`agent-tile ${styles.pickTile}`}
          aria-pressed={picked}
          disabled={disabled || unavailable}
          onClick={() => onPick(picked ? "" : key)}
        >
          <span className="agent-tile-name">{name}</span>
          {label ? (
            <span className="agent-pill" data-visibility={visibility}>
              {label}
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
    <ModuleGrid>
      <ModuleCard
        title={t("agents")}
        labelledBy="chat-pick-agents"
        empty={agents.length ? undefined : t("noAgents")}
      >
        {agents.length ? (
          <ul className="agent-tile-grid module-tile-grid">
            {agents.map((agent) =>
              tile(
                `agent:${agent.version_id}`,
                agent.name,
                agent.version_label,
                agent.visibility,
                agent.available === false,
              ),
            )}
          </ul>
        ) : undefined}
      </ModuleCard>
      <ModuleCard
        title={t("chatTargetTeams")}
        labelledBy="chat-pick-teams"
        empty={teams.length ? undefined : t("teamNoneYet")}
      >
        {teams.length ? (
          <ul className="agent-tile-grid module-tile-grid">
            {teams.map((team) =>
              tile(
                `team:${team.id}`,
                team.display_name,
                team.current_version_seq
                  ? teamVersionLabel(team.current_version_seq)
                  : null,
                team.visibility,
              ),
            )}
          </ul>
        ) : undefined}
      </ModuleCard>
    </ModuleGrid>
  );
}
