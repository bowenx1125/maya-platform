"use client";

import { Suspense, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { RouteGuard } from "../../../components/session-provider";

function RecordRedirect() {
  const router = useRouter();
  const query = useSearchParams();

  useEffect(() => {
    const groupId = query.get("group_id");
    router.replace(
      groupId ? `/teacher/quizzes/records?group_id=${groupId}` : "/teacher/quizzes/records",
    );
  }, [router, query]);

  return null;
}

// The query is read in the browser, so following a link here needs no
// server render.
export default function TeacherRecordPage() {
  return (
    <Suspense fallback={null}>
      <RouteGuard role="teacher">
        <RecordRedirect />
      </RouteGuard>
    </Suspense>
  );
}
