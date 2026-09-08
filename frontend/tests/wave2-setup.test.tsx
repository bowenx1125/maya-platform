import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
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
    group_name: `${name} Group`,
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
  ])("accepts unrestricted topic %s (%s)", (value) => {
    expect(validateDebateTopic(value)).toEqual({
      valid: true,
      normalized: value,
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
      "议题",
    );
    expect(localizeError({ code: "topic_language_invalid" }, "en")).toContain(
      "topic",
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
    expect(screen.getByText("2 Rounds")).toBeTruthy();
  });

  it.each([
    ["draft", false, false],
    ["draft", true, true],
    ["running", false, true],
    ["completed", false, true],
    ["failed", true, false],
    ["stopped", true, false],
  ] as const)(
    "gates Immerse for %s / preview %s",
    async (status, ready, enabled) => {
      useSessionMock.mockReturnValue(teacherSession());
      render(
        <TeacherDebateList
          controller={{
            load: vi.fn().mockResolvedValue([
              {
                id: "stage-entry",
                course_id: courseId,
                topic: "Stage entry",
                status,
                created_at: "2026-09-08T00:00:00Z",
                preview: { ready },
                audio_restore_needed: false,
              },
            ]),
          }}
        />,
      );
      await screen.findByRole("link", { name: /Stage entry/ });
      if (enabled) {
        const entry = screen.getByRole("link", { name: "Immerse" });
        expect(entry.getAttribute("href")).toBe(
          "/teacher/debates-beta/stage-entry/control",
        );
        expect(
          entry.compareDocumentPosition(
            screen.getByRole("button", { name: "Devocalize" }),
          ) & Node.DOCUMENT_POSITION_FOLLOWING,
        ).toBeTruthy();
        if (status === "completed") {
          expect(
            screen
              .getByRole("button", { name: "Rebirth" })
              .compareDocumentPosition(entry) &
              Node.DOCUMENT_POSITION_FOLLOWING,
          ).toBeTruthy();
        }
      } else {
        expect(
          (screen.getByRole("button", { name: "Immerse" }) as HTMLButtonElement)
            .disabled,
        ).toBe(true);
      }
    },
  );

  it("preserves click order and sends the fixed four-round request", async () => {
    useSessionMock.mockReturnValue(teacherSession());
    const create = vi.fn().mockResolvedValue(createdDebate());
    const controller: DebateCreateController = {
      loadRuleset: vi
        .fn()
        .mockResolvedValue({ zh: "# 默认规则", en: "# Default rules" }),
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
    fireEvent.change(screen.getByLabelText("Topic"), {
      target: {
        value:
          "Should the United States ban TikTok's recommendation algorithm?",
      },
    });
    fireEvent.click(screen.getByRole("button", { name: "Done" }));

    await waitFor(() => expect(create).toHaveBeenCalledTimes(1));
    const payload = create.mock.calls[0][1];
    expect(payload.round_count).toBe(4);
    expect(payload.total_duration_seconds).toBeNull();
    expect(payload.turn_duration_seconds).toBeNull();
    expect(
      payload.participants.map((item: { agent_id: string }) => item.agent_id),
    ).toEqual(["kaikai", "bowen"]);
    expect(router.replace).toHaveBeenCalledWith("/teacher/debates");
  });

  it("keeps row positions, numbers selection order, and preserves notes across deselection", async () => {
    useSessionMock.mockReturnValue(teacherSession());
    const create = vi.fn().mockResolvedValue(createdDebate());
    render(
      <TeacherDebateCreate
        controller={{
          loadRuleset: vi
            .fn()
            .mockResolvedValue({ zh: "# 中文", en: "# English" }),
          loadCandidates: vi
            .fn()
            .mockResolvedValue([
              candidate("new", "Newest"),
              candidate("old", "Older"),
            ]),
          create,
        }}
      />,
    );
    const newest = await screen.findByRole("button", { name: "Newest" });
    const older = screen.getByRole("button", { name: "Older" });
    expect(screen.getByRole("heading", { name: "Agents Order" })).toBeTruthy();
    expect(screen.queryByText(/snapshot fixed when saved/)).toBeNull();
    expect(within(newest).getByText("Newest Group")).toBeTruthy();
    expect(within(newest).getByText("+")).toBeTruthy();
    fireEvent.click(older);
    fireEvent.click(newest);
    expect(within(older).getByText("1")).toBeTruthy();
    expect(within(newest).getByText("2")).toBeTruthy();
    expect(
      newest.compareDocumentPosition(older) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    const note = screen.getByRole("textbox", { name: /Older.*note/i });
    fireEvent.change(note, {
      target: { value: "Discuss practical consequences" },
    });
    fireEvent.click(note);
    expect(older.getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(older);
    expect(within(newest).getByText("1")).toBeTruthy();
    fireEvent.click(older);
    expect(within(older).getByText("2")).toBeTruthy();
    expect(
      (
        screen.getByRole("textbox", {
          name: /Older.*note/i,
        }) as HTMLInputElement
      ).value,
    ).toBe("Discuss practical consequences");
    fireEvent.change(screen.getByLabelText("Topic"), {
      target: { value: "A shared decision?" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() => expect(create).toHaveBeenCalledTimes(1));
    expect(
      create.mock.calls[0][1].participants.map(
        (row: { agent_id: string }) => row.agent_id,
      ),
    ).toEqual(["new", "old"]);
    expect(create.mock.calls[0][1].participants[1].teacher_note).toBe(
      "Discuss practical consequences",
    );
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
        debateRulesetDefaults: vi
          .fn()
          .mockResolvedValue({ zh: "# 默认规则", en: "# Default rules" }),
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
      loadRuleset: vi
        .fn()
        .mockResolvedValue({ zh: "# 默认规则", en: "# Default rules" }),
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
    fireEvent.change(screen.getByLabelText("Topic"), {
      target: { value: "A stable classroom question" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() => expect(create).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() => expect(create).toHaveBeenCalledTimes(2));
    expect(keys[1]).toBe(keys[0]);
  });

  it("accepts mixed topics and submits optional background with selected language", async () => {
    useSessionMock.mockReturnValue(teacherSession());
    const create = vi.fn().mockResolvedValue(createdDebate());
    const controller: DebateCreateController = {
      loadRuleset: vi
        .fn()
        .mockResolvedValue({ zh: "# 默认规则", en: "# Default rules" }),
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

    fireEvent.change(screen.getByLabelText("Background"), {
      target: { value: "A classroom scenario." },
    });
    fireEvent.click(screen.getByRole("button", { name: "中文" }));
    expect(
      screen.getByRole("button", { name: "中文" }).getAttribute("aria-pressed"),
    ).toBe("true");
    const input = screen.getByLabelText("Topic");
    const mixedTopic = "Should TikTok be banned? 推荐算法";
    fireEvent.change(input, { target: { value: mixedTopic } });
    fireEvent.click(screen.getByRole("button", { name: "Done" }));

    await waitFor(() => expect(create).toHaveBeenCalledTimes(1));
    expect(create.mock.calls[0][1]).toMatchObject({
      topic: mixedTopic,
      background: "A classroom scenario.",
      output_language: "zh",
    });
    expect(input.getAttribute("aria-invalid")).toBe("false");
    expect(screen.queryByRole("combobox", { name: "Language" })).toBeNull();
  });

  it("uses default English when Chinese rules alone were edited", async () => {
    useSessionMock.mockReturnValue(teacherSession());
    const create = vi.fn().mockResolvedValue(createdDebate());
    const controller: DebateCreateController = {
      loadRuleset: vi
        .fn()
        .mockResolvedValue({ zh: "# 默认规则", en: "# Default rules" }),
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

    fireEvent.change(screen.getByLabelText("Background"), {
      target: { value: "A classroom scenario." },
    });
    fireEvent.click(screen.getByRole("button", { name: "中文" }));
    expect(
      screen.getByRole("button", { name: "中文" }).getAttribute("aria-pressed"),
    ).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    fireEvent.change(screen.getByRole("textbox", { name: "中文规则" }), {
      target: { value: "# 仅本场中文修改" },
    });
    expect(
      (
        screen.getByRole("button", {
          name: "Done",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    fireEvent.click(screen.getByRole("button", { name: "English" }));
    const input = screen.getByLabelText("Topic");
    const mixedTopic = "Should TikTok be banned? 推荐算法";
    fireEvent.change(input, { target: { value: mixedTopic } });
    fireEvent.click(screen.getByRole("button", { name: "Done" }));

    await waitFor(() => expect(create).toHaveBeenCalledTimes(1));
    expect(create.mock.calls[0][1]).toMatchObject({
      topic: mixedTopic,
      background: "A classroom scenario.",
      output_language: "en",
      teaching_prompts: { zh: "# 仅本场中文修改", en: "# Default rules" },
    });
    expect(input.getAttribute("aria-invalid")).toBe("false");
    expect(screen.queryByRole("combobox", { name: "Language" })).toBeNull();
  });
});

it("updates debate progress in place without opening the debate", async () => {
  vi.useFakeTimers();
  try {
    useSessionMock.mockReturnValue(teacherSession());
    const initial = {
      id: "progress-debate",
      course_id: courseId,
      topic: "A live preview",
      status: "draft",
      created_at: "2026-09-08T00:00:00Z",
      prepared_turns: 1,
      expected_turns: 6,
    } as DebateSummary;
    const load = vi
      .fn()
      .mockResolvedValueOnce([initial])
      .mockResolvedValue([{ ...initial, prepared_turns: 4 }]);
    render(<TeacherDebateList controller={{ load }} />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(load).toHaveBeenCalledTimes(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(load).toHaveBeenCalledTimes(2);
    expect(
      screen.getByRole("link", { name: /A live preview/ }).textContent,
    ).toContain("4 / 6");
  } finally {
    cleanup();
    vi.useRealTimers();
  }
});

it("places one global Refresh beside New and recovers only stalled records", async () => {
  const failed = {
    id: "failed",
    course_id: courseId,
    topic: "Needs recovery",
    status: "draft",
    created_at: "2026-09-08",
    prepared_turns: 0,
    expected_turns: 12,
    preview: null,
    audio_restore_needed: false,
    stall: {
      turn_id: "turn",
      round_no: 1,
      safe_error_code: "provider_not_sent",
    },
  } as DebateSummary;
  const ready = {
    ...failed,
    id: "ready",
    topic: "Ready lesson",
    stall: null,
    prepared_turns: 12,
    expected_turns: 12,
  } as DebateSummary;
  const api = {
    debates: vi.fn().mockResolvedValue([failed, ready]),
    debate: vi.fn().mockResolvedValue({
      id: "failed",
      revision: 1,
      playback: { control_version: 2 },
    }),
    remakeDebate: vi.fn().mockResolvedValue({}),
  };
  useSessionMock.mockReturnValue({ ...teacherSession(), api });
  render(<TeacherDebateList />);
  await screen.findByText("Needs recovery");
  expect(screen.getAllByRole("button", { name: "Refresh" })).toHaveLength(1);
  fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
  await waitFor(() => expect(api.remakeDebate).toHaveBeenCalledTimes(1));
  expect(api.remakeDebate.mock.calls[0][0]).toBe("failed");
  expect(api.debate).toHaveBeenCalledTimes(1);
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Refresh" })).toHaveProperty(
      "disabled",
      false,
    ),
  );
});
