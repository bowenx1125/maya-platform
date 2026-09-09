"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";

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
  const { user, logout } = useSession();
  const router = useRouter();
  const pathname = usePathname();
  const [busy, setBusy] = useState(false);
  const groupId = user?.groups[0]?.group_id;

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
  const links = isStudent
    ? [
        { href: "/student", label: t("home") },
        ...(groupId
          ? [{ href: `/student/groups/${groupId}`, label: t("groupWorkspace") }]
          : []),
        ...(groupId
          ? [
              {
                href: `/student/groups/${groupId}/knowledge`,
                label: t("knowledge"),
              },
              {
                href: `/student/groups/${groupId}/voices`,
                label: t("voices"),
              },
            ]
          : []),
      ]
    : [
        { href: "/teacher", label: t("dashboard") },
        { href: "/teacher/debates", label: t("debates") },
        { href: "/teacher/roster", label: t("accounts") },
      ];

  const activePath = pathname.startsWith("/teacher/debates-beta/")
    ? pathname.replace("/teacher/debates-beta/", "/teacher/debates/")
    : pathname;
  const activeHref = links
    .filter(
      (link) =>
        activePath === link.href ||
        (!isStudent && activePath.startsWith(`${link.href}/`)),
    )
    .sort((left, right) => right.href.length - left.href.length)[0]?.href;

  return (
    <div className="app-frame">
      <header className="app-nav">
        <Link className="brand-mark" href={isStudent ? "/student" : "/teacher"}>
          <span className="brand-dot" aria-hidden="true" />
          <span>{t("appName")}</span>
        </Link>
        <nav
          aria-label={`${role === "teacher" ? t("teacher") : t("student")} ${t("navigation")}`}
          className="nav-links"
        >
          {links.map((link) => (
            <Link
              aria-current={activeHref === link.href ? "page" : undefined}
              className={
                activeHref === link.href ? "nav-link active" : "nav-link"
              }
              href={link.href}
              key={link.href}
            >
              {link.label}
            </Link>
          ))}
        </nav>
        <div className="nav-account">
          <button
            className="nav-logout"
            type="button"
            disabled={busy}
            onClick={() => void signOut()}
          >
            {t("logout")}
          </button>
        </div>
      </header>
      <main className="app-main">{children}</main>
    </div>
  );
}
