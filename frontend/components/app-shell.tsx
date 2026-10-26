"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";

import workspaceStyles from "./workspace-theme.module.css";
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

import { useT } from "../lib/i18n";
import {
  endTeacherEnter,
  teacherEnterInProgress,
  trackTeacherLeave,
} from "../lib/teacher-visit";
import { useSession } from "./session-provider";
import { OnboardingTour } from "./onboarding-tour";
import {
  SIDEBAR_ID,
  SIDEBAR_MOBILE_QUERY,
  SIDEBAR_REVEAL_EVENT,
} from "../lib/sidebar-reveal";

type ActionRegistration = {
  owner: string;
  priority: number;
  options: WorkspaceActionOptions;
};
type ActionRegistrationState = Partial<
  Record<WorkspaceActionName, ActionRegistration[]>
>;

/** The sidebar's collapsed state survives reloads (DESIGN-RULES §7, toggle A). */
export const SIDEBAR_COLLAPSED_KEY = "maya.sidebar.collapsed";
const collapsedListeners = new Set<() => void>();
let collapsedFallback = false;

function readCollapsed() {
  try {
    const stored = window.localStorage.getItem(SIDEBAR_COLLAPSED_KEY);
    return stored === null ? collapsedFallback : stored === "1";
  } catch {
    return collapsedFallback;
  }
}

function writeCollapsed(value: boolean) {
  collapsedFallback = value;
  try {
    window.localStorage.setItem(SIDEBAR_COLLAPSED_KEY, value ? "1" : "0");
  } catch {
    // Private mode: the state lasts for this page only.
  }
  for (const listener of collapsedListeners) listener();
}

function subscribeCollapsed(listener: () => void) {
  collapsedListeners.add(listener);
  window.addEventListener("storage", listener);
  return () => {
    collapsedListeners.delete(listener);
    window.removeEventListener("storage", listener);
  };
}

const MOBILE_QUERY = SIDEBAR_MOBILE_QUERY;

function subscribeMobile(listener: () => void) {
  const query = window.matchMedia?.(MOBILE_QUERY);
  query?.addEventListener?.("change", listener);
  return () => query?.removeEventListener?.("change", listener);
}

function readMobile() {
  return Boolean(window.matchMedia?.(MOBILE_QUERY).matches);
}

type SidebarItem = {
  key: string;
  href: string;
  label: string;
  icon: WorkspaceIconName;
  tour?: string;
  disabled?: boolean;
};
type SidebarGroup = {
  key: "studyform" | "brainform" | "chatform" | "classroom";
  label: string;
  /** The tour target today's top-level entry carried; now on the first row. */
  tour?: string;
  /** A tour target on the group heading itself (B-final student Brainform). */
  headingTour?: string;
  rail: string;
  tile: string;
  square: string;
  items: SidebarItem[];
};

const ITEM =
  "group/item relative flex min-h-11 items-center gap-2.5 rounded-arc-s border-[3px] px-2 py-1 font-body text-sm font-semibold text-ink no-underline transition-[background-color,box-shadow] duration-150";
const ITEM_IDLE = "border-transparent hover:bg-white/60";
const ITEM_ACTIVE = "border-border bg-main shadow-arc-s";
const ICON_ITEM =
  "relative grid size-11 place-items-center rounded-arc-s border-[3px] text-ink no-underline";

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
  const [, groupRouteId] =
    pathname.match(/^\/(?:student|teacher)\/groups\/([^/]+)/) ?? [];
  // The Agents page names its group in ?group_id.
  const routeGroupId =
    groupRouteId ??
    (pathname === "/student/agents" || pathname === "/student/teams"
      ? (new URLSearchParams(locationSearch).get("group_id") ?? undefined)
      : undefined);
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
      pathname === "/student/agents" ||
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
  // The sidebar's Teams item opens the Teams page, like Agents.
  const teamsHref = visit
    ? `/student/teams?group_id=${visit}`
    : teacherSurface
      ? `/teacher/teams${routeGroupId && !visitingGroup ? `?group_id=${encodeURIComponent(routeGroupId)}` : ""}`
      : groupId
        ? `/student/teams?group_id=${encodeURIComponent(groupId)}`
        : "/student#student-groups";
  // The Teams list, Create Team and Edit Team all light Teams.
  const teamsPage =
    pathname === "/student/teams" || pathname === "/teacher/teams";
  // The sidebar's Agents item opens the Agents page.
  const agentsHref = visit
    ? `/student/agents?group_id=${visit}`
    : teacherSurface
      ? `/teacher/agents${routeGroupId && !visitingGroup ? `?group_id=${encodeURIComponent(routeGroupId)}` : ""}`
      : groupId
        ? `/student/agents?group_id=${encodeURIComponent(groupId)}`
        : "/student#student-groups";
  // The list, an Agent, and New all light Agents.
  const agentsArea =
    pathname === "/student/agents" ||
    pathname === "/teacher/agents" ||
    pathname.startsWith("/teacher/agents/") ||
    Boolean(agentRoute) ||
    /^\/student\/groups\/[^/]+\/agents\/new$/.test(pathname);
  const links: {
    href: string;
    label: string;
    icon: WorkspaceIconName;
    disabled?: boolean;
  }[] = [
    { href: home, label: t("appName"), icon: "home" },
    { href: studyformHref, label: t("studyform"), icon: "knowledge" },
    // Owner request (2026-10-20): RAG, Knowledge and Record live on
    // Studyform for students and teachers alike; only a teacher visiting a
    // group keeps a Brainform entry for that group's read-only library.
    // /teacher/knowledge stays routable for its deep links.
    ...(visit
      ? [
          {
            href: `/teacher/knowledge?group_id=${visit}`,
            label: "Brainform",
            icon: "brain" as const,
          },
        ]
      : []),
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
      : teacherSurface &&
          (pathname === "/student/knowledge" ||
            pathname === "/teacher/knowledge")
        ? "/teacher/studyform"
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

  const collapsedPreference = useSyncExternalStore(
    subscribeCollapsed,
    readCollapsed,
    () => false,
  );
  const mobile = useSyncExternalStore(subscribeMobile, readMobile, () => false);
  const collapsed = collapsedPreference && !mobile;
  // The drawer belongs to the page it was opened on, so navigating closes it.
  const [drawerPath, setDrawerPath] = useState<string | null>(null);
  const drawerOpen = drawerPath === pathname;
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setDrawerPath(null);
        return;
      }
      if (
        !(event.ctrlKey || event.metaKey) ||
        event.altKey ||
        event.shiftKey ||
        event.key.toLowerCase() !== "b"
      )
        return;
      const target = event.target as HTMLElement | null;
      if (target?.isContentEditable) return;
      event.preventDefault();
      if (readMobile())
        setDrawerPath((open) =>
          open === window.location.pathname ? null : window.location.pathname,
        );
      else writeCollapsed(!readCollapsed());
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  useEffect(() => {
    // The tour opens the drawer for a step that points into it.
    const onReveal = (event: Event) => {
      const open = (event as CustomEvent<{ open?: boolean }>).detail?.open;
      setDrawerPath(open ? window.location.pathname : null);
    };
    window.addEventListener(SIDEBAR_REVEAL_EVENT, onReveal);
    return () => window.removeEventListener(SIDEBAR_REVEAL_EVENT, onReveal);
  }, []);

  const studentVoicesHref =
    !teacherSurface && groupId
      ? `/student/groups/${groupId}/voices`
      : undefined;
  const brainHref = visit ? `/teacher/knowledge?group_id=${visit}` : undefined;
  const chatHref = links.find((link) => link.icon === "chat")?.href ?? "";
  const brainItemHref = brainHref ?? studyformHref;
  const groups: SidebarGroup[] = [
    {
      key: "studyform",
      label: t("studyform"),
      tour: "knowledge",
      rail: "border-studyform",
      tile: "bg-studyform",
      square: "bg-studyform",
      items: [
        {
          key: "agents",
          href: agentsHref,
          label: t("agents"),
          icon: "agent",
        },
        {
          key: "teams",
          href: teamsHref,
          label: t("sidebarTeams"),
          icon: "team",
        },
      ],
    },
    {
      key: "brainform",
      label: "Brainform",
      tour: brainHref ? "brain" : undefined,
      // Guide v3 (9 steps): a student's Brainform step points at the heading.
      headingTour: !teacherSurface && !brainHref ? "brain" : undefined,
      rail: "border-brainform",
      tile: "bg-brainform",
      square: "bg-brainform",
      items: [
        { key: "rag", href: brainItemHref, label: t("rag"), icon: "file" },
        {
          key: "voices",
          href: studentVoicesHref ?? brainItemHref,
          label: t("voices"),
          icon: "mic",
        },
        {
          key: "record",
          href: brainItemHref,
          label: t("sidebarRecord"),
          icon: "clock",
        },
        ...(teacherSurface
          ? [
              {
                key: "knowledge",
                href: brainItemHref,
                label: t("knowledge"),
                icon: "knowledge" as const,
              },
            ]
          : []),
      ],
    },
    {
      key: "chatform",
      label: "Chatform",
      tour: "chat",
      rail: "border-chatform",
      tile: "bg-chatform",
      square: "bg-chatform",
      items: [
        {
          key: "chat-agent",
          href: chatHref,
          label: t("sidebarChatAgent"),
          icon: "chat",
        },
        {
          key: "chat-team",
          href: chatHref,
          label: t("sidebarChatTeam"),
          icon: "chatTeam",
        },
      ],
    },
    {
      key: "classroom",
      label: t("sidebarClassroom"),
      rail: "border-ink",
      tile: "bg-surface",
      square: "bg-white",
      items: links
        .filter((link) => ["live", "classroom", "accounts"].includes(link.icon))
        .map((link) => ({
          key: link.icon,
          href: link.href,
          label: link.label,
          icon: link.icon,
          tour: link.icon,
          disabled: link.disabled,
        })),
    },
  ];
  // The pink pill marks the one row for the current page; that row carries
  // aria-current. litSidebarKey prefers the most specific match. Teams lights
  // only on the Teams page; the Studyform grid itself lights no row (owner
  // decision 2026-10-26).
  const onStudyformGrid =
    !teamsPage && pathname === studyformHref.split(/[?#]/, 1)[0];
  const litKey = agentsArea
    ? "studyform:agents"
    : teamsPage
      ? "studyform:teams"
      : onStudyformGrid
        ? undefined
        : litSidebarKey(groups, pathname, activeHref, studentVoicesHref);
  const pill = (
    <ViewTransition name="nav-active" share="nav-pill" default="none">
      <span
        className="absolute inset-0 -z-10 rounded-[inherit]"
        aria-hidden="true"
      />
    </ViewTransition>
  );
  // toggle-A / collapse-C: a collapsed rail labels its tiles with a drawn
  // tooltip (hover or keyboard focus), not a native title.
  const railTip = (label: string) =>
    collapsed && !mobile ? (
      <span
        aria-hidden="true"
        data-rail-tip=""
        className="pointer-events-none invisible absolute top-1/2 left-[calc(100%+10px)] z-50 -translate-y-1/2 rounded-[5px] bg-[#111] px-2 py-[5px] font-body text-xs font-semibold whitespace-nowrap text-white group-hover/tip:visible group-focus-visible/tip:visible"
      >
        {label}
      </span>
    ) : null;
  const lamp = (on: boolean, corner: boolean) => (
    <span
      aria-hidden="true"
      data-live-lamp={on ? "on" : "off"}
      className={`${corner ? "absolute -top-1 -right-1" : "ml-auto"} ${on ? "size-2.5 rounded-full border-2 border-border bg-ok shadow-[0_0_0_2px_rgba(34,197,94,0.35),0_0_10px_2px_rgba(34,197,94,0.75)]" : `${corner ? "size-2" : "size-[11px]"} rounded-full bg-[#6B6B6B] shadow-[0_0_0_2px_#111]`}`}
    />
  );
  const toggleLabel = mobile
    ? t("sidebarCollapse")
    : collapsed
      ? t("sidebarExpand")
      : t("sidebarCollapse");
  const mayaformLit = !agentsArea && activeHref === home;

  function renderItem(group: SidebarGroup, item: SidebarItem, index: number) {
    const lit = litKey === `${group.key}:${item.key}`;
    // Live, Debates and Accounts keep today's aria-current and active class.
    const legacy = links.find((link) => link.icon === item.key);
    const current = legacy ? activeHref === legacy.href : lit;
    // A collapsed rail hides headings, so their target falls to the first row.
    const tour =
      item.tour ??
      (index === 0
        ? (group.tour ?? (collapsed ? group.headingTour : undefined))
        : undefined);
    const isLive = item.key === "live";
    if (item.disabled) {
      return (
        <li key={item.key}>
          <span
            aria-disabled="true"
            data-tour={tour}
            aria-label={collapsed ? item.label : undefined}
            className={
              collapsed
                ? `${ICON_ITEM} group/tip border-transparent`
                : `${ITEM} ${ITEM_IDLE} cursor-not-allowed text-arc-muted hover:bg-transparent`
            }
          >
            <span className="opacity-55">
              <WorkspaceIcon name={item.icon} size={18} />
            </span>
            {collapsed ? null : (
              <span className="opacity-55">{item.label}</span>
            )}
            {isLive ? lamp(false, collapsed) : null}
            {railTip(item.label)}
          </span>
        </li>
      );
    }
    return (
      <li key={item.key}>
        <Link
          href={item.href}
          aria-current={current ? "page" : undefined}
          aria-label={collapsed ? item.label : undefined}
          data-tour={tour}
          data-sidebar-item={item.key}
          data-lit={lit || undefined}
          className={`${collapsed ? `${ICON_ITEM} group/tip` : ITEM} isolate ${lit ? ITEM_ACTIVE : collapsed ? "border-transparent hover:bg-white/60" : ITEM_IDLE}${current ? " active" : ""}`}
        >
          {lit ? pill : null}
          <WorkspaceIcon name={item.icon} size={18} />
          {collapsed ? null : <span>{item.label}</span>}
          {isLive ? (
            collapsed ? (
              lamp(true, true)
            ) : (
              <span
                aria-hidden="true"
                data-live-sticker=""
                className="ml-auto inline-flex -rotate-6 items-center gap-1 rounded-full border-2 border-border bg-ok px-1.5 py-px text-[9px] leading-none font-extrabold tracking-[0.08em] text-white uppercase shadow-[2px_2px_0_#111]"
              >
                <span className="size-1.5 rounded-full bg-white" />
                {t("sidebarOnAir")}
              </span>
            )
          ) : null}
          {railTip(item.label)}
        </Link>
      </li>
    );
  }

  return (
    <WorkspaceActionsContext.Provider value={actionRegistry}>
      <div
        className={`grid min-h-dvh max-[900px]:grid-cols-1 ${pathname === "/student" || pathname === "/teacher" || agentsArea || teamsPage ? "bg-[#DCEBFF] bg-[linear-gradient(#0001_1px,transparent_1px),linear-gradient(90deg,#0001_1px,transparent_1px)] bg-size-[32px_32px]" : ""} ${collapsed ? "grid-cols-[76px_minmax(0,1fr)]" : "grid-cols-[220px_minmax(0,1fr)]"}`}
      >
        <div className="sticky top-0 z-30 hidden h-[50px] items-center justify-center border-b-[3px] border-border bg-sidebar px-3 max-[900px]:flex">
          <button
            type="button"
            className="absolute top-1/2 left-3 grid size-[30px] -translate-y-1/2 place-items-center rounded-[6px] border-[2px] border-border bg-surface text-ink shadow-[2px_2px_0_#111] after:absolute after:-inset-[7px] after:content-[''] active:shadow-none"
            aria-label={t("sidebarExpand")}
            aria-expanded={drawerOpen}
            aria-controls={SIDEBAR_ID}
            onClick={() => setDrawerPath(pathname)}
          >
            <WorkspaceIcon name="menu" size={18} />
          </button>
          <span
            className="flex items-center gap-2 font-display text-lg font-extrabold text-ink"
            aria-hidden="true"
          >
            <span className="size-4 rounded-full border-2 border-border bg-[linear-gradient(90deg,#111_50%,var(--color-main)_50%)]" />
            {t("appName")}
          </span>
        </div>
        {drawerOpen ? (
          <div
            aria-hidden="true"
            className="fixed inset-0 z-40 bg-black/40 min-[901px]:hidden"
            onClick={() => setDrawerPath(null)}
          />
        ) : null}
        <header
          id={SIDEBAR_ID}
          data-collapsed={collapsed || undefined}
          className={`relative z-20 min-h-dvh border-r-[3px] border-border bg-sidebar max-[900px]:fixed max-[900px]:inset-y-0 max-[900px]:left-0 max-[900px]:z-50 max-[900px]:w-[min(300px,85vw)] max-[900px]:transition-transform max-[900px]:duration-150 max-[900px]:motion-reduce:transition-none ${drawerOpen ? "" : "max-[900px]:invisible max-[900px]:-translate-x-full"}`}
        >
          <div data-sidebar-pin className="sticky top-0 h-dvh">
            <button
              type="button"
              data-sidebar-toggle
              className={`group/toggle absolute ${mobile ? "top-4 right-3 size-8 rounded-arc-s" : `top-[calc(50%-16px)] ${collapsed ? "-right-[26px]" : "-right-[22px]"} size-8 rounded-full`} z-10 grid place-items-center border-[3px] border-border bg-surface text-ink shadow-[2px_2px_0_#111] transition-[transform,box-shadow] duration-75 hover:-translate-y-px active:translate-x-[2px] active:translate-y-[2px] active:shadow-none motion-reduce:transition-none`}
              aria-label={toggleLabel}
              aria-expanded={mobile ? drawerOpen : !collapsed}
              aria-controls={SIDEBAR_ID}
              aria-keyshortcuts="Control+B Meta+B"
              onClick={() =>
                mobile ? setDrawerPath(null) : writeCollapsed(!collapsed)
              }
            >
              <WorkspaceIcon
                name={
                  mobile ? "pin" : collapsed ? "chevronRight" : "chevronLeft"
                }
                size={16}
              />
              {mobile ? null : (
                <span
                  aria-hidden="true"
                  data-sidebar-toggle-tip
                  className="pointer-events-none invisible absolute top-[5px] left-[calc(100%+2px)] rounded-[5px] bg-[#111] px-2 py-[5px] font-body text-xs font-semibold whitespace-nowrap text-white group-hover/toggle:visible group-focus-visible/toggle:visible"
                >
                  {toggleLabel} · Ctrl B
                </span>
              )}
            </button>
            <div
              className={`flex h-full flex-col gap-5 pt-5 pb-4 ${collapsed ? "items-center overflow-visible px-2" : "overflow-y-auto px-3"}`}
            >
              <nav
                aria-label={`${teacherSurface ? t("teacher") : t("student")} ${t("navigation")}`}
                className={`nav-links grid content-start ${collapsed ? "justify-items-center gap-3" : "gap-4"}`}
              >
                <Link
                  href={home}
                  aria-current={mayaformLit ? "page" : undefined}
                  aria-label={collapsed ? t("appName") : undefined}
                  data-tour="home"
                  data-lit={mayaformLit || undefined}
                  className={`isolate ${collapsed ? `${ICON_ITEM} group/tip ${mayaformLit ? "border-border bg-main shadow-arc-s" : "border-transparent"}` : mobile ? `${ITEM} w-fit justify-self-start border-transparent font-display text-lg font-extrabold` : `${ITEM} w-fit justify-self-start font-display text-lg font-extrabold ${mayaformLit ? ITEM_ACTIVE : ITEM_IDLE}`}${mayaformLit ? " active" : ""}`}
                >
                  {mayaformLit && !collapsed && !mobile ? pill : null}
                  <span
                    className={`brand-dot size-4 shrink-0 rounded-full border-2 border-border ${(collapsed || mayaformLit) && !mobile ? "bg-[linear-gradient(90deg,#111_50%,var(--color-surface)_50%)]" : "bg-[linear-gradient(90deg,#111_50%,var(--color-main)_50%)]"}`}
                    aria-hidden="true"
                  />
                  {collapsed ? null : <span>{t("appName")}</span>}
                  {railTip(t("appName"))}
                </Link>
                {groups.map((group) => {
                  const headingId = `sidebar-group-${group.key}`;

                  return (
                    <div
                      key={group.key}
                      role="group"
                      aria-labelledby={collapsed ? undefined : headingId}
                      aria-label={collapsed ? group.label : undefined}
                      data-sidebar-group={group.key}
                      className={
                        collapsed
                          ? `grid gap-1 rounded-arc-s border-[3px] border-border p-1 shadow-arc-s ${group.tile}`
                          : "grid gap-1.5"
                      }
                    >
                      {collapsed ? null : (
                        <div
                          id={headingId}
                          data-tour={group.headingTour}
                          className="flex items-center gap-1.5 px-1 font-body text-[11px] font-extrabold tracking-[0.08em] text-ink uppercase"
                        >
                          <span
                            aria-hidden="true"
                            className={`size-2.5 rounded-[3px] border-2 border-border ${group.square}`}
                          />
                          <span>{group.label}</span>
                        </div>
                      )}
                      <ul
                        className={
                          collapsed
                            ? "m-0 grid list-none gap-1 p-0"
                            : `m-0 ml-[9px] grid list-none gap-0.5 border-l-4 py-0 pr-0 pl-2 ${group.rail}`
                        }
                      >
                        {group.items.map((item, index) =>
                          renderItem(group, item, index),
                        )}
                      </ul>
                    </div>
                  );
                })}
                {/* Back and Done live in the page header (A mock); only New stays here. */}
                {([["new", "New"]] as const).map(([name, label]) => {
                  const action = actions[name];
                  // New stays in the sidebar once a page registers it, faded when
                  // it cannot run. Back and Done exist only while their owning
                  // screen needs them, and remain disabled during busy work.
                  if (!action || action.placement === "page") return null;
                  const faded = Boolean(action.disabled);
                  const content = (
                    <>
                      {action.busy ? (
                        <span className="spinner" aria-hidden="true" />
                      ) : (
                        <WorkspaceIcon name={name} size={18} />
                      )}
                      {collapsed ? (
                        <span className="sr-only">{label}</span>
                      ) : (
                        <span>{label}</span>
                      )}
                    </>
                  );
                  const actionClass = `${collapsed ? `${ICON_ITEM} group/tip` : ITEM} border-border bg-surface shadow-arc-s hover:-translate-y-px active:translate-x-[3px] active:translate-y-[3px] active:shadow-none`;
                  return action.href && !faded ? (
                    <Link
                      key={name}
                      className={actionClass}
                      href={action.href}
                      onClick={action.onClick}
                      data-ui-guide={`workspace.${name}`}
                    >
                      {content}
                      {railTip(label)}
                    </Link>
                  ) : (
                    <button
                      key={name}
                      className={`${actionClass} w-full cursor-pointer text-left disabled:cursor-not-allowed disabled:opacity-50`}
                      type={action.form ? "submit" : "button"}
                      form={action.form}
                      disabled={faded}
                      aria-busy={action.busy || undefined}
                      onClick={action.onClick}
                      data-ui-guide={`workspace.${name}`}
                    >
                      {content}
                      {railTip(label)}
                    </button>
                  );
                })}
              </nav>
              <div
                className={`mt-auto grid gap-2 ${collapsed ? "justify-items-center" : ""}`}
              >
                {collapsed ? (
                  <a
                    href="mailto:t330034059@mail.bnbu.edu.cn"
                    className={`${ICON_ITEM} group/tip border-border bg-surface shadow-arc-s`}
                  >
                    <WorkspaceIcon name="mail" size={18} />
                    <span className="sr-only">
                      Meet Problems? Send to t330034059@mail.bnbu.edu.cn
                    </span>
                    <span
                      aria-hidden="true"
                      className="pointer-events-none invisible absolute bottom-0 left-[calc(100%+6px)] z-20 grid w-[190px] gap-[3px] rounded-[6px] border-2 border-border bg-surface px-2.5 py-2 text-left font-body text-xs text-ink shadow-[3px_3px_0_#111] group-hover/tip:visible group-focus-visible/tip:visible"
                    >
                      <span className="font-bold">Meet Problems?</span>
                      <span className="break-all underline">
                        Send to t330034059@mail.bnbu.edu.cn
                      </span>
                    </span>
                  </a>
                ) : (
                  <p className="m-0 grid gap-[3px] rounded-[6px] border-2 border-border bg-surface px-2.5 py-2 font-body text-xs text-ink shadow-[3px_3px_0_#111]">
                    <span className="font-bold text-ink">Meet Problems?</span>
                    <a
                      className="font-normal break-all text-ink underline"
                      href="mailto:t330034059@mail.bnbu.edu.cn"
                    >
                      Send to t330034059@mail.bnbu.edu.cn
                    </a>
                  </p>
                )}
                <button
                  className={`${collapsed ? `${ICON_ITEM} group/tip` : `${ITEM} w-full`} cursor-pointer border-border bg-surface text-left shadow-arc-s active:translate-x-[3px] active:translate-y-[3px] active:shadow-none disabled:cursor-wait disabled:opacity-60`}
                  type="button"
                  disabled={busy}
                  data-ui-guide="workspace.logout"
                  onClick={() => void signOut()}
                >
                  <WorkspaceIcon name="logout" size={18} />
                  {collapsed ? (
                    <span className="sr-only">{t("logout")}</span>
                  ) : (
                    t("logout")
                  )}
                  {railTip(t("logout"))}
                </button>
              </div>
            </div>
          </div>
        </header>
        <main
          id="workspace-content"
          tabIndex={-1}
          className={`relative mx-auto w-[min(100%,1320px)] min-w-0 px-[clamp(24px,4vw,64px)] pt-12 max-[900px]:px-6 max-[900px]:pt-8 max-[480px]:px-4 max-[480px]:pt-7 ${workspaceStyles.surface} ${pathname === "/teacher/chat" || pathname === "/student/chat" ? "pb-[max(24px,env(safe-area-inset-bottom))]" : "pb-20 max-[900px]:pb-16 max-[480px]:pb-12"}`}
        >
          {(actions.back && actions.back.placement !== "page") ||
          (actions.done && actions.done.placement !== "page") ? (
            // Agents banners own theirs (placement "page"). The page header's own Back / Done, top-right (14 option A
            // "New Debate" header, the Agents pattern). Same handlers.
            <div
              data-page-actions
              className="relative z-10 mb-[22px] flex justify-end gap-2.5"
            >
              {(
                [
                  ["back", "Back"],
                  ["done", "Done"],
                ] as const
              ).map(([name, label]) => {
                const action = actions[name];
                if (!action || action.placement === "page") return null;
                const faded = Boolean(action.disabled);
                const cls = `inline-flex items-center gap-1.5 rounded-[10px] border-[3px] border-border px-[18px] py-2 font-body text-sm font-bold text-ink no-underline shadow-[3px_3px_0_#111] hover:-translate-y-px active:translate-x-[3px] active:translate-y-[3px] active:shadow-none max-[480px]:px-3 max-[480px]:py-1.5 max-[480px]:text-[13px] ${name === "done" ? "bg-main" : "bg-surface"}`;
                const content = (
                  <>
                    {action.busy ? (
                      <span className="spinner" aria-hidden="true" />
                    ) : null}
                    <span>{label}</span>
                  </>
                );
                return action.href && !faded ? (
                  <Link
                    key={name}
                    className={cls}
                    href={action.href}
                    onClick={action.onClick}
                    data-ui-guide={`workspace.${name}`}
                  >
                    {content}
                  </Link>
                ) : (
                  <button
                    key={name}
                    className={`${cls} cursor-pointer disabled:cursor-not-allowed disabled:opacity-50`}
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
            </div>
          ) : null}
          <ViewTransition>{children}</ViewTransition>
        </main>
        <SecretDoor />
        {isStudent && user ? (
          <OnboardingTour
            userId={user.id}
            pathname={pathname}
            navigate={router.push}
            startHere={pathname === "/student"}
          />
        ) : null}
      </div>
    </WorkspaceActionsContext.Provider>
  );
}

/** Pages whose own row shares its href with another row (Knowledge opens
 * Studyform), keyed by pathname. */
const PAGE_ROW: Record<string, string> = {
  "/teacher/knowledge": "knowledge",
  "/student/knowledge": "knowledge",
};

/**
 * Picks the sidebar row lit for the current page, most specific first: Voices
 * on its own page, then the first row whose href opens this very path, then
 * the page's own row, then the first row opening the
 * active page, then the row whose href is the longest prefix of the path.
 */
export function litSidebarKey(
  groups: { key: string; items: { key: string; href: string }[] }[],
  pathname: string,
  activeHref: string,
  voicesHref?: string,
): string | undefined {
  const rows = groups.flatMap((group) =>
    group.items.map((item) => ({ ...item, id: `${group.key}:${item.key}` })),
  );
  if (voicesHref && pathname === voicesHref) {
    const voices = rows.find((row) => row.key === "voices");
    if (voices) return voices.id;
  }
  const samePage = rows.find(
    (row) => row.href.split(/[?#]/, 1)[0] === pathname,
  );
  if (samePage) return samePage.id;
  const own = rows.find((row) => row.key === PAGE_ROW[pathname]);
  if (own) return own.id;
  const exact = rows.find((row) => row.href === activeHref);
  if (exact) return exact.id;
  let best: { id: string; length: number } | undefined;
  for (const row of rows) {
    const path = row.href.split(/[?#]/, 1)[0];
    if (!path || !(pathname === path || pathname.startsWith(`${path}/`)))
      continue;
    if (!best || path.length > best.length)
      best = { id: row.id, length: path.length };
  }
  return best?.id;
}
