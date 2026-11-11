"use client";

import { useState } from "react";
import { ReportMarkdown } from "../../report/report-markdown";
import {
  IconArrowLeft,
  IconCheck,
  IconEdit,
  IconGlobe,
  IconLock,
} from "../../quiet-icons";
import { cn } from "../../../lib/utils";
import {
  CREATE_SEG,
  CREATE_SEG_BUTTON,
  CREATE_SMALL_BUTTON,
  CREATE_TEXTAREA,
} from "../debate-chrome";
import { CreateCard } from "./create-card";

/** `.ta.rules`: the ruleset box, monospace, at least 200px. */
const RULES_BOX = cn(
  CREATE_TEXTAREA,
  "h-[200px] min-h-[200px] overflow-auto font-mono text-[13px] leading-[1.55] whitespace-pre-wrap",
);

export type TeachingPrompts = { zh: string; en: string };

export function RulesetEditor({
  prompts,
  contract = null,
  language,
  disabled = false,
  onLanguageChange,
  onSave,
  onEditingChange,
}: {
  prompts: TeachingPrompts;
  /** The platform's execution contract: shown beside the Ruleset, never
   * edited or sent back, so a Ruleset edit cannot reach it. */
  contract?: TeachingPrompts | null;
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
    <CreateCard
      title="Debate Ruleset"
      guide="debate.ruleset"
      action={
        <div className="flex shrink-0 items-center gap-2.5">
          <div className={CREATE_SEG} role="group" aria-label="Language">
            <IconGlobe size={18} />
            {(["zh", "en"] as const).map((value) => (
              <button
                key={value}
                type="button"
                className={CREATE_SEG_BUTTON}
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
              className={CREATE_SMALL_BUTTON}
              disabled={disabled}
              aria-label={dirty ? "Save" : "Back"}
              data-ui-guide={
                dirty ? "debate.rulesetSave" : "debate.rulesetBack"
              }
              onClick={dirty ? save : cancel}
            >
              {dirty ? <IconCheck size={14} /> : <IconArrowLeft size={14} />}
              <span aria-hidden="true">{dirty ? "Save" : "Back"}</span>
            </button>
          ) : (
            <button
              type="button"
              className={CREATE_SMALL_BUTTON}
              disabled={disabled}
              aria-label="Edit"
              data-ui-guide="debate.rulesetEdit"
              onClick={() => {
                setDraft({ ...prompts });
                setMode("edit");
                onEditingChange(true);
              }}
            >
              <IconEdit size={14} />
              <span aria-hidden="true">Edit</span>
            </button>
          )}
        </div>
      }
    >
      <div id="ruleset-content" className="mt-3">
        {editing ? (
          <textarea
            aria-label={language === "zh" ? "中文规则" : "English rules"}
            className={cn(RULES_BOX, "mt-0 min-h-[320px]")}
            value={draft[language]}
            disabled={disabled}
            spellCheck={false}
            onChange={(event) =>
              setDraft({ ...draft, [language]: event.target.value })
            }
          />
        ) : (
          <div className={cn(RULES_BOX, "mt-0 max-h-[420px] overflow-auto")}>
            <ReportMarkdown
              label={language === "zh" ? "中文规则" : "English rules"}
            >
              {prompts[language]}
            </ReportMarkdown>
          </div>
        )}
      </div>
      {contract ? (
        <div className="mt-4" data-testid="ruleset-contract">
          <p className="m-0 flex items-center gap-1.5 font-body text-xs leading-[normal] font-bold text-[#111]">
            <IconLock size={13} />
            Execution contract: fixed by the platform, not editable
          </p>
          <div
            className={cn(
              RULES_BOX,
              "mt-2 max-h-[420px] resize-none border-dashed bg-[#F4F4F5] focus:shadow-none",
            )}
          >
            <ReportMarkdown label="Execution contract">
              {/* The server fills the round number per turn; a raw placeholder reads as a bug. */}
              {contract[language].replaceAll("{round}", "N")}
            </ReportMarkdown>
          </div>
        </div>
      ) : null}
    </CreateCard>
  );
}
