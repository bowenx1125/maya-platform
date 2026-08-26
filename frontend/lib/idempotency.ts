"use client";

import { useCallback, useRef } from "react";

import { createIdempotencyHandle, type IdempotencyHandle } from "./api";

/**
 * Keeps handles scoped to one mounted page. A mutation key is removed only
 * when the caller explicitly finishes or abandons that logical intent.
 */
export function useIdempotencyStore() {
  const handles = useRef(new Map<string, IdempotencyHandle>());

  const handleFor = useCallback((intent: string): IdempotencyHandle => {
    const existing = handles.current.get(intent);
    if (existing) return existing;
    const next = createIdempotencyHandle();
    handles.current.set(intent, next);
    return next;
  }, []);

  const finish = useCallback(
    (intent: string, expected?: IdempotencyHandle): void => {
      const handle = handles.current.get(intent);
      if (expected && handle !== expected) return;
      handle?.complete();
      handles.current.delete(intent);
    },
    [],
  );

  const abandon = useCallback(
    (intent: string, expected?: IdempotencyHandle): void => {
      const handle = handles.current.get(intent);
      if (expected && handle !== expected) return;
      handle?.abandon();
      handles.current.delete(intent);
    },
    [],
  );

  return { handleFor, finish, abandon };
}
