import { useState } from "react";
import { Link } from "react-router";

import { DueTime } from "../components/DueTime";
import { ReasonForm } from "../components/ReasonForm";
import { ScoreHover } from "../components/ScoreHover";
import { TierBadge, WhyChip } from "../components/WhyChip";
import { api, ApiError } from "../lib/api";
import { useAuth } from "../lib/auth";
import { scoreText } from "../lib/format";
import type { QueueOut, QueueRow } from "../lib/types";
import { useApi } from "../lib/useApi";

function addDays(iso: string, days: number): string {
  const d = new Date(`${iso.slice(0, 10)}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

function Row({ row, now, isCm, onChanged }: { row: QueueRow; now: string; isCm: boolean; onChanged: () => void }) {
  const [open, setOpen] = useState<"notforme" | "snooze" | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function run(path: string, body: unknown) {
    try {
      await api(path, { method: "POST", body });
      setOpen(null);
      onChanged();
    } catch (e) {
      setError(e instanceof ApiError ? e.reason : String(e));
    }
  }

  return (
    <tr className="border-b border-slate-200 align-top" data-testid="queue-row" data-member={row.member_id}>
      <td className="px-2 py-2 font-mono text-sm">{row.rank}</td>
      <td className="px-2 py-2">
        <Link to={`/members/${row.member_id}`} className="font-semibold text-blue-900 underline">
          {row.name}
        </Link>
        <div className="text-xs text-slate-700">
          {row.member_id} · {row.lob ?? "UNKNOWN plan"} · {row.age ?? "UNKNOWN"} y
        </div>
        {row.duplicate.flagged && (
          <span className="mt-1 inline-block rounded border border-amber-700 bg-amber-50 px-1.5 text-xs text-amber-950" data-testid="duplicate-badge">
            Possible duplicate · flagged by data layer
          </span>
        )}
      </td>
      <td className="px-2 py-2">
        <TierBadge tier={row.tier} />
        <div className="mt-1">
          <ScoreHover score={row.score} explanation={scoreText(row.score_inputs, row.score)} />
        </div>
      </td>
      <td className="px-2 py-2">
        <ul className="flex flex-col gap-1" aria-label="Why this member">
          {row.why.map((w) => (
            <WhyChip key={w} text={w} />
          ))}
        </ul>
      </td>
      <td className="px-2 py-2">
        <DueTime dueAt={row.due_at} tz={row.due_tz} now={now} />
      </td>
      <td className="max-w-xs px-2 py-2 text-sm">
        {row.next_best_action ? (
          <>
            <p>{row.next_best_action.text}</p>
            <p className="text-xs text-slate-700">Because: {row.next_best_action.reason}</p>
          </>
        ) : (
          <span className="text-slate-700">No suggestion</span>
        )}
      </td>
      <td className="px-2 py-2">
        <div className="flex flex-col gap-1">
          <Link to={`/members/${row.member_id}`} className="rounded bg-blue-800 px-2 py-1 text-center text-sm text-white" aria-label={`Open ${row.name}`}>
            Open
          </Link>
          {isCm && (
            <>
              <button type="button" onClick={() => { setError(null); setOpen("notforme"); }} className="rounded border border-slate-600 px-2 py-1 text-sm" aria-label={`Not for me: ${row.name}`}>
                Not for me
              </button>
              <button type="button" onClick={() => { setError(null); setOpen("snooze"); }} className="rounded border border-slate-600 px-2 py-1 text-sm" aria-label={`Snooze ${row.name}`}>
                Snooze
              </button>
            </>
          )}
        </div>
        {open === "notforme" && (
          <ReasonForm
            title={`Not for me: ${row.name}`}
            submitLabel="Return to supervisor"
            error={error}
            onCancel={() => setOpen(null)}
            onSubmit={(reason) => run(`/members/${row.member_id}/not-for-me`, { reason })}
          />
        )}
        {open === "snooze" && (
          <ReasonForm
            title={`Snooze ${row.name}`}
            submitLabel="Snooze"
            error={error}
            withDate={{ label: "Return to queue on", min: addDays(now, 1), max: addDays(now, 30) }}
            onCancel={() => setOpen(null)}
            onSubmit={(reason, until) => run(`/members/${row.member_id}/snooze`, { reason, until })}
          />
        )}
      </td>
    </tr>
  );
}

function ReassignPanel({ rows, onChanged }: { rows: QueueRow[]; onChanged: () => void }) {
  const [memberId, setMemberId] = useState(rows[0]?.member_id ?? "");
  const [toCm, setToCm] = useState("maria");
  const [override, setOverride] = useState("");
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  async function submit() {
    try {
      await api("/queue/reassign", {
        method: "POST",
        body: { member_id: memberId, to_cm: toCm, override_reason: override.trim() || null },
      });
      setMessage({ ok: true, text: `${memberId} reassigned to ${toCm}.` });
      onChanged();
    } catch (e) {
      setMessage({ ok: false, text: e instanceof ApiError ? e.reason : String(e) });
    }
  }

  return (
    <section aria-labelledby="reassign-title" className="rounded border border-slate-300 bg-white p-3">
      <h2 id="reassign-title" className="font-semibold">
        Reassign
      </h2>
      <div className="mt-2 flex flex-wrap items-end gap-2 text-sm">
        <label className="flex flex-col">
          Member
          <select value={memberId} onChange={(e) => setMemberId(e.target.value)} className="rounded border border-slate-500 p-1">
            {rows.map((r) => (
              <option key={r.member_id} value={r.member_id}>
                {r.member_id} {r.name}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col">
          To case manager
          <select value={toCm} onChange={(e) => setToCm(e.target.value)} className="rounded border border-slate-500 p-1">
            {["maria", "devon", "alma", "priya"].map((u) => (
              <option key={u} value={u}>
                {u}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col">
          Language override reason (optional)
          <input value={override} onChange={(e) => setOverride(e.target.value)} className="rounded border border-slate-500 p-1" />
        </label>
        <button type="button" onClick={submit} className="rounded bg-blue-800 px-3 py-1 text-white">
          Reassign
        </button>
      </div>
      {message && (
        <p role="status" className={`mt-2 text-sm ${message.ok ? "text-emerald-900" : "text-red-800"}`}>
          {message.text}
        </p>
      )}
    </section>
  );
}

export function QueuePage() {
  const { user } = useAuth();
  const supervisor = user?.role === "supervisor";
  const [scope, setScope] = useState(supervisor ? "all" : "me");
  const queue = useApi<QueueOut>(`/queue?cm=${scope}`);
  if (queue.error) return <p role="status">Queue unavailable: {queue.error}</p>;
  if (!queue.data) return <p>Loading queue…</p>;
  const { header, rows } = queue.data;
  const capacity = header.capacity;
  const percent = capacity?.target ? Math.min(100, Math.round((capacity.active / capacity.target) * 100)) : null;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-4">
        <h1 className="text-xl font-semibold">Work queue</h1>
        <p className="text-sm" data-testid="tier-counts">
          T0 <strong>{header.tier_counts.T0}</strong> · T1 <strong>{header.tier_counts.T1}</strong> · T2{" "}
          <strong>{header.tier_counts.T2}</strong>
        </p>
        {capacity && percent !== null && (
          <div className="flex items-center gap-2 text-sm">
            <span id="capacity-label">
              Caseload {capacity.active} of {capacity.target}
            </span>
            <div role="progressbar" aria-labelledby="capacity-label" aria-valuemin={0} aria-valuemax={capacity.target ?? 0} aria-valuenow={capacity.active} className="h-2 w-32 rounded bg-slate-200">
              <div className="h-2 rounded bg-blue-800" style={{ width: `${percent}%` }} />
            </div>
          </div>
        )}
        {supervisor && (
          <label className="text-sm">
            Show{" "}
            <select value={scope} onChange={(e) => setScope(e.target.value)} className="rounded border border-slate-500 p-1">
              <option value="all">all members</option>
              <option value="unassigned">unassigned</option>
              {["maria", "devon", "alma", "priya"].map((u) => (
                <option key={u} value={u}>
                  {u}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>
      {supervisor && <ReassignPanel rows={rows} onChanged={queue.reload} />}
      <div className="overflow-x-auto rounded border border-slate-300 bg-white">
        <table className="w-full text-left">
          <caption className="sr-only">Members ranked by tier, then score</caption>
          <thead className="bg-slate-100 text-xs uppercase tracking-wide text-slate-800">
            <tr>
              <th scope="col" className="px-2 py-2">#</th>
              <th scope="col" className="px-2 py-2">Member</th>
              <th scope="col" className="px-2 py-2">Tier · score</th>
              <th scope="col" className="px-2 py-2">Why</th>
              <th scope="col" className="px-2 py-2">Due</th>
              <th scope="col" className="px-2 py-2">Next best action (suggested)</th>
              <th scope="col" className="px-2 py-2">Actions</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <Row key={row.member_id} row={row} now={header.now} isCm={user?.role === "cm"} onChanged={queue.reload} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
