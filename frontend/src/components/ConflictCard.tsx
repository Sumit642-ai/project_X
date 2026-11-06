import type { Conflict, Fact } from "../lib/types";
import { sourceLabel, shortDate } from "../lib/format";

interface Props {
  conflict: Conflict;
  facts: Fact[]; // the conflict's own facts
  blockedReason?: string | null; // e.g. while an identity match is pending
  busy?: boolean;
  onMemberReport: (value: string) => void;
  onSendToPrescriber: () => void;
}

/** Shows what each source says. Never picks a winner; people record what they learn. */
export function ConflictCard({ conflict, facts, blockedReason, busy = false, onMemberReport, onSendToPrescriber }: Props) {
  const values = [...new Set(facts.map((f) => String(f.value.strength ?? f.value.code ?? f.key)).filter(Boolean))];
  const disabled = Boolean(blockedReason) || busy || conflict.status === "resolved";
  const titleId = `conflict-${conflict.id}-title`;
  return (
    <article aria-labelledby={titleId} className="rounded border border-red-700 bg-white p-3" data-testid="conflict-card">
      <p className="text-xs font-medium uppercase tracking-wide text-red-900">
        {conflict.kind} conflict · {conflict.label}
      </p>
      <h3 id={titleId} className="font-semibold text-slate-900">
        {conflict.key}
      </h3>
      <p className="text-sm text-slate-800">{conflict.summary}</p>
      <ul className="mt-2 space-y-1 text-sm">
        {facts.map((fact) => (
          <li key={fact.id} className="text-slate-800">
            <strong>{sourceLabel(fact.source_system)}</strong>: {String(fact.value.strength ?? fact.value.reported ?? "")}{" "}
            <span className="text-slate-700">({shortDate(fact.event_date)}, {fact.status.replace("_", " ")})</span>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-sm text-slate-800">
        Status: <strong>{conflict.status.replace(/_/g, " ")}</strong>
      </p>
      {blockedReason && <p className="mt-1 text-sm text-amber-900">{blockedReason}</p>}
      <div className="mt-2 flex flex-wrap items-center gap-2" role="group" aria-label={`Record what the member reports about ${conflict.key}`}>
        <span className="text-sm text-slate-800">Member reports:</span>
        {[...values, "none on hand", "unsure"].map((value) => (
          <button
            key={value}
            type="button"
            disabled={disabled}
            onClick={() => onMemberReport(value)}
            className="rounded border border-slate-700 bg-white px-2 py-1 text-sm text-slate-900 disabled:opacity-60"
          >
            {value}
          </button>
        ))}
        <button
          type="button"
          disabled={disabled || conflict.status !== "open"}
          onClick={onSendToPrescriber}
          className="rounded bg-blue-800 px-2 py-1 text-sm text-white disabled:opacity-60"
        >
          Send to prescriber
        </button>
      </div>
    </article>
  );
}
