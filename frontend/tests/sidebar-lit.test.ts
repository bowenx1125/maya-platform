import { describe, expect, it } from "vitest";
import { litSidebarKey } from "../components/app-shell";

const teacher = [
  {
    key: "studyform",
    items: [
      { key: "agents", href: "/teacher/studyform" },
      { key: "teams", href: "/teacher/studyform" },
    ],
  },
  {
    key: "brainform",
    items: [
      { key: "rag", href: "/teacher/studyform" },
      { key: "knowledge", href: "/teacher/studyform" },
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
      litSidebarKey(teacher, "/teacher/knowledge", "/teacher/studyform"),
    ).toBe("brainform:knowledge");
  });
  it("lights the first row opening the active page", () => {
    expect(
      litSidebarKey(teacher, "/teacher/studyform", "/teacher/studyform"),
    ).toBe("studyform:agents");
    expect(litSidebarKey(teacher, "/teacher/chat", "/teacher/chat")).toBe(
      "chatform:chat-agent",
    );
  });
  it("prefers the longest href prefix for nested pages", () => {
    const rows = [
      { key: "a", items: [{ key: "home", href: "/student" }] },
      { key: "b", items: [{ key: "group", href: "/student/groups/g1" }] },
    ];
    expect(litSidebarKey(rows, "/student/groups/g1/agents/x", "/none")).toBe(
      "b:group",
    );
  });
  it("lights Voices on its own page", () => {
    const rows = [
      {
        key: "brainform",
        items: [
          { key: "rag", href: "/student/groups/g1" },
          { key: "voices", href: "/student/groups/g1/voices" },
        ],
      },
    ];
    expect(
      litSidebarKey(
        rows,
        "/student/groups/g1/voices",
        "/student/groups/g1",
        "/student/groups/g1/voices",
      ),
    ).toBe("brainform:voices");
  });
});

describe("litSidebarKey for a visiting teacher", () => {
  it("lights the row whose href opens the current path", () => {
    const rows = [
      {
        key: "studyform",
        items: [{ key: "agents", href: "/student/groups/g" }],
      },
      {
        key: "brainform",
        items: [
          { key: "rag", href: "/teacher/knowledge?group_id=g" },
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
    ).toBe("brainform:rag");
  });
});
