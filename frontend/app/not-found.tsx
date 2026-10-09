import Link from "next/link";

import appearance from "../components/workspace-appearance.module.css";
import styles from "./not-found.module.css";

export default function NotFound() {
  return (
    <main className={`${appearance.appearance} ${styles.page}`}>
      <p className={styles.code}>404</p>
      <h1 className={styles.title}>Page not found</h1>
      <Link className={styles.home} href="/">
        Home
      </Link>
    </main>
  );
}
