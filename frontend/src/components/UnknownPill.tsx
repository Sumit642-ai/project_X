/** Missing data is shown as UNKNOWN with the reason, never as "none" or 0. */
export function UnknownPill({ reason }: { reason: string }) {
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full border border-slate-400 bg-slate-100 px-2 py-0.5 text-xs text-slate-800"
      data-testid="unknown-pill"
    >
      <span className="font-semibold tracking-wide">UNKNOWN</span>
      <span aria-hidden="true">·</span>
      <span>{reason}</span>
    </span>
  );
}
