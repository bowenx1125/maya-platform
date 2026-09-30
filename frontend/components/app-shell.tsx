"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import workspaceStyles from "./workspace-theme.module.css";
import styles from "./app-shell.module.css";
import { WorkspaceIcon, type WorkspaceIconName } from "./workspace-icon";
import {
  WorkspaceActionsContext,
  type WorkspaceActions,
} from "./workspace-actions";

import { useT } from "./locale";
import { useSession } from "./session-provider";

export function AppShell({
  children,
  role,
}: {
  children: ReactNode;
  role: "student" | "teacher";
}) {
  const t = useT();
  const { api, user, logout } = useSession();
  const router = useRouter();
  const pathname = usePathname();
  const [busy, setBusy] = useState(false);
  const courseId = user?.courses?.[0]?.course_id;
  const [live, setLive] = useState(false);
  const [actions, setActions] = useState<WorkspaceActions>({});
  const [agentGroup, setAgentGroup] = useState<{
    route: string;
    groupId: string;
  } | null>(null);

  const isStudent = role === "student";
  // The sidebar's group links follow the group on screen. groups[0] is only a
  // fallback for pages that belong to no group, or it sends anyone who sits in
  // several groups into a different one than they are working in. Agent URLs
  // name no group, so with several to choose from the shell asks which one owns
  // the Agent and shows no group links until it knows.
  const [, routeGroupId] = pathname.match(/^\/student\/groups\/([^/]+)/) ?? [];
  const [agentRoute, agentRouteKind, agentRouteId] =
    pathname.match(/^\/student\/(agents|agent-versions)\/([^/]+)/) ?? [];
  const lookUpAgentGroup =
    isStudent && Boolean(agentRoute) && (user?.groups?.length ?? 0) > 1;
  const agentGroupId =
    agentGroup !== null && agentGroup.route === agentRoute
      ? agentGroup.groupId
      : undefined;
  const groupId =
    routeGroupId ??
    (lookUpAgentGroup ? agentGroupId : user?.groups?.[0]?.group_id);

  useEffect(() => {
    if (!lookUpAgentGroup || !agentRoute || !agentRouteId) return;
    let active = true;
    void (
      agentRouteKind === "agents"
        ? Promise.resolve(agentRouteId)
        : api.version(agentRouteId).then((version) => version.agent_id)
    )
      .then((agentId) => api.agent(agentId))
      .then((agent) => {
        if (active)
          setAgentGroup({ route: agentRoute, groupId: agent.group_id });
      })
      // A failed lookup leaves the group links hidden; the page's own Back
      // still leads to the right group.
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [api, agentRoute, agentRouteId, agentRouteKind, lookUpAgentGroup]);

  useEffect(() => {
    if (
      role !== "student" ||
      !courseId ||
      typeof api?.classroomLive !== "function"
    )
      return;
    let active = true;
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
    refresh();
    const timer = window.setInterval(refresh, 5000);
    window.addEventListener("focus", refresh);
    return () => {
      active = false;
      window.clearInterval(timer);
      window.removeEventListener("focus", refresh);
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

  const isCourseTeacher = user?.courses?.some(
    (membership) => membership.role === "teacher",
  );
  // The brand mark goes home, and a teacher's home is the teacher side even
  // while they work inside a group they entered from the roster.
  const home = isStudent && !isCourseTeacher ? "/student" : "/teacher";
  const links: {
    href: string;
    label: string;
    icon: WorkspaceIconName;
    disabled?: boolean;
  }[] = isStudent
    ? [
        { href: home, label: t("appName"), icon: "home" },
        { href: "/student/chat", label: "Chats", icon: "chat" },
        { href: "/student/live", label: "Live", icon: "live", disabled: !live },
        ...(groupId
          ? [
              {
                href: `/student/groups/${groupId}`,
                label: t("groupWorkspace"),
                icon: "agents" as const,
              },
              {
                href: `/student/groups/${groupId}/knowledge`,
                label: t("knowledge"),
                icon: "knowledge" as const,
              },
              {
                href: `/student/groups/${groupId}/voices`,
                label: t("voices"),
                icon: "voice" as const,
              },
            ]
          : []),
      ]
    : [
        { href: home, label: t("appName"), icon: "home" },
        { href: "/teacher/chat", label: "Chats", icon: "chat" },
        { href: "/teacher/debates", label: t("debateList"), icon: "classroom" },
        { href: "/teacher/roster", label: t("accounts"), icon: "accounts" },
      ];

  const activePath =
    isStudent && groupId && agentRoute
      ? `/student/groups/${groupId}`
      : pathname.startsWith("/teacher/debates-beta/")
        ? pathname.replace("/teacher/debates-beta/", "/teacher/debates/")
        : pathname;
  // Unmatched pages fall back to home only inside home's own side: a teacher
  // on a student page is not at home.
  const activeHref =
    links
      .filter(
        (link) =>
          activePath === link.href ||
          (link.href !== home && activePath.startsWith(`${link.href}/`)),
      )
      .sort((left, right) => right.href.length - left.href.length)[0]?.href ??
    (activePath.startsWith(`${home}/`) ? home : undefined);

  return (
    <WorkspaceActionsContext.Provider value={setActions}>
      <div className={styles.frame}>
        <header className={styles.sidebar}>
          <nav
            aria-label={`${role === "teacher" ? t("teacher") : t("student")} ${t("navigation")}`}
            className={styles.navigation}
          >
            {links.map((link) =>
              link.disabled ? (
                <span
                  className={`${styles.link} ${styles.disabled}`}
                  aria-disabled="true"
                  key={link.href}
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
                >
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
              // it cannot run. Back and Done only appear when that screen
              // needs them and they are usable.
              if (!action) return null;
              if (name !== "new" && action.disabled) return null;
              const faded = Boolean(action.disabled);
              const content = (
                <>
                  <WorkspaceIcon name={name} />
                  <span>{label}</span>
                </>
              );
              return action.href ? (
                <Link
                  key={name}
                  className={`${styles.link}${faded ? ` ${styles.disabled}` : ""}`}
                  href={action.href}
                  onClick={action.onClick}
                  aria-disabled={faded || undefined}
                  tabIndex={faded ? -1 : undefined}
                >
                  {content}
                </Link>
              ) : (
                <button
                  key={name}
                  className={`${styles.link} ${styles.action}${faded ? ` ${styles.disabled}` : ""}`}
                  type={action.form ? "submit" : "button"}
                  form={action.form}
                  disabled={faded}
                  onClick={action.onClick}
                >
                  {content}
                </button>
              );
            })}
          </nav>
          <div className={styles.account}>
            <button
              className={styles.logout}
              type="button"
              disabled={busy}
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
          className={`${styles.main} ${workspaceStyles.surface}`}
        >
          {children}
        </main>
      </div>
    </WorkspaceActionsContext.Provider>
  );
}
