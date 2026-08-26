import Link from "next/link";

export default function HomePage() {
  return (
    <main className="shell">
      <section className="hero-card" aria-labelledby="home-title">
        <div className="eyebrow">MAYA · WAVE 0</div>
        <h1 id="home-title">Culture, evidence, and a better conversation.</h1>
        <p className="lede">
          A calm workspace for building a cultural agent, checking its evidence,
          and preparing a classroom debate.
        </p>
        <div className="hero-actions">
          <Link className="primary-action" href="/health">
            Open environment
          </Link>
          <span className="quiet-label">Local-first demo shell</span>
        </div>
      </section>

      <section className="feature-grid" aria-label="Wave 0 boundaries">
        <article className="feature-card">
          <span className="feature-index">01</span>
          <h2>Build with intention</h2>
          <p>
            Agent identity and knowledge stay explicit so students can see what
            shaped each answer.
          </p>
        </article>
        <article className="feature-card">
          <span className="feature-index">02</span>
          <h2>Debate with context</h2>
          <p>
            Teacher-controlled turns keep the sequence stable while each speaker
            responds to the room.
          </p>
        </article>
        <article className="feature-card accent-card">
          <span className="feature-index">03</span>
          <h2>Keep the boundary clear</h2>
          <p>
            The browser talks only to Maya APIs; credentials and supplier
            details remain server-side.
          </p>
        </article>
      </section>
    </main>
  );
}
