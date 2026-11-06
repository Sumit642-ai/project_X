import { useId } from "react";

import { freshnessTooltip } from "../lib/format";
import type { Freshness } from "../lib/types";

const STYLES: Record<Freshness, { label: string; className: string; mark: string }> = {
  green: { label: "Fresh", className: "bg-emerald-100 text-emerald-900 border-emerald-700", mark: "●" },
  amber: { label: "Aging", className: "bg-amber-100 text-amber-950 border-amber-700", mark: "◐" },
  red: { label: "Stale", className: "bg-red-100 text-red-900 border-red-700", mark: "▲" },
  grey: { label: "Never received", className: "bg-slate-100 text-slate-800 border-slate-500", mark: "○" },
};
const UNDATED = { label: "Undated", className: "bg-slate-100 text-slate-800 border-slate-500", mark: "◇" };

interface Props {
  freshness: Freshness;
  sourceSystem?: string;
  type?: string;
  eventDate?: string | null;
  value?: Record<string, unknown>;
  /** A record we hold that carries no event date (grey, but not "never received"). */
  undated?: boolean;
}

/** Colour plus a word and a shape, so meaning never rests on colour alone. */
export function FreshnessBadge({ freshness, sourceSystem, type, eventDate, value, undated = false }: Props) {
  const style = undated && freshness === "grey" ? UNDATED : STYLES[freshness];
  const tipId = useId();
  const tooltip = sourceSystem && type ? freshnessTooltip(sourceSystem, type, eventDate ?? null, value) : null;
  return (
    <span className="group relative inline-flex">
      <span
        tabIndex={tooltip ? 0 : undefined}
        aria-describedby={tooltip ? tipId : undefined}
        className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-xs font-medium ${style.className}`}
        data-testid="freshness-badge"
        data-freshness={freshness}
      >
        <span aria-hidden="true">{style.mark}</span>
        {style.label}
      </span>
      {tooltip && (
        <span
          id={tipId}
          role="tooltip"
          className="pointer-events-none absolute left-0 top-full z-20 mt-1 hidden whitespace-nowrap rounded bg-slate-900 px-2 py-1 text-xs text-white group-focus-within:block group-hover:block"
        >
          {tooltip}
        </span>
      )}
    </span>
  );
}
