import type { PendingLink } from "../lib/types";

interface Props {
  links: PendingLink[];
  busy?: boolean;
  onConfirm: (linkId: number) => void;
  onReject: (linkId: number) => void;
}

const SOURCES: Record<string, string> = {
  hospital: "Hospital-created record",
  eligibility: "Older eligibility record",
};

/** A possible duplicate from the data layer. Charting waits until a person decides. */
export function MatchBanner({ links, busy = false, onConfirm, onReject }: Props) {
  if (links.length === 0) return null;
  return (
    <section
      aria-labelledby="match-banner-title"
      className="rounded border-2 border-amber-700 bg-amber-50 p-3 text-amber-950"
      data-testid="match-banner"
    >
      <h2 id="match-banner-title" className="font-semibold">
        Possible duplicate · flagged by data layer
      </h2>
      <p className="text-sm">Charting is paused until you confirm or reject this match.</p>
      <ul className="mt-2 space-y-2">
        {links.map((link) => (
          <li key={link.id} className="flex flex-wrap items-center gap-2 text-sm">
            <span>
              {SOURCES[link.source_system] ?? link.source_system} <strong>{link.source_record_id}</strong>,
              match confidence {Number(link.confidence).toFixed(2)}
            </span>
            <button
              type="button"
              disabled={busy}
              onClick={() => onConfirm(link.id)}
              className="rounded bg-blue-800 px-2 py-1 text-white disabled:opacity-60"
            >
              Same person: confirm
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => onReject(link.id)}
              className="rounded border border-slate-700 bg-white px-2 py-1 text-slate-900 disabled:opacity-60"
            >
              Not the same person
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
