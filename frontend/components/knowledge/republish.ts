import type { AgentDetail, AgentVersion } from "../../lib/api";

type RepublishApi = {
  version(versionId: string): Promise<AgentVersion>;
  agent(agentId: string): Promise<AgentDetail>;
  nextVersion(agentId: string): Promise<AgentVersion>;
  updateDraft(
    versionId: string,
    body: {
      expected_revision: number;
      agent_md: string;
      avatar_config?: AgentVersion["avatar_config"];
      voice_profile_id?: string | null;
    },
  ): Promise<AgentVersion>;
  setDocuments(
    versionId: string,
    expectedRevision: number,
    documentIds: string[],
  ): Promise<AgentVersion>;
  publish(versionId: string, expectedRevision: number): Promise<AgentVersion>;
};

export type RepublishTarget = {
  agent_id: string;
  version_id: string;
  name: string;
};

export type RepublishResult = { updated: string[]; failed: string[] };

function documentIds(version: AgentVersion): string[] {
  return (version.enabled_documents ?? []).map((document) => document.id);
}

function sameIds(left: string[], right: string[]): boolean {
  return (
    left.length === right.length && left.every((id, index) => id === right[index])
  );
}

/**
 * Publish a new version of every Agent this account may edit whose published
 * version reads the edited RAG file, so the new text replaces its frozen copy.
 *
 * Owner decision (2026-10-13): saving a RAG file updates its Agents, and the
 * server moves their Teams along. The new version repeats the published one
 * exactly; a leftover draft is overwritten, as Done in the editor does.
 */
export async function republishAgentsUsingDocument(
  api: RepublishApi,
  targets: RepublishTarget[],
  documentId: string,
): Promise<RepublishResult> {
  const result: RepublishResult = { updated: [], failed: [] };
  for (const target of targets) {
    let published: AgentVersion;
    let agent: AgentDetail;
    try {
      published = await api.version(target.version_id);
      if (!documentIds(published).includes(documentId)) continue;
      agent = await api.agent(target.agent_id);
      if (!agent.can_edit) continue;
    } catch {
      continue;
    }
    try {
      let draft: AgentVersion;
      if (agent.current_draft_version_id) {
        const leftover = await api.version(agent.current_draft_version_id);
        draft = await api.updateDraft(leftover.id, {
          expected_revision: leftover.revision,
          agent_md: published.agent_md ?? "",
          ...(published.avatar_config
            ? { avatar_config: published.avatar_config }
            : {}),
          ...((published.voice_profile_id ?? null) !==
          (leftover.voice_profile_id ?? null)
            ? { voice_profile_id: published.voice_profile_id ?? null }
            : {}),
        });
        const wanted = documentIds(published);
        if (!sameIds(wanted, documentIds(draft))) {
          draft = await api.setDocuments(draft.id, draft.revision, wanted);
        }
      } else {
        draft = await api.nextVersion(agent.id);
      }
      await api.publish(draft.id, draft.revision);
      result.updated.push(target.name);
    } catch {
      result.failed.push(target.name);
    }
  }
  return result;
}
