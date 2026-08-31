"use client";

import { useMemo } from "react";

import { useSession } from "../session-provider";
import { ProviderDataCallDebateList } from "./provider-data-call-debate-list";

export function TeacherProviderDataCallDebatePage({
  debateId,
}: {
  debateId: string;
}) {
  const { api } = useSession();
  const controller = useMemo(
    () => ({
      load: () => api.listProviderDataCallDebateManifests(debateId),
    }),
    [api, debateId],
  );
  return <ProviderDataCallDebateList controller={controller} />;
}
