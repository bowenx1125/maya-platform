import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const session = vi.hoisted(() => ({
  user: {
    id: "student-music",
    display_name: "Student",
    username: "student",
    courses: [] as { course_id: string; role: string }[],
    groups: [],
  },
  api: {},
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/student",
  useRouter: () => ({ replace: vi.fn() }),
}));
vi.mock("../components/session-provider", () => ({
  useSession: () => ({ ...session, logout: vi.fn() }),
}));

import { AppShell, SIDEBAR_COLLAPSED_KEY } from "../components/app-shell";
import { MusicKey } from "../components/music-key";
import {
  BETA_DOCK,
  BETA_DOCK_MUSIC_KEY,
} from "../components/debate-beta/stage/beta-chrome";
import {
  enterStageMusic,
  musicStateForTests,
  resetBackgroundMusicForTests,
} from "../lib/background-music";

function assertInteractive(button: HTMLElement) {
  expect(button.getAttribute("disabled")).toBeNull();
  for (
    let element: HTMLElement | null = button;
    element;
    element = element.parentElement
  ) {
    expect(element.classList.contains("pointer-events-none")).toBe(false);
    expect(element.getAttribute("inert")).toBeNull();
  }
}

function toggleTwice(button: HTMLElement, channel: "workspace" | "stage") {
  assertInteractive(button);
  expect(button.getAttribute("data-slot")).toBe("button");
  expect(button.getAttribute("aria-pressed")).toBe("false");
  expect(button.getAttribute("data-music-state")).toBe("stop");
  fireEvent.click(button);
  expect(button.getAttribute("aria-pressed")).toBe("true");
  expect(button.getAttribute("data-music-state")).toBe("playing");
  expect(musicStateForTests(channel).wanted).toBe(true);
  expect(HTMLMediaElement.prototype.play).toHaveBeenCalled();
  fireEvent.click(button);
  expect(button.getAttribute("aria-pressed")).toBe("false");
  expect(button.getAttribute("data-music-state")).toBe("stop");
  expect(musicStateForTests(channel).wanted).toBe(false);
}

beforeEach(() => {
  window.localStorage.clear();
  session.user.courses = [];
  vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
  resetBackgroundMusicForTests({
    workspace: ["/music/lobby.m4a"],
    stage: ["/music/stage.m4a"],
  });
});

afterEach(() => {
  cleanup();
  resetBackgroundMusicForTests();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("student music key", () => {
  describe.each(["expanded", "collapsed", "mobile"])(
    "%s playback animation",
    (layout) => {
      function mountKey() {
        if (layout === "collapsed") {
          window.localStorage.setItem(SIDEBAR_COLLAPSED_KEY, "1");
        }
        if (layout === "mobile") {
          vi.stubGlobal("matchMedia", () => ({
            matches: true,
            addEventListener: vi.fn(),
            removeEventListener: vi.fn(),
          }));
        }
        render(<AppShell role="student">Content</AppShell>);
        if (layout === "mobile") {
          fireEvent.click(
            screen.getByRole("button", { name: "Expand sidebar" }),
          );
        }
        return screen.getByRole("button", { name: "Play music" });
      }

      function expectAnimation(button: HTMLElement, playing: boolean) {
        expect(button.hasAttribute("data-playing")).toBe(playing);
        expect(button.className.includes("[&_svg]:animate-[music-hop_")).toBe(
          playing,
        );
        if (playing) {
          expect(button.className).toContain(
            "motion-reduce:[&_svg]:animate-none",
          );
        }
      }

      it("waits for real playing, stops on pause/end/error, and restarts with the next playing event", async () => {
        const button = mountKey();
        expectAnimation(button, false);
        expect(musicStateForTests("workspace").audio).toBeNull();
        await act(async () => fireEvent.click(button));
        const audio = musicStateForTests("workspace").audio!;
        expect(button.getAttribute("aria-pressed")).toBe("true");
        expectAnimation(button, false);
        for (const event of ["pause", "ended", "error"] as const) {
          fireEvent.playing(audio);
          expectAnimation(button, true);
          fireEvent(audio, new Event(event));
          expectAnimation(button, false);
        }
      });

      it("stays still while autoplay is blocked, then animates only after playback starts", async () => {
        vi.mocked(HTMLMediaElement.prototype.play).mockRejectedValueOnce(
          Object.assign(new Error("gesture required"), {
            name: "NotAllowedError",
          }),
        );
        const button = mountKey();
        await act(async () => fireEvent.click(button));
        expect(musicStateForTests("workspace").waiting).toBe(true);
        expectAnimation(button, false);
        await act(async () => fireEvent.click(button));
        expectAnimation(button, false);
        fireEvent.playing(musicStateForTests("workspace").audio!);
        expectAnimation(button, true);
        fireEvent.click(button);
        expectAnimation(button, false);
      });
    },
  );

  it("lets the expanded capsule's music segment receive clicks through its moving frame", () => {
    render(<AppShell role="student">Content</AppShell>);
    const button = screen.getByRole("button", { name: "Play music" });
    const capsule = button.parentElement!;
    // PRESS_MOTION adds a positioned ::after on hover/press. The frame must
    // pass those hits through to the segment, as the teacher capsule does.
    expect(capsule.classList.contains("after:pointer-events-none")).toBe(true);
    toggleTwice(button, "workspace");
    expect(
      window.localStorage.getItem("maya.bgm.off.workspace.student-music"),
    ).toBe("1");
  });

  it("keeps an operable music key when the student sidebar is collapsed", () => {
    window.localStorage.setItem(SIDEBAR_COLLAPSED_KEY, "1");
    render(<AppShell role="student">Content</AppShell>);
    expect(
      document.querySelector("header")?.getAttribute("data-collapsed"),
    ).toBe("true");
    toggleTwice(
      screen.getByRole("button", { name: "Play music" }),
      "workspace",
    );
  });

  it("keeps the mobile key inside the drawer above its backdrop", () => {
    vi.stubGlobal("matchMedia", () => ({
      matches: true,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }));
    render(<AppShell role="student">Content</AppShell>);
    fireEvent.click(screen.getByRole("button", { name: "Expand sidebar" }));
    const button = screen.getByRole("button", { name: "Play music" });
    expect(button.closest("header")?.className).toContain("max-[900px]:z-50");
    expect(button.className).toContain("z-10");
    toggleTwice(button, "workspace");
  });

  it("toggles the stage channel inside the same chrome as neighbouring dock controls", () => {
    enterStageMusic();
    render(
      <div className={BETA_DOCK}>
        <MusicKey channel="stage" className={BETA_DOCK_MUSIC_KEY} />
      </div>,
    );
    const button = screen.getByRole("button", { name: "Pause music" });
    fireEvent.click(button);
    toggleTwice(button, "stage");
  });

  it("disables the key only when its channel has no configured tracks", () => {
    resetBackgroundMusicForTests({ workspace: [], stage: [] });
    render(<MusicKey channel="workspace" />);
    const button = screen.getByRole("button", { name: "No music yet" });
    expect(button.getAttribute("disabled")).not.toBeNull();
    expect(button.getAttribute("data-music-state")).toBe("empty");
    fireEvent.click(button);
    expect(musicStateForTests("workspace").wanted).toBe(false);
  });

  it("recovers from a first-gesture refusal when the music key itself is pressed again", async () => {
    vi.mocked(HTMLMediaElement.prototype.play).mockRejectedValueOnce(
      Object.assign(new Error("gesture required"), { name: "NotAllowedError" }),
    );
    render(<MusicKey channel="workspace" />);
    const button = screen.getByRole("button", { name: "Play music" });
    await act(async () => fireEvent.click(button));
    expect(musicStateForTests("workspace").waiting).toBe(true);
    fireEvent.click(button);
    expect(musicStateForTests("workspace").waiting).toBe(false);
    expect(button.getAttribute("aria-pressed")).toBe("true");
  });

  it("renders no music key on a teacher surface, including a teacher visiting a student page", () => {
    session.user.courses = [{ course_id: "course", role: "teacher" }];
    render(<AppShell role="student">Content</AppShell>);
    expect(document.querySelector("[data-music-key]")).toBeNull();
  });
});
