import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  bowenLandingGroup,
  bowenStudentClassId,
  readBowenStudentClass,
  rememberBowenStudentClass,
} from "../lib/bowen-student";

const state = vi.hoisted(() => ({
  user: {
    id: "bowen",
    username: "bowen",
    display_name: "Bowen",
    courses: [
      { course_id: "maya1001", role: "student" },
      { course_id: "maya1002", role: "student" },
    ],
    groups: [
      { group_id: "shell-1002", role: "member" },
      { group_id: "shell-1001", role: "member" },
      { group_id: "demo-1001", role: "member" },
    ],
  },
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/student",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock("../components/session-provider", () => ({
  useSession: () => ({
    api: {
      group: async (groupId: string) =>
        ({
          "shell-1002": {
            id: "shell-1002",
            course_id: "maya1002",
            name: "Students",
            members: [
              {
                user_id: "other-class",
                display_name: "Other Class",
                role: "member",
              },
            ],
          },
          "shell-1001": {
            id: "shell-1001",
            course_id: "maya1001",
            name: "Students",
            members: [
              { user_id: "bowen", display_name: "Bowen", role: "member" },
              { user_id: "bowen1", display_name: "Bowen1", role: "member" },
            ],
          },
          "demo-1001": {
            id: "demo-1001",
            course_id: "maya1001",
            name: "Demo Group",
            members: [
              { user_id: "guyue", display_name: "Guyue", role: "member" },
              { user_id: "bowen", display_name: "Bowen", role: "member" },
            ],
          },
        })[groupId],
      agents: async () => [],
      knowledge: async () => [],
      publishedAgents: async () => [],
      conversations: async () => [],
      voiceProfiles: async () => [],
      registrationOptions: async () => ({ classes: [], groups: [] }),
    },
    user: state.user,
    identityGeneration: 1,
    status: "authenticated",
    refresh: vi.fn(),
  }),
}));

import { StudentDashboard } from "../components/student-workspace";

afterEach(() => {
  cleanup();
  window.localStorage.clear();
});

describe("Bowen student class memory", () => {
  it("lets an explicit class choice replace the stored class", () => {
    rememberBowenStudentClass("maya1002");
    expect(readBowenStudentClass()).toBe("maya1002");
    rememberBowenStudentClass("maya1001");
    expect(readBowenStudentClass()).toBe("maya1001");
    expect(
      bowenStudentClassId({
        username: "bowen",
        courses: [
          { course_id: "maya1001", role: "student" },
          { course_id: "maya1002", role: "student" },
        ],
      }),
    ).toBe("maya1001");
    expect(bowenStudentClassId({ username: "kaikai", courses: [] })).toBe(
      undefined,
    );
  });

  it("lands on the first non-Students group of that class, in list order", () => {
    const groups = [
      { id: "shell-1002", name: "Students", course_id: "maya1002" },
      { id: "shell-1001", name: "Students", course_id: "maya1001" },
      { id: "later", name: "Later Team", course_id: "maya1001" },
      { id: "demo-1001", name: "Demo Group", course_id: "maya1001" },
    ];
    expect(bowenLandingGroup(groups, "maya1001")?.id).toBe("later");
    expect(bowenLandingGroup(groups, "maya1002")?.name).toBe("Students");
  });
});

describe("Bowen student home", () => {
  it("uses the login class and skips the Students shell and the other class", async () => {
    render(<StudentDashboard />);
    const rag = await screen.findByRole("link", { name: /Add the RAG/ });
    expect(rag.getAttribute("href")).toBe(
      "/student/rag?group_id=demo-1001&mode=rag-new",
    );
    expect(screen.getByRole("heading", { name: "Demo Group" })).toBeTruthy();
    expect(screen.getByText("Bowen1")).toBeTruthy();
    expect(screen.queryByText("Other Class")).toBeNull();
    await waitFor(() => expect(readBowenStudentClass()).toBe("maya1001"));
  });
});
