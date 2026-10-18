/**
 * Page-load round trips for Studyform, Brainform and Chatform.
 *
 * Every API read answers after LATENCY_MS. A read's round is one more than
 * the highest round already answered when it started, so the deepest round
 * is the number of sequential round trips the page waits for. Voice lists
 * are left out (the Voices panel is measured separately).
 * MEASURE_FILE=<path> also appends timings for before/after comparisons.
 */
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { appendFileSync } from "node:fs";
import type { ReactElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

const LATENCY_MS = Number(process.env.LATENCY_MS ?? 40);
const VOICE_READS = new Set(["voiceProfiles", "personalVoiceProfiles"]);

type Call = { name: string; round: number; end?: number };

const h = vi.hoisted(() => ({
  session: {
    api: {} as Record<string, unknown>,
    identityGeneration: 1,
    user: null as unknown,
  },
  pathname: "/student/groups/group-1",
}));

vi.mock("../components/session-provider", () => ({
  useSession: () => h.session,
}));
vi.mock("next/navigation", () => ({
  usePathname: () => h.pathname,
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

import { AgentChat } from "../components/agent-chat";
import { BrainformWorkspace } from "../components/knowledge/brainform-workspace";
import { LocaleProvider } from "../components/locale";
import { GroupWorkspace } from "../components/student-workspace";
import { TeacherStudyformWorkspace } from "../components/teacher-workspace";

const team = {
  id: "team-1",
  display_name: "Debate Team",
  current_version_seq: 1,
  visibility: "public",
  can_edit: false,
};
const chatAgent = {
  agent_id: "agent-1",
  version_id: "version-1",
  course_id: "course-1",
  name: "Socrates",
  version_label: "V1",
  avatar_config: {},
};
const answers: Record<string, unknown> = {
  group: { id: "group-1", course_id: "course-1", name: "Group One" },
  agents: [
    {
      id: "agent-1",
      name: "Socrates",
      status: "published",
      can_edit: true,
      visibility: "public",
    },
  ],
  versions: [{ id: "v1", state: "published", version_label: "V1.0" }],
  teams: [team],
  chatAgents: [chatAgent],
  publishedAgents: [],
  workspaceAgents: [],
  courses: [{ id: "course-1", name: "Course One" }],
  groups: [],
  knowledge: [],
  workspaceDocuments: [],
  brainformKnowledge: [
    {
      canonical_set_id: "set-1",
      source_agent_display_name: "Socrates",
      knowledge_display_name: "Socrates Knowledge",
      version_seq: 1,
      content_hash: "b".repeat(64),
      projection_available: true,
      can_read: true,
      can_edit: false,
      created_at: "2026-10-06T00:00:00Z",
    },
  ],
  mayaTeams: [],
  conversationSessions: [],
  conversations: [],
  voiceProfiles: [],
  personalVoiceProfiles: [],
};

let calls: Call[] = [];
let answered = 0;

function trackedApi(): Record<string, unknown> {
  const fns = new Map<string, (...args: unknown[]) => Promise<unknown>>();
  return new Proxy(
    {},
    {
      get(_target, prop) {
        if (typeof prop !== "string" || prop === "then") return undefined;
        if (!(prop in answers)) return undefined;
        let fn = fns.get(prop);
        if (!fn) {
          fn = () => {
            const call: Call = { name: prop, round: answered + 1 };
            calls.push(call);
            return new Promise((done) =>
              setTimeout(() => {
                if (!VOICE_READS.has(prop))
                  answered = Math.max(answered, call.round);
                call.end = performance.now();
                done(structuredClone(answers[prop]));
              }, LATENCY_MS),
            );
          };
          fns.set(prop, fn);
        }
        return fn;
      },
    },
  );
}

type Visit = {
  /** Until the page's content is on screen. */
  paintMs: number;
  rounds: number;
  requests: number;
  /** Until every read the page started has answered. */
  ms: number;
  names: string[];
};

async function visit(page: () => ReactElement, marker: string): Promise<Visit> {
  calls = [];
  answered = 0;
  const started = performance.now();
  render(<LocaleProvider initialLocale="en">{page()}</LocaleProvider>);
  await screen.findAllByText(marker, {}, { timeout: 5000 });
  const paintMs = performance.now() - started;
  await waitFor(
    () =>
      expect(
        calls.filter((call) => !VOICE_READS.has(call.name) && !call.end),
      ).toEqual([]),
    { timeout: 5000 },
  );
  const ms = performance.now() - started;
  await new Promise((done) => setTimeout(done, LATENCY_MS * 2));
  const page_calls = calls.filter((call) => !VOICE_READS.has(call.name));
  cleanup();
  return {
    paintMs,
    rounds: Math.max(0, ...page_calls.map((call) => call.round)),
    requests: page_calls.length,
    ms,
    names: page_calls.map((call) => `${call.name}@${call.round}`),
  };
}

function record(page: string, label: string, result: Visit) {
  const file = process.env.MEASURE_FILE;
  if (!file) return;
  appendFileSync(
    file,
    `${page}\t${label}\trounds=${result.rounds}\trequests=${result.requests}\tpaint=${result.paintMs.toFixed(0)}ms\tsettled=${result.ms.toFixed(0)}ms\t${result.names.join(",")}\n`,
  );
}

async function visits(
  page: string,
  render: () => ReactElement,
  marker: string,
) {
  const first = await visit(render, marker);
  record(page, "first", first);
  const soon = await visit(render, marker);
  record(page, "return<10s", soon);
  const now = Date.now() + 60_000;
  vi.spyOn(Date, "now").mockReturnValue(now);
  const later = await visit(render, marker);
  record(page, "return>10s", later);
  vi.restoreAllMocks();
  return { first, soon, later };
}

function signIn(role: "student" | "teacher", userId: string) {
  h.session = {
    api: trackedApi(),
    identityGeneration: 1,
    user: {
      id: userId,
      username: userId,
      display_name: userId,
      courses: [{ course_id: "course-1", role, name: "Course One" }],
      groups:
        role === "student" ? [{ group_id: "group-1", role: "member" }] : [],
    },
  };
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("page-load round trips", () => {
  it("student Studyform: two round trips, nothing re-asked on a quick return", async () => {
    signIn("student", "student-studyform");
    h.pathname = "/student/groups/group-1";
    const { first, soon, later } = await visits(
      "studyform-student",
      () => <GroupWorkspace groupId="group-1" />,
      "Debate Team",
    );
    expect(first.rounds).toBeLessThanOrEqual(2);
    expect(soon.requests).toBe(0);
    expect(later.requests).toBe(first.requests);
  });

  it("teacher Studyform: one round trip", async () => {
    signIn("teacher", "teacher-studyform");
    h.pathname = "/teacher/studyform";
    const { first, soon } = await visits(
      "studyform-teacher",
      () => <TeacherStudyformWorkspace />,
      "Debate Team",
    );
    expect(first.rounds).toBe(1);
    expect(soon.requests).toBe(0);
  });

  it("student Brainform: one round trip, each group read once", async () => {
    signIn("student", "student-brainform");
    h.pathname = "/student/knowledge";
    const { first, soon } = await visits(
      "brainform-student",
      () => <BrainformWorkspace role="student" />,
      "Socrates Knowledge",
    );
    expect(first.rounds).toBe(1);
    expect(first.names.filter((name) => name.startsWith("group@"))).toEqual([
      "group@1",
    ]);
    expect(soon.requests).toBe(0);
  });

  it("student Chatform: catalog, history and Team choices in one round trip", async () => {
    signIn("student", "student-chat");
    h.pathname = "/student/chat";
    const { first, soon } = await visits(
      "chatform-student",
      () => <AgentChat />,
      "No chats yet.",
    );
    expect(first.rounds).toBe(1);
    // History is always read fresh; the catalog and Team lists are reused.
    expect(soon.names).toEqual(["conversationSessions@1"]);
  });
});
