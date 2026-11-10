import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import {
  ChatTargetPicker,
  type ChatTargetAgent,
} from "../components/chats/chat-target-picker";
import type { ChatAgent } from "../lib/api";

const avatar = {
  template_id: "wave1-default-head",
  material_theme: "demo",
  eye_color: null,
  default_expression: "neutral" as const,
  expression_strength: "medium" as const,
  motion_style: "calm" as const,
};

function agent(
  name: string,
  extra: Partial<ChatTargetAgent> = {},
): ChatTargetAgent {
  return {
    agent_id: "00000000-0000-4000-8000-000000000001",
    version_id: "00000000-0000-4000-8000-000000000101",
    course_id: "00000000-0000-4000-8000-000000000200",
    name,
    version_label: "V1.0",
    visibility: "public",
    available: true,
    deleted: false,
    avatar_config: avatar,
    ...extra,
  };
}

function renderAgents(agents: ChatTargetAgent[]) {
  return render(
    <ChatTargetPicker
      surface="agent"
      teams={[]}
      agents={agents}
      value=""
      disabled={false}
      onPick={() => undefined}
    />,
  );
}

afterEach(cleanup);

describe("New Agent chat cards", () => {
  it("shows the name and version and leaves off visibility", () => {
    renderAgents([agent("Socrates")]);
    const card = screen.getByRole("button", { name: /Socrates/ });
    expect(card.textContent).toContain("V1.0");
    expect(card.textContent).toContain("Version");
    expect(card.textContent).not.toContain("Public");
    expect(card.textContent).not.toContain("Private");
    expect(card.getAttribute("type")).toBe("button");
    expect(card.hasAttribute("disabled")).toBe(false);
  });

  it("shows group and last editor only when the catalog sent them", () => {
    const { unmount } = renderAgents([
      agent("Socrates", {
        group_name: "Philosophy",
        last_edited_by_name: "Kaikai",
      }),
    ]);
    const full = screen.getByRole("button", { name: /Socrates/ });
    expect(full.textContent).toContain("Group");
    expect(full.textContent).toContain("Philosophy");
    expect(full.textContent).toContain("Last edited by: Kaikai");
    unmount();

    renderAgents([
      agent("Mencius", {
        version_label: "V2.0",
        group_name: "   ",
        last_edited_by_name: "",
      }),
    ]);
    const sparse = screen.getByRole("button", { name: /Mencius/ });
    expect(sparse.textContent).toContain("V2.0");
    expect(sparse.textContent).not.toContain("Group");
    expect(sparse.textContent).not.toContain("Last edited by");
  });

  it("keeps a long name inside the card and a 44px hit target", () => {
    const name = "Aristotle of Stagira Who Wrote on Everything That Moves";
    renderAgents([agent(name, { version_label: "V12.4" })]);
    const card = screen.getByRole("button", { name: new RegExp(name) });
    expect(card.querySelector(".fit-title-text")?.textContent).toBe(name);
    const css = readFileSync(
      resolve(process.cwd(), "components/agent-chat.module.css"),
      "utf8",
    );
    expect(css).toContain(".pickAgentCard");
    expect(css).toMatch(/\.pickAgentCard\s*\{[^}]*min-height:\s*44px/);
    expect(css).toContain("overflow-wrap: anywhere");
    expect(css).toMatch(/\.pickAgentCard:focus-visible/);
  });

  it("still accepts a plain ChatAgent from the current catalog", () => {
    const catalog: ChatAgent[] = [agent("Socrates")];
    render(
      <ChatTargetPicker
        surface="agent"
        teams={[]}
        agents={catalog}
        value=""
        disabled={false}
        onPick={() => undefined}
      />,
    );
    expect(
      screen.getByRole("button", { name: /Socrates/ }).textContent,
    ).toContain("V1.0");
  });
});
