"use client";

import { useState } from "react";
import { ReportMarkdown } from "../../report/report-markdown";
import { IconArrowLeft, IconCheck, IconEdit } from "../../quiet-icons";
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
  // Dirty only when the visible language's text changed — drives back→checkmark.
  const dirty = editing && draft[language] !== prompts[language];

  function save() {
    if (disabled) return;
    onSave({ ...prompts, [language]: draft[language] });
    setMode("details");
    onEditingChange(false);
  }

  function cancel() {
    setDraft({ ...prompts });
    setMode("details");
    onEditingChange(false);
  }

  // Ruleset chrome stays on this card: edit → back → checkmark when dirty.
  // Do not register left-rail Back/Done here — those belong to the whole Debate.
  return (
    <SectionCard
      title="Debate Ruleset"
      className={`${styles.card} ${sectionStyles.section}`}
      guide="debate.ruleset"
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
          {editing ? (
            <button
              type="button"
              className={`${styles.action} ${styles.iconAction}`}
              disabled={disabled}
              aria-label={dirty ? "Save" : "Back"}
              data-ui-guide={dirty ? "debate.rulesetSave" : "debate.rulesetBack"}
              onClick={dirty ? save : cancel}
            >
              {dirty ? <IconCheck /> : <IconArrowLeft />}
            </button>
          ) : (
            <button
              type="button"
              className={`${styles.action} ${styles.iconAction}`}
              disabled={disabled}
              aria-label="Edit"
              data-ui-guide="debate.rulesetEdit"
              onClick={() => {
                setDraft({ ...prompts });
                setMode("edit");
                onEditingChange(true);
              }}
            >
              <IconEdit />
            </button>
          )}
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
