"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { useT } from "../locale";
import type { ProviderDataCallDebateManifestListResponse } from "../../lib/api";
import styles from "./provider-data-call-disclosure.module.css";

export type ProviderDataCallDebateListController = {
  load: () => Promise<ProviderDataCallDebateManifestListResponse>;
};

/**
 * Teacher-only turn approval projection.
 *
 * The list deliberately renders only the opaque turn/manifest references and
 * confirmation state. The exact disclosure route remains the single place
 * where teacher-visible external-data terms are shown.
 */
export function ProviderDataCallDebateList({
  controller,
}: {
  controller: ProviderDataCallDebateListController;
}) {
  const t = useT();
  const [value, setValue] =
    useState<ProviderDataCallDebateManifestListResponse | null>(null);
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
      <section className={styles.card} data-testid="debate-turn-approvals">
        <p className={styles.hint} role="status">
          {t("debateApprovalLoading")}
        </p>
      </section>
    );
  }

  if (error || !value) {
    return (
      <section className={styles.card} data-testid="debate-turn-approvals">
        <p className={styles.error} role="alert">
          {t("debateApprovalError")}
        </p>
        <button
          className={styles.retry}
          type="button"
          onClick={() => void load()}
        >
          {t("retry")}
        </button>
      </section>
    );
  }

  return (
    <section
      className={styles.card}
      data-testid="debate-turn-approvals"
      aria-labelledby="debate-turn-approvals-title"
    >
      <div className={styles.header}>
        <div>
          <h2 id="debate-turn-approvals-title">{t("debateApprovalTitle")}</h2>
        </div>
      </div>

      {value.items.length === 0 ? (
        <p className={styles.hint}>{t("debateApprovalEmpty")}</p>
      ) : (
        <dl className={styles.fields}>
          {value.items.map((item) => (
            <div className={styles.field} key={item.turn_id}>
              <dt>{t("debateApprovalTurn")}</dt>
              <dd>{item.turn_id}</dd>
              <dd>
                <span
                  className={`${styles.status} ${
                    item.confirmed ? styles.confirmed : styles.pending
                  }`}
                >
                  {item.confirmed
                    ? t("debateApprovalConfirmed")
                    : t("debateApprovalNeedsConfirmation")}
                </span>
              </dd>
              <dd>
                <Link
                  className="text-link"
                  href={`/teacher/provider-disclosures/${item.manifest_hash}`}
                >
                  {t("debateApprovalReview")}
                </Link>
              </dd>
            </div>
          ))}
        </dl>
      )}
    </section>
  );
}
