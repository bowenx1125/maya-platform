import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  MUSIC_FADE_MS,
  enterStageMusic,
  leaveStageMusic,
  musicStateForTests,
  parseTracks,
  resetBackgroundMusicForTests,
  stopBackgroundMusic,
  toggleMusic,
} from "../lib/background-music";

// 2026-11-03: a music key beside Mayaform (workspace music, off by default)
// and one on the 3D stage (its own music, on while the stage is open). Every
// hand-off fades; each list loops.
let refuse = false;

class FakeAudio {
  static made: FakeAudio[] = [];
  src = "";
  preload = "";
  volume = 1;
  paused = true;
  handlers = new Map<string, Array<() => void>>();
  play = vi.fn(() => {
    if (refuse) return Promise.reject(new Error("NotAllowedError"));
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
    FakeAudio.made = [];
    vi.stubGlobal("Audio", FakeAudio);
    resetBackgroundMusicForTests({ workspace: WORKSPACE, stage: STAGE });
  });
  afterEach(() => {
    resetBackgroundMusicForTests();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("makes no player until a key is pressed", () => {
    expect(FakeAudio.made).toHaveLength(0);
    expect(musicStateForTests("workspace").wanted).toBe(false);
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

  it("gives up quietly when the browser refuses to play", async () => {
    refuse = true;
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
