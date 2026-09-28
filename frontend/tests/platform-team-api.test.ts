import { afterEach, describe, expect, it, vi } from "vitest";

import {
  createIdempotencyHandle,
  PlatformApi,
  type TeamDetailDto,
} from "../lib/api/platform";

const detail = {
  id: "team-1",
  course_id: "course-1",
  owner_user_id: "teacher-1",
  ownership_scope: "personal",
  group_id: null,
  display_name: "Dialogue team",
  visibility: "public",
  metadata_revision: 4,
  authorization_epoch: 1,
  current_version_id: "team-version-2",
  current_version_seq: 2,
  member_count: 2,
  can_edit: true,
  created_at: "2026-09-28T00:00:00Z",
  updated_at: "2026-09-28T00:00:00Z",
  members: [],
  shared_knowledge_set_ids: [],
  publication_state: "unpublished",
} satisfies TeamDetailDto;
const summary = {
  id: detail.id,
  course_id: detail.course_id,
  owner_user_id: detail.owner_user_id,
  ownership_scope: detail.ownership_scope,
  group_id: detail.group_id,
  display_name: detail.display_name,
  visibility: detail.visibility,
  metadata_revision: detail.metadata_revision,
  authorization_epoch: detail.authorization_epoch,
  current_version_id: detail.current_version_id,
  current_version_seq: detail.current_version_seq,
  member_count: detail.member_count,
  can_edit: detail.can_edit,
};

afterEach(() => vi.restoreAllMocks());

describe("PlatformApi Team contract", () => {
  it("uses the scoped directory routes and keeps mutation payloads and idempotency headers exact", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    fetchMock
      .mockResolvedValueOnce(
        new Response(JSON.stringify(detail), { status: 201 }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(detail), { status: 200 }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify([summary]), { status: 200 }),
      );
    const api = new PlatformApi({ baseUrl: "/api/v1", csrfToken: "csrf" });
    const body = {
      display_name: "Dialogue team",
      group_id: null,
      visibility: "public" as const,
      members: [
        { agent_version_id: "agent-v1", is_leader: true, position: 0 },
        { agent_version_id: "agent-v2", is_leader: false, position: 1 },
      ],
      shared_knowledge_set_ids: ["set-1"],
    };

    expect(await api.createTeam("course-1", body)).toEqual(detail);
    const createRequest = fetchMock.mock.calls[0];
    expect(createRequest[0]).toBe("/api/v1/courses/course-1/teams");
    expect(createRequest[1]?.method).toBe("POST");
    expect(JSON.parse(String(createRequest[1]?.body))).toEqual(body);
    expect(createRequest[1]?.headers).toMatchObject({
      "X-CSRF-Token": "csrf",
      "Content-Type": "application/json",
    });
    expect(
      (createRequest[1]?.headers as Record<string, string>)["Idempotency-Key"],
    ).toBeTruthy();

    const retry = createIdempotencyHandle();
    const updateKey = retry.key;
    const updateBody = { ...body, expected_metadata_revision: 4 };
    await api.updateTeam("team-1", updateBody, { idempotency: retry });
    const updateRequest = fetchMock.mock.calls[1];
    expect(updateRequest[0]).toBe("/api/v1/teams/team-1");
    expect(updateRequest[1]?.method).toBe("PUT");
    expect(JSON.parse(String(updateRequest[1]?.body))).toEqual(updateBody);
    expect(
      (updateRequest[1]?.headers as Record<string, string>)["Idempotency-Key"],
    ).toBe(updateKey);
    expect(await api.teams("course-1")).toEqual([summary]);
    expect(fetchMock.mock.calls[2][0]).toBe("/api/v1/courses/course-1/teams");
  });

  it("does not send client membership fields to the Maya Team catalog or expose catalog data as an editable DTO", async () => {
    const catalog = [
      {
        id: "published-team",
        team_version_id: "version-5",
        course_id: "course-1",
        display_name: "Course Dialogue Team",
        leader_display_name: "Socrates",
        members: [
          {
            display_name: "Socrates",
            avatar_config: {},
            position: 0,
            is_leader: true,
          },
          {
            display_name: "Mencius",
            avatar_config: {},
            position: 1,
            is_leader: false,
          },
        ],
        published_at: "2026-09-28T00:00:00Z",
      },
    ];
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(
        new Response(JSON.stringify(catalog), { status: 200 }),
      );
    const api = new PlatformApi({ baseUrl: "/api/v1" });

    expect(await api.mayaTeams("course-1")).toEqual(catalog);
    expect(fetchMock.mock.calls[0][0]).toBe(
      "/api/v1/courses/course-1/maya-teams",
    );
    expect(fetchMock.mock.calls[0][1]?.method).toBe("GET");
    expect(catalog[0]).not.toHaveProperty("members.0.agent_version_id");
    expect(catalog[0]).not.toHaveProperty("shared_knowledge_set_ids");
  });
});
