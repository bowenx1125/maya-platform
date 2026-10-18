import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({
  api: {} as Record<string, ReturnType<typeof vi.fn>>,
}));

vi.mock("../components/session-provider", () => ({
  useSession: () => ({ api: state.api }),
}));

import { ChatAttachments } from "../components/chats/chat-attachments";
import { LocaleProvider } from "../components/locale";
import { PlatformApiError } from "../lib/api/platform";

const saved = {
  id: "attachment-1",
  conversation_id: "conversation-1",
  filename: "她的聊天记录.txt",
  media_type: "text/plain",
  size_bytes: 12,
  text_chars: 4,
  created_at: "2026-10-18T00:00:00Z",
};

function view(disabled = false) {
  return render(
    <LocaleProvider initialLocale="zh">
      <ChatAttachments conversationId="conversation-1" disabled={disabled} />
    </LocaleProvider>,
  );
}

afterEach(() => {
  cleanup();
  state.api = {};
});

describe("Chat attachments", () => {
  it("lists this chat's files, uploads one and removes one", async () => {
    state.api = {
      conversationAttachments: vi.fn().mockResolvedValue([saved]),
      uploadConversationAttachment: vi.fn().mockResolvedValue({
        ...saved,
        id: "attachment-2",
        filename: "export.json",
      }),
      deleteConversationAttachment: vi.fn().mockResolvedValue(undefined),
    };
    view();
    expect(await screen.findByText("她的聊天记录.txt")).toBeTruthy();
    expect(state.api.conversationAttachments).toHaveBeenCalledWith(
      "conversation-1",
    );
    const add = screen.getByRole("button", { name: "添加附件" });
    expect(add.getAttribute("title")).toContain("只有你能看到");
    const file = new File(["{}"], "export.json", { type: "application/json" });
    const input = screen.getByTestId("chat-attachment-input");
    expect(input.getAttribute("accept")).toBe(".txt,.md,.json,.csv,.html,.htm");
    fireEvent.change(input, { target: { files: [file] } });
    expect(await screen.findByText("export.json")).toBeTruthy();
    expect(state.api.uploadConversationAttachment).toHaveBeenCalledWith(
      "conversation-1",
      file,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "移除 她的聊天记录.txt" }),
    );
    await waitFor(() =>
      expect(screen.queryByText("她的聊天记录.txt")).toBeNull(),
    );
    expect(state.api.deleteConversationAttachment).toHaveBeenCalledWith(
      "conversation-1",
      "attachment-1",
    );
  });

  it("shows the server's refusal and keeps nothing", async () => {
    state.api = {
      conversationAttachments: vi.fn().mockResolvedValue([]),
      uploadConversationAttachment: vi.fn().mockRejectedValue(
        new PlatformApiError(422, "unsupported", {
          code: "chat_attachment_type_unsupported",
          message: "unsupported",
          request_id: "r",
        }),
      ),
    };
    view();
    fireEvent.change(screen.getByTestId("chat-attachment-input"), {
      target: { files: [new File(["x"], "photo.png")] },
    });
    expect((await screen.findByRole("alert")).textContent).toBe(
      "请上传 .txt、.md、.json、.csv 或 .html 文件。",
    );
    expect(screen.queryByText("photo.png")).toBeNull();
  });

  it("is disabled while the Team is answering", async () => {
    state.api = { conversationAttachments: vi.fn().mockResolvedValue([]) };
    view(true);
    const add = screen.getByRole("button", { name: "添加附件" });
    expect((add as HTMLButtonElement).disabled).toBe(true);
  });
});
