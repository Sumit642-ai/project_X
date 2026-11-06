import { clockTime, hoursBetween, PLAN_TZ } from "../lib/format";

/** Clock time in the member's zone; red with an hour count when under 24 h away. */
export function DueTime({ dueAt, tz, now }: { dueAt: string | null; tz: string | null; now: string }) {
  if (!dueAt) return <span className="text-sm text-slate-700">No contact deadline</span>;
  const hours = hoursBetween(now, dueAt);
  const urgent = hours < 24;
  return (
    <span className={`text-sm ${urgent ? "font-semibold text-red-800" : "text-slate-900"}`} data-testid="due-time">
      <time dateTime={dueAt}>{clockTime(dueAt, tz ?? PLAN_TZ)}</time>
      {urgent && <span> · {hours <= 0 ? "overdue" : `in ${Math.max(1, Math.round(hours))} h`}</span>}
    </span>
  );
}

