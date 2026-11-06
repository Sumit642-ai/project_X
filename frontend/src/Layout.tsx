import { useState } from "react";
import { NavLink, Outlet } from "react-router";

import { api, ApiError } from "./lib/api";
import { useAuth } from "./lib/auth";
import { useDemoConfig, type DemoState } from "./lib/demo";
import { clockTime } from "./lib/format";
import type { QueueOut } from "./lib/types";
import { useApi } from "./lib/useApi";

function StaleFeedBanner({ header }: { header: QueueOut["header"] }) {
  if (header.stale_feeds.length === 0) return null;
  const adtPaused = header.stale_feeds.some((s) => s.feed === "adt");
  return (
    <div
      role="status"
      className={`border-b px-4 py-2 text-sm ${adtPaused ? "border-red-800 bg-red-100 text-red-950" : "border-amber-700 bg-amber-100 text-amber-950"}`}
      data-testid="stale-banner"
    >
      <strong>{adtPaused ? "ADT feed paused: admissions and discharges may be missing." : "Some data is older than expected."}</strong>{" "}
      {header.stale_feeds.map((s) => `${s.feed} (${s.reason})`).join("; ")}
    </div>
  );
}

function demoTime(iso: string): string {
  return new Intl.DateTimeFormat("en-GB", {
    weekday: "short",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "America/New_York",
  }).format(new Date(iso));
}

/** Demo only: the frozen clock, and buttons that move it (loading the scripted feed files). */
function DemoClockBar() {
  const state = useApi<DemoState>("/demo/state");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  if (!state.data) return null;

  async function run(label: string, path: string) {
    setBusy(label);
    setError(null);
    try {
      await api(path, { method: "POST" });
      window.location.reload(); // every screen re-reads the data at the new time
    } catch (e) {
      setError(e instanceof ApiError ? e.reason : String(e));
      setBusy(null);
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-violet-800 bg-violet-50 px-4 py-1.5 text-sm text-violet-950" data-testid="demo-clock">
      <strong>Demo clock:</strong> <span data-testid="demo-clock-time">{demoTime(state.data.instant)}</span>
      {state.data.steps
        .filter((s) => s.available)
        .map((s) => (
          <button
            key={s.id}
            type="button"
            disabled={busy !== null}
            onClick={() => run(s.id, `/demo/clock/advance/${s.id}`)}
            className="rounded border border-violet-800 bg-white px-2 py-0.5"
            title={s.story}
          >
            {busy === s.id ? "Loading feed files…" : `Advance to ${s.label}`}
          </button>
        ))}
      <button type="button" disabled={busy !== null} onClick={() => run("reset", "/demo/clock/reset")} className="rounded border border-violet-800 bg-white px-2 py-0.5">
        {busy === "reset" ? "Resetting…" : "Reset demo"}
      </button>
      <NavLink to="/demo-admin" className="ml-auto text-violet-900 underline">
        Operator panel
      </NavLink>
      {error && (
        <span role="status" className="text-red-800">
          {error}
        </span>
      )}
    </div>
  );
}

const NAV = [
  { to: "/queue", label: "Queue" },
  { to: "/members", label: "Members" },
  { to: "/tasks", label: "Tasks" },
];

export function Layout() {
  const { user, logout } = useAuth();
  const queue = useApi<QueueOut>(user && user.role !== "call_agent" ? "/queue" : null);
  const header = queue.data?.header;
  const demo = useDemoConfig().data?.demo_mode ?? false;
  return (
    <div className="flex min-h-screen bg-slate-50 text-slate-900">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-white focus:p-2">
        Skip to content
      </a>
      <nav aria-label="Main" className="w-44 shrink-0 border-r border-slate-300 bg-white p-3">
        <p className="mb-4 text-lg font-bold text-blue-900">CaseCompass</p>
        <ul className="space-y-1">
          {NAV.map((item) => (
            <li key={item.to}>
              <NavLink
                to={item.to}
                className={({ isActive }) =>
                  `block rounded px-2 py-1 ${isActive ? "bg-blue-800 font-semibold text-white" : "text-slate-900 hover:bg-slate-100"}`
                }
              >
                {item.label}
              </NavLink>
            </li>
          ))}
          {user?.role === "supervisor" && (
            <li>
              <NavLink
                to="/admin/metrics"
                className={({ isActive }) => `block rounded px-2 py-1 ${isActive ? "bg-blue-800 font-semibold text-white" : "text-slate-900 hover:bg-slate-100"}`}
              >
                Metrics
              </NavLink>
            </li>
          )}
          {demo && (
            <li>
              <NavLink
                to="/demo-admin"
                className={({ isActive }) => `block rounded px-2 py-1 ${isActive ? "bg-violet-800 font-semibold text-white" : "text-violet-900 hover:bg-violet-50"}`}
              >
                Demo operator
              </NavLink>
            </li>
          )}
        </ul>
        <p className="mt-6 text-xs text-slate-700">Synthetic data only.</p>
      </nav>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-slate-300 bg-white px-4 py-2">
          <p className="text-sm text-slate-800" data-testid="data-as-of">
            Data as of {header?.data_as_of ? clockTime(header.data_as_of) : "UNKNOWN"}
          </p>
          <div className="flex items-center gap-3 text-sm">
            <span>
              {user?.name} · {user?.role === "cm" ? `${user.credential ?? ""} case manager` : user?.role}
            </span>
            <button type="button" onClick={logout} className="rounded border border-slate-600 px-2 py-1">
              Sign out
            </button>
          </div>
        </header>
        {demo && <DemoClockBar />}
        {header && <StaleFeedBanner header={header} />}
        <main id="main" className="min-w-0 flex-1 p-4">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
