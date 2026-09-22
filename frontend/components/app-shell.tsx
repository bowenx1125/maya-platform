"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import workspaceStyles from "./workspace-theme.module.css";
import styles from "./app-shell.module.css";
import { WorkspaceIcon, type WorkspaceIconName } from "./workspace-icon";
import { WorkspaceNewContext, type WorkspaceNewAction } from "./workspace-new";

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
  const groupId = user?.groups[0]?.group_id;
  const courseId = user?.courses?.[0]?.course_id;
  const [live, setLive] = useState(false);
  const [newAction, setNewAction] = useState<WorkspaceNewAction | null>(null);

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

  const isStudent = role === "student";
  const isCourseTeacher = user?.courses?.some(
    (membership) => membership.role === "teacher",
  );
  const links: {
    href: string;
    label: string;
    icon: WorkspaceIconName;
    disabled?: boolean;
  }[] = isStudent
    ? [
        { href: "/student", label: t("appName"), icon: "home" },
        { href: "/student/chat", label: "Chat", icon: "chat" },
        { href: "/student/live", label: "Live", icon: "live", disabled: !live },
        // Back to the roster, not the dashboard: the roster is the only door
        // into a group for a teacher, so it is the page they left to get here
        // and the one that still has the row they are working through.
        ...(isCourseTeacher
          ? [
              {
                href: "/teacher/roster",
                label: t("homeward"),
                icon: "accounts" as const,
              },
            ]
          : []),
        ...(groupId
          ? [
              {
                href: `/student/groups/${groupId}`,
                label: t("groupWorkspace"),
                icon: "agents" as const,
              },
            ]
          : []),
        ...(groupId
          ? [
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
        { href: "/teacher", label: t("appName"), icon: "home" },
        { href: "/teacher/chat", label: "Chat", icon: "chat" },
        { href: "/teacher/debates", label: t("debateList"), icon: "classroom" },
        { href: "/teacher/roster", label: t("accounts"), icon: "accounts" },
      ];

  const activePath = pathname.startsWith("/teacher/debates-beta/")
    ? pathname.replace("/teacher/debates-beta/", "/teacher/debates/")
    : pathname;
  const activeHref =
    links
      .filter(
        (link) =>
          activePath === link.href ||
          (!["/teacher", "/student"].includes(link.href) &&
            activePath.startsWith(`${link.href}/`)),
      )
      .sort((left, right) => right.href.length - left.href.length)[0]?.href ??
    (isStudent ? "/student" : "/teacher");

  return (
    <WorkspaceNewContext.Provider value={setNewAction}>
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
            {newAction?.href && !newAction.disabled ? (
              <Link className={styles.link} href={newAction.href}>
                <WorkspaceIcon name="new" />
                <span>New</span>
              </Link>
            ) : (
              <button
                className={`${styles.link} ${styles.newAction}`}
                type="button"
                disabled={!newAction || newAction.disabled}
                onClick={newAction?.onClick}
              >
                <WorkspaceIcon name="new" />
                <span>New</span>
              </button>
            )}
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
    </WorkspaceNewContext.Provider>
  );
}
