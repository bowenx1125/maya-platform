"use client";

import Link from "next/link";

import { LanguageSwitcher, useT } from "../components/locale";
import { LoginForm } from "../components/session-provider";

export default function HomePage() {
  const t = useT();
  return (
    <main className="shell">
      <section className="hero-card landing-card" aria-labelledby="home-title">
        <div className="landing-language">
          <LanguageSwitcher />
        </div>
        <div className="landing-grid">
          <div className="landing-copy">
            <div className="eyebrow">{t("heroEyebrow")}</div>
            <h1 id="home-title">{t("heroTitle")}</h1>
            <p className="lede">{t("heroLede")}</p>
            <div className="hero-actions">
              <Link className="secondary-action" href="/health">
                {t("environmentHealth")}
              </Link>
            </div>
          </div>
          <LoginForm />
        </div>
      </section>

      <section className="feature-grid" aria-label={t("waveBoundary")}>
        <article className="feature-card">
          <span className="feature-index">01</span>
          <h2>{t("heroFeatureOne")}</h2>
          <p>{t("heroFeatureOneLede")}</p>
        </article>
        <article className="feature-card">
          <span className="feature-index">02</span>
          <h2>{t("heroFeatureTwo")}</h2>
          <p>{t("heroFeatureTwoLede")}</p>
        </article>
        <article className="feature-card accent-card">
          <span className="feature-index">03</span>
          <h2>{t("heroFeatureThree")}</h2>
          <p>{t("heroFeatureThreeLede")}</p>
        </article>
      </section>
    </main>
  );
}
