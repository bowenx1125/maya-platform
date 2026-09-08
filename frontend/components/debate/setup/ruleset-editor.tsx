"use client";

import { useState } from "react";
import { ReportMarkdown } from "../../report/report-markdown";
import { SectionCard } from "../../ui";
import styles from "./ruleset-editor.module.css";

export type TeachingPrompts = { zh: string; en: string };

export function RulesetEditor({
  prompts,
  language,
  disabled = false,
  onLanguageChange,
  onSave,
  onEditingChange,
}: {
  prompts: TeachingPrompts;
  language: "zh" | "en";
  disabled?: boolean;
  onLanguageChange: (language: "zh" | "en") => void;
  onSave: (prompts: TeachingPrompts) => void;
  onEditingChange: (editing: boolean) => void;
}) {
  const [mode, setMode] = useState<"closed" | "details" | "edit">("closed");
  const [draft, setDraft] = useState(prompts);
  const editing = mode === "edit";

  return (
    <SectionCard
      title="Debate Ruleset"
      className={styles.card}
      action={
        <div className={styles.actions}>
          <div
            className={styles.languageSwitch}
            role="group"
            aria-label="Language"
          >
            {(["zh", "en"] as const).map((value) => (
              <button
                key={value}
                type="button"
                disabled={disabled || editing}
                aria-pressed={language === value}
                onClick={() => onLanguageChange(value)}
              >
                {value === "zh" ? "中文" : "English"}
              </button>
            ))}
          </div>
          <button
            type="button"
            className={styles.action}
            disabled={disabled || editing}
            aria-expanded={mode !== "closed"}
            aria-controls="ruleset-content"
            onClick={() => setMode(mode === "closed" ? "details" : "closed")}
          >
            Details
          </button>
          <button
            type="button"
            className={styles.action}
            disabled={disabled || mode === "closed"}
            onClick={() => {
              if (editing) {
                onSave({ ...draft });
                setMode("details");
                onEditingChange(false);
              } else {
                setDraft({ ...prompts });
                setMode("edit");
                onEditingChange(true);
              }
            }}
          >
            {editing ? "Save" : "Edit"}
          </button>
        </div>
      }
    >
      {mode !== "closed" ? (
        <div id="ruleset-content" className={styles.columns}>
          {(["zh", "en"] as const).map((value) => (
            <section className={styles.column} key={value}>
              <h3>{value === "zh" ? "Prompt CN" : "Prompt EN"}</h3>
              {editing ? (
                <textarea
                  aria-label={value === "zh" ? "Prompt CN" : "Prompt EN"}
                  className={styles.raw}
                  value={draft[value]}
                  disabled={disabled}
                  spellCheck={false}
                  onChange={(event) =>
                    setDraft({ ...draft, [value]: event.target.value })
                  }
                />
              ) : (
                <div className={styles.document}>
                  <ReportMarkdown
                    label={value === "zh" ? "Prompt CN" : "Prompt EN"}
                  >
                    {prompts[value]}
                  </ReportMarkdown>
                </div>
              )}
            </section>
          ))}
        </div>
      ) : null}
    </SectionCard>
  );
}
