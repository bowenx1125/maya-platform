import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

const session = vi.hoisted(() => ({
  api: { group: vi.fn() },
  user: {
    username: "bowen",
    courses: [
      { course_id: "maya1002", role: "student" },
      { course_id: "maya1001", role: "student" },
    ],
    groups: [
      { group_id: "five-1002", role: "member" },
      { group_id: "demo", role: "member" },
      { group_id: "five-1001", role: "member" },
    ],
  },
}));
vi.mock("../components/session-provider", () => ({
  useSession: () => session,
}));

import { useBowenLandingGroupId } from "../components/use-bowen-landing-group";

function Landing() {
  const { ready, groupId } = useBowenLandingGroupId();
  return <output>{ready ? (groupId ?? "none") : "loading"}</output>;
}

afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

it.each(["Demo Group", "No Group"])(
  "preserves the server's chosen group ahead of %s",
  async (defaultName) => {
    session.api.group.mockImplementation(async (id: string) => ({
      id,
      course_id: id === "five-1001" ? "maya1001" : "maya1002",
      name: id === "demo" ? defaultName : "5",
    }));
    const view = render(<Landing />);
    await screen.findByText("five-1002");
    session.user = {
      ...session.user,
      courses: [...session.user.courses].reverse(),
    };
    view.rerender(<Landing />);
    await screen.findByText("five-1001");
    session.user = {
      ...session.user,
      courses: [...session.user.courses].reverse(),
    };
  },
);

it("does not publish a stale landing group after the login class changes", async () => {
  let resolve!: (group: {
    id: string;
    course_id: string;
    name: string;
  }) => void;
  session.api.group.mockImplementation((id: string) =>
    id === "five-1002"
      ? new Promise((done) => {
          resolve = done;
        })
      : Promise.resolve({
          id,
          course_id: id === "demo" ? "maya1002" : "maya1001",
          name: "5",
        }),
  );
  const view = render(<Landing />);
  await waitFor(() => expect(session.api.group).toHaveBeenCalled());
  session.user = {
    ...session.user,
    courses: [...session.user.courses].reverse(),
  };
  session.api.group.mockResolvedValue({
    id: "five-1001",
    course_id: "maya1001",
    name: "5",
  });
  view.rerender(<Landing />);
  await screen.findByText("five-1001");
  await act(async () => {
    resolve({ id: "five-1002", course_id: "maya1002", name: "5" });
  });
  await waitFor(() => expect(screen.getByText("five-1001")).toBeTruthy());
  session.user = {
    ...session.user,
    courses: [...session.user.courses].reverse(),
  };
});
