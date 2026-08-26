import Link from "next/link";

import { t } from "../lib/i18n";

export default function HomePage() {
  return (
    <main className="shell">
      <section className="hero-card" aria-labelledby="home-title">
        <div className="eyebrow">{t("heroEyebrow")}</div>
        <h1 id="home-title">{t("heroTitle")}</h1>
        <p className="lede">{t("heroLede")}</p>
        <div className="hero-actions">
          <Link className="primary-action" href="/login">
            {t("signIn")}
          </Link>
          <Link className="secondary-action" href="/health">
            {t("environmentHealth")}
          </Link>
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
