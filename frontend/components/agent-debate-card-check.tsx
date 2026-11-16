"use client";

import { useEffect, useRef, useState } from "react";
import type { components } from "../lib/api/generated/schema";
import { DebateCardCheck } from "./debate/preview/debate-card-check";

type StoredCard = components["schemas"]["AgentCardResponse"];

export function AgentDebateCardCheck({
  agentName,
  agentMd,
  voiceProfileId,
  load,
}: {
  agentName: string;
  agentMd: string;
  voiceProfileId?: string | null;
  load: () => Promise<StoredCard>;
}) {
  const [result, setResult] = useState<StoredCard | null>(null);
  const pending = useRef(false);
  const active = useRef(true);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);

  async function check() {
    if (pending.current) return;
    pending.current = true;
    setResult({ card_status: "compiling" });
    try {
      const deadline = Date.now() + 60_000;
      while (active.current) {
        const next = await load();
        if (!active.current) return;
        setResult(next);
        if (next.card_status !== "compiling" || Date.now() >= deadline) break;
        await new Promise((resolve) => setTimeout(resolve, 1000));
      }
    } catch {
      setResult({ card_status: "fallback", card_teacher_reason: "other" });
    } finally {
      pending.current = false;
    }
  }

  return (
    <DebateCardCheck
      agentName={agentName}
      status={result?.card_status ?? "compiling"}
      card={result?.card}
      card_teacher_reason={result?.card_teacher_reason}
      voiceProfileId={voiceProfileId}
      agentMd={agentMd}
      onCheck={() => void check()}
    />
  );
}
