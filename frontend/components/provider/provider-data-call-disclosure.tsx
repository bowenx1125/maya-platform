"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { DismissibleAlert } from "../dismissible-alert";
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

type DisclosureViewState = {
  controller: ProviderDataCallDisclosureController;
  scopeKey: string;
  value: ProviderDataCallDisclosureResponse | null;
  confirmedKey: string | null;
  loading: boolean;
  busy: boolean;
  error: unknown;
};

function confirmationKey(value: ProviderDataCallDisclosureResponse): string {
  return `${value.policy_hash}:${value.manifest_hash}:${value.confirmation_revision}`;
}

function emptyViewState(
  controller: ProviderDataCallDisclosureController,
  scopeKey: string,
): DisclosureViewState {
  return {
    controller,
    scopeKey,
    value: null,
    confirmedKey: null,
    loading: true,
    busy: false,
    error: null,
  };
}

export function ProviderDataCallDisclosure({
  controller,
  scopeKey = "",
  confirmable = true,
  existingDisclosure,
  existingDisclosureError,
  onRetry,
}: {
  controller: ProviderDataCallDisclosureController;
  scopeKey?: string;
  confirmable?: boolean;
  existingDisclosure?: ProviderDataCallDisclosureResponse | null;
  existingDisclosureError?: unknown;
  onRetry?: () => void;
}) {
  const currentScopeKey = scopeKey;
  const usesExistingDisclosure = existingDisclosure !== undefined;
  const [state, setState] = useState<DisclosureViewState>(() =>
    emptyViewState(controller, currentScopeKey),
  );
  const stateMatchesScope =
    state.controller === controller && state.scopeKey === currentScopeKey;
  const currentState = stateMatchesScope
    ? state
    : emptyViewState(controller, currentScopeKey);
  const storedValue = currentState.value;
  const value = usesExistingDisclosure
    ? existingDisclosure === null
      ? null
      : currentState.confirmedKey !== null &&
          storedValue !== null &&
          currentState.confirmedKey === confirmationKey(storedValue) &&
          storedValue.policy_hash === existingDisclosure?.policy_hash &&
          storedValue.manifest_hash === existingDisclosure.manifest_hash
        ? storedValue
        : existingDisclosure
    : storedValue;
  const confirmedKey = currentState.confirmedKey;
  const loading = usesExistingDisclosure
    ? existingDisclosure === null && existingDisclosureError == null
    : currentState.loading;
  const busy =
    usesExistingDisclosure && value !== storedValue ? false : currentState.busy;
  const error = currentState.error ?? existingDisclosureError;
  const requestSequence = useRef(0);
  const activeScope = useRef<{
    controller: ProviderDataCallDisclosureController;
    scopeKey: string;
  } | null>(null);

  useEffect(() => {
    activeScope.current = { controller, scopeKey: currentScopeKey };
    return () => {
      activeScope.current = null;
      requestSequence.current += 1;
    };
  }, [controller, currentScopeKey]);

  const updateCurrentState = useCallback(
    (update: Partial<DisclosureViewState>) => {
      setState((previous) => {
        const base =
          previous.controller === controller &&
          previous.scopeKey === currentScopeKey
            ? previous
            : emptyViewState(controller, currentScopeKey);
        return { ...base, ...update };
      });
    },
    [controller, currentScopeKey],
  );

  const load = useCallback(async () => {
    if (usesExistingDisclosure) {
      if (existingDisclosure === null) {
        updateCurrentState({
          value: null,
          confirmedKey: null,
          loading: existingDisclosureError == null,
          busy: false,
          error: existingDisclosureError ?? null,
        });
        return;
      }
      updateCurrentState({
        value: existingDisclosure,
        confirmedKey: null,
        loading: false,
        busy: false,
        error: null,
      });
      return;
    }
    const requestId = ++requestSequence.current;
    const isCurrent = () => {
      const active = activeScope.current;
      return (
        requestSequence.current === requestId &&
        active?.controller === controller &&
        active.scopeKey === currentScopeKey
      );
    };
    updateCurrentState({ loading: true, error: null });
    try {
      const next = await controller.load();
      if (!isCurrent()) return;
      updateCurrentState({
        value: next,
        confirmedKey: null,
      });
    } catch (cause) {
      if (!isCurrent()) return;
      updateCurrentState({ error: cause });
    } finally {
      if (isCurrent()) updateCurrentState({ loading: false });
    }
  }, [
    controller,
    currentScopeKey,
    existingDisclosure,
    existingDisclosureError,
    updateCurrentState,
    usesExistingDisclosure,
  ]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  async function confirm() {
    if (!confirmable || !value || confirmedKey === confirmationKey(value))
      return;
    const requestId = ++requestSequence.current;
    const isCurrent = () => {
      const active = activeScope.current;
      return (
        requestSequence.current === requestId &&
        active?.controller === controller &&
        active.scopeKey === currentScopeKey
      );
    };
    updateCurrentState({ busy: true, error: null });
    try {
      const next = await controller.confirm({
        policy_hash: value.policy_hash,
        manifest_hash: value.manifest_hash,
        expected_revision: value.confirmation_revision,
      });
      if (!isCurrent()) return;
      updateCurrentState({
        value: next,
        confirmedKey: confirmationKey(next),
      });
    } catch (cause) {
      if (!isCurrent()) return;
      updateCurrentState({ error: cause });
    } finally {
      if (isCurrent()) updateCurrentState({ busy: false });
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
        <DismissibleAlert className={styles.error} resetKey={error}>
          The provider disclosure could not be loaded.
        </DismissibleAlert>
        <button
          className={styles.retry}
          type="button"
          onClick={() => (onRetry ? onRetry() : void load())}
        >
          Try again
        </button>
      </section>
    );
  }

  const disclosure = value.disclosure;
  const confirmed = confirmable && confirmedKey === confirmationKey(value);
  return (
    <section
      className={styles.card}
      data-testid="provider-disclosure"
      aria-labelledby="provider-disclosure-title"
    >
      <div className={styles.header}>
        <div>
          <h2 id="provider-disclosure-title">External data disclosure</h2>
        </div>
        <span
          className={`${styles.status} ${confirmed ? styles.confirmed : styles.pending}`}
        >
          {confirmable
            ? confirmed
              ? "Confirmed"
              : "Needs confirmation"
            : "Reference only"}
        </span>
      </div>
      <dl className={styles.fields}>
        <div className={styles.field}>
          <dt>Policy hash</dt>
          <dd className={styles.hash}>{value.policy_hash}</dd>
        </div>
        <div className={styles.field}>
          <dt>Manifest hash</dt>
          <dd className={styles.hash}>{value.manifest_hash}</dd>
        </div>
        <div className={styles.field}>
          <dt>Disclosure revision</dt>
          <dd>{value.confirmation_revision}</dd>
        </div>
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
          {confirmable
            ? "Confirmation is tied to this disclosure revision and expires when the policy or manifest changes."
            : "Team authorization is confirmed for each exact published resource binding below."}
        </p>
        {confirmable ? (
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
        ) : null}
      </div>
    </section>
  );
}
