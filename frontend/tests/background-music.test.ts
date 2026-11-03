import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  MUSIC_FADE_MS,
  enterStageMusic,
  leaveStageMusic,
  musicStateForTests,
  parseTracks,
  resetBackgroundMusicForTests,
  setMusicAccountId,
  startDefaultMusic,
  stopBackgroundMusic,
  toggleMusic,
  useMusicPlaying,
} from "../lib/background-music";

// 2026-11-03: a music key beside Mayaform (workspace music, on by default
// per account) and one on the 3D stage (its own music, on while the stage
// is open). Every hand-off fades; each list loops. A browser that refuses
// sound before a gesture keeps the key on and starts on the first gesture;
// a workspace key turned off by hand is remembered per account.
let refuse: false | "autoplay" | "broken" = false;

class FakeAudio {
  static made: FakeAudio[] = [];
  src = "";
  preload = "";
  volume = 1;
  paused = true;
  handlers = new Map<string, Array<() => void>>();
  play = vi.fn(() => {
    if (refuse === "autoplay") {
      return Promise.reject(
        Object.assign(new Error("no gesture"), { name: "NotAllowedError" }),
      );
    }
    if (refuse === "broken") {
      return Promise.reject(
        Object.assign(new Error("bad file"), { name: "NotSupportedError" }),
      );
    }
    this.paused = false;
    return Promise.resolve();
  });
  pause = vi.fn(() => {
    this.paused = true;
  });
  constructor() {
    FakeAudio.made.push(this);
  }
  addEventListener(name: string, handler: () => void) {
    this.handlers.set(name, [...(this.handlers.get(name) ?? []), handler]);
  }
  fire(name: string) {
    for (const handler of this.handlers.get(name) ?? []) handler();
  }
}

const WORKSPACE = ["/music/a.mp3", "/music/b.mp3"];
const STAGE = ["/music/stage.mp3"];

async function settle() {
  await vi.advanceTimersByTimeAsync(MUSIC_FADE_MS + 100);
}

function player(name: "workspace" | "stage") {
  return musicStateForTests(name).audio as unknown as FakeAudio;
}

describe("background music", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    refuse = false;
    window.localStorage.clear();
    FakeAudio.made = [];
    vi.stubGlobal("Audio", FakeAudio);
    resetBackgroundMusicForTests({ workspace: WORKSPACE, stage: STAGE });
    setMusicAccountId("u1");
  });
  afterEach(() => {
    resetBackgroundMusicForTests();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("makes no player before the site loads", () => {
    expect(FakeAudio.made).toHaveLength(0);
    expect(musicStateForTests("workspace").wanted).toBe(false);
  });

  it("starts the workspace music by default and buffers ahead", async () => {
    startDefaultMusic();
    const audio = player("workspace");
    expect(audio.preload).toBe("auto");
    expect(musicStateForTests("workspace").wanted).toBe(true);
    await settle();
    expect(audio.paused).toBe(false);
    expect(audio.volume).toBeCloseTo(0.6);
  });

  it("keeps the key on when autoplay is refused and plays on the first gesture", async () => {
    refuse = "autoplay";
    startDefaultMusic();
    await settle();
    expect(musicStateForTests("workspace")).toMatchObject({
      wanted: true,
      audible: false,
      waiting: true,
    });
    refuse = false;
    document.body.dispatchEvent(new Event("pointerdown", { bubbles: true }));
    await settle();
    expect(player("workspace").paused).toBe(false);
    expect(player("workspace").volume).toBeCloseTo(0.6);
    // The listener is gone after the first gesture.
    const plays = player("workspace").play.mock.calls.length;
    document.body.dispatchEvent(new Event("keydown", { bubbles: true }));
    expect(player("workspace").play.mock.calls.length).toBe(plays);
  });

  it("treats a press on the waiting key as the gesture, not as off", async () => {
    refuse = "autoplay";
    startDefaultMusic();
    await settle();
    refuse = false;
    toggleMusic("workspace");
    await settle();
    expect(musicStateForTests("workspace").wanted).toBe(true);
    expect(player("workspace").paused).toBe(false);
  });

  it("remembers workspace off per account, not across accounts", async () => {
    startDefaultMusic();
    await settle();
    toggleMusic("workspace");
    expect(window.localStorage.getItem("maya.bgm.off.workspace.u1")).toBe("1");
    resetBackgroundMusicForTests({ workspace: WORKSPACE, stage: STAGE });
    setMusicAccountId("u1");
    startDefaultMusic();
    expect(musicStateForTests("workspace").wanted).toBe(false);
    // Another account on the same browser still auto-starts.
    resetBackgroundMusicForTests({ workspace: WORKSPACE, stage: STAGE });
    setMusicAccountId("u2");
    startDefaultMusic();
    expect(musicStateForTests("workspace").wanted).toBe(true);
    // Turning it back on forgets the choice for that account.
    resetBackgroundMusicForTests({ workspace: WORKSPACE, stage: STAGE });
    setMusicAccountId("u1");
    toggleMusic("workspace");
    resetBackgroundMusicForTests({ workspace: WORKSPACE, stage: STAGE });
    setMusicAccountId("u1");
    startDefaultMusic();
    expect(musicStateForTests("workspace").wanted).toBe(true);
  });

  it("always starts the stage on enter; stage off is not remembered", async () => {
    enterStageMusic();
    await settle();
    toggleMusic("stage");
    leaveStageMusic();
    enterStageMusic();
    expect(musicStateForTests("stage").wanted).toBe(true);
    expect(window.localStorage.getItem("maya.bgm.off.stage")).toBeNull();
  });

  it("keeps the workspace preference across logout", async () => {
    startDefaultMusic();
    await settle();
    toggleMusic("workspace");
    stopBackgroundMusic();
    expect(window.localStorage.getItem("maya.bgm.off.workspace.u1")).toBe("1");
    resetBackgroundMusicForTests({ workspace: WORKSPACE, stage: STAGE });
    setMusicAccountId("u1");
    startDefaultMusic();
    expect(musicStateForTests("workspace").wanted).toBe(false);
  });

  it("ignores the legacy unscoped workspace off key", async () => {
    window.localStorage.setItem("maya.bgm.off.workspace", "1");
    setMusicAccountId("u1");
    startDefaultMusic();
    expect(musicStateForTests("workspace").wanted).toBe(true);
    expect(window.localStorage.getItem("maya.bgm.off.workspace")).toBeNull();
  });

  it("fades the workspace music in and loops its list", async () => {
    toggleMusic("workspace");
    const audio = player("workspace");
    expect(audio.src).toBe("/music/a.mp3");
    expect(audio.volume).toBe(0);
    await settle();
    expect(audio.volume).toBeCloseTo(0.6);
    audio.fire("ended");
    expect(audio.src).toBe("/music/b.mp3");
    audio.fire("ended");
    expect(audio.src).toBe("/music/a.mp3");
  });

  it("fades out and pauses when its key is pressed again", async () => {
    toggleMusic("workspace");
    await settle();
    toggleMusic("workspace");
    expect(musicStateForTests("workspace").wanted).toBe(false);
    await settle();
    expect(player("workspace").volume).toBe(0);
    expect(player("workspace").paused).toBe(true);
  });

  it("hands the speakers to the stage and back with fades", async () => {
    toggleMusic("workspace");
    await settle();
    enterStageMusic();
    // The stage starts by itself, at its own quieter level.
    expect(musicStateForTests("stage").wanted).toBe(true);
    await settle();
    expect(player("workspace").paused).toBe(true);
    expect(player("stage").paused).toBe(false);
    expect(player("stage").volume).toBeCloseTo(0.35);
    // The workspace key stays on while the stage plays.
    expect(musicStateForTests("workspace").wanted).toBe(true);

    leaveStageMusic();
    expect(musicStateForTests("stage").wanted).toBe(false);
    await settle();
    expect(player("stage").paused).toBe(true);
    expect(player("workspace").paused).toBe(false);
    expect(player("workspace").volume).toBeCloseTo(0.6);
  });

  it("leaves the workspace silent after the stage when its key was off", async () => {
    enterStageMusic();
    await settle();
    leaveStageMusic();
    await settle();
    expect(musicStateForTests("workspace").audio).toBeNull();
    expect(player("stage").paused).toBe(true);
  });

  it("pauses the stage music from its key without waking the workspace", async () => {
    toggleMusic("workspace");
    await settle();
    enterStageMusic();
    await settle();
    toggleMusic("stage");
    await settle();
    expect(player("stage").paused).toBe(true);
    expect(player("workspace").paused).toBe(true);
    // Turning the workspace key off on the stage changes what comes back.
    toggleMusic("workspace");
    leaveStageMusic();
    await settle();
    expect(player("workspace").paused).toBe(true);
  });

  it("keeps the stage key on when autoplay is refused", async () => {
    refuse = "autoplay";
    enterStageMusic();
    await settle();
    expect(musicStateForTests("stage")).toMatchObject({
      wanted: true,
      waiting: true,
    });
    refuse = false;
    document.body.dispatchEvent(new Event("keydown", { bubbles: true }));
    await settle();
    expect(player("stage").paused).toBe(false);
  });

  it("turns the key off when the music cannot load", async () => {
    refuse = "broken";
    enterStageMusic();
    await settle();
    expect(musicStateForTests("stage").wanted).toBe(false);
  });

  it("stops everything at logout", async () => {
    toggleMusic("workspace");
    await settle();
    enterStageMusic();
    stopBackgroundMusic();
    expect(player("workspace").paused).toBe(true);
    expect(player("stage").paused).toBe(true);
    expect(musicStateForTests("workspace").wanted).toBe(false);
  });
  it("reports playing only while the element really plays and no fade-out began", async () => {
    const { result } = renderHook(() => useMusicPlaying("workspace"));
    refuse = "autoplay";
    act(() => startDefaultMusic());
    await act(settle);
    // Wanted but blocked: not playing.
    expect(musicStateForTests("workspace").wanted).toBe(true);
    expect(result.current).toBe(false);
    refuse = false;
    act(() => toggleMusic("workspace"));
    await act(settle);
    act(() => player("workspace").fire("playing"));
    expect(result.current).toBe(true);
    act(() => toggleMusic("workspace"));
    expect(result.current).toBe(false);
    act(() => player("workspace").fire("pause"));
    expect(musicStateForTests("workspace").playing).toBe(false);
  });
});

describe("track list from the deployment", () => {
  // Site paths only: the production CSP allows media from the site alone.
  it("keeps site paths in order, drops anything else", () => {
    expect(
      parseTracks(
        " /music/a.mp3, https://cdn.example.org/b.m4a ,javascript:alert(1),//evil.example/c.mp3,http://x/d.mp3,,",
      ),
    ).toEqual(["/music/a.mp3"]);
    expect(parseTracks(undefined)).toEqual([]);
  });
});
