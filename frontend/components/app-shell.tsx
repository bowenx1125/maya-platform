"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import workspaceStyles from "./workspace-theme.module.css";
import styles from "./app-shell.module.css";
import { SecretDoor } from "./card-table/secret-door";
import { ViewTransition } from "./view-transition";
import { WorkspaceIcon, type WorkspaceIconName } from "./workspace-icon";
import {
  WorkspaceActionsContext,
  type WorkspaceActionName,
  type WorkspaceActionOptions,
  type WorkspaceActionRegistry,
  type WorkspaceActions,
} from "./workspace-actions";

import { useT } from "./locale";
import {
  endTeacherEnter,
  teacherEnterInProgress,
  trackTeacherLeave,
} from "../lib/teacher-visit";
import { useSession } from "./session-provider";

type ActionRegistration = {
  owner: string;
  priority: number;
  options: WorkspaceActionOptions;
};
type ActionRegistrationState = Partial<
  Record<WorkspaceActionName, ActionRegistration[]>
>;

export function AppShell({
  children,
  role,
}: {
  children: ReactNode;
  role: "student" | "teacher";
}) {
  const t = useT();
  const { api, user, logout, refresh, identityGeneration } = useSession();
  const router = useRouter();
  const pathname = usePathname();
  const [locationHash, setLocationHash] = useState("");
  const [locationSearch, setLocationSearch] = useState("");
  const [busy, setBusy] = useState(false);
  const courseId = user?.courses?.[0]?.course_id;
  const [live, setLive] = useState(false);
  const [actionRegistrations, setActionRegistrations] =
    useState<ActionRegistrationState>({});
  const actionRegistry = useMemo<WorkspaceActionRegistry>(
    () => ({
      register(name, owner, options, priority) {
        setActionRegistrations((current) => {
          const entries = (current[name] ?? []).filter(
            (entry) => entry.owner !== owner,
          );
          return {
            ...current,
            [name]: [...entries, { owner, priority, options }],
          };
        });
        return () =>
          setActionRegistrations((current) => {
            const entries = current[name];
            if (!entries?.some((entry) => entry.owner === owner))
              return current;
            const nextEntries = entries.filter(
              (entry) => entry.owner !== owner,
            );
            const next = { ...current };
            if (nextEntries.length) next[name] = nextEntries;
            else delete next[name];
            return next;
          });
      },
    }),
    [],
  );
  const actions = useMemo<WorkspaceActions>(() => {
    const result: WorkspaceActions = {};
    for (const name of ["new", "back", "done"] as const) {
      const registrations = actionRegistrations[name];
      if (!registrations?.length) continue;
      const current = [...registrations].sort(
        (left, right) =>
          right.priority - left.priority ||
          left.owner.localeCompare(right.owner),
      )[0];
      if (current) result[name] = current.options;
    }
    return result;
  }, [actionRegistrations]);
  const [agentGroup, setAgentGroup] = useState<{
    scope: string;
    groupId: string | null;
  } | null>(null);
  const [, routeGroupId] =
    pathname.match(/^\/(?:student|teacher)\/groups\/([^/]+)/) ?? [];
  const [agentRoute, agentRouteKind, agentRouteId] =
    pathname.match(/^\/student\/(agents|agent-versions)\/([^/]+)/) ?? [];
  const lookUpAgentGroup =
    role === "student" &&
    Boolean(agentRoute) &&
    (user?.groups?.length ?? 0) > 1;
  const agentScope = `${user?.id ?? "anonymous"}:${identityGeneration ?? 0}:${agentRoute ?? ""}`;
  const membershipGroupIds = [
    ...new Set((user?.groups ?? []).map((membership) => membership.group_id)),
  ];
  const groupId =
    routeGroupId ??
    (lookUpAgentGroup
      ? agentGroup?.scope === agentScope
        ? agentGroup.groupId
        : undefined
      : membershipGroupIds.length === 1
        ? membershipGroupIds[0]
        : undefined);

  useEffect(() => {
    const syncLocation = () => {
      setLocationHash(window.location.hash);
      setLocationSearch(window.location.search);
    };
    syncLocation();
    window.addEventListener("hashchange", syncLocation);
    window.addEventListener("popstate", syncLocation);
    return () => {
      window.removeEventListener("hashchange", syncLocation);
      window.removeEventListener("popstate", syncLocation);
    };
  }, [pathname]);

  useEffect(() => {
    if (!lookUpAgentGroup || !agentRouteId) return;
    let active = true;
    void (
      agentRouteKind === "agents"
        ? Promise.resolve(agentRouteId)
        : api.version(agentRouteId).then((version) => version.agent_id)
    )
      .then((agentId) => api.agent(agentId))
      .then((agent) => {
        if (active)
          setAgentGroup({ scope: agentScope, groupId: agent.group_id });
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [api, agentRouteId, agentRouteKind, agentScope, lookUpAgentGroup]);

  useEffect(() => {
    if (
      role !== "student" ||
      !courseId ||
      typeof api?.classroomLive !== "function"
    )
      return;
    // Live badge (2026-10-20): the server pushes start/stop over one socket
    // per tab; a slow poll (60 s, and on focus/visibility/reconnect) covers a
    // dropped socket or a server that refused it (4429 = process full).
    let active = true;
    let socket: WebSocket | null = null;
    let retry: number | undefined;
    let attempts = 0;
    const refresh = () => {
      if (document.visibilityState === "hidden") return;
      void api
        .classroomLive(courseId)
        .then((value) => {
          if (active) setLive(Boolean(value));
        })
        .catch(() => {
          if (active) setLive(false);
        });
    };
    const connect = () => {
      if (!active || socket || typeof WebSocket === "undefined") return;
      const url = new URL(
        `/api/v1/courses/${courseId}/live/events`,
        window.location.href,
      );
      url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
      let connection: WebSocket;
      try {
        connection = new WebSocket(url.href);
      } catch {
        return;
      }
      socket = connection;
      connection.onmessage = (event) => {
        if (!active || socket !== connection) return;
        attempts = 0;
        try {
          const message = JSON.parse(String(event.data)) as {
            live?: unknown;
          };
          setLive(Boolean(message.live));
        } catch {
          // Ignore a malformed frame; the slow poll corrects the badge.
        }
      };
      connection.onclose = (event) => {
        if (socket !== connection) return;
        socket = null;
        if (!active) return;
        // Signed out / no access: stop; full or dropped: back off.
        if (event.code === 4401 || event.code === 4403) return;
        attempts += 1;
        const delay = Math.min(60_000, 2_000 * 2 ** Math.min(attempts, 5));
        window.clearTimeout(retry);
        retry = window.setTimeout(() => {
          refresh();
          connect();
        }, delay);
      };
    };
    const wake = () => {
      refresh();
      connect();
    };
    const onVisible = () => {
      if (document.visibilityState === "visible") wake();
    };
    connect();
    refresh();
    const timer = window.setInterval(refresh, 60_000);
    window.addEventListener("focus", wake);
    window.addEventListener("online", wake);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      active = false;
      window.clearInterval(timer);
      window.clearTimeout(retry);
      window.removeEventListener("focus", wake);
      window.removeEventListener("online", wake);
      document.removeEventListener("visibilitychange", onVisible);
      const current = socket;
      socket = null;
      current?.close();
    };
  }, [api, courseId, role]);

  async function signOut() {
    setBusy(true);
    try {
      await logout();
      router.replace("/");
    } finally {
      setBusy(false);
    }
  }

  const isStudent = role === "student";
  const isCourseTeacher = user?.courses?.some(
    (membership) => membership.role === "teacher",
  );
  const teacherSurface = role === "teacher" || Boolean(isCourseTeacher);
  const home = isStudent && !isCourseTeacher ? "/student" : "/teacher";
  // A teacher inside a student group is a temporary visitor opened from
  // Accounts. While visiting, Studyform, Brainform and Chatform stay in that
  // group, as they do for its members; every other teacher page ends the
  // visit and removes that access.
  const visitPageGroupId =
    teacherSurface &&
    (pathname === "/teacher/knowledge" || pathname === "/teacher/chat")
      ? new URLSearchParams(locationSearch).get("group_id")
      : null;
  const visitPage = Boolean(
    visitPageGroupId && membershipGroupIds.includes(visitPageGroupId),
  );
  const visitingGroup =
    teacherSurface &&
    (pathname.startsWith("/student/groups/") ||
      Boolean(agentRoute) ||
      visitPage);
  const visitGroupId =
    routeGroupId ?? (visitPage ? visitPageGroupId : groupId) ?? undefined;
  const onTeacherPage =
    teacherSurface && !pathname.startsWith("/student/") && !visitPage;
  const membershipKey = membershipGroupIds.join("|");
  const visitedGroupIds = useMemo(
    () => (onTeacherPage && membershipKey ? membershipKey.split("|") : []),
    [onTeacherPage, membershipKey],
  );
  const leaving = useRef(new Set<string>());
  useEffect(() => {
    // The group route mounts before the session knows about the join. Load
    // that membership here, not on the Accounts page, or the visit is revoked.
    if (visitingGroup && membershipGroupIds.length === 0) {
      void refresh?.();
    }
  }, [membershipGroupIds.length, refresh, visitingGroup]);
  useEffect(() => {
    if (visitingGroup) endTeacherEnter();
  }, [visitingGroup]);
  useEffect(() => {
    if (
      teacherEnterInProgress() ||
      !visitedGroupIds.length ||
      typeof api?.leaveGroupAsTeacher !== "function"
    )
      return;
    // The query string reaches state a render late, so read the URL itself:
    // arriving at a visited group's Brainform or Chatform must not end that
    // visit.
    const reading =
      window.location.pathname === "/teacher/knowledge" ||
      window.location.pathname === "/teacher/chat"
        ? new URLSearchParams(window.location.search).get("group_id")
        : null;
    const pending = visitedGroupIds.filter(
      (visited) => !leaving.current.has(visited) && visited !== reading,
    );
    if (!pending.length) return;
    for (const visited of pending) leaving.current.add(visited);
    const job = Promise.allSettled(
      pending.map((visited) => api.leaveGroupAsTeacher(visited)),
    ).then(async () => {
      try {
        await refresh?.();
      } finally {
        for (const visited of pending) leaving.current.delete(visited);
      }
    });
    trackTeacherLeave(job);
  }, [api, refresh, visitedGroupIds]);
  useEffect(() => {
    if (!visitingGroup) return;
    return actionRegistry.register(
      "back",
      "group-visit",
      { href: "/teacher/roster" },
      -1,
    );
  }, [actionRegistry, visitingGroup]);
  const teacherLegacyBrainform =
    teacherSurface && pathname === "/student/knowledge" ? locationSearch : "";
  const visit =
    visitingGroup && visitGroupId
      ? encodeURIComponent(visitGroupId)
      : undefined;
  const studyformHref = visit
    ? `/student/groups/${visit}`
    : teacherSurface
      ? `/teacher/studyform${routeGroupId && !visitingGroup ? `?group_id=${encodeURIComponent(routeGroupId)}` : ""}`
      : groupId
        ? `/student/groups/${groupId}`
        : "/student#student-groups";
  const links: {
    href: string;
    label: string;
    icon: WorkspaceIconName;
    disabled?: boolean;
  }[] = [
    { href: home, label: t("appName"), icon: "home" },
    { href: studyformHref, label: t("studyform"), icon: "knowledge" },
    {
      href: visit
        ? `/teacher/knowledge?group_id=${visit}`
        : teacherSurface
          ? `/teacher/knowledge${teacherLegacyBrainform}`
          : "/student/knowledge",
      label: "Brainform",
      icon: "brain",
    },
    {
      href: visit
        ? `/teacher/chat?group_id=${visit}`
        : teacherSurface
          ? "/teacher/chat"
          : "/student/chat",
      label: "Chatform",
      icon: "chat",
    },
    ...(teacherSurface
      ? []
      : [
          {
            href: "/student/live",
            label: "Live",
            icon: "live" as const,
            disabled: !live,
          },
        ]),
    ...(teacherSurface
      ? [
          {
            href: "/teacher/debates",
            label: t("debateList"),
            icon: "classroom" as const,
          },
          {
            href: "/teacher/roster",
            label: t("accounts"),
            icon: "accounts" as const,
          },
        ]
      : []),
  ];

  const activePath = visitingGroup
    ? visitPage
      ? pathname
      : studyformHref.split("?", 1)[0]
    : isStudent && groupId && agentRoute
      ? `/student/groups/${groupId}`
      : teacherSurface && pathname === "/student/knowledge"
        ? "/teacher/knowledge"
        : teacherSurface && pathname.startsWith("/teacher/agents/")
          ? "/teacher/studyform"
          : pathname.startsWith("/teacher/debates")
            ? "/teacher/debates"
            : pathname.startsWith("/student/groups/") &&
                pathname.endsWith("/voices")
              ? pathname.slice(0, -"/voices".length)
              : // A new Agent is made from Studyform, so Studyform stays lit.
                pathname.startsWith("/student/groups/") &&
                  pathname.endsWith("/agents/new")
                ? pathname.slice(0, -"/agents/new".length)
                : pathname.startsWith("/student/groups/") &&
                    pathname.endsWith("/knowledge")
                  ? "/student/knowledge"
                  : pathname;
  const studentGroupPicker =
    !teacherSurface &&
    pathname === "/student" &&
    locationHash === "#student-groups";
  const activeHref =
    links
      .filter((link) => {
        const [linkTarget, linkHash] = link.href.split("#", 2);
        const [linkPath] = linkTarget.split("?", 2);
        if (studentGroupPicker && link.href === home) return false;
        return (
          activePath === linkPath &&
          (!linkHash || locationHash === `#${linkHash}`)
        );
      })
      .sort((left, right) => right.href.length - left.href.length)[0]?.href ??
    (activePath.startsWith(`${home}/`) ? home : undefined);

  return (
    <WorkspaceActionsContext.Provider value={actionRegistry}>
      <div className={styles.frame}>
        <header className={styles.sidebar}>
          <nav
            aria-label={`${teacherSurface ? t("teacher") : t("student")} ${t("navigation")}`}
            className={`${styles.navigation} nav-links`}
          >
            {links.map((link) =>
              link.disabled ? (
                <span
                  className={`${styles.link} ${styles.disabled}`}
                  aria-disabled="true"
                  key={link.href}
                  data-tour={link.icon}
                >
                  <WorkspaceIcon name={link.icon} />
                  <span>{link.label}</span>
                </span>
              ) : (
                <Link
                  aria-current={activeHref === link.href ? "page" : undefined}
                  className={`${styles.link} ${activeHref === link.href ? styles.active : ""} ${link.icon === "live" ? styles.live : ""}`}
                  href={link.href}
                  key={link.href}
                  data-tour={link.icon}
                >
                  {activeHref === link.href ? (
                    <ViewTransition
                      name="nav-active"
                      share="nav-pill"
                      default="none"
                    >
                      <span className={styles.pill} aria-hidden="true" />
                    </ViewTransition>
                  ) : null}
                  {link.icon === "home" ? (
                    <span
                      className={`brand-dot ${styles.homeMark}`}
                      aria-hidden="true"
                    />
                  ) : (
                    <WorkspaceIcon name={link.icon} />
                  )}
                  <span>{link.label}</span>
                </Link>
              ),
            )}
            {(
              [
                ["new", "New"],
                ["back", "Back"],
                ["done", "Done"],
              ] as const
            ).map(([name, label]) => {
              const action = actions[name];
              // New stays in the sidebar once a page registers it, faded when
              // it cannot run. Back and Done exist only while their owning
              // screen needs them, and remain disabled during busy work.
              if (!action) return null;
              const faded = Boolean(action.disabled);
              const content = (
                <>
                  {action.busy ? (
                    <span className="spinner" aria-hidden="true" />
                  ) : (
                    <WorkspaceIcon name={name} />
                  )}
                  <span>{label}</span>
                </>
              );
              return action.href && !faded ? (
                <Link
                  key={name}
                  className={`${styles.link} ${styles.sidebarAction}`}
                  href={action.href}
                  onClick={action.onClick}
                  data-ui-guide={`workspace.${name}`}
                  aria-disabled={faded || undefined}
                  tabIndex={faded ? -1 : undefined}
                >
                  {content}
                </Link>
              ) : (
                <button
                  key={name}
                  className={`${styles.link} ${styles.action} ${styles.sidebarAction}${faded ? ` ${styles.disabled}` : ""}`}
                  type={action.form ? "submit" : "button"}
                  form={action.form}
                  disabled={faded}
                  aria-busy={action.busy || undefined}
                  onClick={action.onClick}
                  data-ui-guide={`workspace.${name}`}
                >
                  {content}
                </button>
              );
            })}
          </nav>
          <div className={styles.account}>
            <p className={styles.credit}>
              <span className={styles.creditTitle}>Meet Problems?</span>
              <a
                className={styles.creditMail}
                href="mailto:t330034059@mail.bnbu.edu.cn"
              >
                Send to t330034059@mail.bnbu.edu.cn
              </a>
            </p>
            <button
              className={styles.logout}
              type="button"
              disabled={busy}
              data-ui-guide="workspace.logout"
              onClick={() => void signOut()}
            >
              <WorkspaceIcon name="logout" />
              {t("logout")}
            </button>
          </div>
        </header>
        <main
          id="workspace-content"
          tabIndex={-1}
          className={`${styles.main} ${workspaceStyles.surface} ${pathname === "/teacher/chat" || pathname === "/student/chat" ? styles.chatMain : ""}`}
        >
          <ViewTransition>{children}</ViewTransition>
        </main>
        <SecretDoor />
      </div>
    </WorkspaceActionsContext.Provider>
  );
}
