"use client";

import { useEffect, useRef, useState } from "react";
import type { components } from "../lib/api/generated/schema";
import { DebateCardCheck } from "./debate/preview/debate-card-check";

type StoredCard = components["schemas"]["AgentCardResponse"];
type LoadedCard = StoredCard & { keepPolling?: boolean };

export function AgentDebateCardCheck({
  agentName,
  agentMd,
  storedStatus = null,
  load,
}: {
  agentName: string;
  agentMd: string;
  /** Status of the stored agent_debate_cards row. Null when none exists. */
  storedStatus?: StoredCard["card_status"] | null;
  load: () => Promise<LoadedCard>;
}) {
  const [result, setResult] = useState<LoadedCard | null>(null);
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
        // A missing version is Compiling, not a failed card, and there is no
        // in-flight compile to poll.
        if (
          next.card_status !== "compiling" ||
          next.keepPolling === false ||
          Date.now() >= deadline
        )
          break;
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
      status={result?.card_status}
      tagStatus={result ? null : storedStatus}
      showWhenUnknown
      card={result?.card}
      card_teacher_reason={result?.card_teacher_reason}
      agentMd={agentMd}
      onCheck={() => void check()}
    />
  );
}
