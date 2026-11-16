import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MASCOT_IDS } from "../components/academy/mascots";
import { teamFaces, TeamsPage } from "../components/teams-page";
import { agentMascot } from "../components/ui/agent-card";
import type { TeamSummaryDto } from "../lib/api";

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...rest
  }: {
    href: string;
    children: unknown;
  }) => (
    <a href={href} {...rest}>
      {children as never}
    </a>
  ),
}));

function team(members: unknown, extra: Partial<TeamSummaryDto> = {}) {
  return {
    id: extra.id ?? "11111111-1111-4111-8111-111111111111",
    member_count: 5,
    display_name: "Team Alpha",
    members,
    ...extra,
  } as unknown as TeamSummaryDto;
}

describe("Team card faces from TeamSummary.members", () => {
  it("puts the leader first and caps at four", () => {
    const faces = teamFaces(
      team([
        { agent_id: "a1", material_theme: null, is_leader: false },
        { agent_id: "a2", material_theme: "demo", is_leader: true },
        { agent_id: "a3", material_theme: null, is_leader: false },
        { agent_id: "a4", material_theme: null, is_leader: false },
        { agent_id: "a5", material_theme: null, is_leader: false },
      ]),
    );
    expect(faces).toHaveLength(4);
    expect(faces[0]).toBe("wave");
    expect(faces[1]).toBe(agentMascot("a1"));
  });

  it("gives a deleted Agent (agent_id null) its theme or the neutral default", () => {
    const faces = teamFaces(
      team([
        { agent_id: null, material_theme: "warm_sand", is_leader: true },
        { agent_id: null, material_theme: null, is_leader: false },
        { agent_id: null, material_theme: "unknown_theme", is_leader: false },
      ]),
    );
    expect(faces).toEqual(["wreath", MASCOT_IDS[0], MASCOT_IDS[0]]);
  });

  it("renders a card with null members without crashing or member links", () => {
    const { container } = render(
      <TeamsPage
        teams={[
          {
            team: team([
              { agent_id: null, material_theme: null, is_leader: true },
              { agent_id: "a2", material_theme: "demo", is_leader: false },
            ]),
            href: "/student/teams?team_id=t1",
          } as never,
        ]}
        deleting={false}
      />,
    );
    const hrefs = [...container.querySelectorAll("a")].map((a) =>
      a.getAttribute("href"),
    );
    expect(hrefs.some((href) => !href || /null|undefined/.test(href))).toBe(
      false,
    );
  });

  it("reads Teacher on a teacher-owned Public Team and Public otherwise", () => {
    render(
      <TeamsPage
        teams={[
          {
            team: team(
              [{ agent_id: "a1", material_theme: null, is_leader: true }],
              {
                id: "22222222-2222-4222-8222-222222222222",
                display_name: "Teacher Team",
                visibility: "public",
                is_teacher_owned: true,
                member_count: 2,
                current_version_seq: 1,
              },
            ),
            href: "/student/teams?team_id=t-teacher",
          },
          {
            team: team(
              [{ agent_id: "a2", material_theme: null, is_leader: true }],
              {
                id: "33333333-3333-4333-8333-333333333333",
                display_name: "Student Team",
                visibility: "public",
                is_teacher_owned: false,
                member_count: 2,
                current_version_seq: 1,
              },
            ),
            href: "/student/teams?team_id=t-student",
          },
        ]}
        deleting={false}
      />,
    );
    expect(screen.getByText("Teacher")).toBeTruthy();
    expect(screen.getByText("Public")).toBeTruthy();
  });
});
