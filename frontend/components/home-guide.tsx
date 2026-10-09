"use client";

import Link from "next/link";

import { useT } from "./locale";

export type GuideStep = {
  label: string;
  complete: boolean;
  href: string;
  optional?: boolean;
};

/**
 * The home's steps, set like a syllabus rather than a checklist: each marked
 * with the sign-in rule's gold diamond, and with only the step that comes next
 * asking to be clicked.
 */
export function HomeGuide({ steps }: { steps: GuideStep[] }) {
  const t = useT();
  const next = steps.findIndex((step) => !step.complete);
  return (
    <ol className="home-guide-list">
      {steps.map((step, index) => {
        const state = step.complete ? "done" : index === next ? "next" : "todo";
        return (
          <li key={step.label}>
            <Link
              className="home-guide-row"
              href={step.href}
              data-state={state}
              aria-current={state === "next" ? "step" : undefined}
            >
              <span className="home-guide-marker" aria-hidden="true" />
              <strong>{step.label}</strong>
              {step.optional ? <small>{t("guideOptional")}</small> : null}
              <span
                className={state === "next" ? "home-guide-state" : "sr-only"}
              >
                {step.complete ? t("guideDone") : t("guideNext")}
              </span>
              <span className="home-guide-arrow" aria-hidden="true">
                →
              </span>
            </Link>
          </li>
        );
      })}
    </ol>
  );
}
