"use client";

import { useCallback, useEffect, useState } from "react";

import styles from "./provider-data-call-disclosure.module.css";

export type ProviderDataCallDisclosure = {
  supplier_display_name: string;
  region: "cn-beijing";
  purpose: string;
  outbound_field_classes: readonly string[];
  storage_fact: string;
  no_training_basis: string;
  retention_setting: string;
};

export type ProviderDataCallDisclosureResponse = {
  disclosure: ProviderDataCallDisclosure;
  policy_hash: string;
  manifest_hash: string;
  confirmation_revision: number;
};

export type ProviderDataCallConfirmation = {
  policy_hash: string;
  manifest_hash: string;
  expected_revision: number;
};

export type ProviderDataCallDisclosureController = {
  load: () => Promise<ProviderDataCallDisclosureResponse>;
  confirm: (
    request: ProviderDataCallConfirmation,
  ) => Promise<ProviderDataCallDisclosureResponse>;
};

export function ProviderDataCallDisclosure({
  controller,
}: {
  controller: ProviderDataCallDisclosureController;
}) {
  const [value, setValue] = useState<ProviderDataCallDisclosureResponse | null>(
    null,
  );
  const [confirmedRevision, setConfirmedRevision] = useState<number | null>(
    null,
  );
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setValue(await controller.load());
      setConfirmedRevision(null);
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

  async function confirm() {
    if (!value || confirmedRevision === value.confirmation_revision) return;
    setBusy(true);
    setError(null);
    try {
      const next = await controller.confirm({
        policy_hash: value.policy_hash,
        manifest_hash: value.manifest_hash,
        expected_revision: value.confirmation_revision,
      });
      setValue(next);
      setConfirmedRevision(next.confirmation_revision);
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(false);
    }
  }

  if (loading) {
    return (
      <section className={styles.card} data-testid="provider-disclosure">
        <p className={styles.hint}>Loading provider disclosure…</p>
      </section>
    );
  }
  if (error || !value) {
    return (
      <section className={styles.card} data-testid="provider-disclosure">
        <p className={styles.error} role="alert">
          The provider disclosure could not be loaded.
        </p>
        <button className={styles.retry} type="button" onClick={() => void load()}>
          Try again
        </button>
      </section>
    );
  }

  const disclosure = value.disclosure;
  const confirmed = confirmedRevision === value.confirmation_revision;
  return (
    <section
      className={styles.card}
      data-testid="provider-disclosure"
      aria-labelledby="provider-disclosure-title"
    >
      <div className={styles.header}>
        <div>
          <h2 id="provider-disclosure-title">External data disclosure</h2>
          <p>
            Review the exact data classes and supplier terms before allowing a
            future external request.
          </p>
        </div>
        <span
          className={`${styles.status} ${confirmed ? styles.confirmed : styles.pending}`}
        >
          {confirmed ? "Confirmed" : "Needs confirmation"}
        </span>
      </div>
      <dl className={styles.fields}>
        <div className={styles.field}>
          <dt>Supplier</dt>
          <dd>{disclosure.supplier_display_name}</dd>
        </div>
        <div className={styles.field}>
          <dt>Region</dt>
          <dd>{disclosure.region}</dd>
        </div>
        <div className={styles.field}>
          <dt>Purpose</dt>
          <dd>{disclosure.purpose}</dd>
        </div>
        <div className={styles.field}>
          <dt>Outbound data classes</dt>
          <dd>
            <ul>
              {disclosure.outbound_field_classes.map((fieldClass) => (
                <li key={fieldClass}>{fieldClass}</li>
              ))}
            </ul>
          </dd>
        </div>
        <div className={styles.field}>
          <dt>Storage</dt>
          <dd>{disclosure.storage_fact}</dd>
        </div>
        <div className={styles.field}>
          <dt>No-training basis</dt>
          <dd>{disclosure.no_training_basis}</dd>
        </div>
        <div className={styles.field}>
          <dt>Retention</dt>
          <dd>{disclosure.retention_setting}</dd>
        </div>
      </dl>
      <div className={styles.actionRow}>
        <p className={styles.hint}>
          Confirmation is tied to this disclosure revision and expires when the
          policy or manifest changes.
        </p>
        <button
          className={styles.confirm}
          type="button"
          disabled={busy || confirmed}
          onClick={() => void confirm()}
        >
          {busy
            ? "Confirming…"
            : confirmed
              ? "Disclosure confirmed"
              : "Confirm disclosure"}
        </button>
      </div>
    </section>
  );
}
