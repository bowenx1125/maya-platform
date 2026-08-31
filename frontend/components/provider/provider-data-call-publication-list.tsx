"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import type { ProviderDataCallPublicationManifestListResponse } from "../../lib/api/platform";
import styles from "./provider-data-call-disclosure.module.css";

export type ProviderDataCallPublicationListController = {
  load: () => Promise<ProviderDataCallPublicationManifestListResponse>;
};

export function ProviderDataCallPublicationList({
  controller,
}: {
  controller: ProviderDataCallPublicationListController;
}) {
  const [value, setValue] =
    useState<ProviderDataCallPublicationManifestListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setValue(await controller.load());
    } catch (cause) {
      setError(cause);
    } finally {
      setLoading(false);
    }
  }, [controller]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  if (loading) {
    return (
      <section className={styles.card} data-testid="provider-publication-list">
        <p className={styles.hint}>Loading publication approvals…</p>
      </section>
    );
  }
  if (error || !value) {
    return (
      <section className={styles.card} data-testid="provider-publication-list">
        <p className={styles.error} role="alert">
          Publication approvals could not be loaded.
        </p>
        <button
          className={styles.retry}
          type="button"
          onClick={() => void load()}
        >
          Try again
        </button>
      </section>
    );
  }

  return (
    <section
      className={styles.card}
      data-testid="provider-publication-list"
      aria-labelledby="provider-publication-title"
    >
      <div className={styles.header}>
        <div>
          <h2 id="provider-publication-title">
            External publication approvals
          </h2>
          <p>
            Review each exact disclosure for this Agent version. No request is
            allowed until its manifest is confirmed.
          </p>
        </div>
      </div>
      {value.items.length === 0 ? (
        <p className={styles.hint}>
          No publication disclosure is waiting for review.
        </p>
      ) : (
        <dl className={styles.fields}>
          {value.items.map((item) => (
            <div className={styles.field} key={item.manifest_hash}>
              <dt>Publication disclosure</dt>
              <dd>
                <span
                  className={`${styles.status} ${
                    item.confirmed ? styles.confirmed : styles.pending
                  }`}
                >
                  {item.confirmed ? "Confirmed" : "Needs confirmation"}
                </span>
              </dd>
              <dd>
                <Link
                  className="text-link"
                  href={`/teacher/provider-disclosures/${item.manifest_hash}`}
                >
                  Review exact disclosure
                </Link>
              </dd>
            </div>
          ))}
        </dl>
      )}
    </section>
  );
}
