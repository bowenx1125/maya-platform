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
import { validateDebateTopic } from "../lib/debate-topic";
import { localizeError } from "../lib/i18n";

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
  it.each([
    ["中文议题", "中文"],
    ["TikTok 推荐算法", "mixed CJK"],
    ["Запрет TikTok", "Cyrillic"],
    ["حظر TikTok", "Arabic"],
    ["12345?!", "numbers and punctuation only"],
    ["English\nline", "control character"],
    ["English\u202Etopic", "bidi control"],
    ["English\u2C2E", "Glagolitic letter"],
    ["English\u2C5E", "Glagolitic letter"],
    ["English 🙂", "emoji"],
    ["English ∑", "mathematical symbol"],
    ["English\u2028line", "line separator"],
    ["\u0301English", "isolated combining mark"],
    ["123\u0301", "combining mark after a number"],
    ["你\u0301", "combining mark after a non-Latin letter"],
  ])("rejects %s (%s)", (value) => {
    expect(validateDebateTopic(value)).toEqual({
      valid: false,
      reason: "english",
    });
  });

  it.each([
    "Should the United States ban TikTok's recommendation algorithm?",
    "Māori perspectives on digital sovereignty",
    "Cafe\u0301 perspectives on digital sovereignty",
    "C\u0327ultural exchange in class",
    "A\u030Angström and cultural exchange",
    "São Paulo and José's classroom debate",
    "TikTok—should it be banned?",
    "Should TikTok's algorithm be regulated in 2026?",
    "\u0149 and \u2132 perspectives",
    "\ua7cb compatibility letter",
    "Should Māori and Cafe\u0301/C\u0327 perspectives shape platform policy?",
  ])("accepts a valid Latin-script topic: %s", (value) => {
    const result = validateDebateTopic(value);
    expect(result.valid).toBe(true);
    if (result.valid) expect(result.normalized).toBe(value);
  });

  it("accepts a long topic without adding a product length limit", () => {
    const value = Array.from({ length: 80 }, () => "TikTok policy").join(" ");
    const result = validateDebateTopic(value);
    expect(result).toEqual({ valid: true, normalized: value });
  });

  it("keeps the existing empty-topic error distinct", () => {
    expect(validateDebateTopic(" \u00a0 ")).toEqual({
      valid: false,
      reason: "required",
    });
  });

  it("localizes a server topic-language error without exposing provider data", () => {
    expect(localizeError({ code: "topic_language_invalid" }, "zh")).toContain(
      "拉丁字母",
    );
    expect(localizeError({ code: "topic_language_invalid" }, "en")).toContain(
      "Latin-script",
    );
  });

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
          candidate("kaikai", "Kaikai"),
        ]),
      create,
    };

    render(<TeacherDebateCreate controller={controller} />);
    await screen.findByRole("button", { name: /Bowen/ });
    fireEvent.click(screen.getByRole("button", { name: /Kaikai/ }));
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

  it("loads candidates once with the stable default platform controller", async () => {
    const publishedAgents = vi
      .fn()
      .mockResolvedValue([
        candidate("bowen", "Bowen"),
        candidate("kaikai", "Kaikai"),
      ]);
    useSessionMock.mockReturnValue({
      api: {
        publishedAgents,
        createDebate: vi.fn().mockResolvedValue(createdDebate()),
      },
      user: teacherSession().user,
    });

    render(<TeacherDebateCreate />);
    await screen.findByRole("button", { name: /Bowen/ });
    await new Promise((resolve) => window.setTimeout(resolve, 50));
    expect(publishedAgents).toHaveBeenCalledTimes(1);
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
          candidate("kaikai", "Kaikai"),
        ]),
      create,
    };

    render(<TeacherDebateCreate controller={controller} />);
    await screen.findByRole("button", { name: /Bowen/ });
    fireEvent.click(screen.getByRole("button", { name: /Bowen/ }));
    fireEvent.click(screen.getByRole("button", { name: /Kaikai/ }));
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

  it("blocks invalid topics before create and keeps the input accessible", async () => {
    useSessionMock.mockReturnValue(teacherSession());
    const create = vi.fn().mockResolvedValue(createdDebate());
    const controller: DebateCreateController = {
      loadCandidates: vi
        .fn()
        .mockResolvedValue([
          candidate("bowen", "Bowen"),
          candidate("kaikai", "Kaikai"),
        ]),
      create,
    };

    render(<TeacherDebateCreate controller={controller} />);
    await screen.findByRole("button", { name: /Bowen/ });
    fireEvent.click(screen.getByRole("button", { name: /Bowen/ }));
    fireEvent.click(screen.getByRole("button", { name: /Kaikai/ }));

    const input = screen.getByLabelText("Topic (English)");
    const invalidTopic = "Should TikTok be banned? 推荐算法";
    fireEvent.change(input, { target: { value: invalidTopic } });
    fireEvent.click(
      screen.getByRole("button", { name: "Create debate draft" }),
    );

    const error = await screen.findByRole("alert");
    expect(error.textContent).toContain("Latin-script");
    expect(input.getAttribute("aria-invalid")).toBe("true");
    expect(input.getAttribute("aria-describedby")).toBe("debate-topic-error");
    expect((input as HTMLTextAreaElement).value).toBe(invalidTopic);
    expect(create).not.toHaveBeenCalled();
  });
});
