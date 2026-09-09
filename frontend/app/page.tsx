"use client";

import { useState } from "react";

import { AcademyIntro } from "../components/academy/intro";
import { AcademyMoodProvider } from "../components/academy/mood";
import { AcademyMascots } from "../components/academy/mascots";
import {
  AcademyBackdrop,
  AcademyEmblem,
  AcademyFrame,
} from "../components/academy/scene";
import { LanguageSwitcher, useT } from "../components/locale";
import { RegisterForm } from "../components/register-form";
import { LoginForm } from "../components/session-provider";

export default function HomePage() {
  const t = useT();
  const [registering, setRegistering] = useState(false);
  return (
    <AcademyMoodProvider>
      <AcademyIntro />
      <main className="academy-shell">
        <div className="academy-card">
          <AcademyFrame />
          <section className="academy-stage" aria-label={t("academyStageLabel")}>
            <AcademyBackdrop />
            <AcademyMascots label={t("academyMascotsLabel")} />
            <div className="academy-tagline">
              <div className="eyebrow">{t("academyEyebrow")}</div>
              <h1>{t("appName")}</h1>
            </div>
          </section>

          <section className="academy-panel">
            <div className="academy-panel-head">
              <LanguageSwitcher />
            </div>
            <AcademyEmblem />
            <h2 className="academy-welcome">
              {registering ? t("registerTitle") : t("academyWelcome")}
            </h2>
            <div className="academy-rule" aria-hidden="true">
              <span />
              <i />
              <span />
            </div>
            {registering ? (
              <RegisterForm onCancel={() => setRegistering(false)} />
            ) : (
              <LoginForm onRegister={() => setRegistering(true)} />
            )}
          </section>
        </div>
      </main>
    </AcademyMoodProvider>
  );
}
