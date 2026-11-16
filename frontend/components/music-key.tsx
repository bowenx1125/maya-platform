"use client";

import {
  musicAvailable,
  toggleMusic,
  useMusicOn,
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
  const available = musicAvailable(channel);
  const state = !available ? "empty" : on ? "playing" : "stop";
  return (
    <Button
      variant="neutral"
      size="icon"
      data-music-key={channel}
      data-music-state={state}
      data-playing={on || undefined}
      className={cn(
        "relative size-11 shrink-0 rounded-[10px] border-[3px] aria-pressed:bg-main",
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
