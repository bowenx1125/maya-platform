import { redirect } from "next/navigation";

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string | string[] }>;
}) {
  const requestedNext = (await searchParams).next;
  const next = Array.isArray(requestedNext) ? requestedNext[0] : requestedNext;
  redirect(next ? `/?next=${encodeURIComponent(next)}` : "/");
}
