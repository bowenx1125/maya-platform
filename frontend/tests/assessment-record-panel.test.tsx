import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { invalidateRequestCache } from "../lib/request-cache";

// The formal chat-assessment Record moved from Brainform to Quiz Records
// (owner decision, 2026-11-08). These are the Brainform Record tests, kept
// with the same assertions against the moved panel.
const state = vi.hoisted(() => ({
  api: {} as Record<string, ReturnType<typeof vi.fn>>,
  userId: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
}));

vi.mock("../components/session-provider", () => ({
  useSession: () => ({
    api: state.api,
    identityGeneration: 1,
    user: {
      id: state.userId,
      courses: [{ course_id: "course-1", role: "teacher" }],
      groups: [],
    },
  }),
}));

import { AssessmentRecordPanel } from "../components/knowledge/assessment-record";

function renderPanel(scope: "course" | "own") {
  return render(<AssessmentRecordPanel courseId="course-1" scope={scope} />);
}

beforeEach(() => {
  state.api = {
    courseAssessmentAttempts: vi.fn().mockResolvedValue([]),
    myAssessmentAttempts: vi.fn().mockResolvedValue([]),
    deleteCourseAssessmentAttempt: vi.fn().mockResolvedValue(undefined),
  };
  invalidateRequestCache(state.api);
});

afterEach(() => {
  cleanup();
});

describe("Assessment Record panel", () => {
  it("shows teachers Record by assessment Team, then every student's result", async () => {
    const attempt = {
      user_id: "student-1",
      student_name: "Ada",
      test_name: "Keynotes · Formal diagnostic questions · V1.0",
      team_name: "Keynotes",
      status: "completed",
      phase: "completed",
      conversation_id: "4afc794f-1111-4111-8111-111111111111",
      group_name: "Group A",
      started_at: "2026-10-13T08:00:00Z",
      ended_at: "2026-10-13T08:20:00Z",
      points_awarded: 3,
      points_total: 4,
      questions: [
        {
          number: 1,
          prompt: "What is ren?",
          answers: ["Humaneness"],
          skipped: false,
          points_awarded: 1,
          points_total: 1,
          feedback: "Right.",
        },
      ],
      report_download_path: "/api/v1/learning/reports/r/download?revision_id=v",
    };
    state.api.courseAssessmentAttempts.mockResolvedValue([
      { ...attempt, attempt_id: "attempt-1" },
      {
        ...attempt,
        attempt_id: "attempt-2",
        user_id: "student-2",
        student_name: "Ben",
        status: "in_progress",
        phase: "answering",
        points_awarded: null,
        points_total: null,
        questions: [],
        report_download_path: null,
      },
    ]);
    renderPanel("course");

    expect(await screen.findByRole("heading", { name: "Record" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Memory" })).toBeNull();
    expect(state.api.courseAssessmentAttempts).toHaveBeenCalledWith("course-1");
    const team = await screen.findByRole("button", {
      name: "Open the Record for Keynotes",
    });
    expect(team.textContent).toContain("Students 2 · Attempts 2");
    fireEvent.click(team);

    expect(
      await screen.findByRole("heading", { name: "Keynotes" }),
    ).toBeTruthy();
    const ada = screen.getByRole("button", { name: /^Ada.*3 \/ 4$/ });
    expect(ada.textContent).toContain(
      "Group A · Formal diagnostic questions · V1.0",
    );
    expect(
      screen.getByRole("button", { name: /^Ben.*Unfinished$/ }),
    ).toBeTruthy();
    expect(
      screen
        .getByRole("link", {
          name: "Download the report for Keynotes · Formal diagnostic questions · V1.0",
        })
        .getAttribute("href"),
    ).toBe("/api/v1/learning/reports/r/download?revision_id=v");
    fireEvent.click(ada);
    expect(screen.getByRole("cell", { name: "Humaneness" })).toBeTruthy();
    expect(screen.getByRole("cell", { name: "Right." })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(
      await screen.findByRole("button", {
        name: "Open the Record for Keynotes",
      }),
    ).toBeTruthy();
  });

  // Owner request (2026-10-18): Record keeps revoked versions' and
  // unfinished attempts, and a teacher can delete (hide) one after a confirm.
  it("labels revoked and unfinished attempts and deletes one after a confirm", async () => {
    const revoked = {
      attempt_id: "attempt-revoked",
      user_id: "student-1",
      student_name: "Ada",
      test_name: "Keynotes · Formal diagnostic questions · V1.0",
      team_name: "Keynotes",
      status: "in_progress",
      phase: "answering",
      conversation_id: "4afc794f-5555-4555-8555-555555555555",
      group_name: "Group A",
      started_at: "2026-10-16T02:25:00Z",
      ended_at: null,
      points_awarded: null,
      points_total: null,
      questions: [
        {
          number: 1,
          prompt: "What is ren?",
          answers: ["Half an answer"],
          skipped: false,
          points_awarded: null,
          points_total: null,
          feedback: "",
        },
      ],
      report_download_path: null,
      publication_state: "revoked",
      version_label: "V1.0",
    };
    state.api.courseAssessmentAttempts
      .mockResolvedValueOnce([revoked])
      .mockResolvedValue([]);
    const confirm = vi.spyOn(window, "confirm");
    renderPanel("course");

    fireEvent.click(
      await screen.findByRole("button", {
        name: "Open the Record for Keynotes",
      }),
    );
    const row = await screen.findByRole("button", {
      name: /^Ada.*Unfinished$/,
    });
    expect(row.textContent).toContain(
      "Formal diagnostic questions · V1.0 · Revoked version",
    );
    fireEvent.click(row);
    expect(screen.getByRole("cell", { name: "Half an answer" })).toBeTruthy();

    const remove = screen.getByRole("button", {
      name: "Delete Ada's attempt",
    });
    confirm.mockReturnValueOnce(false);
    fireEvent.click(remove);
    expect(state.api.deleteCourseAssessmentAttempt).not.toHaveBeenCalled();

    confirm.mockReturnValueOnce(true);
    fireEvent.click(remove);
    await waitFor(() =>
      expect(state.api.deleteCourseAssessmentAttempt).toHaveBeenCalledWith(
        "course-1",
        "attempt-revoked",
      ),
    );
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: /^Ada/ })).toBeNull(),
    );
    confirm.mockRestore();
  });

  it("never offers a student the Record delete", async () => {
    state.api.myAssessmentAttempts.mockResolvedValue([
      {
        attempt_id: "own-attempt-2",
        user_id: state.userId,
        student_name: "Bowen",
        test_name: "Keynotes · Formal diagnostic questions · V1.0",
        team_name: "Keynotes",
        status: "completed",
        phase: "completed",
        conversation_id: "4afc794f-4444-4444-8444-444444444444",
        group_name: "Group A",
        started_at: "2026-10-16T02:25:00Z",
        ended_at: "2026-10-16T02:45:00Z",
        points_awarded: null,
        points_total: null,
        questions: [],
        report_download_path: null,
      },
    ]);
    renderPanel("own");
    fireEvent.click(
      await screen.findByRole("button", {
        name: "Open your answers for Keynotes",
      }),
    );
    await screen.findByRole("heading", { name: "Keynotes" });
    expect(
      screen.queryByRole("button", { name: /^Delete .*'s attempt$/ }),
    ).toBeNull();
    expect(state.api.deleteCourseAssessmentAttempt).not.toHaveBeenCalled();
  });

  it("shows the last Record at once while it refreshes (#123)", async () => {
    state.api.courseAssessmentAttempts.mockResolvedValue([
      {
        attempt_id: "attempt-cached",
        user_id: "student-1",
        student_name: "Ada",
        test_name: "Cached · Formal diagnostic questions · V1.0",
        team_name: "Cached",
        status: "completed",
        phase: "completed",
        conversation_id: "4afc794f-2222-4222-8222-222222222222",
        group_name: "Group A",
        started_at: "2026-10-13T08:00:00Z",
        ended_at: "2026-10-13T08:20:00Z",
        points_awarded: 1,
        points_total: 1,
        questions: [],
        report_download_path: null,
      },
    ]);
    const first = renderPanel("course");
    await screen.findByRole("button", { name: "Open the Record for Cached" });
    first.unmount();

    // The refresh never answers: the cached list is what shows. (Record now
    // reads through the shared request cache; a later visit, past its fresh
    // window, asks the server again.)
    invalidateRequestCache(state.api);
    state.api.courseAssessmentAttempts.mockReturnValue(new Promise(() => {}));
    renderPanel("course");
    expect(
      await screen.findByRole("button", {
        name: "Open the Record for Cached",
      }),
    ).toBeTruthy();
    expect(state.api.courseAssessmentAttempts).toHaveBeenCalledTimes(2);
  });

  // Owner request (2026-10-18): a student's Memory became Record, listing
  // only the student's own answers per assessment Team.
  it("shows a student's own Record and never reads course results", async () => {
    state.api.myAssessmentAttempts.mockResolvedValue([
      {
        attempt_id: "own-attempt-1",
        user_id: state.userId,
        student_name: "Bowen",
        test_name: "Keynotes · Formal diagnostic questions · V1.0",
        team_name: "Keynotes",
        status: "in_progress",
        phase: "answering",
        conversation_id: "4afc794f-3333-4333-8333-333333333333",
        group_name: "Group A",
        started_at: "2026-10-16T02:25:00Z",
        ended_at: null,
        points_awarded: null,
        points_total: null,
        questions: [
          {
            number: 1,
            prompt: "What is ren?",
            answers: ["Humaneness"],
            skipped: false,
            points_awarded: null,
            points_total: null,
            feedback: "",
          },
          {
            number: 2,
            prompt: "What is li?",
            answers: [],
            skipped: false,
            points_awarded: null,
            points_total: null,
            feedback: "",
          },
        ],
        report_download_path: null,
      },
    ]);
    renderPanel("own");

    expect(await screen.findByRole("heading", { name: "Record" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Memory" })).toBeNull();
    expect(state.api.myAssessmentAttempts).toHaveBeenCalledWith("course-1");
    expect(state.api.courseAssessmentAttempts).not.toHaveBeenCalled();
    const team = await screen.findByRole("button", {
      name: "Open your answers for Keynotes",
    });
    expect(team.textContent).toContain("Attempts 1");
    expect(team.textContent).not.toContain("Students");
    fireEvent.click(team);

    expect(
      await screen.findByRole("heading", { name: "Keynotes" }),
    ).toBeTruthy();
    const attempt = screen.getByRole("button", {
      name: /^Formal diagnostic questions · V1\.0.*In progress$/,
    });
    expect(screen.queryByText("Average score")).toBeNull();
    fireEvent.click(attempt);
    expect(screen.getByRole("cell", { name: "Humaneness" })).toBeTruthy();
    expect(screen.getByRole("cell", { name: "(not answered)" })).toBeTruthy();
    // Scores and feedback stay with the teacher.
    expect(screen.queryByRole("columnheader", { name: "Points" })).toBeNull();
    expect(screen.queryByRole("columnheader", { name: "Feedback" })).toBeNull();
  });
});
