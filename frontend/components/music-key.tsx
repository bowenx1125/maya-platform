"use client";

import {
  musicAvailable,
  toggleMusic,
  useMusicOn,
  useMusicPlaying,
  type MusicChannelName,
} from "../lib/background-music";
import { useT } from "../lib/i18n";
import { cn } from "../lib/utils";
import { Button } from "./ui/button";
import { WorkspaceIcon } from "./workspace-icon";

export function MusicKey({
  channel,
  className,
}: {
  channel: MusicChannelName;
  className?: string;
}) {
  const t = useT();
  const on = useMusicOn(channel);
  const playing = useMusicPlaying(channel);
  const available = musicAvailable(channel);
  const state = !available ? "empty" : on ? "playing" : "stop";
  return (
    <Button
      variant="neutral"
      size="icon"
      data-music-key={channel}
      data-music-state={state}
      data-playing={playing || undefined}
      className={cn(
        "relative size-11 shrink-0 rounded-[10px] border-[3px] aria-pressed:bg-main",
        playing &&
          "[&_svg]:origin-bottom [&_svg]:animate-[music-hop_0.6s_ease-in-out_infinite] motion-reduce:[&_svg]:animate-none",
        className,
      )}
      aria-label={
        state === "empty"
          ? t("musicUnavailable")
          : on
            ? t("musicPause")
            : t("musicPlay")
      }
      aria-pressed={on}
      disabled={!available}
      onClick={() => toggleMusic(channel)}
    >
      <WorkspaceIcon name="music" size={18} />
    </Button>
  );
}
