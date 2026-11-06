import { useApi } from "../lib/useApi";

interface Metrics {
  at: string;
  feeds: { feed: string; stream: string; age_hours: number | null; stale: boolean; reason: string | null }[];
  signals_per_rule: { run_day: string | null; counts: Record<string, number> };
  override_rate: { window_days: number; rate: number | null; overrides: Record<string, number>; calls_started: number };
  ai: { drafts: number; sentences: number; unsupported_sentence_rate: number | null; major_edit_ratio: number | null };
  writeback: { pending: number; oldest_pending_seconds: number; alerted: number; synced: number; median_sync_lag_seconds: number | null };
}

function pct(value: number | null): string {
  return value === null ? "UNKNOWN" : `${Math.round(value * 1000) / 10}%`;
}

function Tile({ label, value, note, testId }: { label: string; value: string; note: string; testId: string }) {
  return (
    <div className="rounded border border-slate-300 bg-white p-3" data-testid={testId}>
      <p className="text-xs uppercase tracking-wide text-slate-700">{label}</p>
      <p className="text-2xl font-semibold">{value}</p>
      <p className="text-xs text-slate-700">{note}</p>
    </div>
  );
}

/** Supervisor view of /admin/metrics: counts and ages only, no member data. */
export function MetricsPage() {
  const metrics = useApi<Metrics>("/admin/metrics");
  if (metrics.error) return <p role="status">Metrics unavailable: {metrics.error}</p>;
  if (!metrics.data) return <p>Loading metrics…</p>;
  const m = metrics.data;
  const rules = Object.entries(m.signals_per_rule.counts);
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Operational metrics</h1>
      <p className="text-sm text-slate-800">
        Also at <code>/metrics</code> in Prometheus format. Counts and ages only; no member data.
      </p>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Tile
          testId="metric-override"
          label={`Override rate (${m.override_rate.window_days} days)`}
          value={pct(m.override_rate.rate)}
          note={`${Object.values(m.override_rate.overrides).reduce((a, b) => a + b, 0)} overrides · ${m.override_rate.calls_started} calls started`}
        />
        <Tile
          testId="metric-ai"
          label="AI unsupported sentences"
          value={pct(m.ai.unsupported_sentence_rate)}
          note={`${m.ai.sentences} sentences in ${m.ai.drafts} drafts · major edits ${pct(m.ai.major_edit_ratio)}`}
        />
        <Tile
          testId="metric-writeback"
          label="Write-back waiting"
          value={String(m.writeback.pending)}
          note={`oldest ${m.writeback.oldest_pending_seconds} s · ${m.writeback.alerted} alerted · median lag ${m.writeback.median_sync_lag_seconds ?? "UNKNOWN"} s`}
        />
        <Tile
          testId="metric-stale"
          label="Stale feeds"
          value={String(m.feeds.filter((f) => f.stale).length)}
          note={`of ${m.feeds.length} streams`}
        />
      </div>
      <section aria-labelledby="feeds-title" className="rounded border border-slate-300 bg-white p-3">
        <h2 id="feeds-title" className="font-semibold">
          Feed ages
        </h2>
        <table className="mt-1 w-full text-left text-sm" data-testid="metric-feeds">
          <thead>
            <tr>
              <th className="pr-2">Stream</th>
              <th className="pr-2">Age (hours)</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {m.feeds.map((f) => (
              <tr key={f.stream} className="border-t border-slate-200">
                <td className="pr-2">
                  {f.feed} / {f.stream}
                </td>
                <td className="pr-2">{f.age_hours ?? "UNKNOWN"}</td>
                <td className={f.stale ? "font-semibold text-red-900" : ""}>{f.stale ? `stale: ${f.reason}` : "ok"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      <section aria-labelledby="signals-title" className="rounded border border-slate-300 bg-white p-3">
        <h2 id="signals-title" className="font-semibold">
          Signals per rule ({m.signals_per_rule.run_day ?? "UNKNOWN"})
        </h2>
        <ul className="mt-1 grid gap-1 text-sm sm:grid-cols-2" data-testid="metric-signals">
          {rules.map(([rule, count]) => (
            <li key={rule}>
              {rule}: <strong>{count}</strong>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
