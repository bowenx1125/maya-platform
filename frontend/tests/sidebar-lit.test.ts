import { describe, expect, it } from "vitest";
import { litSidebarKey } from "../components/app-shell";

const teacher = [
  {
    key: "studyform",
    items: [
      { key: "agents", href: "/teacher/agents" },
      { key: "teams", href: "/teacher/teams" },
    ],
  },
  {
    key: "brainform",
    items: [
      { key: "rag", href: "/teacher/rag" },
      { key: "record", href: "/teacher/record" },
      { key: "knowledge", href: "/teacher/knowledge" },
    ],
  },
  { key: "chatform", items: [{ key: "chat-agent", href: "/teacher/chat" }] },
  {
    key: "classroom",
    items: [
      { key: "classroom", href: "/teacher/debates" },
      { key: "accounts", href: "/teacher/roster" },
    ],
  },
];

describe("litSidebarKey", () => {
  it("lights Knowledge on /teacher/knowledge, not Teams or Agents", () => {
    expect(
      litSidebarKey(teacher, "/teacher/knowledge", "/teacher/knowledge"),
    ).toBe("brainform:knowledge");
  });

  it("lights Record on /teacher/record, not Teams or Knowledge", () => {
    expect(litSidebarKey(teacher, "/teacher/record", "/teacher/record")).toBe(
      "brainform:record",
    );
  });
  it("lights Team chat only for a team list URL", () => {
    const rows = [
      {
        key: "chatform",
        items: [
          { key: "chat-agent", href: "/teacher/chat" },
          { key: "chat-team", href: "/teacher/chat?kind=team" },
        ],
      },
    ];
    expect(litSidebarKey(rows, "/teacher/chat", "/teacher/chat")).toBe(
      "chatform:chat-agent",
    );
    expect(
      litSidebarKey(
        rows,
        "/teacher/chat",
        "/teacher/chat",
        undefined,
        "?kind=team",
      ),
    ).toBe("chatform:chat-team");
    expect(
      litSidebarKey(
        rows,
        "/teacher/chat",
        "/teacher/chat?group_id=g",
        undefined,
        "?group_id=g&kind=team",
      ),
    ).toBe("chatform:chat-team");
  });
  it("lights the first row opening the active page", () => {
    expect(litSidebarKey(teacher, "/teacher/agents", "/teacher/agents")).toBe(
      "studyform:agents",
    );
    expect(litSidebarKey(teacher, "/teacher/chat", "/teacher/chat")).toBe(
      "chatform:chat-agent",
    );
  });
  it("prefers the longest href prefix for nested pages", () => {
    const rows = [
      { key: "a", items: [{ key: "home", href: "/student" }] },
      {
        key: "b",
        items: [{ key: "group", href: "/student/agents?group_id=g1" }],
      },
    ];
    expect(
      litSidebarKey(rows, "/student/agents", "/student/agents?group_id=g1"),
    ).toBe("b:group");
  });
  it("lights Voices on its own page", () => {
    const rows = [
      {
        key: "brainform",
        items: [
          { key: "rag", href: "/student/rag" },
          { key: "voices", href: "/student/voices" },
        ],
      },
    ];
    expect(
      litSidebarKey(
        rows,
        "/student/voices",
        "/student/voices",
        "/student/voices",
      ),
    ).toBe("brainform:voices");
  });
});

describe("litSidebarKey for a visiting teacher", () => {
  it("lights the row whose href opens the current path", () => {
    const rows = [
      {
        key: "studyform",
        items: [{ key: "agents", href: "/student/agents?group_id=g" }],
      },
      {
        key: "brainform",
        items: [
          { key: "rag", href: "/teacher/rag?group_id=g" },
          { key: "knowledge", href: "/teacher/knowledge?group_id=g" },
        ],
      },
    ];
    expect(
      litSidebarKey(
        rows,
        "/teacher/knowledge",
        "/teacher/knowledge?group_id=g",
      ),
    ).toBe("brainform:knowledge");
  });
});
