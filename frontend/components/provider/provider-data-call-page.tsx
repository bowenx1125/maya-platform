"use client";

import { useMemo } from "react";

import { useSession } from "../session-provider";
import { ProviderDataCallDisclosure } from "./provider-data-call-disclosure";

export function TeacherProviderDataCallPage({
  manifestHash,
}: {
  manifestHash: string;
}) {
  const { api, identityGeneration, user } = useSession();
  const scopeKey = `${user?.id ?? "anonymous"}:${identityGeneration}:${manifestHash}`;
  const controller = useMemo(
    () => ({
      load: () => api.getProviderDataCallDisclosure(manifestHash),
      confirm: (request: {
        policy_hash: string;
        manifest_hash: string;
        expected_revision: number;
      }) => api.confirmProviderDataCallDisclosure(request),
    }),
    [api, manifestHash],
  );
  return (
    <ProviderDataCallDisclosure
      key={scopeKey}
      controller={controller}
      scopeKey={scopeKey}
    />
  );
}
