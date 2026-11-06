import { useState } from "react";

import { api, ApiError } from "../lib/api";
import { useDemoConfig, type DemoState } from "../lib/demo";
import { useApi } from "../lib/useApi";

interface Toggle {
  label: string;
  hint: string;
  on: boolean;
  onLabel: string;
  offLabel: string;
  onPath: string;
  offPath: string;
}

function ToggleRow({ t, busy, run }: { t: Toggle; busy: boolean; run: (label: string, path: string) => void }) {
  return (
    <li className="flex flex-wrap items-center justify-between gap-2 py-2" data-testid={`toggle-${t.label}`}>
      <div>
        <p className="font-semibold">
          {t.label}{" "}
          <span className={`rounded px-1.5 text-xs ${t.on ? "bg-red-100 text-red-900" : "bg-green-100 text-green-900"}`}>{t.on ? "broken" : "normal"}</span>
        </p>
        <p className="text-xs text-slate-700">{t.hint}</p>
      </div>
      <button
        type="button"
        disabled={busy}
        onClick={() => run(t.on ? t.offLabel : t.onLabel, t.on ? t.offPath : t.onPath)}
        className={`rounded px-3 py-1 text-sm text-white ${t.on ? "bg-green-800" : "bg-red-800"}`}
      >
        {t.on ? t.offLabel : t.onLabel}
      </button>
    </li>
  );
}

function OneShot({ label, hint, path, busy, run }: { label: string; hint: string; path: string; busy: boolean; run: (label: string, path: string) => void }) {
  return (
    <li className="flex flex-wrap items-center justify-between gap-2 py-2">
      <div>
        <p className="font-semibold">{label}</p>
        <p className="text-xs text-slate-700">{hint}</p>
      </div>
      <button type="button" disabled={busy} onClick={() => run(label, path)} className="rounded border border-red-800 px-3 py-1 text-sm text-red-900">
        {label}
      </button>
    </li>
  );
}

export function DemoAdminPage() {
  const config = useDemoConfig();
  const state = useApi<DemoState>(config.data?.demo_mode ? "/demo/state" : null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  if (config.data && !config.data.demo_mode) return <p>Demo mode is off. Start the app with make demo (DEMO_MODE=true).</p>;
  if (!state.data) return <p>Loading the operator panel…</p>;
  const s = state.data;

  async function run(label: string, path: string) {
    setBusy(true);
    setMessage(null);
    try {
      const result = await api<Record<string, unknown>>(path, { method: "POST" });
      if (path.startsWith("/demo/clock/")) {
        window.location.reload(); // the whole app re-reads its data at the new time
        return;
      }
      setMessage(`${label}: done. ${summarise(result)}`);
    } catch (e) {
      setMessage(`${label}: ${e instanceof ApiError ? e.reason : String(e)}`);
    } finally {
      setBusy(false);
      state.reload();
    }
  }

  const toggles: Toggle[] = [
    {
      label: "Pharmacy feed",
      hint: "Paused: no new pharmacy files. The queue shows an amber stale-feed banner; scripted fills wait until it resumes.",
      on: s.paused_feeds.includes("pharmacy"),
      onLabel: "Pause pharmacy feed",
      offLabel: "Resume pharmacy feed",
      onPath: "/demo/feeds/pharmacy/pause",
      offPath: "/demo/feeds/pharmacy/resume",
    },
    {
      label: "ADT feed",
      hint: "Paused: admissions and discharges may be missing. Red banner; the member view offers Add discharge.",
      on: s.paused_feeds.includes("adt"),
      onLabel: "Pause ADT feed",
      offLabel: "Resume ADT feed",
      onPath: "/demo/feeds/adt/pause",
      offPath: "/demo/feeds/adt/resume",
    },
    {
      label: "Mock CM platform",
      hint: "Down: saves show “Saved here, syncing to record”. Restoring sends each waiting save exactly once.",
      on: s.cm_mode === "down",
      onLabel: "Take CM platform down",
      offLabel: "Restore CM platform",
      onPath: "/demo/cm/down",
      offPath: "/demo/cm/up",
    },
    {
      label: "AI draft",
      hint: "Time-out: the Live pane says “AI draft unavailable” and the nurse writes notes as normal.",
      on: s.ai_timeout,
      onLabel: "Make the AI draft time out",
      offLabel: "Stop AI time-outs",
      onPath: "/demo/ai-timeout/on",
      offPath: "/demo/ai-timeout/off",
    },
    {
      label: "Kayla's Part 2 consent",
      hint: "Expired: revealing her Part 2 records is blocked. Restore: she signs a new consent today.",
      on: s.kayla_part2_consent === "expired",
      onLabel: "Expire Kayla's Part 2 consent",
      offLabel: "Restore Kayla's Part 2 consent",
      onPath: "/demo/consent/kayla-part2/expire",
      offPath: "/demo/consent/kayla-part2/restore",
    },
  ];

  return (
    <div className="space-y-4" data-testid="demo-admin">
      <h1 className="text-xl font-semibold">Demo operator panel</h1>
      <p className="text-sm text-slate-800">
        Breaks things on purpose, through the same paths as real life: feed files go through the data layer, consents arrive as snapshots, the
        mock CM platform is told to go down. Synthetic data only.
      </p>
      {message && (
        <p role="status" className="rounded border border-slate-400 bg-white p-2 text-sm" data-testid="demo-message">
          {message}
        </p>
      )}
      <section aria-labelledby="clock-title" className="rounded border border-violet-800 bg-white p-3">
        <h2 id="clock-title" className="font-semibold">
          Clock
        </h2>
        <ul className="divide-y divide-slate-200">
          {s.steps.map((step) => (
            <li key={step.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
              <p>
                <strong>{step.label}</strong> · {step.story} {step.applied && <span className="text-xs text-green-900">(loaded)</span>}
              </p>
              <button
                type="button"
                disabled={busy || !step.available}
                onClick={() => run(`Advance to ${step.label}`, `/demo/clock/advance/${step.id}`)}
                className="rounded border border-violet-800 px-3 py-1 text-sm text-violet-950 disabled:border-slate-400 disabled:text-slate-600"
              >
                Advance to {step.label}
              </button>
            </li>
          ))}
          <OneShot label="Reset demo" hint="Pristine database, Monday 08:00, CM platform empty and up." path="/demo/clock/reset" busy={busy} run={run} />
        </ul>
      </section>
      <section aria-labelledby="toggles-title" className="rounded border border-slate-300 bg-white p-3">
        <h2 id="toggles-title" className="font-semibold">
          Toggles
        </h2>
        <ul className="divide-y divide-slate-200">
          {toggles.map((t) => (
            <ToggleRow key={t.label} t={t} busy={busy} run={run} />
          ))}
          <OneShot
            label="Create a record-version conflict"
            hint="Someone else edits Raymond's record in the CM platform: the next save shows both versions and writes nothing."
            path="/demo/cm/conflict"
            busy={busy}
            run={run}
          />
          <OneShot
            label="Inject a bad pharmacy file"
            hint="A file whose layout changed upstream: quarantined, and the previous load stays active."
            path="/demo/inject/bad-pharmacy-file"
            busy={busy}
            run={run}
          />
          <OneShot
            label="Inject an unknown NDC"
            hint="A fill for a drug the terminology tables do not know: shown by its raw name and listed below."
            path="/demo/inject/unknown-ndc"
            busy={busy}
            run={run}
          />
        </ul>
      </section>
      <section aria-labelledby="loads-title" className="rounded border border-slate-300 bg-white p-3">
        <h2 id="loads-title" className="font-semibold">
          Recent feed loads
        </h2>
        <table className="mt-1 w-full text-left text-sm" data-testid="recent-loads">
          <thead>
            <tr>
              <th className="pr-2">Load</th>
              <th className="pr-2">File</th>
              <th className="pr-2">Status</th>
              <th>Note</th>
            </tr>
          </thead>
          <tbody>
            {s.recent_loads.map((l) => (
              <tr key={l.id} className="border-t border-slate-200">
                <td className="pr-2">{l.id}</td>
                <td className="pr-2">{l.file}</td>
                <td className={`pr-2 ${l.status === "QUARANTINE" ? "font-semibold text-red-900" : ""}`}>
                  {l.status}
                  {l.active ? " · active" : ""}
                </td>
                <td>{l.error ?? ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      <section aria-labelledby="unmapped-title" className="rounded border border-slate-300 bg-white p-3">
        <h2 id="unmapped-title" className="font-semibold">
          Unmapped codes report (data layer)
        </h2>
        <ul className="mt-1 text-sm" data-testid="unmapped-codes">
          {s.unmapped_codes.map((u, i) => (
            <li key={i}>
              {u.code_system} {u.code ?? "(no code)"} · “{u.display ?? "UNKNOWN"}” · {u.source_stream} · {u.occurrences}×
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

function summarise(result: Record<string, unknown>): string {
  if (typeof result.status === "string") return `Load status ${result.status}${result.error ? `: ${String(result.error)}` : ""}.`;
  if (Array.isArray(result.synced)) return `${result.synced.length} waiting save(s) synced.`;
  if (Array.isArray(result.resolved_tasks) && result.resolved_tasks.length) return `${result.resolved_tasks.length} task(s) resolved by the new data.`;
  if (typeof result.held === "string") return result.held;
  return "";
}
