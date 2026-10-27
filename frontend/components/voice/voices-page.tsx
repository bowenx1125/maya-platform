"use client";

import { useSession } from "../session-provider";
import { VoiceLibrary } from "./voice-library";

/**
 * The dedicated Voices page (/student/voices, /teacher/voices): the Voice
 * Sticker Album list. A student sees one group's voices (?group_id, or their
 * only group), or every group they belong to. A teacher sees their own
 * personal voices, or listens in on a visited group's (?group_id).
 */
export function VoicesPage({
  role,
  groupId,
  initialCreate = false,
}: {
  role: "student" | "teacher";
  groupId?: string;
  /** Open the create form (legacy ?mode=new). */
  initialCreate?: boolean;
}) {
  const { user, identityGeneration } = useSession();
  const membershipGroupIds = [
    ...new Set((user?.groups ?? []).map((membership) => membership.group_id)),
  ];
  const scope = `${user?.id ?? "anonymous"}:${identityGeneration ?? 0}`;
  if (role === "teacher") {
    const teacherCourseId = user?.courses.find(
      (membership) => membership.role === "teacher",
    )?.course_id;
    return groupId ? (
      <VoiceLibrary
        key={`${scope}:visit:${groupId}`}
        id="voices"
        album
        groupId={groupId}
        listenOnly
      />
    ) : (
      <VoiceLibrary
        key={`${scope}:own`}
        id="voices"
        album
        groupId={null}
        courseId={teacherCourseId ?? null}
      />
    );
  }
  const studentGroupId =
    groupId && membershipGroupIds.includes(groupId)
      ? groupId
      : membershipGroupIds.length === 1
        ? membershipGroupIds[0]
        : null;
  return (
    <VoiceLibrary
      key={`${scope}:${studentGroupId ?? "all"}:${initialCreate ? "new" : "list"}`}
      id="voices"
      album
      groupId={studentGroupId}
      membershipGroupIds={studentGroupId ? [] : membershipGroupIds}
      initialCreate={initialCreate}
    />
  );
}
