"use client";

import { useEffect, useRef, useState } from "react";

import type { ChatAttachment } from "../../lib/api/platform";
import { localizeError } from "../../lib/i18n";
import { useT } from "../../lib/i18n";
import { IconClose } from "../quiet-icons";
import { useSession } from "../session-provider";
import styles from "../agent-chat.module.css";

const ACCEPT = ".txt,.md,.json,.csv,.html,.htm";

/**
 * The "+" at the composer's lower left and the files above the text box.
 * Files belong to this one Chat (Team or single Agent) and are read only by
 * its owner; the
 * server enforces both, this only lists what it returns. Callers key it by
 * the Chat id so switching Chats starts from an empty list.
 */
export function ChatAttachments({
  conversationId,
  disabled,
}: {
  conversationId: string;
  disabled: boolean;
}) {
  const { api } = useSession();
  const t = useT();
  const input = useRef<HTMLInputElement>(null);
  const [items, setItems] = useState<ChatAttachment[]>([]);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    let active = true;
    // A refused list (no access, no longer this user's Chat) shows no files.
    Promise.resolve()
      .then(() => api.conversationAttachments(conversationId))
      .then((rows) => {
        if (active) setItems(rows);
      })
      .catch(() => {
        if (active) setItems([]);
      });
    return () => {
      active = false;
    };
  }, [api, conversationId]);

  const upload = async (file: File) => {
    setUploading(true);
    setError(null);
    try {
      const created = await api.uploadConversationAttachment(
        conversationId,
        file,
      );
      setItems((current) => [...current, created]);
    } catch (cause) {
      setError(cause);
    } finally {
      setUploading(false);
    }
  };

  const remove = async (attachment: ChatAttachment) => {
    setError(null);
    try {
      await api.deleteConversationAttachment(conversationId, attachment.id);
      setItems((current) =>
        current.filter((item) => item.id !== attachment.id),
      );
    } catch (cause) {
      setError(cause);
    }
  };

  return (
    <>
      {items.length || uploading || error ? (
        <div className={styles.attachmentRow}>
          {items.map((item) => (
            <span key={item.id} className={styles.attachmentChip}>
              <span className={styles.attachmentName}>{item.filename}</span>
              <button
                type="button"
                className={styles.attachmentRemove}
                aria-label={t("chatAttachmentRemove", { name: item.filename })}
                disabled={disabled}
                onClick={() => void remove(item)}
              >
                <IconClose size={12} />
              </button>
            </span>
          ))}
          {uploading ? (
            <span className={styles.attachmentChip} role="status">
              {t("chatAttachmentUploading")}
            </span>
          ) : null}
          {error ? (
            <p className={styles.attachmentError} role="alert">
              {localizeError(error, "errorFileOperationFailed")}
            </p>
          ) : null}
        </div>
      ) : null}
      <button
        type="button"
        className={styles.attachButton}
        aria-label={t("chatAttach")}
        title={t("chatAttachHelp")}
        disabled={disabled || uploading}
        onClick={() => input.current?.click()}
      >
        <svg
          viewBox="0 0 24 24"
          width="18"
          height="18"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.2"
          strokeLinecap="round"
          aria-hidden="true"
        >
          <path d="M12 5v14M5 12h14" />
        </svg>
      </button>
      <input
        ref={input}
        type="file"
        accept={ACCEPT}
        hidden
        data-testid="chat-attachment-input"
        onChange={(event) => {
          const file = event.target.files?.[0];
          event.target.value = "";
          if (file) void upload(file);
        }}
      />
    </>
  );
}
