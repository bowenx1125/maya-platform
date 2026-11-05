import {
  act,
  cleanup,
  fireEvent,
  render as renderComponent,
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
import { PlatformApiError } from "../lib/api";
import { validateDebateTopic } from "../lib/debate-topic";
import { localizeError } from "../lib/i18n";

const useSessionMock = vi.hoisted(() => vi.fn());
const router = vi.hoisted(() => ({ replace: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => router,
  usePathname: () => "/teacher/debates/new",
}));
vi.mock("../components/session-provider", () => ({
  useSession: useSessionMock,
}));

import {
  TeacherDebateCreate,
  TeacherDebateList,
  type DebateCreateController,
} from "../components/debate/setup/debate-setup";

const courseId = "b1ae79ed-e4a6-5b02-9abd-3a3ae944284b";
import { AppShell } from "../components/app-shell";

function render(ui: Parameters<typeof renderComponent>[0]) {
  return renderComponent(<AppShell role="teacher">{ui}</AppShell>);
}

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

function completedDebate(
  status: "completed" | "debate_finished" = "completed",
): DebateSummary {
  return {
    id: "completed-classroom",
    course_id: courseId,
    topic: "A saved classroom",
    status,
    round_count: 4,
    created_at: "2026-10-13T00:00:00Z",
    audio_restore_needed: false,
    prepared_turns: 8,
    expected_turns: 8,
    preview: { prepared_turns: 6, expected_turns: 6, ready: true },
    stall: null,
  };
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
    expect(localizeError({ code: "topic_language_invalid" })).toContain(
      "topic",
    );
  });

  it("opens the retained Preview screen from a debate summary", async () => {
    useSessionMock.mockReturnValue(teacherSession());
    const rows = [
      {
        id: "debate-one",
        course_id: courseId,
        topic:
          "Should the United States ban TikTok's recommendation algorithm?",
        status: "draft",
        round_count: 4,
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
    expect(screen.getByText("4 Rounds")).toBeTruthy();
    expect(
      link.closest("section")?.querySelector(".section-card-header") ?? null,
    ).toBeNull();
    expect(
      (
        await within(screen.getByRole("main")).findByRole("link", {
          name: "New",
        })
      ).getAttribute("href"),
    ).toBe("/teacher/debates/new");
  });

  it.each(["completed", "debate_finished"] as const)(
    "clicks Rebirth once and refreshes %s to Ready",
    async (status) => {
      const confirmed = vi.spyOn(window, "confirm").mockReturnValue(true);
      const completed = completedDebate(status);
      let reborn = false;
      let finishRefresh: () => void = () => {};
      const refreshPending = new Promise<void>((resolve) => {
        finishRefresh = resolve;
      });
      const api = {
        debates: vi.fn(async () => {
          if (reborn) await refreshPending;
          return [
            reborn
              ? { ...completed, status: "draft", prepared_turns: 6 }
              : completed,
          ];
        }),
        debate: vi
          .fn()
          .mockResolvedValue({ revision: 4, playback: { control_version: 7 } }),
        rebirthDebate: vi.fn(async () => {
          reborn = true;
        }),
      };
      useSessionMock.mockReturnValue({ ...teacherSession(), api });
      try {
        render(<TeacherDebateList />);
        await screen.findByText("Completed");
        const button = screen.getByRole("button", { name: "Replay" });
        fireEvent.click(button);
        fireEvent.click(button);
        await waitFor(() => expect(api.debates).toHaveBeenCalledTimes(2));
        expect((button as HTMLButtonElement).disabled).toBe(true);
        fireEvent.click(button);
        await act(async () => finishRefresh());
        await screen.findByText("Ready");
        expect(api.rebirthDebate).toHaveBeenCalledTimes(1);
        expect(api.rebirthDebate).toHaveBeenCalledWith(
          completed.id,
          { expected_revision: 4, expected_control_version: 7 },
          { idempotency: expect.anything() },
        );
        expect(confirmed).toHaveBeenCalledTimes(1);
        expect(screen.queryByText("Completed")).toBeNull();
        expect(screen.queryByRole("button", { name: "Replay" })).toBeNull();
        // The row itself opens Preview; there is no separate Preview button.
        expect(screen.queryByRole("link", { name: "Preview" })).toBeNull();
        expect(
          screen
            .getByRole("heading", { name: completed.topic })
            .closest("a")
            ?.getAttribute("href"),
        ).toBe(`/teacher/debates/${completed.id}/control`);
      } finally {
        confirmed.mockRestore();
      }
    },
  );

  it("shows Rebirth refusal and keeps the saved classroom and error through polling", async () => {
    const confirmed = vi.spyOn(window, "confirm").mockReturnValue(true);
    const api = {
      debates: vi.fn().mockResolvedValue([completedDebate()]),
      debate: vi
        .fn()
        .mockResolvedValue({ revision: 4, playback: { control_version: 7 } }),
      rebirthDebate: vi.fn().mockRejectedValue(
        new PlatformApiError(409, "private provider detail", {
          code: "preview_not_ready",
        }),
      ),
    };
    useSessionMock.mockReturnValue({ ...teacherSession(), api });
    try {
      render(<TeacherDebateList />);
      fireEvent.click(await screen.findByRole("button", { name: "Replay" }));
      const alert = await screen.findByRole("alert");
      expect(alert.textContent).toBeTruthy();
      expect(alert.textContent).not.toContain("private provider detail");
      expect(screen.getByText("Completed")).toBeTruthy();
      expect(screen.queryByText("Ready")).toBeNull();
      expect(api.debates).toHaveBeenCalledTimes(1);
      fireEvent.focus(window);
      await waitFor(() => expect(api.debates).toHaveBeenCalledTimes(2));
      expect(screen.getByRole("alert")).toBeTruthy();
      expect(
        (screen.getByRole("button", { name: "Replay" }) as HTMLButtonElement)
          .disabled,
      ).toBe(false);
    } finally {
      confirmed.mockRestore();
    }
  });

  it("recovers a committed Rebirth with only a list GET after refresh fails", async () => {
    const confirmed = vi.spyOn(window, "confirm").mockReturnValue(true);
    const completed = completedDebate();
    const api = {
      debates: vi
        .fn()
        .mockResolvedValueOnce([completed])
        .mockRejectedValueOnce(new TypeError("private refresh failure"))
        .mockRejectedValueOnce(new TypeError("private polling failure"))
        .mockResolvedValue([{ ...completed, status: "draft" }]),
      debate: vi
        .fn()
        .mockResolvedValue({ revision: 4, playback: { control_version: 7 } }),
      rebirthDebate: vi.fn().mockResolvedValue({}),
    };
    useSessionMock.mockReturnValue({ ...teacherSession(), api });
    try {
      render(
        <>
          <TeacherDebateList />
        </>,
      );
      fireEvent.click(await screen.findByRole("button", { name: "Replay" }));
      const alert = await screen.findByRole("alert");
      expect(alert.textContent).toContain("The classroom was reset");
      expect(alert.textContent).not.toContain("private refresh failure");
      const reset = screen.getByRole("button", {
        name: "Replay",
      }) as HTMLButtonElement;
      expect(reset.disabled).toBe(true);
      fireEvent.click(reset);
      expect(api.rebirthDebate).toHaveBeenCalledTimes(1);
      expect(api.debates).toHaveBeenCalledTimes(2);

      fireEvent.focus(window);
      await waitFor(() => expect(api.debates).toHaveBeenCalledTimes(3));
      expect(screen.getByRole("alert").textContent).toContain(
        "Retry only reloads the list",
      );
      fireEvent.click(
        screen.getByRole("button", {
          name: "Retry",
        }),
      );
      await screen.findByText("Ready");
      expect(api.debates).toHaveBeenCalledTimes(4);
      expect(api.debate).toHaveBeenCalledTimes(1);
      expect(api.rebirthDebate).toHaveBeenCalledTimes(1);
      expect(confirmed).toHaveBeenCalledTimes(1);
      expect(screen.queryByRole("alert")).toBeNull();
    } finally {
      confirmed.mockRestore();
    }
  });

  it("retries an ambiguous Rebirth with the original request and idempotency key", async () => {
    const confirmed = vi.spyOn(window, "confirm").mockReturnValue(true);
    const completed = completedDebate();
    let reborn = false;
    const api = {
      debates: vi.fn(async () => [
        reborn ? { ...completed, status: "draft" } : completed,
      ]),
      debate: vi
        .fn()
        .mockResolvedValue({ revision: 4, playback: { control_version: 7 } }),
      rebirthDebate: vi
        .fn()
        .mockRejectedValueOnce(new TypeError("connection reset"))
        .mockImplementationOnce(async () => {
          reborn = true;
        }),
    };
    useSessionMock.mockReturnValue({ ...teacherSession(), api });
    try {
      render(<TeacherDebateList />);
      fireEvent.click(await screen.findByRole("button", { name: "Replay" }));
      fireEvent.click(await screen.findByRole("button", { name: "Retry" }));
      await screen.findByText("Ready");
      expect(api.rebirthDebate).toHaveBeenCalledTimes(2);
      expect(api.rebirthDebate.mock.calls[1]).toEqual(
        api.rebirthDebate.mock.calls[0],
      );
      expect(api.debate).toHaveBeenCalledTimes(1);
      expect(confirmed).toHaveBeenCalledTimes(1);
    } finally {
      confirmed.mockRestore();
    }
  });

  it("leaves the saved classroom unchanged when Rebirth is cancelled", async () => {
    const confirmed = vi.spyOn(window, "confirm").mockReturnValue(false);
    const api = {
      debates: vi.fn().mockResolvedValue([completedDebate()]),
      debate: vi.fn(),
      rebirthDebate: vi.fn(),
    };
    useSessionMock.mockReturnValue({ ...teacherSession(), api });
    try {
      render(<TeacherDebateList />);
      fireEvent.click(await screen.findByRole("button", { name: "Replay" }));
      expect(api.debate).not.toHaveBeenCalled();
      expect(api.rebirthDebate).not.toHaveBeenCalled();
      expect(screen.getByText("Completed")).toBeTruthy();
    } finally {
      confirmed.mockRestore();
    }
  });

  it("renders each saved round count, including historical debates", async () => {
    useSessionMock.mockReturnValue(teacherSession());
    const rows: DebateSummary[] = [2, 3, 4, 5].map((roundCount) => ({
      id: `rounds-${roundCount}`,
      course_id: courseId,
      topic: `Saved ${roundCount} round lesson`,
      status: "draft",
      round_count: roundCount,
      created_at: "2026-09-08T00:00:00Z",
      audio_restore_needed: false,
      prepared_turns: 0,
      expected_turns: roundCount * 2,
      preview: null,
      stall: null,
    }));
    render(
      <>
        <TeacherDebateList
          controller={{ load: vi.fn().mockResolvedValue(rows) }}
        />
      </>,
    );
    await screen.findByRole("heading", { name: "Saved 4 round lesson" });
    for (const roundCount of [2, 3, 4, 5]) {
      expect(screen.getByText(`${roundCount} Rounds`)).toBeTruthy();
    }
  });

  it.each([
    ["draft", null, false],
    ["draft", false, false],
    ["draft", true, true],
    ["running", false, true],
    ["completed", false, true],
    ["debate_finished", false, true],
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
                round_count: 4,
                created_at: "2026-09-08T00:00:00Z",
                preview:
                  ready === null
                    ? null
                    : {
                        ready,
                        prepared_turns: ready ? 6 : 1,
                        expected_turns: 6,
                      },
                audio_restore_needed: false,
              },
            ]),
          }}
        />,
      );
      const heading = await screen.findByRole("heading", {
        name: /Stage entry/,
      });
      // Clicking the row is Preview, for every status; no extra button.
      expect(heading.closest("a")?.getAttribute("href")).toBe(
        "/teacher/debates/stage-entry/control",
      );
      expect(screen.queryByRole("link", { name: "Preview" })).toBeNull();
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
              .getByRole("button", { name: "Replay" })
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

  it("keeps Preview accessible for a stalled draft while Immerse stays disabled", async () => {
    useSessionMock.mockReturnValue(teacherSession());
    const stalled: DebateSummary = {
      id: "stalled-preview",
      course_id: courseId,
      topic: "A stalled preview",
      status: "draft",
      round_count: 4,
      created_at: "2026-09-08T00:00:00Z",
      audio_restore_needed: false,
      prepared_turns: 1,
      expected_turns: 6,
      preview: { prepared_turns: 1, expected_turns: 6, ready: false },
      stall: {
        turn_id: "failed-turn",
        round_no: 1,
        safe_error_code: "provider_not_sent",
      },
    };
    render(
      <TeacherDebateList
        controller={{ load: vi.fn().mockResolvedValue([stalled]) }}
      />,
    );

    await screen.findByRole("heading", { name: "A stalled preview" });
    expect(screen.getByText("Stalled")).toBeTruthy();
    expect(
      screen
        .getByRole("heading", { name: "A stalled preview" })
        .closest("a")
        ?.getAttribute("href"),
    ).toBe("/teacher/debates/stalled-preview/control");
    expect(screen.queryByRole("link", { name: "Preview" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Immerse" })).toBeNull();
    expect(
      (screen.getByRole("button", { name: "Immerse" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
  });

  it("shows list actions as labelled icons: enter, recycle, bell / bell-off, X", async () => {
    useSessionMock.mockReturnValue(teacherSession());
    const row = (id: string, restore: boolean): DebateSummary => ({
      id,
      course_id: courseId,
      topic: `Topic ${id}`,
      status: "running",
      round_count: 4,
      created_at: "2026-09-08T00:00:00Z",
      audio_restore_needed: restore,
      prepared_turns: 6,
      expected_turns: 8,
      preview: { prepared_turns: 6, expected_turns: 6, ready: true },
      stall: null,
    });
    render(
      <TeacherDebateList
        controller={{
          load: vi
            .fn()
            .mockResolvedValue([
              row("voiced", false),
              row("silent", true),
              { ...row("finished", false), status: "debate_finished" },
            ]),
        }}
      />,
    );
    const voiced = (
      await screen.findByRole("heading", { name: "Topic voiced" })
    ).closest("a")!.parentElement as HTMLElement;
    const silent = screen
      .getByRole("heading", { name: "Topic silent" })
      .closest("a")!.parentElement as HTMLElement;
    const finished = screen
      .getByRole("heading", { name: "Topic finished" })
      .closest("a")!.parentElement as HTMLElement;
    for (const scope of [voiced, silent]) {
      const enter = within(scope).getByRole("link", { name: "Immerse" });
      const remove = within(scope).getByRole("button", { name: "Delete" });
      // Final redesign: icon + visible label (same accessible name).
      for (const control of [enter, remove]) {
        expect(control.textContent).toBe(control.getAttribute("aria-label"));
        expect(control.querySelector("svg[aria-hidden='true']")).toBeTruthy();
      }
      expect(within(scope).queryByText("Preview")).toBeNull();
    }
    // Replay label; recycle icon; API remains rebirthDebate.
    const rebirth = within(finished).getByRole("button", { name: "Replay" });
    expect(rebirth.textContent).toBe("Replay");
    expect(rebirth.querySelector("svg[aria-hidden='true']")).toBeTruthy();
    // Audio present: a bell; clicking it devocalizes.
    const bell = within(voiced).getByRole("button", { name: "Devocalize" });
    expect(bell.getAttribute("data-vocalized")).toBe("true");
    expect(bell.textContent).toBe("Devocalize");
    // Audio removed: the bell is struck through; clicking it revocalizes.
    const bellOff = within(silent).getByRole("button", { name: "Revocalize" });
    expect(bellOff.getAttribute("data-vocalized")).toBe("false");
    expect(bellOff.textContent).toBe("Revocalize");
    expect(bellOff.querySelectorAll("path").length).toBe(
      bell.querySelectorAll("path").length + 1,
    );
  });

  it("uses separate Topic and Background cards with bidirectional height synchronization", async () => {
    let resized: ResizeObserverCallback | undefined;
    const disconnect = vi.fn();
    vi.stubGlobal(
      "ResizeObserver",
      class {
        constructor(callback: ResizeObserverCallback) {
          resized = callback;
        }
        observe() {}
        disconnect = disconnect;
      },
    );
    try {
      useSessionMock.mockReturnValue(teacherSession());
      const view = render(
        <TeacherDebateCreate
          controller={{
            loadRuleset: vi
              .fn()
              .mockResolvedValue({ zh: "# 中文", en: "# English" }),
            loadCandidates: vi.fn().mockResolvedValue([]),
            create: vi.fn(),
          }}
        />,
      );
      const topic = (await screen.findByRole("textbox", {
        name: "Topic",
      })) as HTMLTextAreaElement;
      const background = screen.getByRole("textbox", {
        name: "Background",
      }) as HTMLTextAreaElement;
      expect(topic.closest("section")).not.toBe(background.closest("section"));
      for (const input of [topic, background]) {
        const bounds = input.getBoundingClientRect();
        vi.spyOn(input, "getBoundingClientRect").mockImplementation(() => ({
          ...bounds,
          height: parseFloat(input.style.height),
        }));
      }
      topic.style.height = "208px";
      act(() =>
        resized?.(
          [{ target: topic }] as unknown as ResizeObserverEntry[],
          {} as ResizeObserver,
        ),
      );
      expect(background.style.height).toBe("208px");
      background.style.height = "260px";
      act(() =>
        resized?.(
          [{ target: background }] as unknown as ResizeObserverEntry[],
          {} as ResizeObserver,
        ),
      );
      expect(topic.style.height).toBe("260px");
      view.unmount();
      expect(disconnect).toHaveBeenCalled();
    } finally {
      vi.unstubAllGlobals();
    }
  });

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

  it("requires two speakers and lets a teacher add or remove speakers up to five", async () => {
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
            .mockResolvedValue(
              ["A", "B", "C", "D", "E", "F"].map((name) =>
                candidate(name, name),
              ),
            ),
          create,
        }}
      />,
    );
    await screen.findByRole("button", { name: "A" });
    fireEvent.change(screen.getByLabelText("Topic"), {
      target: { value: "A classroom debate" },
    });
    fireEvent.click(screen.getByRole("button", { name: "A" }));
    expect(screen.getByRole("status").textContent).toContain("1/5");
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(create).not.toHaveBeenCalled();
    expect(screen.getByRole("alert").textContent).toContain("at least two");

    for (const name of ["B", "C", "D", "E"]) {
      fireEvent.click(screen.getByRole("button", { name }));
    }
    expect(screen.getByRole("status").textContent).toContain("5/5");
    fireEvent.click(screen.getByRole("button", { name: "F" }));
    expect(screen.getByRole("status").textContent).toContain("5/5");
    expect(screen.getByRole("alert").textContent).toContain("at most five");

    for (const name of ["C", "D", "E"]) {
      fireEvent.click(screen.getByRole("button", { name }));
    }
    expect(screen.getByRole("status").textContent).toContain("2/5");
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() => expect(create).toHaveBeenCalledTimes(1));
    expect(
      create.mock.calls[0][1].participants.map(
        (item: { agent_id: string }) => item.agent_id,
      ),
    ).toEqual(["A", "B"]);
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
        debateLLMDefaults: vi
          .fn()
          .mockResolvedValue({ params: [], voice_params: [] }),
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
    expect((await screen.findByRole("alert")).textContent).toContain(
      "Maya could not be reached. Check your connection and try again.",
    );
    const done = screen.getByRole("button", { name: "Done" });
    await waitFor(() =>
      expect((done as HTMLButtonElement).disabled).toBe(false),
    );
    fireEvent.click(done);
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
    // Ruleset chrome is on the card (edit → back → save). Left-rail Back/Done
    // stay for the whole Debate and must not cancel/save the ruleset draft.
    const navigation = within(screen.getByRole("navigation"));
    const main = within(screen.getByRole("main"));
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    expect(navigation.queryByRole("button", { name: "Back" })).toBeNull();
    expect(navigation.queryByRole("button", { name: "Done" })).toBeNull();
    // Unchanged edit → card Back discards and restores the default heading.
    fireEvent.click(main.getByRole("button", { name: "Back" }));
    expect(create).not.toHaveBeenCalled();
    expect(screen.queryByRole("textbox", { name: "中文规则" })).toBeNull();
    expect(screen.getByRole("heading", { name: "默认规则" })).toBeTruthy();
    expect(
      within(screen.getByRole("main"))
        .getByRole("link", { name: "Back" })
        .getAttribute("href"),
    ).toBe("/teacher/debates");

    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    fireEvent.change(screen.getByRole("textbox", { name: "中文规则" }), {
      target: { value: "# 仅本场中文修改" },
    });
    // Dirty → card checkmark Save; rail Done is still hidden while editing.
    expect(navigation.queryByRole("button", { name: "Done" })).toBeNull();
    fireEvent.click(main.getByRole("button", { name: "Save" }));
    expect(create).not.toHaveBeenCalled();
    expect(screen.queryByRole("textbox", { name: "中文规则" })).toBeNull();
    expect(
      screen.getByRole("heading", { name: "仅本场中文修改" }),
    ).toBeTruthy();
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
      round_count: 4,
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
      screen.getByRole("heading", { name: /A live preview/ }),
    ).toBeTruthy();
    expect(screen.getByText(/4 \/ 6/)).toBeTruthy();
  } finally {
    cleanup();
    vi.useRealTimers();
  }
});

it("removes bulk Refresh and never retries stalled records when reading the list", async () => {
  const failed = {
    id: "failed",
    course_id: courseId,
    topic: "Needs recovery",
    status: "draft",
    round_count: 4,
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
  expect(screen.queryByRole("button", { name: "Refresh" })).toBeNull();
  // Final redesign: New is a shared Button in the list title row.
  expect(
    (
      await within(screen.getByRole("main")).findByRole("link", {
        name: "New",
      })
    ).getAttribute("href"),
  ).toBe("/teacher/debates/new");
  fireEvent.focus(window);
  await waitFor(() => expect(api.debates).toHaveBeenCalledTimes(2));
  expect(api.remakeDebate).not.toHaveBeenCalled();
  expect(api.debate).not.toHaveBeenCalled();
});
