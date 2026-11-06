import { useEffect, useRef, useState } from "react";

import { api, ApiError } from "../../lib/api";
import { longDate } from "../../lib/format";
import { ConflictPanel, SyncStatus, type WritebackConflict } from "./SyncStatus";
import { show, type EncounterField, type EncounterOut } from "./types";

interface Props {
  encounter: EncounterOut;
  notes: string;
  onChange: (e: EncounterOut) => void;
  onSaved: () => void;
}

function HighRiskField({ field, encounterId, onDone }: { field: EncounterField; encounterId: number; onDone: () => void }) {
  const shownAt = useRef(performance.now()); // time on field for high-risk confirmations
  const [answer, setAnswer] = useState("");
  const [error, setError] = useState<string | null>(null);
  async function confirm() {
    try {
      await api(`/encounters/${encounterId}/fields/${field.field_id}/confirm`, {
        method: "POST",
        body: { answer: answer.trim() || null, time_on_field_ms: Math.round(performance.now() - shownAt.current) },
      });
      onDone();
    } catch (e) {
      setError(e instanceof ApiError ? e.reason : String(e));
    }
  }
  return (
    <li className="rounded border border-red-700 p-2 text-sm" data-testid="high-risk-field">
      <p className="font-semibold">{field.label}</p>
      <p>On file: {show(field.prefill)}</p>
      {field.confirmed ? (
        <p className="font-medium text-emerald-900">✓ Confirmed one by one</p>
      ) : (
        <div className="mt-1 flex flex-wrap items-center gap-2">
          <label className="sr-only" htmlFor={`ans-${field.field_id}`}>
            What the member says about {field.label}
          </label>
          <input id={`ans-${field.field_id}`} value={answer} onChange={(e) => setAnswer(e.target.value)} placeholder="What the member says (optional if it matches)" className="min-w-64 flex-1 rounded border border-slate-500 p-1" />
          <button type="button" onClick={confirm} className="rounded bg-blue-800 px-2 py-1 text-white" aria-label={`Confirm ${field.label}`}>
            Confirm
          </button>
        </div>
      )}
      {error && <p role="status" className="text-red-800">{error}</p>}
    </li>
  );
}

export function WrapUp({ encounter, notes, onChange, onSaved }: Props) {
  const [message, setMessage] = useState<string | null>(null);
  const [conflict, setConflict] = useState<WritebackConflict | null>(null);

  // While syncing, check back every 5 s; move on once the CM record has it.
  useEffect(() => {
    if (encounter.status === "synced") {
      const done = window.setTimeout(onSaved, 1200);
      return () => window.clearTimeout(done);
    }
    if (encounter.status !== "syncing") return;
    const timer = window.setInterval(async () => {
      onChange(await api<EncounterOut>(`/encounters/${encounter.id}`));
    }, 5000);
    return () => window.clearInterval(timer);
  }, [encounter.status, encounter.id, onChange, onSaved]);

  async function saveRecord(acknowledgedVersion?: number) {
    setMessage(null);
    try {
      const body = acknowledgedVersion != null ? { acknowledged_version: acknowledgedVersion } : undefined;
      onChange(await api<EncounterOut>(`/encounters/${encounter.id}/save`, { method: "POST", body }));
      setConflict(null);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && e.detail && typeof e.detail === "object" && "ours" in e.detail) {
        setConflict(e.detail as WritebackConflict);
      } else {
        setMessage(e instanceof ApiError ? e.reason : String(e));
      }
    }
  }
  const reload = async () => onChange(await api<EncounterOut>(`/encounters/${encounter.id}`));
  const highRisk = encounter.fields.filter((f) => f.risk === "high" && f.status !== "live_only");
  const lowRisk = encounter.fields.filter((f) => f.risk === "low" && f.status === "prefilled_fresh");
  const lowOpen = lowRisk.filter((f) => !f.confirmed);
  const toAsk = encounter.fields.filter((f) => f.status !== "prefilled_fresh" && !(f.risk === "high" && f.status !== "live_only"));

  async function run(path: string, body?: unknown) {
    setMessage(null);
    try {
      onChange(await api<EncounterOut>(path, { method: "POST", body }));
      return true;
    } catch (e) {
      setMessage(e instanceof ApiError ? e.reason : String(e));
      return false;
    }
  }

  async function bulk() {
    try {
      await api(`/encounters/${encounter.id}/fields/bulk-confirm`, { method: "POST", body: { field_ids: lowOpen.map((f) => f.field_id) } });
      await reload();
    } catch (e) {
      setMessage(e instanceof ApiError ? e.reason : String(e));
    }
  }

  return (
    <section aria-labelledby="wrap-title" className="space-y-3 rounded border border-slate-300 bg-white p-3" data-testid="wrap-pane">
      <h2 id="wrap-title" className="text-lg font-semibold">
        Wrap-up
      </h2>
      <p className="text-sm" data-testid="field-counts">
        <strong>{encounter.counts.prefilled_fresh}</strong> to confirm · <strong>{encounter.counts.prefilled_stale}</strong> to re-ask ·{" "}
        <strong>{encounter.counts.live_only}</strong> live only
      </p>
      <h3 className="font-semibold">High-risk fields: confirm one by one</h3>
      <ul className="space-y-2">
        {highRisk.map((f) => (
          <HighRiskField key={f.field_id} field={f} encounterId={encounter.id} onDone={reload} />
        ))}
      </ul>
      <button type="button" onClick={bulk} disabled={lowOpen.length === 0} className="rounded bg-blue-800 px-3 py-1 text-white disabled:opacity-60">
        {lowOpen.length ? `Confirm ${lowOpen.length} low-risk fields` : `All ${lowRisk.length} low-risk fields confirmed`}
      </button>
      <details className="text-sm">
        <summary className="cursor-pointer font-semibold">Re-ask and live-only questions ({toAsk.length})</summary>
        <ul className="mt-1 list-disc pl-5">
          {toAsk.map((f) => (
            <li key={f.field_id}>
              {f.label} · {f.status === "live_only" ? "ask live" : (f.reason ?? "re-ask")}
              {f.source_as_of ? ` (on file ${longDate(f.source_as_of)})` : ""}
            </li>
          ))}
        </ul>
      </details>
      {encounter.status === "open" ? (
        <button type="button" onClick={() => run(`/encounters/${encounter.id}/wrap-up`, { notes })} className="rounded bg-blue-800 px-3 py-1 text-white">
          End call and create tasks
        </button>
      ) : (
        <>
          <h3 className="font-semibold">Tasks from this call</h3>
          <ul className="space-y-1 text-sm" data-testid="task-list">
            {encounter.tasks.map((t) => (
              <li key={t.id}>
                {t.title} · due {longDate(t.due_date)} <span className="text-xs text-slate-700">(from {t.signal_rule_id})</span>
              </li>
            ))}
          </ul>
          <button
            type="button"
            disabled={encounter.status !== "wrapped"}
            onClick={() => saveRecord()}
            className="rounded bg-emerald-800 px-3 py-1 text-white disabled:opacity-60"
          >
            Save to record
          </button>
          <SyncStatus status={encounter.status} />
          {conflict && <ConflictPanel conflict={conflict} onSaveAgainst={(v) => saveRecord(v)} />}
        </>
      )}
      {message && (
        <p role="status" className="text-sm text-red-800">
          {message}
        </p>
      )}
    </section>
  );
}
