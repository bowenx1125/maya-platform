"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";

import {
  createIdempotencyHandle,
  isAmbiguousMutationFailure,
  type ChatAgent,
  type IdempotencyHandle,
  type MayaTeamDirectoryDto,
  type PlatformApi,
  type TeamDetailDto,
  type TeamSummaryDto,
  type TeamUpdateRequest,
  type TeamWriteRequest,
} from "../../lib/api";
import { useT } from "../locale";
import styles from "../agent-chat.module.css";

type TeamVisibility = TeamWriteRequest["visibility"];

type KnowledgeSetChoice = { id: string; name: string };

type TeamWriteBody = TeamWriteRequest;

type TeamEntryApi = {
  teams(courseId: string): Promise<TeamSummaryDto[]>;
  mayaTeams(courseId: string): Promise<MayaTeamDirectoryDto[]>;
  team(teamId: string): Promise<TeamDetailDto>;
  createTeam(
    courseId: string,
    body: TeamWriteBody,
    options?: { idempotency: IdempotencyHandle },
  ): Promise<TeamDetailDto>;
  updateTeam(
    teamId: string,
    body: TeamUpdateRequest,
    options?: { idempotency: IdempotencyHandle },
  ): Promise<TeamDetailDto>;
};

type PendingTeamMutation = {
  handle: IdempotencyHandle;
  body: TeamWriteBody;
  teamId: string | null;
  expectedRevision: number | null;
};

type Entry = "chooser" | "agent" | "team" | "maya";
type FormState = {
  name: string;
  visibility: TeamVisibility;
  memberVersionIds: string[];
  leaderVersionId: string;
  sharedSetIds: string[];
};

const EMPTY_FORM: FormState = {
  name: "",
  visibility: "private",
  memberVersionIds: [],
  leaderVersionId: "",
  sharedSetIds: [],
};

function teamApi(api: PlatformApi): TeamEntryApi | null {
  const candidate = api as PlatformApi & Partial<TeamEntryApi>;
  return [
    candidate.teams,
    candidate.mayaTeams,
    candidate.team,
    candidate.createTeam,
    candidate.updateTeam,
  ].every((method) => typeof method === "function")
    ? (candidate as PlatformApi & TeamEntryApi)
    : null;
}

export function TeamEntryFlow({
  api,
  courseId,
  agents,
  onClose,
  onStartAgent,
  onStartTeam,
}: {
  api: PlatformApi;
  courseId: string;
  agents: ChatAgent[];
  onClose: () => void;
  onStartAgent: (versionId: string) => void;
  onStartTeam: (
    entry: {
      kind: "team" | "maya_team";
      team_id: string;
      team_version_id?: string;
    },
    visibility: TeamVisibility,
  ) => void;
}) {
  const t = useT();
  const apiForTeams = teamApi(api);
  const [entry, setEntry] = useState<Entry>("chooser");
  const [teams, setTeams] = useState<TeamSummaryDto[]>([]);
  const [directory, setDirectory] = useState<MayaTeamDirectoryDto[]>([]);
  const [knowledgeSets, setKnowledgeSets] = useState<KnowledgeSetChoice[]>([]);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [editing, setEditing] = useState<TeamDetailDto | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [selectedMayaTeam, setSelectedMayaTeam] = useState("");
  const [chatVisibility, setChatVisibility] =
    useState<TeamVisibility>("private");
  const [loading, setLoading] = useState(false);
  const [teamListRefreshing, setTeamListRefreshing] = useState(false);
  const [teamListRefreshError, setTeamListRefreshError] = useState(false);
  const [saving, setSaving] = useState(false);
  const [starting, setStarting] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const requestSeq = useRef(0);
  const pendingMutation = useRef<PendingTeamMutation | null>(null);
  const [mutationUnknown, setMutationUnknown] = useState(false);

  useEffect(
    () => () => {
      requestSeq.current += 1;
    },
    [],
  );

  async function openTeamList() {
    setEntry("team");
    setError(null);
    setSaved(false);
    setTeamListRefreshError(false);
    if (!apiForTeams) {
      setError(new Error(t("teamApiNotConnected")));
      return;
    }
    const sequence = ++requestSeq.current;
    setLoading(true);
    try {
      const [teamList, sets] = await Promise.all([
        apiForTeams.teams(courseId),
        api.knowledgeSets(courseId),
      ]);
      if (requestSeq.current !== sequence) return;
      setTeams(teamList.filter((item) => item.can_edit));
      setKnowledgeSets(
        sets.map((set) => ({ id: set.id, name: set.display_name })),
      );
    } catch (cause) {
      if (requestSeq.current === sequence) setError(cause);
    } finally {
      if (requestSeq.current === sequence) setLoading(false);
    }
  }

  async function refreshTeamList() {
    if (!apiForTeams) return;
    const sequence = ++requestSeq.current;
    setTeamListRefreshing(true);
    setTeamListRefreshError(false);
    try {
      const teamList = await apiForTeams.teams(courseId);
      if (requestSeq.current !== sequence) return;
      setTeams(teamList.filter((item) => item.can_edit));
    } catch {
      if (requestSeq.current === sequence) setTeamListRefreshError(true);
    } finally {
      if (requestSeq.current === sequence) setTeamListRefreshing(false);
    }
  }

  async function openMayaDirectory() {
    setEntry("maya");
    setError(null);
    setSaved(false);
    if (!apiForTeams) {
      setError(new Error(t("teamApiNotConnected")));
      return;
    }
    const sequence = ++requestSeq.current;
    setLoading(true);
    try {
      const result = await apiForTeams.mayaTeams(courseId);
      if (requestSeq.current !== sequence) return;
      setDirectory(result);
      setSelectedMayaTeam("");
      setChatVisibility("private");
    } catch (cause) {
      if (requestSeq.current === sequence) setError(cause);
    } finally {
      if (requestSeq.current === sequence) setLoading(false);
    }
  }

  function newTeam() {
    if (mutationUnknown) return;
    pendingMutation.current = null;
    setEditing(null);
    setFormOpen(true);
    setForm(EMPTY_FORM);
    setSaved(false);
    setError(null);
  }

  async function editTeam(teamId: string) {
    if (!apiForTeams || mutationUnknown) return;
    const sequence = ++requestSeq.current;
    setLoading(true);
    setError(null);
    try {
      const detail = await apiForTeams.team(teamId);
      if (requestSeq.current !== sequence) return;
      if (!detail.can_edit) throw new Error(t("teamNotEditable"));
      setEditing(detail);
      const memberIds = [...detail.members]
        .sort((left, right) => left.position - right.position)
        .map((member) => member.agent_version_id);
      setForm({
        name: detail.display_name,
        visibility: detail.visibility,
        memberVersionIds: memberIds,
        leaderVersionId:
          detail.members.find((member) => member.is_leader)?.agent_version_id ??
          "",
        sharedSetIds: detail.shared_knowledge_set_ids,
      });
      setFormOpen(true);
      setSaved(false);
    } catch (cause) {
      if (requestSeq.current === sequence) setError(cause);
    } finally {
      if (requestSeq.current === sequence) setLoading(false);
    }
  }

  function toggleMember(versionId: string) {
    setForm((current) => {
      const selected = current.memberVersionIds.includes(versionId);
      const memberVersionIds = selected
        ? current.memberVersionIds.filter((id) => id !== versionId)
        : [...current.memberVersionIds, versionId];
      return {
        ...current,
        memberVersionIds,
        leaderVersionId:
          selected && current.leaderVersionId === versionId
            ? ""
            : current.leaderVersionId,
      };
    });
  }

  async function saveTeam(event: FormEvent) {
    event.preventDefault();
    if (!apiForTeams || saving) return;
    const pending = pendingMutation.current ?? {
      handle: createIdempotencyHandle(),
      body: {
        display_name: form.name.trim(),
        group_id: null,
        visibility: form.visibility,
        members: form.memberVersionIds.map((agent_version_id, position) => ({
          agent_version_id,
          is_leader: agent_version_id === form.leaderVersionId,
          position,
        })),
        shared_knowledge_set_ids: form.sharedSetIds,
      },
      teamId: editing?.id ?? null,
      expectedRevision: editing?.metadata_revision ?? null,
    };
    pendingMutation.current = pending;
    setSaving(true);
    setError(null);
    setSaved(false);
    let savedTeam: TeamDetailDto;
    try {
      if (pending.teamId && pending.expectedRevision !== null) {
        savedTeam = await apiForTeams.updateTeam(
          pending.teamId,
          {
            display_name: pending.body.display_name,
            visibility: pending.body.visibility,
            members: pending.body.members,
            shared_knowledge_set_ids: pending.body.shared_knowledge_set_ids,
            expected_metadata_revision: pending.expectedRevision,
          },
          { idempotency: pending.handle },
        );
      } else {
        savedTeam = await apiForTeams.createTeam(courseId, pending.body, {
          idempotency: pending.handle,
        });
      }
    } catch (cause) {
      setError(cause);
      if (isAmbiguousMutationFailure(cause)) {
        setMutationUnknown(true);
      } else {
        pendingMutation.current = null;
      }
      setSaving(false);
      return;
    }
    setSaving(false);

    // Once the write returns a receipt, only a list refresh may still fail.
    // Keep the receipt and never submit the mutation again for a GET failure.
    setTeams((current) => [
      savedTeam,
      ...current.filter((item) => item.id !== savedTeam.id),
    ]);
    pendingMutation.current = null;
    setMutationUnknown(false);
    setError(null);
    setTeamListRefreshError(false);
    setEditing(null);
    setFormOpen(false);
    setForm(EMPTY_FORM);
    setSaved(true);
    await refreshTeamList();
  }

  async function startTeam(entry: {
    kind: "team" | "maya_team";
    team_id: string;
    team_version_id?: string;
  }) {
    if (starting) return;
    setStarting(true);
    try {
      await onStartTeam(entry, chatVisibility);
    } finally {
      setStarting(false);
    }
  }

  const selectedDirectoryTeam = directory.find(
    (item) => item.id === selectedMayaTeam,
  );
  const formErrors = !form.name.trim()
    ? t("teamNameRequired")
    : form.memberVersionIds.length < 2
      ? t("teamNeedsTwoMembers")
      : !form.leaderVersionId
        ? t("teamChooseLeader")
        : "";

  return (
    <section className={styles.entryFlow} aria-labelledby="chat-entry-title">
      <div className={styles.entryHeading}>
        <div>
          <h2 id="chat-entry-title">{t("chatNewEntryTitle")}</h2>
        </div>
        <button
          className="inline-button"
          type="button"
          onClick={onClose}
          disabled={mutationUnknown || starting}
        >
          {t("cancel")}
        </button>
      </div>

      {entry === "chooser" ? (
        <div className={styles.entryOptions}>
          <button
            className={styles.entryOption}
            type="button"
            disabled={!agents.some((agent) => agent.available !== false)}
            onClick={() => setEntry("agent")}
          >
            <strong>{t("chatNewAgent")}</strong>
            <span>{t("chatNewAgentHelp")}</span>
          </button>
          <button
            className={styles.entryOption}
            type="button"
            onClick={() => void openTeamList()}
          >
            <strong>{t("chatNewTeam")}</strong>
            <span>{t("chatNewTeamHelp")}</span>
          </button>
          <button
            className={styles.entryOption}
            type="button"
            onClick={() => void openMayaDirectory()}
          >
            <strong>{t("chatNewMayaTeam")}</strong>
            <span>{t("chatNewMayaTeamHelp")}</span>
          </button>
        </div>
      ) : null}

      {entry === "agent" ? (
        <div className={styles.entrySection}>
          <h3>{t("chatChooseAgent")}</h3>
          <ul className={styles.entryAgentList}>
            {agents.map((agent) => (
              <li key={agent.version_id}>
                <button
                  type="button"
                  className={styles.entryOption}
                  disabled={agent.available === false}
                  onClick={() => onStartAgent(agent.version_id)}
                >
                  <strong>{agent.name}</strong>
                  <span>{agent.version_label}</span>
                </button>
              </li>
            ))}
          </ul>
          <button
            className="inline-button"
            type="button"
            onClick={() => setEntry("chooser")}
            disabled={mutationUnknown}
          >
            {t("back")}
          </button>
        </div>
      ) : null}

      {entry === "team" ? (
        <div className={styles.entrySection}>
          <div className={styles.entrySectionHeading}>
            <div>
              <h3>{t("chatTeamManagement")}</h3>
              <p>{t("teamVisibilityHelp")}</p>
            </div>
            <button
              className="inline-button"
              type="button"
              onClick={newTeam}
              disabled={loading || !apiForTeams}
            >
              {t("chatCreateTeam")}
            </button>
          </div>
          {loading ? <p role="status">{t("loading")}</p> : null}
          {error ? (
            <p role="alert" className={styles.entryError}>
              {apiForTeams ? t("teamLoadFailed") : t("teamApiNotConnected")}
            </p>
          ) : null}
          {teams.length ? (
            <ul
              className={styles.entryTeamList}
              aria-label={t("chatTeamManagement")}
            >
              {teams.map((team) => (
                <li key={team.id}>
                  <span>
                    <strong>{team.display_name}</strong>
                    <small>
                      {t("teamVersionLabel", { seq: team.current_version_seq })}
                    </small>
                  </span>
                  <button
                    className="inline-button"
                    type="button"
                    disabled={loading || !team.can_edit}
                    onClick={() => void editTeam(team.id)}
                  >
                    {t("edit")}
                  </button>
                  <button
                    className="inline-button"
                    type="button"
                    disabled={loading || starting || !team.current_version_id}
                    onClick={() =>
                      void startTeam({
                        kind: "team",
                        team_id: team.id,
                        team_version_id: team.current_version_id,
                      })
                    }
                  >
                    {t("teamStartChat")}
                  </button>
                </li>
              ))}
            </ul>
          ) : null}

          {saved ? (
            <p role="status" className={styles.entryNotice}>
              {t("teamSavedWaitingForChat")}
            </p>
          ) : null}
          {teamListRefreshError ? (
            <div className={styles.entryError}>
              <p role="status">{t("teamListRefreshFailed")}</p>
              <button
                className="inline-button"
                type="button"
                disabled={teamListRefreshing}
                onClick={() => void refreshTeamList()}
              >
                {teamListRefreshing ? t("loading") : t("retryTeamList")}
              </button>
            </div>
          ) : null}

          {!loading &&
          apiForTeams &&
          (editing || formOpen || (!teams.length && !saved)) ? (
            <form
              className={styles.teamForm}
              onSubmit={(event) => void saveTeam(event)}
            >
              <h3>{editing ? t("chatEditTeam") : t("chatCreateTeam")}</h3>
              <label>
                {t("teamName")}
                <input
                  value={form.name}
                  maxLength={120}
                  disabled={saving || mutationUnknown}
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      name: event.target.value,
                    }))
                  }
                  required
                />
              </label>
              <fieldset>
                <legend>{t("teamVisibility")}</legend>
                {(["private", "public"] as const).map((visibility) => (
                  <label className={styles.entryChoice} key={visibility}>
                    <input
                      type="radio"
                      name="team-visibility"
                      value={visibility}
                      checked={form.visibility === visibility}
                      disabled={saving || mutationUnknown}
                      onChange={() =>
                        setForm((current) => ({ ...current, visibility }))
                      }
                    />
                    <span>
                      {t(
                        visibility === "private" ? "teamPrivate" : "teamPublic",
                      )}
                    </span>
                  </label>
                ))}
              </fieldset>
              <fieldset>
                <legend>{t("teamMembers")}</legend>
                <p>{t("teamMembersHelp")}</p>
                <div className={styles.entryMemberList}>
                  {agents.map((agent) => {
                    const checked = form.memberVersionIds.includes(
                      agent.version_id,
                    );
                    return (
                      <div
                        className={styles.entryMember}
                        key={agent.version_id}
                      >
                        <label className={styles.entryChoice}>
                          <input
                            type="checkbox"
                            checked={checked}
                            disabled={
                              agent.available === false ||
                              saving ||
                              mutationUnknown
                            }
                            onChange={() => toggleMember(agent.version_id)}
                          />
                          <span>
                            {agent.name} · {agent.version_label}
                          </span>
                        </label>
                        <label className={styles.entryChoice}>
                          <input
                            type="radio"
                            name="team-leader"
                            aria-label={t("teamSetLeader", {
                              name: agent.name,
                            })}
                            checked={form.leaderVersionId === agent.version_id}
                            disabled={!checked || saving || mutationUnknown}
                            onChange={() =>
                              setForm((current) => ({
                                ...current,
                                leaderVersionId: agent.version_id,
                              }))
                            }
                          />
                          <span>{t("leader")}</span>
                        </label>
                      </div>
                    );
                  })}
                </div>
              </fieldset>
              <fieldset>
                <legend>{t("teamSharedKnowledge")}</legend>
                <p>{t("teamSharedKnowledgeHelp")}</p>
                {knowledgeSets.length ? (
                  knowledgeSets.map((set) => (
                    <label className={styles.entryChoice} key={set.id}>
                      <input
                        type="checkbox"
                        checked={form.sharedSetIds.includes(set.id)}
                        disabled={saving || mutationUnknown}
                        onChange={() =>
                          setForm((current) => ({
                            ...current,
                            sharedSetIds: current.sharedSetIds.includes(set.id)
                              ? current.sharedSetIds.filter(
                                  (id) => id !== set.id,
                                )
                              : [...current.sharedSetIds, set.id],
                          }))
                        }
                      />
                      <span>{set.name}</span>
                    </label>
                  ))
                ) : (
                  <p>{t("teamNoSharedKnowledge")}</p>
                )}
              </fieldset>
              {error ? (
                <p role="alert" className={styles.entryError}>
                  {mutationUnknown ? t("teamSaveUnknown") : t("teamSaveFailed")}
                </p>
              ) : null}
              <button
                className="primary-button"
                type="submit"
                disabled={saving || (!mutationUnknown && Boolean(formErrors))}
              >
                {saving
                  ? t("saving")
                  : mutationUnknown
                    ? t("teamRetrySave")
                    : editing
                      ? t("saveNewTeamVersion")
                      : t("chatCreateTeam")}
              </button>
              {formErrors ? (
                <p className={styles.entryHint}>{formErrors}</p>
              ) : null}
            </form>
          ) : null}
          <button
            className="inline-button"
            type="button"
            onClick={() => setEntry("chooser")}
            disabled={mutationUnknown}
          >
            {t("back")}
          </button>
        </div>
      ) : null}

      {entry === "maya" ? (
        <div className={styles.entrySection}>
          <div className={styles.entrySectionHeading}>
            <div>
              <h3>{t("chatMayaTeamDirectory")}</h3>
              <p>{t("mayaTeamDirectoryHelp")}</p>
            </div>
            <button
              className="inline-button"
              type="button"
              onClick={() => setEntry("chooser")}
              disabled={mutationUnknown}
            >
              {t("back")}
            </button>
          </div>
          {loading ? <p role="status">{t("loading")}</p> : null}
          {directory.length ? (
            <fieldset className={styles.entryDirectory}>
              <legend>{t("mayaTeamChoose")}</legend>
              {directory.map((team) => (
                <label className={styles.entryDirectoryCard} key={team.id}>
                  <input
                    type="radio"
                    name="maya-team"
                    checked={selectedMayaTeam === team.id}
                    onChange={() => setSelectedMayaTeam(team.id)}
                  />
                  <span>
                    <strong>{team.display_name}</strong>
                    <small>
                      {t("mayaTeamMembers", {
                        names: team.members
                          .map((member) => member.display_name)
                          .join(", "),
                      })}
                    </small>
                  </span>
                </label>
              ))}
            </fieldset>
          ) : !loading ? (
            <p>{t("mayaTeamNoneAvailable")}</p>
          ) : null}
          {selectedDirectoryTeam ? (
            <>
              <fieldset>
                <legend>{t("chatPrivacy")}</legend>
                <p>{t("chatPrivacyHelp")}</p>
                {(["private", "public"] as const).map((visibility) => (
                  <label className={styles.entryChoice} key={visibility}>
                    <input
                      type="radio"
                      name="chat-visibility"
                      value={visibility}
                      checked={chatVisibility === visibility}
                      onChange={() => setChatVisibility(visibility)}
                    />
                    <span>
                      {t(
                        visibility === "private" ? "teamPrivate" : "teamPublic",
                      )}
                    </span>
                  </label>
                ))}
              </fieldset>
              <button
                className="primary-button"
                type="button"
                disabled={starting}
                onClick={() =>
                  void startTeam({
                    kind: "maya_team",
                    team_id: selectedDirectoryTeam.id,
                  })
                }
              >
                {starting ? t("loading") : t("teamStartChat")}
              </button>
            </>
          ) : null}
        </div>
      ) : null}

      {error && entry === "maya" ? (
        <p role="alert" className={styles.entryError}>
          {apiForTeams ? t("teamLoadFailed") : t("teamApiNotConnected")}
        </p>
      ) : null}
    </section>
  );
}
