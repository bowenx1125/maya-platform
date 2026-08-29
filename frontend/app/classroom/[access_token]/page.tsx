import type { Metadata } from "next";

import { AudienceInteractionForm } from "../../../components/interaction";

export const dynamic = "force-dynamic";
export const revalidate = 0;

export const metadata: Metadata = {
  title: "Maya classroom interaction",
  referrer: "no-referrer",
};

export default async function ClassroomInteractionPage({
  params,
}: {
  params: Promise<{ access_token: string }>;
}) {
  const { access_token: accessToken } = await params;
  return <AudienceInteractionForm accessToken={accessToken} />;
}
