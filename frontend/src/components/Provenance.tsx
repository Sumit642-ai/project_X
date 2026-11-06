import { useEffect, useRef } from "react";

import { longDate, sourceLabel } from "../lib/format";
import type { Fact } from "../lib/types";

export function ProvenanceChip({ fact, onOpen }: { fact: Fact; onOpen: (fact: Fact) => void }) {
  return (
    <button
      type="button"
      onClick={() => onOpen(fact)}
      className="rounded border border-slate-400 bg-white px-1.5 py-0.5 text-xs text-slate-800 underline-offset-2 hover:underline"
      aria-label={`Source: ${sourceLabel(fact.source_system)} record ${fact.source_record_id}`}
    >
      {sourceLabel(fact.source_system)}
    </button>
  );
}

/** Side drawer with the source record behind a fact. Esc or Close returns focus. */
export function ProvenanceDrawer({ fact, onClose }: { fact: Fact | null; onClose: () => void }) {
  const closeRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!fact) return;
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [fact, onClose]);
  if (!fact) return null;
  return (
    <aside
      role="dialog"
      aria-modal="false"
      aria-labelledby="provenance-title"
      className="fixed inset-y-0 right-0 z-30 w-full max-w-md overflow-y-auto border-l border-slate-300 bg-white p-4 shadow-xl"
    >
      <div className="flex items-center justify-between">
        <h2 id="provenance-title" className="text-lg font-semibold">
          Source record
        </h2>
        <button ref={closeRef} type="button" onClick={onClose} className="rounded border border-slate-500 px-2 py-1 text-sm">
          Close
        </button>
      </div>
      <dl className="mt-3 grid grid-cols-3 gap-x-2 gap-y-1 text-sm">
        <dt className="font-medium">Source</dt>
        <dd className="col-span-2">{sourceLabel(fact.source_system)} ({fact.source_system})</dd>
        <dt className="font-medium">Record ID</dt>
        <dd className="col-span-2 font-mono">{fact.source_record_id}</dd>
        <dt className="font-medium">Event date</dt>
        <dd className="col-span-2">{longDate(fact.event_date)}</dd>
        <dt className="font-medium">Loaded</dt>
        <dd className="col-span-2">{longDate(fact.loaded_at)}</dd>
        <dt className="font-medium">Status</dt>
        <dd className="col-span-2">{fact.status}</dd>
        <dt className="font-medium">Confidence</dt>
        <dd className="col-span-2">{fact.confidence}</dd>
        <dt className="font-medium">Fact ID</dt>
        <dd className="col-span-2 font-mono">{fact.id}</dd>
      </dl>
      <h3 className="mt-4 font-medium">Values</h3>
      <pre className="mt-1 overflow-x-auto rounded bg-slate-100 p-2 text-xs text-slate-900">
        {JSON.stringify(fact.value, null, 2)}
      </pre>
    </aside>
  );
}
