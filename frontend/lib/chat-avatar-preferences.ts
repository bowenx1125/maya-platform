import {
  isChatAvatarModelId,
  type ChatAvatarModelId,
} from "../components/avatar/types";

const memoryPreferences = new Map<string, ChatAvatarModelId>();

function preferenceKey(userId: string, agentId: string): string {
  return `maya.chat-avatar.v1:${encodeURIComponent(userId)}:${encodeURIComponent(agentId)}`;
}

export function readChatAvatarPreference(
  userId: string,
  agentId: string,
): ChatAvatarModelId | null {
  const key = preferenceKey(userId, agentId);
  const inMemory = memoryPreferences.get(key);
  if (inMemory) return inMemory;
  try {
    const saved = window.localStorage.getItem(key);
    if (saved && isChatAvatarModelId(saved)) {
      memoryPreferences.set(key, saved);
      return saved;
    }
  } catch {
    return null;
  }
  return null;
}

export function saveChatAvatarPreference(
  userId: string,
  agentId: string,
  modelId: ChatAvatarModelId,
): void {
  const key = preferenceKey(userId, agentId);
  memoryPreferences.set(key, modelId);
  try {
    window.localStorage.setItem(key, modelId);
  } catch {
    // The in-memory preference still applies for this page session.
  }
}
