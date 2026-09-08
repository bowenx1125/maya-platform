"use client";

import { useState } from "react";
import { ReportMarkdown } from "../../report/report-markdown";
import { SectionCard } from "../../ui";
import styles from "./ruleset-editor.module.css";
import sectionStyles from "./create-section.module.css";

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
  const [mode, setMode] = useState<"details" | "edit">("details");
  const [draft, setDraft] = useState(prompts);
  const editing = mode === "edit";

  return (
    <SectionCard
      title="Debate Ruleset"
      className={`${styles.card} ${sectionStyles.section}`}
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
            disabled={disabled}
            onClick={() => {
              if (editing) {
                onSave({ ...prompts, [language]: draft[language] });
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
      <div id="ruleset-content" className={styles.content}>
        {editing ? (
          <textarea
            aria-label={language === "zh" ? "中文规则" : "English rules"}
            className={styles.raw}
            value={draft[language]}
            disabled={disabled}
            spellCheck={false}
            onChange={(event) =>
              setDraft({ ...draft, [language]: event.target.value })
            }
          />
        ) : (
          <div className={styles.document}>
            <ReportMarkdown
              label={language === "zh" ? "中文规则" : "English rules"}
            >
              {prompts[language]}
            </ReportMarkdown>
          </div>
        )}
      </div>
    </SectionCard>
  );
}
