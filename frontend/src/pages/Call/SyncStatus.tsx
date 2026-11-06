export interface WritebackConflict {
  reason: string;
  base_version: number | null;
  current_version: number | null;
  ours: { note?: { body?: string } };
  theirs: { version?: number; notes?: { body?: string }[] } | null;
}

/** Where the save stands. While syncing, the record is safe here and on its way. */
export function SyncStatus({ status }: { status: string }) {
  if (status === "syncing" || status === "saved") {
    return (
      <p role="status" className="rounded border border-amber-700 bg-amber-50 p-2 text-sm text-amber-950" data-testid="sync-status">
        Saved here, syncing to record. You can keep working; we will retry automatically.
      </p>
    );
  }
  if (status === "synced") {
    return (
      <p role="status" className="rounded border border-emerald-700 bg-emerald-50 p-2 text-sm text-emerald-950" data-testid="sync-status">
        Synced to the CM record.
      </p>
    );
  }
  return null;
}

/** Both versions side by side; nothing is overwritten until the nurse chooses. */
export function ConflictPanel({ conflict, onSaveAgainst }: { conflict: WritebackConflict; onSaveAgainst: (version: number) => void }) {
  const latest = conflict.theirs?.notes?.at(-1)?.body;
  return (
    <section aria-labelledby="wb-conflict" className="rounded border-2 border-red-800 bg-red-50 p-3 text-sm text-red-950" data-testid="writeback-conflict">
      <h3 id="wb-conflict" className="font-semibold">
        The CM record changed since you opened it (version {conflict.base_version ?? "UNKNOWN"} → {conflict.current_version ?? "UNKNOWN"})
      </h3>
      <p>Nothing was written. Review both versions before saving.</p>
      <div className="mt-2 grid gap-2 md:grid-cols-2">
        <div className="rounded border border-slate-400 bg-white p-2">
          <h4 className="font-semibold">Your note</h4>
          <p>{conflict.ours.note?.body || "UNKNOWN"}</p>
        </div>
        <div className="rounded border border-slate-400 bg-white p-2">
          <h4 className="font-semibold">Latest in the CM record</h4>
          <p>{latest ?? "No notes in the record yet (another field changed)."}</p>
        </div>
      </div>
      {conflict.current_version != null && (
        <button type="button" onClick={() => onSaveAgainst(conflict.current_version!)} className="mt-2 rounded bg-blue-800 px-3 py-1 text-white">
          I reviewed it: save against version {conflict.current_version}
        </button>
      )}
    </section>
  );
}
