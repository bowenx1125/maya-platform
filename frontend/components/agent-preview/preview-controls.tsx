"use client";

import { useState } from "react";
import { WorkspaceIcon } from "../workspace-icon";
import styles from "./preview.module.css";

export function PreviewControls({
  question,
  answer,
  onClose,
  onSend,
}: {
  question: string;
  answer: string;
  onClose: () => void;
  onSend: (message: string) => void;
}) {
  const [message, setMessage] = useState("");
  return (
    <>
      <button
        type="button"
        className={styles.close}
        aria-label="Close"
        onClick={onClose}
      >
        <WorkspaceIcon name="close" size={20} />
      </button>
      <div className={styles.captions} aria-live="polite">
        {answer ? (
          <p className={`${styles.bubble} ${styles.answer}`}>{answer}</p>
        ) : null}
        <div className={styles.dock}>
          {question ? (
            <p className={`${styles.bubble} ${styles.question}`}>{question}</p>
          ) : null}
          <form
            className={styles.pill}
            onSubmit={(event) => {
              event.preventDefault();
              if (!message.trim()) return;
              onSend(message.trim());
              setMessage("");
            }}
          >
            <input
              aria-label="Message"
              placeholder="Type a message..."
              value={message}
              onChange={(event) => setMessage(event.target.value)}
            />
            <button type="submit" aria-label="Send">
              <WorkspaceIcon name="send" size={20} />
            </button>
          </form>
        </div>
      </div>
    </>
  );
}
