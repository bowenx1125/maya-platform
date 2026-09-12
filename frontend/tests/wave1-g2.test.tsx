import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  createIdempotencyHandle,
  isConflict,
  PlatformApi,
  PlatformApiError,
  type AgentDetail,
  type AgentVersion,
  type AuthSession,
} from "../lib/api";
import {
  DraftConflictNotice,
  preserveDraftOnRetry,
} from "../components/agent-workspace";
import {
  LoginForm,
  SessionProvider,
  useSession,
} from "../components/session-provider";

const navigation = vi.hoisted(() => ({
  replace: vi.fn(),
  push: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => navigation,
  usePathname: () => "/login",
}));

function session(role: "teacher" | "student", csrfToken: string): AuthSession {
  return {
    csrf_token: csrfToken,
    expires_at: "2026-08-27T12:00:00Z",
    user: {
      id: `${role}-id`,
      username: role,
      display_name: role === "teacher" ? "Teacher" : "Student",
      courses: [{ course_id: "course-id", role }],
      groups: [],
    },
  };
}

function SessionProbe() {
  const { session: current, api } = useSession();
  return (
    <output data-testid="session-probe">
      {current?.user.display_name ?? "anonymous"}|{api.getCsrfToken() ?? "none"}
    </output>
  );
}

describe("G2 session and draft recovery paths", () => {
  beforeEach(() => {
    navigation.replace.mockReset();
    navigation.push.mockReset();
  });

  afterEach(() => vi.restoreAllMocks());

  it("switches demo identity through SessionProvider and atomically updates role/CSRF", async () => {
    let csrfToken = "none";
    const fakeApi = {
      me: vi.fn(async () => {
        csrfToken = "csrf-student";
        return session("student", csrfToken);
      }),
      demoIdentities: vi.fn(async () => [
        {
          user_id: "teacher-id",
          display_name: "Teacher",
          role: "teacher" as const,
        },
      ]),
      switchDemoIdentity: vi.fn(async () => {
        csrfToken = "csrf-teacher";
        return session("teacher", csrfToken);
      }),
      getCsrfToken: vi.fn(() => csrfToken),
    } as unknown as PlatformApi;

    render(
      <SessionProvider api={fakeApi}>
        <SessionProbe />
        <LoginForm />
      </SessionProvider>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("session-probe").textContent).toBe(
        "Student|csrf-student",
      ),
    );
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Teacher/ })).toBeTruthy(),
    );
    fireEvent.click(screen.getByRole("button", { name: /Teacher/ }));

    await waitFor(() =>
      expect(screen.getByTestId("session-probe").textContent).toBe(
        "Teacher|csrf-teacher",
      ),
    );
    expect(navigation.replace).toHaveBeenCalledWith("/teacher");
    expect(fakeApi.switchDemoIdentity).toHaveBeenCalledWith("teacher-id");
  });

  it("offers only local-preserving draft recovery for stale_revision", () => {
    const stale = new PlatformApiError(409, "Draft changed", {
      code: "stale_revision",
    });
    const otherConflict = new PlatformApiError(409, "Invalid state", {
      code: "invalid_state",
    });
    expect(isConflict(stale)).toBe(true);
    expect(isConflict(otherConflict)).toBe(false);
    expect(preserveDraftOnRetry(stale)).toBe(true);
    expect(preserveDraftOnRetry(otherConflict)).toBe(false);

    const refresh = vi.fn();
    render(<DraftConflictNotice onRefresh={refresh} />);
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    expect(refresh).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("alert").textContent).toContain("local AGENT.md");
  });
});

describe("G2 idempotency key lifecycle", () => {
  function draftAgent(): AgentDetail {
    return {
      id: "agent-id",
      group_id: "group-id",
      name: "Agent",
      status: "active",
      description: "",
      metadata_revision: 0,
      current_draft_version_id: "version-id",
      current_published_version_id: null,
      versions: [],
    } as AgentDetail;
  }

  function draftVersion(state: AgentVersion["state"] = "draft"): AgentVersion {
    return {
      id: "version-id",
      agent_id: "agent-id",
      version_label: "V1.0",
      state,
      revision: 0,
      agent_md: "# Agent",
      avatar_config: {
        template_id: "wave1-default-head",
        material_theme: "indigo",
        default_expression: "neutral",
        expression_strength: "medium",
        motion_style: "calm",
      },
      voice_fallback_active: true,
      persona_confirmed: false,
      enabled_documents: [],
      publish_blockers: [],
    } as AgentVersion;
  }

  it("reuses a key through ambiguous create/upload retries and rotates after publish completion", async () => {
    const api = new PlatformApi({ csrfToken: "csrf-token" });
    const client = (
      api as unknown as {
        client: { POST: (...args: unknown[]) => Promise<unknown> };
      }
    ).client;
    const post = vi.spyOn(client, "POST");
    const success = (data: unknown, status: number) => ({
      data,
      response: new Response(null, { status }),
    });

    const createAttempt = createIdempotencyHandle();
    post
      .mockRejectedValueOnce(new TypeError("connection reset"))
      .mockResolvedValueOnce(success(draftAgent(), 201));
    await expect(
      api.createAgent("group-id", "Agent", "", { idempotency: createAttempt }),
    ).rejects.toThrow("connection reset");
    await api.createAgent("group-id", "Agent", "", {
      idempotency: createAttempt,
    });
    const createKey1 = (
      post.mock.calls[0][1] as {
        params: { header: { "Idempotency-Key": string } };
      }
    ).params.header["Idempotency-Key"];
    const createKey2 = (
      post.mock.calls[1][1] as {
        params: { header: { "Idempotency-Key": string } };
      }
    ).params.header["Idempotency-Key"];
    expect(createKey2).toBe(createKey1);

    const uploadAttempt = createIdempotencyHandle();
    post
      .mockRejectedValueOnce(new TypeError("request timed out"))
      .mockResolvedValueOnce(
        success({ document: {}, agent_version: draftVersion() }, 201),
      );
    await expect(
      api.uploadKnowledge(
        "group-id",
        "version-id",
        new File(["# evidence"], "evidence.md"),
        0,
        { idempotency: uploadAttempt },
      ),
    ).rejects.toThrow("request timed out");
    await api.uploadKnowledge(
      "group-id",
      "version-id",
      new File(["# evidence"], "evidence.md"),
      0,
      { idempotency: uploadAttempt },
    );
    const uploadKey1 = (
      post.mock.calls[2][1] as {
        params: { header: { "Idempotency-Key": string } };
      }
    ).params.header["Idempotency-Key"];
    const uploadKey2 = (
      post.mock.calls[3][1] as {
        params: { header: { "Idempotency-Key": string } };
      }
    ).params.header["Idempotency-Key"];
    expect(uploadKey2).toBe(uploadKey1);

    const publishAttempt = createIdempotencyHandle();
    post
      .mockResolvedValueOnce(success(draftVersion("published"), 200))
      .mockResolvedValueOnce(success(draftVersion("published"), 200));
    await api.publish("version-id", 0, { idempotency: publishAttempt });
    const publishKey1 = (
      post.mock.calls[4][1] as {
        params: { header: { "Idempotency-Key": string } };
      }
    ).params.header["Idempotency-Key"];
    await api.publish("version-id", 0, { idempotency: publishAttempt });
    const publishKey2 = (
      post.mock.calls[5][1] as {
        params: { header: { "Idempotency-Key": string } };
      }
    ).params.header["Idempotency-Key"];
    expect(publishKey2).not.toBe(publishKey1);
  });
});
