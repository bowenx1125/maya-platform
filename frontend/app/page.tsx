"use client";

import { useT } from "../components/locale";
import { LoginForm } from "../components/session-provider";

export default function HomePage() {
  const t = useT();
  return (
    <main className="shell">
      <section className="hero-card landing-card" aria-labelledby="home-title">
        <div className="landing-grid">
          <div className="landing-copy">
            <div className="eyebrow">{t("appName")}</div>
            <h1 id="home-title">{t("appName")}</h1>
          </div>
          <LoginForm />
        </div>
      </section>
    </main>
  );
}
