"use client";

import { useMemo } from "react";

import { useSession } from "../session-provider";
import { ProviderDataCallPublicationList } from "./provider-data-call-publication-list";

export function TeacherProviderDataCallPublicationPage({
  agentVersionId,
}: {
  agentVersionId: string;
}) {
  const { api } = useSession();
  const controller = useMemo(
    () => ({
      load: () => api.listProviderDataCallPublicationManifests(agentVersionId),
    }),
    [agentVersionId, api],
  );
  return <ProviderDataCallPublicationList controller={controller} />;
}
