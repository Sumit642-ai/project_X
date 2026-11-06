import { useState, type FormEvent } from "react";
import { Link, Navigate } from "react-router";

import { UnknownPill } from "../components/UnknownPill";
import { ApiError } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useDemoConfig } from "../lib/demo";
import type { QueueOut } from "../lib/types";
import type { CallTask } from "./Call/types";
import { useApi } from "../lib/useApi";

function HealthStatus() {
  const health = useApi<{ status: string }>("/health");
  return (
    <p className="mt-6 text-xs text-slate-700">
      API status: <span data-testid="health-status">{health.data?.status ?? (health.error ? "unreachable" : "checking")}</span>
    </p>
  );
}

export function LoginPage() {
  const { user, login } = useAuth();
  const config = useDemoConfig();
  const [error, setError] = useState<string | null>(null);
  const [username, setUsername] = useState("");
  if (user) return <Navigate to="/queue" replace />;
  const demoUsers = config.data?.users ?? []; // listed in demo mode only

  async function choose(e: FormEvent, username: string) {
    e.preventDefault();
    try {
      await login(username);
    } catch (err) {
      setError(err instanceof ApiError ? err.reason : String(err));
    }
  }

  return (
    <main id="main" className="mx-auto max-w-md p-8 text-slate-900">
      <h1 className="text-2xl font-semibold">CaseCompass</h1>
      <p className="mt-1 text-sm text-slate-800">Demo sign-in. Synthetic data only.</p>
      {config.data && !config.data.demo_mode && (
        <form onSubmit={(e) => choose(e, username.trim())} className="mt-4 flex gap-2">
          <label htmlFor="username" className="sr-only">
            Username
          </label>
          <input
            id="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder="Username"
            className="flex-1 rounded border border-slate-600 px-2 py-1"
          />
          <button type="submit" className="rounded bg-blue-800 px-3 py-1 text-white">
            Sign in
          </button>
        </form>
      )}
      {config.data?.demo_mode && (
        <p className="mt-3 text-sm">
          <Link to="/demo/old-way" className="text-blue-900 underline">
            Open with the old way (seven portal tabs)
          </Link>
        </p>
      )}
      <ul className="mt-4 space-y-2">
        {demoUsers.map((u) => (
          <li key={u.username}>
            <form onSubmit={(e) => choose(e, u.username)}>
              <button type="submit" className="w-full rounded border border-slate-600 bg-white px-3 py-2 text-left hover:bg-slate-100">
                Sign in as {u.label}
              </button>
            </form>
          </li>
        ))}
      </ul>
      {error && (
        <p role="status" className="mt-3 text-sm text-red-800">
          {error}
        </p>
      )}
      <HealthStatus />
    </main>
  );
}

export function MembersPage() {
  const { user } = useAuth();
  const queue = useApi<QueueOut>(user?.role === "supervisor" ? "/queue?cm=all" : "/queue");
  if (!queue.data) return <p>Loading members…</p>;
  const rows = [...queue.data.rows].sort((a, b) => a.name.localeCompare(b.name));
  return (
    <div>
      <h1 className="text-xl font-semibold">Members</h1>
      <ul className="mt-2 divide-y divide-slate-200 rounded border border-slate-300 bg-white">
        {rows.map((r) => (
          <li key={r.member_id} className="px-3 py-2 text-sm">
            <Link to={`/members/${r.member_id}`} className="font-semibold text-blue-900 underline">
              {r.name}
            </Link>{" "}
            · {r.member_id} · {r.lob ?? "UNKNOWN plan"} · {r.age ?? "UNKNOWN"} y
          </li>
        ))}
      </ul>
    </div>
  );
}

export function TasksPage() {
  const tasks = useApi<CallTask[]>("/tasks");
  if (!tasks.data) return <p>Loading tasks…</p>;
  return (
    <div>
      <h1 className="text-xl font-semibold">Tasks</h1>
      {tasks.data.length === 0 ? (
        <p className="mt-2">
          <UnknownPill reason="no tasks yet: tasks are created when a call is wrapped up" />
        </p>
      ) : (
        <ul className="mt-2 space-y-2" data-testid="tasks">
          {tasks.data.map((t) => {
            const byData = t.status === "done" && Boolean(t.resolution);
            return (
              <li
                key={t.id}
                data-testid="task-card"
                data-status={t.status}
                className={`rounded border px-3 py-2 text-sm ${byData ? "border-green-700 bg-green-50" : "border-slate-300 bg-white"}`}
              >
                <Link to={`/members/${t.member_id}`} className="font-semibold text-blue-900 underline">
                  {t.member_id}
                </Link>{" "}
                · {t.title} · due {t.due_date} · {t.status}{" "}
                <span className="text-xs text-slate-700">(from {t.signal_rule_id ?? "call"})</span>
                {byData && (
                  <p className="mt-1 font-semibold text-green-900">
                    ✓ {t.resolution} <span className="text-xs font-normal">(fact {t.resolution_fact_ids?.join(", ")})</span>
                  </p>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
