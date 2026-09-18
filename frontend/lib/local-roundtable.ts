export type LocalDebateTurn = {
  character: string;
  speaker_id: string;
  speech: string;
  audio_file: string;
  duration_seconds: number;
};

export type LocalDebateManifest = {
  topic: string;
  turns: LocalDebateTurn[];
};

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

export function parseLocalDebateManifest(value: unknown): LocalDebateManifest {
  const root = record(value);
  if (!root || typeof root.topic !== "string" || !root.topic.trim()) {
    throw new Error("辩题无效");
  }
  if (root.topic.length > 300 || !Array.isArray(root.turns)) {
    throw new Error("辩论清单无效");
  }
  const turns: LocalDebateTurn[] = [];
  for (const item of root.turns) {
    const turn = record(item);
    if (!turn) throw new Error("发言无效");
    if (turn.kind === "sample" || turn.audio_file === "woman.wav") continue;
    if (
      typeof turn.character !== "string" ||
      !turn.character.trim() ||
      turn.character.length > 80 ||
      typeof turn.speaker_id !== "string" ||
      !turn.speaker_id.trim() ||
      turn.speaker_id.length > 80 ||
      typeof turn.speech !== "string" ||
      !turn.speech.trim() ||
      turn.speech.length > 2000 ||
      typeof turn.audio_file !== "string" ||
      !/^[a-z0-9_-]+\.wav$/i.test(turn.audio_file) ||
      typeof turn.duration_seconds !== "number" ||
      !Number.isFinite(turn.duration_seconds) ||
      turn.duration_seconds <= 0 ||
      turn.duration_seconds > 600
    ) {
      throw new Error("发言或音频清单无效");
    }
    turns.push(turn as LocalDebateTurn);
  }
  if (turns.length < 2 || turns.length > 5) {
    throw new Error("辩论须包含 2 至 5 位发言者");
  }
  return { topic: root.topic.trim(), turns };
}
