import { describe, expect, it } from "vitest";

import {
  readChatAvatarPreference,
  saveChatAvatarPreference,
} from "../lib/chat-avatar-preferences";

describe("Chat avatar preferences", () => {
  it("keeps choices separate by user and stable Agent ID", () => {
    saveChatAvatarPreference("user-a", "agent-a", "maya-civic-observer");

    expect(readChatAvatarPreference("user-a", "agent-a")).toBe(
      "maya-civic-observer",
    );
    expect(readChatAvatarPreference("user-b", "agent-a")).toBeNull();
    expect(readChatAvatarPreference("user-a", "agent-b")).toBeNull();
  });

  it("ignores values outside the local model catalog", () => {
    window.localStorage.setItem(
      "maya.chat-avatar.v1:user-c:agent-c",
      "/remote/model.glb",
    );

    expect(readChatAvatarPreference("user-c", "agent-c")).toBeNull();
  });
});
