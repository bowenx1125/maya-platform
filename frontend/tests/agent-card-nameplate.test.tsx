import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({
    children,
    href,
    ...props
  }: {
    children: React.ReactNode;
    href: string;
  }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

import { VersionTile } from "../components/studyform-layout";
import { TeamsPage } from "../components/teams-page";
import { AgentsEmpty } from "../components/ui/agent-card";

afterEach(() => cleanup());

const tile = {
  id: "a1",
  name: "Laozi",
  href: "/teacher/agents/a1",
  label: "V1.3",
  pending: false,
  visibility: "public" as const,
  editedBy: "Maya",
  group: "Group 1",
  deleteLabel: "Delete",
};

describe("Agent card information by surface (proposals/37)", () => {
  it("lists version, name, visibility, group and Last edited by on Studyform", () => {
    render(
      <ul>
        <VersionTile variant="list" {...tile} />
      </ul>,
    );
    expect(screen.getByText("V1.3")).toBeTruthy();
    expect(screen.getByText("Public")).toBeTruthy();
    expect(screen.getByText("Group 1")).toBeTruthy();
    expect(screen.getByText("Last edited by: Maya")).toBeTruthy();
  });

  it("reads Teacher instead of Public on a teacher-owned Public Agent", () => {
    render(
      <ul>
        <VersionTile variant="list" {...tile} isTeacherOwned />
      </ul>,
    );
    expect(screen.getByText("Teacher")).toBeTruthy();
    expect(screen.queryByText("Public")).toBeNull();
  });

  it("omits Last edited by on the home card but keeps the group", () => {
    render(
      <ul>
        <VersionTile {...tile} />
      </ul>,
    );
    expect(screen.getByText("Public")).toBeTruthy();
    expect(screen.getByText("Group 1")).toBeTruthy();
    expect(screen.queryByText("Last edited by: Maya")).toBeNull();
  });

  it("gives the Teams empty state the Agents empty card's frame", () => {
    const teams = render(
      <TeamsPage teams={[]} newHref="/student/teams/new" deleting={false} />,
    );
    const teamsCard = teams.getByText("No Teams yet.").closest("div")
      ?.parentElement?.className;
    teams.unmount();
    const agents = render(
      <AgentsEmpty title="No Agents yet." newHref="/x" newLabel="New" />,
    );
    const agentsCard = agents.getByText("No Agents yet.").closest("div")
      ?.parentElement?.className;
    expect(teamsCard).toBeTruthy();
    expect(teamsCard).toBe(agentsCard);
  });
});
