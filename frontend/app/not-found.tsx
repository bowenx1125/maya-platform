import Link from "next/link";

import appearance from "../components/workspace-appearance.module.css";

export default function NotFound() {
  return (
    <main
      className={`${appearance.appearance} grid place-content-center justify-items-center gap-4 px-6 py-12 text-center`}
    >
      <p className="m-0 text-[13px] font-bold tracking-[0.16em] text-(--accent)">
        404
      </p>
      <h1 className="mt-0 mb-2 font-(family-name:--display-serif) text-[clamp(1.8rem,3.2vw,2.4rem)] font-medium">
        Page not found
      </h1>
      <Link
        className="inline-flex min-h-11 items-center rounded-full bg-(--accent-fill) px-6 font-bold text-(--on-accent) no-underline shadow-(--lift) hover:bg-(--accent-hover) focus-visible:outline-2 focus-visible:outline-offset-3 focus-visible:outline-(--accent)"
        href="/"
      >
        Home
      </Link>
    </main>
  );
}
