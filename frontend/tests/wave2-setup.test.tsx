import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  DebateDetail,
  DebateSummary,
  PublishedAgentSummary,
} from "../lib/api";

const useSessionMock = vi.hoisted(() => vi.fn());
const router = vi.hoisted(() => ({ replace: vi.fn() }));

vi.mock("next/navigation", () => ({ useRouter: () => router }));
vi.mock("../components/session-provider", () => ({
  useSession: useSessionMock,
}));

import {
  TeacherDebateCreate,
  TeacherDebateList,
  type DebateCreateController,
} from "../components/debate/setup/debate-setup";

const courseId = "b1ae79ed-e4a6-5b02-9abd-3a3ae944284b";

afterEach(() => {
  cleanup();
  router.replace.mockReset();
  useSessionMock.mockReset();
});

function teacherSession() {
  return {
    api: {},
    user: {
      courses: [{ course_id: courseId, role: "teacher" }],
    },
  };
}

function candidate(id: string, name: string): PublishedAgentSummary {
  return {
    agent: {
      id,
      group_id: `${id}-group`,
      name,
      description: `${name} perspective`,
      status: "active",
      current_published_version_id: `${id}-version`,
      current_draft_version_id: null,
    },
    current_version: {
      id: `${id}-version`,
      agent_id: id,
      version_label: "V1.0",
      state: "published",
      revision: 1,
    },
  } as PublishedAgentSummary;
}

function createdDebate(): DebateDetail {
  return { id: "debate-id" } as DebateDetail;
}

describe("Wave 2 teacher debate setup", () => {
  it("renders teacher debate summaries and links to the control surface", async () => {
    useSessionMock.mockReturnValue(teacherSession());
    const rows = [
      {
        id: "debate-one",
        course_id: courseId,
        topic:
          "Should the United States ban TikTok's recommendation algorithm?",
        status: "draft",
        created_at: "2026-08-27T00:00:00Z",
      } as DebateSummary,
    ];

    render(
      <TeacherDebateList
        controller={{ load: vi.fn().mockResolvedValue(rows) }}
      />,
    );

    const link = await screen.findByRole("link", { name: /TikTok/ });
    expect(link.getAttribute("href")).toBe(
      "/teacher/debates/debate-one/control",
    );
    expect(screen.getByText("2 rounds")).toBeTruthy();
  });

  it("preserves click order and sends the frozen two-round request", async () => {
    useSessionMock.mockReturnValue(teacherSession());
    const create = vi.fn().mockResolvedValue(createdDebate());
    const controller: DebateCreateController = {
      loadCandidates: vi
        .fn()
        .mockResolvedValue([
          candidate("bowen", "Bowen"),
          candidate("kaikai", "KaiKai"),
        ]),
      create,
    };

    render(<TeacherDebateCreate controller={controller} />);
    await screen.findByRole("button", { name: /Bowen/ });
    fireEvent.click(screen.getByRole("button", { name: /KaiKai/ }));
    fireEvent.click(screen.getByRole("button", { name: /Bowen/ }));
    fireEvent.change(screen.getByLabelText("Topic (English)"), {
      target: {
        value:
          "Should the United States ban TikTok's recommendation algorithm?",
      },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Create debate draft" }),
    );

    await waitFor(() => expect(create).toHaveBeenCalledTimes(1));
    const payload = create.mock.calls[0][1];
    expect(payload.round_count).toBe(2);
    expect(payload.total_duration_seconds).toBeNull();
    expect(payload.turn_duration_seconds).toBeNull();
    expect(
      payload.participants.map((item: { agent_id: string }) => item.agent_id),
    ).toEqual(["kaikai", "bowen"]);
    expect(router.replace).toHaveBeenCalledWith("/teacher/debates");
  });

  it("reuses one idempotency key after an ambiguous create response", async () => {
    useSessionMock.mockReturnValue(teacherSession());
    const keys: string[] = [];
    const create = vi.fn(
      async (...args: Parameters<DebateCreateController["create"]>) => {
        keys.push(args[2].key);
        if (keys.length === 1) throw new TypeError("connection reset");
        return createdDebate();
      },
    );
    const controller: DebateCreateController = {
      loadCandidates: vi
        .fn()
        .mockResolvedValue([
          candidate("bowen", "Bowen"),
          candidate("kaikai", "KaiKai"),
        ]),
      create,
    };

    render(<TeacherDebateCreate controller={controller} />);
    await screen.findByRole("button", { name: /Bowen/ });
    fireEvent.click(screen.getByRole("button", { name: /Bowen/ }));
    fireEvent.click(screen.getByRole("button", { name: /KaiKai/ }));
    fireEvent.change(screen.getByLabelText("Topic (English)"), {
      target: { value: "A stable classroom question" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Create debate draft" }),
    );
    await waitFor(() => expect(create).toHaveBeenCalledTimes(1));
    fireEvent.click(
      screen.getByRole("button", { name: "Create debate draft" }),
    );
    await waitFor(() => expect(create).toHaveBeenCalledTimes(2));
    expect(keys[1]).toBe(keys[0]);
  });
});
