import {
  cleanup,
  fireEvent,
  render as renderComponent,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  DebateCreateController,
  DebateDetail,
} from "../components/debate/setup/debate-setup";
import type {
  DebateLLMDefaults,
  PublishedAgentSummary,
  RoundUnitCapDefaultsInput,
} from "../lib/api";

const useSessionMock = vi.hoisted(() => vi.fn());
const router = vi.hoisted(() => ({ replace: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => router,
  usePathname: () => "/teacher/debates/new",
}));
vi.mock("../components/session-provider", () => ({
  useSession: useSessionMock,
}));

import { AppShell } from "../components/app-shell";
import { TeacherDebateCreate } from "../components/debate/setup/debate-setup";

const courseId = "b1ae79ed-e4a6-5b02-9abd-3a3ae944284b";

afterEach(() => {
  cleanup();
  router.replace.mockReset();
  useSessionMock.mockReset();
});

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

function teacherSession() {
  return {
    api: {},
    user: {
      courses: [{ course_id: courseId, role: "teacher" }],
    },
  };
}

function defaultsFor(
  language: "zh" | "en",
  participants: number,
  rate: number,
): [number, number, number, number] {
  if (language === "zh" && participants === 2 && rate === 1)
    return [140, 115, 115, 140];
  if (language === "zh" && participants === 2 && rate === 1.25)
    return [175, 145, 145, 175];
  if (language === "zh" && participants === 3 && rate === 1)
    return [90, 75, 75, 90];
  if (language === "zh" && participants === 3 && rate === 1.25)
    return [115, 95, 95, 115];
  if (language === "en" && participants === 2 && rate === 1)
    return [90, 75, 75, 90];
  if (language === "en" && participants === 2 && rate === 1.25)
    return [115, 90, 90, 115];
  return [40, 40, 40, 40];
}

function controller(create = vi.fn().mockResolvedValue({ id: "debate-id" })) {
  return {
    loadRuleset: vi
      .fn()
      .mockResolvedValue({ zh: "# Default rules", en: "# Default rules" }),
    loadCandidates: vi
      .fn()
      .mockResolvedValue([
        candidate("bowen", "Bowen"),
        candidate("kaikai", "Kaikai"),
        candidate("maya", "Maya"),
      ]),
    loadLLMDefaults: vi.fn().mockResolvedValue({
      params: [],
      voice_params: [
        {
          name: "rate",
          kind: "float",
          default: 1,
          minimum: 0.5,
          maximum: 2,
          step: 0.1,
        },
      ],
    } as DebateLLMDefaults),
    loadRoundUnitCapDefaults: vi.fn(
      async ({ language, participants, rate }: RoundUnitCapDefaultsInput) => ({
        round_unit_caps: defaultsFor(language, participants, rate),
      }),
    ),
    create,
  } satisfies DebateCreateController;
}

function renderCreate(testController: DebateCreateController) {
  useSessionMock.mockReturnValue(teacherSession());
  return renderComponent(
    <AppShell role="teacher">
      <TeacherDebateCreate controller={testController} />
    </AppShell>,
  );
}

async function waitForDefaultCaps(values: string[]) {
  await waitFor(() => {
    expect(
      [1, 2, 3, 4].map(
        (round) =>
          (
            screen.getByRole("spinbutton", {
              name: `R${round} — 每人每轮汉字数`,
            }) as HTMLInputElement
          ).value,
      ),
    ).toEqual(values);
  });
  await waitFor(() => {
    expect(
      (screen.getByRole("button", { name: "Done" }) as HTMLButtonElement)
        .disabled,
    ).toBe(false);
  });
}

function chooseAgents(count: number) {
  ["Bowen", "Kaikai", "Maya"].forEach((name, index) => {
    const button = screen.getByRole("button", { name });
    const selected = button.getAttribute("aria-pressed") === "true";
    if (selected !== index < count) fireEvent.click(button);
  });
}

function enterTopic() {
  fireEvent.change(screen.getByLabelText("Topic"), {
    target: { value: "How should a classroom share speaking time?" },
  });
}

describe("debate round unit caps", () => {
  it("keeps edited R2 and refreshes only untouched rounds when participant count changes", async () => {
    const testController = controller();
    renderCreate(testController);
    await screen.findByRole("button", { name: "Bowen" });
    await waitForDefaultCaps(["140", "115", "115", "140"]);

    fireEvent.change(screen.getByLabelText("R2 — 每人每轮汉字数"), {
      target: { value: "123" },
    });
    chooseAgents(3);

    await waitFor(() => {
      expect(
        (screen.getByLabelText("R1 — 每人每轮汉字数") as HTMLInputElement)
          .value,
      ).toBe("90");
    });
    expect(
      (screen.getByLabelText("R2 — 每人每轮汉字数") as HTMLInputElement).value,
    ).toBe("123");
    expect(
      (screen.getByLabelText("R3 — 每人每轮汉字数") as HTMLInputElement).value,
    ).toBe("75");
    expect(
      (screen.getByLabelText("R4 — 每人每轮汉字数") as HTMLInputElement).value,
    ).toBe("90");
    expect(
      testController.loadRoundUnitCapDefaults?.mock.calls.at(-1)?.[0],
    ).toMatchObject({
      courseId,
      language: "zh",
      participants: 3,
      rate: 1,
    });

    fireEvent.change(screen.getByRole("spinbutton", { name: "rate" }), {
      target: { value: "1.25" },
    });
    await waitFor(() => {
      expect(
        (screen.getByLabelText("R1 — 每人每轮汉字数") as HTMLInputElement)
          .value,
      ).toBe("115");
    });
    expect(
      (screen.getByLabelText("R2 — 每人每轮汉字数") as HTMLInputElement).value,
    ).toBe("123");
    expect(
      (screen.getByLabelText("R3 — 每人每轮汉字数") as HTMLInputElement).value,
    ).toBe("95");
    expect(
      testController.loadRoundUnitCapDefaults?.mock.calls.at(-1)?.[0],
    ).toMatchObject({ participants: 3, rate: 1.25 });
  });

  it("recalculates untouched rounds by language and retains edited values with a unit-change notice", async () => {
    renderCreate(controller());
    await screen.findByRole("button", { name: "Bowen" });
    await waitForDefaultCaps(["140", "115", "115", "140"]);
    fireEvent.change(screen.getByLabelText("R1 — 每人每轮汉字数"), {
      target: { value: "123" },
    });

    fireEvent.click(screen.getByRole("button", { name: "English" }));
    await waitFor(() => {
      expect(
        (
          screen.getByLabelText(
            "R2 — words per person per round",
          ) as HTMLInputElement
        ).value,
      ).toBe("75");
    });
    expect(
      (
        screen.getByLabelText(
          "R1 — words per person per round",
        ) as HTMLInputElement
      ).value,
    ).toBe("123");
    expect(
      screen.getByText("The counting unit changed; edited values were kept."),
    ).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "中文" }));
    await waitFor(() =>
      expect(screen.getByLabelText("R1 — 每人每轮汉字数")).toHaveProperty(
        "value",
        "123",
      ),
    );
    expect(
      screen.getByText("计数单位已变；已编辑的数字保持不变。"),
    ).toBeTruthy();
  });

  it("updates the read-only duration from caps, participant count, language, and voice rate", async () => {
    renderCreate(controller());
    await screen.findByRole("button", { name: "Bowen" });
    await waitForDefaultCaps(["140", "115", "115", "140"]);
    expect(screen.getByTestId("estimated-debate-duration").textContent).toBe(
      "4.93 min",
    );

    [100, 200, 300, 400].forEach((value, index) => {
      fireEvent.change(
        screen.getByLabelText(`R${index + 1} — 每人每轮汉字数`),
        { target: { value: String(value) } },
      );
    });
    chooseAgents(2);
    fireEvent.change(screen.getByRole("spinbutton", { name: "rate" }), {
      target: { value: "1.25" },
    });
    await waitFor(() =>
      expect(screen.getByTestId("estimated-debate-duration").textContent).toBe(
        "7.73 min",
      ),
    );

    fireEvent.click(screen.getByRole("button", { name: "English" }));
    await waitFor(() =>
      expect(screen.getByTestId("estimated-debate-duration").textContent).toBe(
        "11.85 min",
      ),
    );
    chooseAgents(3);
    await waitFor(() =>
      expect(screen.getByTestId("estimated-debate-duration").textContent).toBe(
        "17.78 min",
      ),
    );
    expect(
      screen.getByText(
        "Assumes 3 Agents, voice rate 1.25, and a 10% pause allowance. This is an estimate, not a timer or actual playback duration.",
      ),
    ).toBeTruthy();
  });

  it.each(["39", "2001"])(
    "rejects invalid round cap %s without changing the entered value or sending it",
    async (value: string) => {
      const create = vi
        .fn()
        .mockResolvedValue({ id: "debate-id" } as DebateDetail);
      renderCreate(controller(create));
      await screen.findByRole("button", { name: "Bowen" });
      await waitForDefaultCaps(["140", "115", "115", "140"]);
      chooseAgents(2);
      enterTopic();
      const firstCap = screen.getByLabelText(
        "R1 — 每人每轮汉字数",
      ) as HTMLInputElement;
      fireEvent.change(firstCap, { target: { value } });
      fireEvent.click(screen.getByRole("button", { name: "Done" }));

      expect(
        await screen.findByText(
          "R1 must be an integer from 40 to 2,000 汉字数.",
        ),
      ).toBeTruthy();
      expect(firstCap.value).toBe(value);
      expect(create).not.toHaveBeenCalled();
    },
  );
});
