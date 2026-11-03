import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  resetBackgroundMusicForTests,
  startBackgroundMusic,
  stopBackgroundMusic,
  toggleBackgroundMusic,
} from "../lib/background-music";

// 2026-11-03: a music key beside Mayaform in the open sidebar. Off by
// default, never started by the page, loops the list.
class FakeAudio {
  static made: FakeAudio[] = [];
  src = "";
  preload = "";
  paused = true;
  handlers = new Map<string, Array<() => void>>();
  play = vi.fn(() => {
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

const TRACKS = ["/music/a.mp3", "/music/b.mp3"];

describe("background music", () => {
  beforeEach(() => {
    FakeAudio.made = [];
    vi.stubGlobal("Audio", FakeAudio);
    resetBackgroundMusicForTests();
  });
  afterEach(() => {
    resetBackgroundMusicForTests();
    vi.unstubAllGlobals();
  });

  it("makes no player until it is started", () => {
    expect(FakeAudio.made).toHaveLength(0);
  });

  it("plays the list in order and starts again after the last track", () => {
    startBackgroundMusic(TRACKS);
    const [player] = FakeAudio.made;
    expect(player.src).toBe("/music/a.mp3");
    expect(player.play).toHaveBeenCalledTimes(1);
    player.fire("ended");
    expect(player.src).toBe("/music/b.mp3");
    player.fire("ended");
    expect(player.src).toBe("/music/a.mp3");
    expect(player.play).toHaveBeenCalledTimes(3);
  });

  it("toggles with one player and resumes where it paused", () => {
    toggleBackgroundMusic(TRACKS);
    FakeAudio.made[0].fire("ended");
    toggleBackgroundMusic(TRACKS);
    expect(FakeAudio.made[0].pause).toHaveBeenCalled();
    toggleBackgroundMusic(TRACKS);
    expect(FakeAudio.made).toHaveLength(1);
    expect(FakeAudio.made[0].src).toBe("/music/b.mp3");
  });

  it("does nothing without tracks", () => {
    startBackgroundMusic([]);
    expect(FakeAudio.made).toHaveLength(0);
  });

  it("stops at logout", () => {
    startBackgroundMusic(TRACKS);
    stopBackgroundMusic();
    expect(FakeAudio.made[0].paused).toBe(true);
  });
});

describe("track list from the deployment", () => {
  // Site paths only: the production CSP allows media from the site alone.
  it("keeps site paths in order, drops anything else", async () => {
    const { parseTracks } = await import("../lib/background-music");
    expect(
      parseTracks(
        " /music/a.mp3, https://cdn.example.org/b.m4a ,javascript:alert(1),//evil.example/c.mp3,http://x/d.mp3,,",
      ),
    ).toEqual(["/music/a.mp3"]);
    expect(parseTracks(undefined)).toEqual([]);
  });
});
