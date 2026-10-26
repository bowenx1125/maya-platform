"use client";

import { FitTitle } from "../fit-title";
import type { ChatAgent } from "../../lib/api";
import { useT } from "../../lib/i18n";
import { IconCheck } from "../quiet-icons";
import { MascotFigure } from "../academy/mascots";
import { agentMascot, agentTone } from "../ui/agent-card";
import { teamVersionLabel } from "../studyform-layout";
import { cn } from "../../lib/utils";
import styles from "../agent-chat.module.css";

export type ChatTargetTeam = {
  id: string;
  display_name: string;
  current_version_seq?: number;
  visibility?: "private" | "public";
};

/**
 * The New page: Scheme A sticker cards for Agents and Teams.
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

  const agentTile = (agent: ChatAgent, index: number) => {
    const key = `agent:${agent.version_id}`;
    const picked = value === key;
    const unavailable = agent.available === false;
    const tone = agentTone(agent.agent_id, index);
    const mascot = agentMascot(
      agent.agent_id,
      agent.avatar_config?.material_theme,
    );
    return (
      <li key={key} className={styles.pickCardWrap}>
        <button
          type="button"
          className={cn(styles.pickCard, picked && styles.pickCardPicked)}
          style={{ transform: `rotate(${index % 2 ? 1.2 : -1.2}deg)` }}
          aria-pressed={picked}
          disabled={disabled || unavailable}
          onClick={() => onPick(picked ? "" : key)}
        >
          {agent.version_label ? (
            <span className={styles.pickVersion}>{agent.version_label}</span>
          ) : null}
          <span className={styles.pickName}>
            <FitTitle text={agent.name} />
          </span>
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
    // Same Studyform VersionTile/AgentCard assignment: agentMascot(id) + agentTone.
    // Teams have no material_theme → hash by stable team.id (history/peek/picker share it).
    const tone = agentTone(team.id, index);
    const mascot = agentMascot(team.id);
    return (
      <li key={key} className={styles.pickCardWrap}>
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
            className={styles.pickArt}
            style={{
              backgroundColor: tone,
              backgroundImage:
                "radial-gradient(circle at 50% 60%,#fff8 0 30%,transparent 31%),repeating-conic-gradient(from 0deg at 50% 60%,#fff6 0 10deg,transparent 10deg 20deg)",
            }}
          >
            <MascotFigure id={mascot} className="h-24 w-auto" />
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

  return (
    <div className={styles.pickLayout}>
      <section className={styles.pickCol} aria-labelledby="chat-pick-agents">
        <h2 id="chat-pick-agents" className={styles.pickColTitle}>
          {t("agents")}
        </h2>
        {agents.length ? (
          <ul className={styles.pickGrid}>{agents.map(agentTile)}</ul>
        ) : (
          <p className={styles.pickEmpty}>{t("noAgents")}</p>
        )}
      </section>
      <section className={styles.pickCol} aria-labelledby="chat-pick-teams">
        <h2 id="chat-pick-teams" className={styles.pickColTitle}>
          {t("chatTargetTeams")}
        </h2>
        {teams.length ? (
          <ul className={styles.pickGrid}>{teams.map(teamTile)}</ul>
        ) : (
          <p className={styles.pickEmpty}>{t("teamNoneYet")}</p>
        )}
      </section>
    </div>
  );
}
